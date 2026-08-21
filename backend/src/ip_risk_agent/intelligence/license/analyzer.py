"""License Analyzer.

    의존성 추출 → 버전 확정 → 레지스트리 조회 → SPDX 정규화 → 결정론적 정책
                                                      ↓
                                            RAG 참조 + 모델 설명

판정은 정책이 하고 모델은 설명만 한다. 이 순서를 뒤집지 않는다.
"""

from __future__ import annotations

from iprisk_contracts import AnalysisArtifact
from iprisk_contracts.common import (
    AnalysisCoverage,
    AnalysisType,
    ArtifactKind,
    EvidenceType,
    LicenseCandidate,
)

from ..common.analyzer import ResultBuilder
from ..common.errors import FailureCategory, ProviderFailureError
from ..common.evidence import package_metadata_id, rag_chunk_id
from ..common.validation import validate_artifact
from . import lockfiles, manifests, policy, spdx
from .dependency_models import DependencyDeclaration, DependencySet, Ecosystem
from . import reference_gate
from .explanation import LicenseExplainer, ReferenceRetriever, reference_query
from .package_metadata import PackageMetadataProvider

ANALYZER_VERSION = "license-analyzer-1.0.0"

# 파일명 -> 매니페스트 파서. 잠금 파일은 lockfiles.parser_for 가 맡는다.
_MANIFEST_PARSERS = (
    ("requirements", manifests.parse_requirements_txt),
    ("pyproject.toml", manifests.parse_pyproject_toml),
    ("package.json", manifests.parse_package_json),
)

_DEPENDENCY_KINDS = frozenset({ArtifactKind.MANIFEST, ArtifactKind.LOCKFILE})


def _select_parser(logical_path: str):
    """논리 경로로 파서를 고른다. 잠금 파일을 먼저 확인한다.

    ``package-lock.json`` 은 ``package.json`` 을 포함하므로 순서가 중요하다.
    """
    if lock_parser := lockfiles.parser_for(logical_path):
        return lock_parser
    name = logical_path.rsplit("/", 1)[-1].lower()
    for marker, parser in _MANIFEST_PARSERS:
        if name.startswith(marker) or name == marker:
            return parser
    return None


