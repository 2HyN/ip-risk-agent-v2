"""Patent Analyzer.

    기술 요소 추출 → 검색어 생성 → KIPRIS 검색 → 중복 제거·순위 → 초록 조회
                                                                   ↓
                                    근거 조각 → 모델 대조 → 검증 → 우선순위

법적 결론을 만들지 않는다. 검토해야 할 특허와 그 근거를 좁혀 줄 뿐이다
(Agent 3 Spec 11).
"""

from __future__ import annotations

import json
import logging

import asyncio
from datetime import datetime, timezone

from iprisk_contracts import AnalysisArtifact
from iprisk_contracts.common import (
    AnalysisCoverage,
    AnalysisType,
    ArtifactKind,
    EvidenceType,
    PatentCandidate,
)

from ..common.analyzer import ResultBuilder
from ..common.errors import MalformedProviderOutputError, ProviderFailureError
from ..common.evidence import source_reference, source_segment_id
from ..common.validation import validate_artifact
from ..gemini.client import PromptLibrary, StructuredModelClient
from ..gemini.schemas import PatentComparison, TechnicalExtraction
from . import evidence_builder, grounding
from .candidate_rank import DEFAULT_CANDIDATE_CAP, RankedCandidate, rank_candidates
from .extraction import TechnicalExtractor, render_segments
from .cache import CachedExtraction, EXTRACTION_TTL, extraction_cache_key
from .kipris import PatentDocument, PatentSearchProvider
from .score import evidence_strength
from .query_builder import run_searches

logger = logging.getLogger(__name__)


