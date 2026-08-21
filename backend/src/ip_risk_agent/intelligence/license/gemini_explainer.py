"""정책 판정에 사람이 읽을 설명을 붙인다.

``LicenseExplainer`` 는 Protocol 만 있고 구현체가 없어, 배포에서는 라이선스
판정에 자연어 설명이 한 번도 붙지 않았다. 판정 자체는 규칙 엔진이 하고 이
구현은 **왜 그런 의무가 생기는지**를 참조 자료에 근거해 설명하기만 한다.

설명은 판정을 바꾸지 못한다. 모델이 실제로 없는 참조를 지목하면 호출부가
설명 전체를 폐기하므로, 여기서는 참조 목록을 ID 와 함께 그대로 넘긴다.
"""

from __future__ import annotations

from ..common.evidence import rag_chunk_id
from ..gemini.client import PromptLibrary, StructuredModelClient
from ..gemini.schemas import LicenseExplanationOutput
from .explanation import LicenseExplanation, ReferenceChunk
from .policy import LicensePolicyOutcome

PROMPT_NAME = "license_explain_v1"


def render_references(references: list[ReferenceChunk]) -> str:
    """모델에 넘길 참조 자료.

    각 조각에 근거 ID 를 붙인다. 그래야 모델이 어떤 조각에 근거했는지 가리킬 수
    있고, 호출부가 그 ID 를 근거 원장과 대조할 수 있다.
    """
    return "\n\n".join(
        f"[{rag_chunk_id(chunk.source_id, chunk.chunk_id)}]\n{chunk.text}"
        for chunk in references
    )


class GeminiLicenseExplainer:
    """``LicenseExplainer`` 의 배포용 구현."""

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
        self,
        *,
        package: str,
        license_expression: str,
        outcome: LicensePolicyOutcome,
        references: list[ReferenceChunk],
    ) -> LicenseExplanation:
        prompt = self._prompts.get(PROMPT_NAME)
        rendered = prompt.render(
            package=package,
            license_expression=license_expression,
            outcome=outcome.value,
            references=render_references(references),
        )
        result: LicenseExplanationOutput = await self._client.generate(
            rendered, LicenseExplanationOutput
        )
        return LicenseExplanation(
            summary=result.summary,
            obligations=list(result.obligations),
            reference_chunk_ids=list(result.reference_chunk_ids),
        )


__all__ = ["GeminiLicenseExplainer", "render_references"]
