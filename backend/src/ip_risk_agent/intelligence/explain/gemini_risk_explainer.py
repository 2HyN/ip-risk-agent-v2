"""``RiskExplainer`` 의 배포용 구현.

입력은 **canonical 에 이미 저장된 근거**다. 분석기 내부 상태를 보지 않으므로
새 분석에도, 이미 만들어진 Risk 의 백필에도 같은 코드가 쓰인다.

근거 본문을 그대로 넣되 evidence ID 를 붙여 준다. 모델이 인용한 ID 를 코드가
대조해 지어낸 것을 걸러내기 위해서다 (license 설명기와 같은 규칙).
"""

from __future__ import annotations

from ip_risk_agent.application.risk_explanation import RiskExplanation
from ip_risk_agent.core.risk import Risk, RiskEvidence

from ..gemini.client import PromptLibrary, StructuredModelClient
from ..gemini.schemas import RiskExplanationOutput

PROMPT_NAME = "risk_explain_v1"

#: 설명에 넣을 근거 개수 상한. 전부 넣으면 프롬프트가 커지고, 정작 중요한 근거가
#: 묻힌다. 저장 순서가 곧 인용 순서이므로 앞쪽이 더 중요하다.
MAX_EVIDENCE = 8


def render_evidence(evidence: tuple[RiskEvidence, ...]) -> str:
    """모델이 가리킬 수 있도록 ID 를 붙여 근거를 적는다."""
    return "\n\n".join(
        f"[{item.evidence_id_from_result}] ({item.evidence_type})\n{item.excerpt}"
        for item in evidence[:MAX_EVIDENCE]
    )


class GeminiRiskExplainer:
    def __init__(
        self,
        client: StructuredModelClient,
        prompts: PromptLibrary | None = None,
    ) -> None:
        self._client = client
        self._prompts = prompts or PromptLibrary()

    @property
    def model_id(self) -> str:
        return self._client.model_id

    @property
    def prompt_version(self) -> str:
        return self._prompts.get(PROMPT_NAME).prompt_version

    async def explain(
        self, *, risk: Risk, evidence: tuple[RiskEvidence, ...]
    ) -> RiskExplanation:
        rendered = self._prompts.get(PROMPT_NAME).render(
            summary=risk.summary,
            analysis_type=risk.analysis_type.value,
            priority=risk.review_priority.value,
            evidence=render_evidence(evidence),
        )
        result: RiskExplanationOutput = await self._client.generate(
            rendered, RiskExplanationOutput
        )
        return RiskExplanation(
            summary=result.summary,
            recommendation=result.recommendation,
            reference_evidence_ids=tuple(result.reference_evidence_ids),
        )


__all__ = ["GeminiRiskExplainer", "MAX_EVIDENCE", "PROMPT_NAME", "render_evidence"]
