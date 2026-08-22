"""Risk 설명·권고. 판정을 바꾸지 않고, 지어낸 인용은 버린다."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from iprisk_contracts import AnalysisType, ReviewPriority

from ip_risk_agent.application.repositories import InMemoryControlStore
from ip_risk_agent.application.risk_explanation import (
    RiskExplanation,
    RiskExplanationService,
)
from ip_risk_agent.core.risk import (
    ReviewDisposition,
    Risk,
    RiskEvidence,
    RiskLifecycleState,
)
from ip_risk_agent.core.workspaces import RiskWorkspace

NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


class ScriptedExplainer:
    model_id = "fake-model"
    prompt_version = "risk_explain_v1"

    def __init__(self, explanation=None, *, boom: bool = False) -> None:
        self.explanation = explanation
        self.boom = boom
        self.calls = 0

    async def explain(self, *, risk, evidence):
        self.calls += 1
        if self.boom:
            raise RuntimeError("provider is down")
        return self.explanation


async def seed(store: InMemoryControlStore, *, with_evidence: bool = True) -> str:
    async with store() as uow:
        await uow.workspaces.add(
            RiskWorkspace("vws-1", "W", "owner-1", "sec", "ret", NOW, NOW)
        )
        risk = Risk(
            "risk-1", "vws-1", "artifact-1", AnalysisType.PATENT,
            "risk-patent:artifact-1:1", RiskLifecycleState.NEW,
            ReviewDisposition.UNREVIEWED, ReviewPriority.HIGH,
            "겹치는 구성이 있는 특허", NOW, NOW, "job-1", NOW,
        )
        await uow.risks.add(risk)
        if with_evidence:
            await uow.risks.add_evidence(
                RiskEvidence(
                    "risk-evidence-1", "risk-1", "job-1", "patent:1:claim:1",
                    "PATENT_CLAIM", "청구항 본문", "KIPRIS 출원번호 1", "rev-1", NOW,
                )
            )
        await uow.commit()
    return "risk-1"


def _service(store, explainer):
    return RiskExplanationService(unit_of_work_factory=store, explainer=explainer)


def test_an_explanation_is_attached_without_touching_the_judgement() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        await seed(store)
        explainer = ScriptedExplainer(
            RiskExplanation(
                summary="청구항 1 과 문서의 판정 로직이 겹칩니다.",
                recommendation="특허팀 검토를 요청하세요.",
                reference_evidence_ids=("patent:1:claim:1",),
            )
        )
        outcome = await _service(store, explainer).explain_risks(("risk-1",))
        assert outcome.explained == ("risk-1",)

        async with store() as uow:
            risk = await uow.risks.get("risk-1")
        assert risk.explanation_safe.startswith("청구항 1")
        assert "특허팀" in risk.recommendation_safe
        # 판정은 그대로다. 설명은 등급도 존재도 바꾸지 않는다.
        assert risk.review_priority is ReviewPriority.HIGH
        assert risk.lifecycle_state is RiskLifecycleState.NEW
        assert risk.review_disposition is ReviewDisposition.UNREVIEWED
        assert risk.review_version == 0

    run(scenario())


def test_a_fabricated_reference_discards_the_whole_explanation() -> None:
    """일부가 지어내진 설명에서 나머지만 믿을 근거가 없다."""

    async def scenario() -> None:
        store = InMemoryControlStore()
        await seed(store)
        explainer = ScriptedExplainer(
            RiskExplanation(
                summary="없는 근거를 인용했다.",
                recommendation="무언가 하세요.",
                reference_evidence_ids=("patent:9999:claim:7",),
            )
        )
        outcome = await _service(store, explainer).explain_risks(("risk-1",))
        assert outcome.failed == ("risk-1",)
        async with store() as uow:
            risk = await uow.risks.get("risk-1")
        assert risk.explanation_safe is None

    run(scenario())


def test_a_provider_failure_leaves_the_risk_alone() -> None:
    """설명이 없다고 Risk 가 사라지지는 않는다."""

    async def scenario() -> None:
        store = InMemoryControlStore()
        await seed(store)
        outcome = await _service(store, ScriptedExplainer(boom=True)).explain_risks(
            ("risk-1",)
        )
        assert outcome.failed == ("risk-1",)
        async with store() as uow:
            assert await uow.risks.get("risk-1") is not None

    run(scenario())


def test_an_existing_explanation_is_not_paid_for_twice() -> None:
    """같은 근거로 다시 부르면 돈만 쓰고 문장만 흔들린다."""

    async def scenario() -> None:
        store = InMemoryControlStore()
        await seed(store)
        explanation = RiskExplanation("설명", "권고", ("patent:1:claim:1",))
        explainer = ScriptedExplainer(explanation)
        service = _service(store, explainer)
        assert (await service.explain_risks(("risk-1",))).explained == ("risk-1",)
        assert (await service.explain_risks(("risk-1",))).skipped == ("risk-1",)
        assert explainer.calls == 1
        # 다시 만들고 싶으면 명시해야 한다.
        assert (
            await service.explain_risks(("risk-1",), overwrite=True)
        ).explained == ("risk-1",)
        assert explainer.calls == 2

    run(scenario())


def test_a_risk_without_evidence_is_skipped() -> None:
    """근거가 없으면 설명할 것도 없다. 지어내게 두지 않는다."""

    async def scenario() -> None:
        store = InMemoryControlStore()
        await seed(store, with_evidence=False)
        explainer = ScriptedExplainer(RiskExplanation("x", "y", ()))
        outcome = await _service(store, explainer).explain_risks(("risk-1",))
        assert outcome.skipped == ("risk-1",)
        assert explainer.calls == 0

    run(scenario())


def test_without_an_explainer_nothing_happens() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        await seed(store)
        outcome = await RiskExplanationService(
            unit_of_work_factory=store, explainer=None
        ).explain_risks(("risk-1",))
        assert outcome.skipped == ("risk-1",)

    run(scenario())
