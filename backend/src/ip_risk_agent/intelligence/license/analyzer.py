"""License Analyzer.

    의존성 추출 → 버전 확정 → 레지스트리 조회 → SPDX 정규화 → 결정론적 정책
                                                      ↓
                                            RAG 참조 + 모델 설명

판정은 정책이 하고 모델은 설명만 한다. 이 순서를 뒤집지 않는다.
"""

from __future__ import annotations

import json
import logging

from iprisk_contracts import AnalysisArtifact
from iprisk_contracts.common import (
    AnalysisCoverage,
    AnalysisType,
    ArtifactKind,
    ContentScope,
    EvidenceType,
    LicenseCandidate,
)

from ip_risk_agent.core.artifacts.dependency_files import (
    DEPENDENCY_KINDS,
    DependencyFormat,
    dependency_format,
)

from ..common.analyzer import ResultBuilder
from ..common.errors import FailureCategory, ProviderFailureError
from ..common.evidence import package_metadata_id, rag_chunk_id
from ..common.validation import validate_artifact
from . import lockfiles, manifests, policy, spdx
from .dependency_models import (
    DependencyDeclaration,
    DependencyParseError,
    DependencySet,
    Ecosystem,
)
from . import reference_gate
from .explanation import ReferenceRetriever, reference_query
from .package_metadata import PackageMetadataProvider

ANALYZER_VERSION = "license-analyzer-1.0.0"

logger = logging.getLogger(__name__)


