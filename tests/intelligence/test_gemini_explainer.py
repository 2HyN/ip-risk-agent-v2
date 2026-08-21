"""배포용 LicenseExplainer 구현.

Protocol 만 있고 구현체가 없어 배포에서는 라이선스 판정에 설명이 한 번도 붙지
않았다. 판정은 규칙 엔진이 하고 이 구현은 이유만 붙인다.
"""

from __future__ import annotations

import asyncio

from ip_risk_agent.intelligence.gemini.schemas import LicenseExplanationOutput
from ip_risk_agent.intelligence.license.explanation import ReferenceChunk
from ip_risk_agent.intelligence.license.gemini_explainer import (
    GeminiLicenseExplainer,
    render_references,
)
from ip_risk_agent.intelligence.license.policy import LicensePolicyOutcome


class FakeClient:
    model_id = "fake-model"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, prompt: str, schema):
        self.prompts.append(prompt)
        return LicenseExplanationOutput(
            summary="네트워크 제공에도 소스 공개 의무가 있다.",
            obligations=["결합 저작물의 소스를 제공한다."],
            reference_chunk_ids=["rag:agpl-3.0-obligations:network"],
        )


def _chunk() -> ReferenceChunk:
    return ReferenceChunk(
        source_id="agpl-3.0-obligations",
        chunk_id="network",
        text="네트워크를 통해 제공해도 소스코드를 제공해야 한다.",
        canonical_reference="https://spdx.org/licenses/AGPL-3.0-only.html",
    )


def test_references_are_rendered_with_their_evidence_ids() -> None:
    """모델이 근거를 가리키려면 원장과 같은 ID 를 보아야 한다.

    다른 ID 를 보면 호출부의 대조에서 전부 '없는 참조' 가 되어 설명이 폐기된다.
    """
    rendered = render_references([_chunk()])
    assert "[rag:agpl-3.0-obligations:network]" in rendered
    assert "네트워크를 통해" in rendered


def test_explanation_carries_summary_obligations_and_reference_ids() -> None:
    client = FakeClient()
    explainer = GeminiLicenseExplainer(client)

    explanation = asyncio.run(
        explainer.explain(
            package="pymupdf",
            license_expression="AGPL-3.0-only",
            outcome=LicensePolicyOutcome.POLICY_CONFLICT,
            references=[_chunk()],
        )
    )

    assert explanation.summary
    assert explanation.obligations == ["결합 저작물의 소스를 제공한다."]
    assert explanation.reference_chunk_ids == ["rag:agpl-3.0-obligations:network"]
    assert explainer.model_id == "fake-model"
    assert explainer.prompt_version

    prompt = client.prompts[0]
    assert "pymupdf" in prompt
    assert "AGPL-3.0-only" in prompt
    assert "POLICY_CONFLICT" in prompt
    assert "rag:agpl-3.0-obligations:network" in prompt