def _diagnostic(**counts: int) -> None:
    """특허 검색 단계의 개수만 남긴다.

    후보 0건은 여러 이유로 생긴다 — 검색어를 못 만들었거나, KIPRIS 히트가 0이거나,
    대조에서 전부 탈락했거나. 최종 결과 수만 보면 이 셋을 구별할 수 없어 튜닝의
    출발점이 없다.

    검색어와 문서 본문은 남기지 않는다. 검색어는 문서에서 파생된 값이므로 개수만
    기록한다.
    """
    logger.info(
        json.dumps(
            {"schema_version": 1, "event": "patent_search_diagnostic", **counts},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def _priority_diagnostic(
    *,
    match_count: int,
    has_claim_evidence: bool,
    caveat_count: int,
    evidence_truncated: bool,
    evidence_strength: float,
    segment_count: int,
    distinct_segments: int,
    priority: str,
) -> None:
    """후보 하나의 등급이 **왜** 그 값이 되었는지 남긴다.

    실측에서 특허 Risk 33 건이 모두 MEDIUM 이었다. 등급이 한 값으로 뭉치면 검토
    순서에 아무 정보를 주지 못하는데, 원인이 셋이라 결과만 보고는 가릴 수 없다 —
    겹치는 구성이 하나뿐인지, 청구항 근거가 없는지, HIGH 였다가 불확실 표시로
    내려온 것인지.

    ``suggested_priority`` 의 입력을 그대로 남기면 그 셋이 갈린다. 개수와 불리언만
    남기고 표시의 문구나 본문은 남기지 않는다.
    """
    logger.info(
        json.dumps(
            {
                "schema_version": 1,
                "event": "patent_priority_diagnostic",
                "match_count": match_count,
                "has_claim_evidence": has_claim_evidence,
                "caveat_count": caveat_count,
                "evidence_truncated": evidence_truncated,
                "evidence_strength": evidence_strength,
                "segment_count": segment_count,
                "distinct_segments": distinct_segments,
                "priority": priority,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


#: 이월된 후보는 검색 순위가 없다. 정렬에서 뒤로 보낸다.
_CARRIED_POSITION = 10_000


async def _safe_cache(awaitable):
    """캐시 오류는 삼킨다. 캐시는 정확성의 일부가 아니다."""
    try:
        return await awaitable
    except Exception:  # noqa: BLE001
        return None


ANALYZER_VERSION = "patent-analyzer-1.0.0"
COMPARE_PROMPT = "patent_compare_v2"

# 기획·설계 문서만 본다. 의존성 파일에는 발명이 없다.
_DOCUMENT_KINDS = frozenset(
    {ArtifactKind.DOCUMENT_TEXT, ArtifactKind.TEXT, ArtifactKind.SOURCE_CODE}
)


class PatentAnalyzer:
    """``AnalysisType.PATENT`` 담당."""

    analysis_type = AnalysisType.PATENT

    def __init__(
        self,
        search_provider: PatentSearchProvider,
        model_client: StructuredModelClient,
        *,
        prompts: PromptLibrary | None = None,
        candidate_cap: int = DEFAULT_CANDIDATE_CAP,
        response_cache=None,
        previously_matched=None,
    ) -> None:
        self._search = search_provider
        self._client = model_client
        self._prompts = prompts or PromptLibrary()
        self._extractor = TechnicalExtractor(model_client, self._prompts)
        self._cap = candidate_cap
        # 같은 문서면 같은 검색어를 쓴다. 없으면 매번 다시 뽑는다.
        self._cache = response_cache
        # 이 artifact 에서 이미 매칭된 출원번호. 검색과 무관하게 다시 대조한다.
        self._previously_matched = previously_matched

    def supports(self, artifact: AnalysisArtifact) -> bool:
        return artifact.artifact_kind in _DOCUMENT_KINDS

    async def analyze(self, artifact: AnalysisArtifact):
        validate_artifact(artifact, self.analysis_type)
        builder = ResultBuilder(artifact, self.analysis_type, ANALYZER_VERSION)
        versions: dict[str, str | None] = {
            "model_id": self._client.model_id,
            # 등급을 정하는 것은 대조 프롬프트이므로 함께 남긴다. 규칙이나 프롬프트가
            # 바뀌면 과거 판정의 뜻이 조용히 달라지는데, 무엇이 판정했는지 남아 있지
            # 않으면 "그때의 상" 이 무엇이었는지 설명할 수 없다.
            "prompt_version": (
                f"{self._extractor.prompt_version}+"
                f"{self._prompts.get(COMPARE_PROMPT).prompt_version}"
            ),
        }

        # ── 1. 기술 요소 추출
        try:
            extraction = await self._extract(artifact)
        except ProviderFailureError as failure:
            builder.record_failure(failure)
            return builder.failed(**versions)

        if not extraction.is_technical:
            # 특허 검토 대상이 아니다. 실패가 아니라 해당 없음이다.
            return builder.skipped(**versions)
        if not extraction.search_queries:
            # 대상이긴 하나 검색어를 만들 만큼의 기술 내용이 없다.
            return builder.inconclusive(**versions)

        # ── 2. 검색
        outcome = await run_searches(self._search, extraction.search_queries)
        for failure in outcome.failures:
            builder.record_failure(failure)

        if not outcome.hits_by_query and outcome.failures:
            # 모든 검색어가 실패했다. 후보 0건이 아니라 모르는 상태다.
            return builder.failed(**versions)

        candidates = rank_candidates(outcome.hits_by_query, cap=self._cap)
        # 검색이 데려오지 않았어도, 이 문서에서 이미 매칭된 특허는 다시 대조한다.
        #
        # 그러지 않으면 검색어가 조금만 달라져도 이전 후보가 결과에서 빠지고,
        # canonical 은 그것을 "판정해 보니 더 이상 위험이 아니다" 로 읽어 Risk 를
        # RESOLVED 로 닫는다. 실제로는 **이번에 보지도 않은 것**이다. 운영에서
        # 같은 문서를 재검사했더니 특허 2 건이 그렇게 조용히 해소됐다.
        carried = await self._carried_forward(artifact, candidates)
        candidates = [*candidates, *carried]
        _diagnostic(
            query_count=len(extraction.search_queries),
            queries_answered=len(outcome.hits_by_query),
            hit_total=sum(len(hits) for hits in outcome.hits_by_query.values()),
            ranked_candidates=len(candidates),
            search_failures=len(outcome.failures),
        )
        if not candidates:
            # 검색은 정상이고 결과가 없었다. 이것은 성공이다.
            coverage = (
                AnalysisCoverage.COMPLETE if outcome.is_complete else AnalysisCoverage.PARTIAL
            )
            return builder.succeeded([], coverage=coverage, **versions)

        # ── 3. 원문 등록
        for segment in artifact.text_segments:
            builder.ledger.add(
                source_segment_id(segment.segment_id),
                EvidenceType.SOURCE_EXCERPT,
                segment.text,
                source_reference(artifact.logical_path),
                # 줄 범위를 근거에 실어 둔다. 검토 화면이 "문서의 어느 줄" 을 짚고,
                # 나중에 문장 단위 하이라이트가 이 범위 안에서 다시 좁힌다.
                {
                    "segment_kind": segment.segment_kind.value,
                    **(
                        {}
                        if segment.line_start is None
                        else {
                            "line_start": segment.line_start,
                            "line_end": segment.line_end or segment.line_start,
                        }
                    ),
                },
            )

        # ── 4. 후보별 대조
        documents = await self._fetch_documents(candidates, builder)
        results: list[PatentCandidate] = []
        assessed = 0

        for candidate in candidates:
            document = documents.get(candidate.application_number)
            if document is None or not document.has_content:
                continue
            evaluated = await self._compare(
                artifact,
                candidate,
                document,
                builder,
                extracted_elements=len(extraction.technical_elements),
                total_queries=len(extraction.search_queries),
            )
            if evaluated is not None:
                assessed += 1
                if evaluated.matched_elements:
                    results.append(evaluated.candidate)

        _diagnostic(
            ranked_candidates=len(candidates),
            documents_fetched=len(documents),
            assessed=assessed,
            matched=len(results),
        )
        # 후보를 다 보지 못했으면 범위가 완전하지 않다.
        complete = outcome.is_complete and assessed == len(candidates)
        return builder.succeeded(
            results,
            coverage=AnalysisCoverage.COMPLETE if complete else AnalysisCoverage.PARTIAL,
            **versions,
        )

    # ------------------------------------------------------------ 내부

    async def _extract(self, artifact: AnalysisArtifact):
        """검색어를 뽑는다. 문서 내용이 같으면 지난번 것을 그대로 쓴다.

        추출은 모델이 하므로 같은 문서라도 실행마다 검색어가 달라진다. 그러면
        후보가 달라져 **바뀐 것이 없는데 Risk 가 새로 생긴다.**
        """
        checksum = artifact.security_context.analysis_input_checksum
        key = None
        if self._cache is not None and checksum:
            key = extraction_cache_key(checksum, self._extractor.prompt_version)
            cached = await _safe_cache(self._cache.get_extraction(key))
            now = datetime.now(timezone.utc)
            if cached is not None and now - cached.stored_at < EXTRACTION_TTL:
                return TechnicalExtraction.model_validate(cached.payload)

        extraction = await self._extractor.extract(artifact)
        if key is not None:
            await _safe_cache(
                self._cache.put_extraction(
                    key,
                    CachedExtraction(
                        payload=extraction.model_dump(mode="json"),
                        stored_at=datetime.now(timezone.utc),
                        risk_workspace_id=artifact.risk_workspace_id,
                    ),
                )
            )
        return extraction

    async def _carried_forward(
        self, artifact: AnalysisArtifact, candidates: list[RankedCandidate]
    ) -> list[RankedCandidate]:
        if self._previously_matched is None:
            return []
        try:
            known = await self._previously_matched(artifact.artifact_id)
        except Exception:  # noqa: BLE001 - 이월을 못 해도 분석은 진행한다
            return []
        seen = {candidate.application_number for candidate in candidates}
        return [
            RankedCandidate(
                application_number=number,
                title="",
                # 검색이 데려온 것이 아니므로 적중 질의가 없다. 점수의
                # query_reach 가 0 이 되는 것은 사실 그대로다.
                matched_queries=[],
                best_position=_CARRIED_POSITION,
                metadata={"carried_forward": "true"},
            )
            for number in known
            if number and number not in seen
        ]

    async def _fetch_documents(
        self, candidates: list[RankedCandidate], builder: ResultBuilder
    ) -> dict[str, PatentDocument]:
        fetched = await asyncio.gather(
            *(self._search.fetch_detail(c.application_number) for c in candidates),
            return_exceptions=True,
        )
        documents: dict[str, PatentDocument] = {}
        for candidate, result in zip(candidates, fetched, strict=True):
            if isinstance(result, ProviderFailureError):
                builder.record_failure(result)
            elif isinstance(result, BaseException):
                raise result
            else:
                documents[candidate.application_number] = result
        return documents

    async def _compare(
        self,
        artifact: AnalysisArtifact,
        candidate: RankedCandidate,
        document: PatentDocument,
        builder: ResultBuilder,
        *,
        extracted_elements: int,
        total_queries: int,
    ):
        """특허 한 건과 대조한다. 실패하면 None 을 돌려 미판정으로 남긴다."""
        evidence = evidence_builder.build_patent_evidence(document, builder.ledger)
        if evidence.is_empty:
            return None

        prompt = self._prompts.get(COMPARE_PROMPT).render(
            segments=render_segments(artifact),
            patent_evidence=evidence_builder.render_evidence(evidence),
        )
        try:
            comparison = await self._client.generate(prompt, PatentComparison)
        except ProviderFailureError as failure:
            builder.record_failure(failure)
            return None

        try:
            grounded = grounding.validate_comparison(
                comparison,
                allowed_segment_ids={s.segment_id for s in artifact.text_segments},
                evidence_types=evidence.types,
                # 잘렸는지는 모델에게 묻지 않는다. 원장이 아는 사실이다.
                truncated_evidence_ids=builder.ledger.truncated_ids,
                # 인용이 본문에 실제로 있는지 코드가 확인한다. 양쪽 본문을 넘긴다.
                evidence_bodies={
                    **{
                        source_segment_id(segment.segment_id): segment.text
                        for segment in artifact.text_segments
                    },
                    **evidence.text_by_id,
                },
            )
        except MalformedProviderOutputError as failure:
            # 지어낸 근거가 섞였다. 이 특허에 대한 판단 전체를 버린다.
            builder.record_failure(failure)
            return None

        priority = grounding.suggested_priority(grounded)
        # 점수는 관측만 한다. 판정은 위 규칙이 하고 이 값은 기록만 된다 (설계 노트 §6-3).
        strength = evidence_strength(
            matched_elements=grounded.match_count,
            extracted_elements=extracted_elements,
            claim_backed_evidence=sum(
                1
                for evidence_id in grounded.evidence_ids
                if evidence.types.get(evidence_id) is EvidenceType.PATENT_CLAIM
            ),
            patent_evidence=sum(
                1 for evidence_id in grounded.evidence_ids if evidence_id in evidence.types
            ),
            answered_queries=len(candidate.matched_queries),
            total_queries=total_queries,
        )
        _priority_diagnostic(
            match_count=grounded.match_count,
            has_claim_evidence=grounded.has_claim_evidence,
            caveat_count=len(grounded.review_caveats),
            evidence_truncated=grounded.evidence_truncated,
            segment_count=len(artifact.text_segments),
            distinct_segments=sum(
                1 for value in grounded.evidence_ids if value.startswith("src:")
            ),
            priority=priority.value,
            evidence_strength=strength.score,
        )
        return _Evaluated(
            matched_elements=grounded.matched_elements,
            candidate=PatentCandidate(
                normalized_application_number=candidate.application_number,
                title=document.title or candidate.title,
                suggested_review_priority=priority,
                matched_elements=grounded.matched_elements,
                evidence_ids=grounded.evidence_ids,
                provider_metadata_safe={
                    "query_hits": candidate.query_hits,
                    "matched_queries": candidate.matched_queries,
                    "review_caveats": grounded.review_caveats,
                    "evidence_truncated": grounded.evidence_truncated,
                    # 근거 안에서 강조할 구간. 후보마다 다를 수 있으므로 후보에
                    # 싣는다 — 같은 청구항을 두 후보가 다른 문장으로 인용한다.
                    "quote_spans": {
                        evidence_id: {"start": span.start, "end": span.end}
                        for evidence_id, span in grounded.quote_spans.items()
                    },
                    **strength.as_metadata(),
                    "has_claim_evidence": grounded.has_claim_evidence,
                },
            ),
        )


class _Evaluated:
    """대조를 마친 후보. 겹치는 것이 없으면 결과에 싣지 않는다."""

    __slots__ = ("matched_elements", "candidate")

    def __init__(self, matched_elements: list[str], candidate: PatentCandidate) -> None:
        self.matched_elements = matched_elements
        self.candidate = candidate