class LicenseAnalyzer:
    """``AnalysisType.LICENSE`` 담당."""

    analysis_type = AnalysisType.LICENSE

    def __init__(
        self,
        metadata_provider: PackageMetadataProvider,
        *,
        retriever: ReferenceRetriever | None = None,
        explainer: LicenseExplainer | None = None,
    ) -> None:
        self._metadata = metadata_provider
        self._retriever = retriever
        self._explainer = explainer

    def supports(self, artifact: AnalysisArtifact) -> bool:
        """의존성 파일만 본다. 소스 코드에는 의존성 선언이 없다."""
        return (
            artifact.artifact_kind in _DEPENDENCY_KINDS
            and _select_parser(artifact.logical_path) is not None
        )

    async def analyze(self, artifact: AnalysisArtifact):
        validate_artifact(artifact, self.analysis_type)
        builder = ResultBuilder(artifact, self.analysis_type, ANALYZER_VERSION)
        versions: dict[str, str | None] = {"policy_version": policy.POLICY_VERSION}

        parser = _select_parser(artifact.logical_path)
        if parser is None:
            return builder.skipped(**versions)

        dependencies = DependencySet()
        for segment in artifact.text_segments:
            dependencies.extend(parser(segment.text, artifact.logical_path))

        if not len(dependencies):
            # 파일은 맞지만 선언이 없다. 실패가 아니라 위험이 없는 것이다.
            return builder.succeeded([], **versions)

        candidates: list[LicenseCandidate] = []
        partial = False
        for declaration in dependencies.items():
            candidate, degraded = await self._evaluate(declaration, builder, versions)
            if candidate is not None:
                candidates.append(candidate)
            partial = partial or degraded

        coverage = (
            AnalysisCoverage.PARTIAL
            if partial or builder.has_failures
            else AnalysisCoverage.COMPLETE
        )
        return builder.succeeded(candidates, coverage=coverage, **versions)

    # ------------------------------------------------------------ 개별 평가

    async def _evaluate(
        self,
        declaration: DependencyDeclaration,
        builder: ResultBuilder,
        versions: dict[str, str | None],
    ) -> tuple[LicenseCandidate | None, bool]:
        """의존성 하나를 평가한다. 두 번째 값은 coverage 를 낮춰야 하는지."""
        uncertainty = declaration.uncertainty_flags()
        evidence_ids: list[str] = []

        try:
            fact = await self._metadata.get_license(
                declaration.ecosystem, declaration.name, declaration.version
            )
        except ProviderFailureError as failure:
            # 조회 실패를 "라이선스 없음"으로 바꾸지 않는다. 후보는 남기되 UNKNOWN 이다.
            builder.record_failure(failure)
            return (
                LicenseCandidate(
                    ecosystem=declaration.ecosystem.value,
                    normalized_package_name=declaration.name,
                    resolved_version=declaration.version,
                    normalized_license_expression=spdx.UNKNOWN_LICENSE,
                    policy_outcome=policy.LicensePolicyOutcome.UNKNOWN,
                    evidence_ids=[],
                    uncertainty_flags=[*uncertainty, "METADATA_LOOKUP_FAILED"],
                ),
                True,
            )

        if fact.inferred_from_free_text:
            uncertainty.append("LICENSE_INFERRED_FROM_FREE_TEXT")

        outcome = policy.evaluate_expression(fact.license_expression)

        evidence_ids.append(
            builder.ledger.add(
                package_metadata_id(
                    declaration.ecosystem.value, declaration.name, declaration.version
                ),
                EvidenceType.PACKAGE_METADATA,
                f"{declaration.name} {declaration.version or '(버전 미상)'}: "
                f"{fact.license_expression}",
                fact.source,
                {
                    "resolution": declaration.resolution.value,
                    "spdx_snapshot": spdx.SPDX_SNAPSHOT_VERSION,
                },
            )
        )

        degraded = await self._attach_explanation(
            declaration, fact.license_expression, outcome, evidence_ids, builder, versions
        )

        return (
            LicenseCandidate(
                ecosystem=declaration.ecosystem.value,
                normalized_package_name=declaration.name,
                resolved_version=declaration.version,
                normalized_license_expression=fact.license_expression,
                policy_outcome=outcome,
                evidence_ids=evidence_ids,
                uncertainty_flags=uncertainty,
            ),
            degraded,
        )

    async def _attach_explanation(
        self,
        declaration: DependencyDeclaration,
        expression: str,
        outcome: policy.LicensePolicyOutcome,
        evidence_ids: list[str],
        builder: ResultBuilder,
        versions: dict[str, str | None],
    ) -> bool:
        """근거 조항과 설명을 붙인다. 실패하면 True 를 돌려 coverage 를 낮춘다."""
        if self._retriever is None or not policy.needs_review(outcome):
            return False

        try:
            chunks = await self._retriever.retrieve(
                reference_query(expression, outcome), top_k=3
            )
        except Exception as exc:  # noqa: BLE001 - provider 예외를 결과로 옮긴다
            failure = (
                exc
                if isinstance(exc, ProviderFailureError)
                else ProviderFailureError(
                    "RAG_ENGINE", FailureCategory.UNAVAILABLE, type(exc).__name__
                )
            )
            builder.record_failure(failure)
            return True

        # 임베딩 검색은 관련 문서가 없어도 항상 top_k 개를 돌려준다. 주제가 맞는
        # 것만 남긴다 — 근거가 없는 것보다 틀린 근거가 붙는 것이 나쁘다.
        relevant = reference_gate.select_relevant(chunks, expression)
        if not relevant:
            # 참조를 못 붙였다는 것이 실패는 아니다. 근거 없이 policy 고정 문구로
            # 간다. corpus 커버리지 밖의 라이선스에서는 정상 경로다.
            return False

        versions["rag_corpus_version"] = self._retriever.corpus_version
        for chunk in relevant:
            evidence_ids.append(
                builder.ledger.add(
                    rag_chunk_id(chunk.source_id, chunk.chunk_id),
                    EvidenceType.LICENSE_REFERENCE,
                    chunk.text,
                    chunk.canonical_reference,
                    dict(chunk.metadata),
                )
            )

        if self._explainer is None:
            return False

        try:
            explanation = await self._explainer.explain(
                package=declaration.name,
                license_expression=expression,
                outcome=outcome,
                references=relevant,
            )
        except ProviderFailureError as failure:
            builder.record_failure(failure)
            return True

        # 모델이 실제로 없는 참조를 들었다면 설명 전체를 믿지 않는다.
        unknown = [
            cid
            for cid in explanation.reference_chunk_ids
            if not builder.ledger.has(cid)
        ]
        if unknown:
            builder.record_failure(
                ProviderFailureError(
                    "GEMINI",
                    FailureCategory.MALFORMED_OUTPUT,
                    "explanation referenced unknown evidence",
                )
            )
            return True

        versions["model_id"] = self._explainer.model_id
        versions["prompt_version"] = self._explainer.prompt_version
        return False