def _log_analysis(
    artifact: AnalysisArtifact,
    *,
    declarations: int,
    candidates: int,
    coverage: AnalysisCoverage | None,
) -> None:
    """라이선스 경로가 무엇을 읽었는지 한 줄로 남긴다.

    ## 왜 필요한가

    이 경로에는 로그가 한 줄도 없었다. 그래서 ``pyproject.toml`` 하나에서 통짜로는
    20 건이 나오는데 조각을 거치면 3 건만 나오는 손실이 **운영에서 보이지 않았다.**
    결과는 ``SUCCEEDED`` 이고 화면에는 Risk 가 줄어든 것으로만 보인다. 세 수를 나란히
    남기면 그 손실이 한 줄에서 드러난다 — 조각 수, 선언 수, 후보 수.

    ## 무엇을 넣지 않는가

    **패키지 이름도 파일 경로도 넣지 않는다.** 둘 다 사용자 소스에서 온 내용이고, 로그
    정책이 금지한다. 대신 ``artifact_id`` 와 ``revision`` 을 남긴다 — 그것으로 어느
    파일인지 canonical 저장소에서 되짚을 수 있고, 로그 자체는 내용을 담지 않는다.

    형식(``PYPROJECT_TOML`` 같은 값)은 파일 이름이 아니라 **종류**라 남긴다. 어느 파서가
    돌았는지 모르면 수를 해석할 수 없다.
    """
    logger.info(
        json.dumps(
            {
                "schema_version": 1,
                "event": "license_analysis_diagnostic",
                "analysis_job_id": artifact.analysis_job_id,
                "artifact_id": artifact.artifact_id,
                "revision": artifact.revision,
                "dependency_format": getattr(
                    dependency_format(artifact.logical_path), "value", None
                ),
                "content_scope": artifact.content_scope.value,
                "segment_count": len(artifact.text_segments),
                "declaration_count": declarations,
                "candidate_count": candidates,
                "coverage": coverage.value if coverage is not None else None,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )

def _parse_requirements_lock(text: str, source_path: str | None = None):
    """``requirements.lock`` — 문법은 같고 신뢰도만 다르다."""
    return manifests.parse_requirements_txt(text, source_path, lockfile=True)


#: 형식마다 파서 하나. 어떤 이름이 어떤 형식인지는 커넥터와 함께 쓰는 표가 정한다
#: (``core.artifacts.dependency_files``). 표와 파서가 따로 놀면 커넥터가 의존성으로
#: 분류한 파일을 분석기가 읽지 못해 **어느 분석기도 맡지 못하는 파일**이 생긴다.
_PARSERS = {
    DependencyFormat.REQUIREMENTS_TXT: manifests.parse_requirements_txt,
    DependencyFormat.REQUIREMENTS_LOCK: _parse_requirements_lock,
    DependencyFormat.PYPROJECT_TOML: manifests.parse_pyproject_toml,
    DependencyFormat.SETUP_CFG: manifests.parse_setup_cfg,
    DependencyFormat.PACKAGE_JSON: manifests.parse_package_json,
    DependencyFormat.PACKAGE_LOCK_JSON: lockfiles.parse_package_lock_json,
    DependencyFormat.UV_LOCK: lockfiles.parse_uv_lock,
    DependencyFormat.POETRY_LOCK: lockfiles.parse_poetry_lock,
}

def _select_parser(logical_path: str):
    """파일 이름으로 파서를 고른다. 읽을 수 없으면 ``None``."""
    found = dependency_format(logical_path)
    return None if found is None else _PARSERS[found]


def _input_was_cut(artifact: AnalysisArtifact) -> bool:
    """게이트가 입력을 잘랐는가.

    ``content_scope`` 는 계약에 처음부터 있었고 게이트가 채워 보내는데
    **`intelligence/` 전체에서 아무도 읽지 않았다.** 그래서 바이트 상한에 걸려 잘린
    파일을 분석기가 온전한 것으로 알고 파싱했다.

    줄 지향 파일에서 특히 조용하다. 잘린 JSON·TOML 은 파서가 못 읽었다고 말하지만
    (§6.6), ``requirements.txt`` 는 뒤가 잘려도 **앞부분이 멀쩡한 파일처럼 읽힌다.**
    선언 스무 개 중 여덟 개만 나오고 그것이 `COMPLETE` 로 올라간다 — 나머지 열둘은
    "없는 것" 이 되어 그 Risk 가 해소된다.

    잘렸으면 이 결과는 파일을 설명하지 못하므로 ``PARTIAL`` 이다.
    """
    return artifact.content_scope is not ContentScope.FULL_TEXT


class LicenseAnalyzer:
    """``AnalysisType.LICENSE`` 담당."""

    analysis_type = AnalysisType.LICENSE

    def __init__(
        self,
        metadata_provider: PackageMetadataProvider,
        *,
        retriever: ReferenceRetriever | None = None,
    ) -> None:
        self._metadata = metadata_provider
        self._retriever = retriever

    def supports(self, artifact: AnalysisArtifact) -> bool:
        """의존성 파일만 본다. 소스 코드에는 의존성 선언이 없다."""
        return (
            artifact.artifact_kind in DEPENDENCY_KINDS
            and _select_parser(artifact.logical_path) is not None
        )

    async def analyze(self, artifact: AnalysisArtifact):
        validate_artifact(artifact, self.analysis_type)
        builder = ResultBuilder(artifact, self.analysis_type, ANALYZER_VERSION)
        versions: dict[str, str | None] = {"policy_version": policy.POLICY_VERSION}

        parser = _select_parser(artifact.logical_path)
        if parser is None:
            return builder.skipped(**versions)

        # 줄 단위 형식은 못 읽은 줄을 **건너뛴다.** JSON·TOML 처럼 예외를 던지지
        # 않으므로 따로 물어야 한다. 묻지 않으면 BOM 하나가 파일 전체를 "선언 없음"
        # 으로 만들고, 그것이 `COMPLETE` 로 올라가 Risk 를 해소한다. 실제로 그랬다.
        line_based = dependency_format(artifact.logical_path) in {
            DependencyFormat.REQUIREMENTS_TXT,
            DependencyFormat.REQUIREMENTS_LOCK,
        }

        dependencies = DependencySet()
        unreadable = False
        skipped_lines = 0
        for segment in artifact.text_segments:
            try:
                dependencies.extend(parser(segment.text, artifact.logical_path))
            except DependencyParseError:
                # 못 읽은 것은 "선언이 없다" 가 아니다. 여기서 삼키면 결과가
                # SUCCEEDED + COMPLETE 로 올라가 그 파일의 Risk 를 전부 해소한다.
                unreadable = True
            else:
                if line_based:
                    skipped_lines += len(
                        manifests.unreadable_requirement_lines(segment.text)
                    )

        if unreadable:
            # 일부라도 못 읽었으면 이 결과는 파일을 설명하지 못한다. PARTIAL 은
            # 해소 권한을 갖지 않으므로(§7.2) 잘못된 해소가 일어나지 않는다.
            _log_analysis(
                artifact,
                declarations=len(dependencies),
                candidates=0,
                coverage=AnalysisCoverage.PARTIAL,
            )
            return builder.succeeded(
                [], coverage=AnalysisCoverage.PARTIAL, **versions
            )

        if not len(dependencies):
            # 파일은 맞지만 선언이 없다. 여기가 조용한 오보가 시작되는 자리다 —
            # 읽기가 망가져도 결과는 똑같이 "0 건" 이고 SUCCEEDED 로 올라간다.
            # 그래서 나가기 전에 반드시 남긴다. 해소를 막는 것은 Control 쪽 0-L 이다.
            #
            # 건너뛴 줄이 있으면 0 건이 아니라 **모른다**. `COMPLETE` 로 내보내면
            # 해소 권한이 붙는다.
            coverage = AnalysisCoverage.PARTIAL if skipped_lines else None
            _log_analysis(artifact, declarations=0, candidates=0, coverage=coverage)
            if coverage is None:
                return builder.succeeded([], **versions)
            return builder.succeeded([], coverage=coverage, **versions)

        candidates: list[LicenseCandidate] = []
        partial = False
        for declaration in dependencies.items():
            candidate, degraded = await self._evaluate(declaration, builder, versions)
            if candidate is not None:
                candidates.append(candidate)
            partial = partial or degraded

        coverage = (
            AnalysisCoverage.PARTIAL
            if partial
            or skipped_lines
            or builder.has_failures
            or _input_was_cut(artifact)
            else AnalysisCoverage.COMPLETE
        )
        _log_analysis(
            artifact,
            declarations=len(dependencies),
            candidates=len(candidates),
            coverage=coverage,
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
        if fact.version_not_found:
            # 요청한 버전이 레지스트리에 없었다. 최신 버전으로 대체하지 않았으므로
            # 판정은 UNKNOWN 이고, 왜 모르는지가 여기에 남는다.
            uncertainty.append("VERSION_NOT_IN_REGISTRY")

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

        degraded = await self._attach_reference_evidence(
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

    async def _attach_reference_evidence(
        self,
        declaration: DependencyDeclaration,
        expression: str,
        outcome: policy.LicensePolicyOutcome,
        evidence_ids: list[str],
        builder: ResultBuilder,
        versions: dict[str, str | None],
    ) -> bool:
        """정책 판정의 근거가 될 라이선스 조항을 붙인다.

        실패하면 True 를 돌려 coverage 를 낮춘다 — 근거를 못 붙였다는 것은
        "모른다" 이고, 그것을 COMPLETE 로 두면 없는 권위를 주장하게 된다.
        """
        if self._retriever is None or not policy.needs_review(outcome):
            return False

        # 검색을 실제로 시도했다는 사실을 먼저 남긴다. 예전에는 조각이 **붙었을 때만**
        # 기록해서, 주제 불일치로 전부 버린 경우와 조회 실패가 `None` 으로 같아졌다.
        #
        # corpus 갱신이 판정을 바꾸는 구조에서 이 필드가 **감사의 전부**다. 어느 판본을
        # 보고 내린 판단인지 모르면, corpus 를 올린 뒤 판정이 달라졌을 때 그것이 corpus
        # 때문인지 다른 것 때문인지 가를 수 없다 (§7.4 의 원인 귀속).
        versions["rag_corpus_version"] = self._retriever.corpus_version

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

        # 설명은 여기서 만들지 않는다.
        #
        # 예전에는 이 자리에서 Gemini 를 부르고 결과를 **버렸다.** 계약의
        # ``LicenseCandidate`` 에는 설명을 실을 필드가 없고 계약은 동결이라 담을 곳이
        # 없었기 때문이다. 후보마다 한 번씩 호출하고 아무 데도 쓰지 않은 셈이다.
        #
        # 지금은 ``RiskExplanationService`` 가 **저장된 근거**에서 설명을 만든다.
        # 위에서 등록한 RAG 참조 조각도 후보 근거에 들어가므로 같은 자료를 본다.
        # 그래서 여기서 부를 이유가 없다.
        return False
        return False
