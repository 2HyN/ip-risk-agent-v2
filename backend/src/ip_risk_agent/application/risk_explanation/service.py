"""이미 판정이 끝난 Risk 에 설명과 권고를 붙인다.

## 왜 분석기 안이 아닌가

설명을 분석 파이프라인 안에서만 만들면 **이미 만들어진 Risk 는 영영 설명이 없다.**
새로 분석해야 하는데, 특허는 그때마다 KIPRIS 호출 한도를 쓴다.

그리고 계약상 담을 곳도 없다. ``LicenseCandidate`` 에는 설명을 실을 필드가 아예
없고 ``shared/contracts/**`` 는 동결이다.

그래서 **저장된 근거에서** 동작하게 만든다. 같은 코드가 두 곳에 쓰인다.

* 새 분석이 끝난 뒤 — 자동으로 붙는다
* 기존 Risk — 백필로 붙는다. provider 는 Gemini 하나뿐이다

## 판정과의 경계

설명은 등급도 Risk 의 존재도 바꾸지 않는다. 모델이 없는 근거를 인용하면 설명
전체를 버린다 — license 설명기와 같은 규칙이다. 설명이 없다고 Risk 가 사라지지는
않으므로, 실패는 조용히 넘긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ip_risk_agent.application.repositories import ControlUnitOfWorkFactory
from ip_risk_agent.application.risk_reconcile.retention import (
    EvidenceRetentionPolicy,
    sanitize_explanation,
)
from ip_risk_agent.core.risk import Risk, RiskEvidence


@dataclass(frozen=True, slots=True)
class RiskExplanation:
    summary: str
    recommendation: str
    reference_evidence_ids: tuple[str, ...]


class RiskExplainer(Protocol):
    async def explain(
        self, *, risk: Risk, evidence: tuple[RiskEvidence, ...]
    ) -> RiskExplanation: ...

    @property
    def model_id(self) -> str: ...

    @property
    def prompt_version(self) -> str: ...


@dataclass(frozen=True, slots=True)
class ExplanationOutcome:
    explained: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[str, ...]


class RiskExplanationService:
    """Risk 에 설명과 권고를 붙인다. 판정은 건드리지 않는다."""

    def __init__(
        self,
        *,
        unit_of_work_factory: ControlUnitOfWorkFactory,
        explainer: RiskExplainer | None,
        retention_policy: EvidenceRetentionPolicy | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._explainer = explainer
        self._retention = retention_policy or EvidenceRetentionPolicy()

    async def explain_risks(
        self, risk_ids: tuple[str, ...], *, overwrite: bool = False
    ) -> ExplanationOutcome:
        """주어진 Risk 들에 설명을 붙인다.

        이미 설명이 있으면 건너뛴다 — 같은 근거로 다시 부르면 돈만 쓰고 문장만
        흔들린다. 근거가 없으면 설명할 것도 없으므로 건너뛴다.
        """
        if self._explainer is None:
            return ExplanationOutcome((), tuple(risk_ids), ())

        explained: list[str] = []
        skipped: list[str] = []
        failed: list[str] = []

        for risk_id in risk_ids:
            async with self._unit_of_work_factory() as uow:
                risk = await uow.risks.get(risk_id)
                if risk is None:
                    skipped.append(risk_id)
                    continue
                if risk.explanation_safe and not overwrite:
                    skipped.append(risk_id)
                    continue
                evidence = await uow.risks.list_evidence(
                    risk_id, analysis_job_id=risk.latest_analysis_job_id
                )
            if not evidence:
                skipped.append(risk_id)
                continue

            try:
                explanation = await self._explainer.explain(risk=risk, evidence=evidence)
            except Exception:  # noqa: BLE001 - 설명 실패가 Risk 를 없애지 않는다
                failed.append(risk_id)
                continue

            known = {item.evidence_id_from_result for item in evidence}
            if any(cid not in known for cid in explanation.reference_evidence_ids):
                # 없는 근거를 인용했다. 일부가 지어내진 설명은 통째로 믿지 않는다.
                failed.append(risk_id)
                continue

            try:
                summary = sanitize_explanation(explanation.summary, self._retention)
                recommendation = sanitize_explanation(
                    explanation.recommendation, self._retention
                )
            except Exception:  # noqa: BLE001 - 보존 정책을 못 지나면 붙이지 않는다
                failed.append(risk_id)
                continue

            async with self._unit_of_work_factory() as uow:
                current = await uow.risks.get(risk_id)
                if current is None:
                    skipped.append(risk_id)
                    continue
                from dataclasses import replace

                await uow.risks.save(
                    replace(
                        current,
                        explanation_safe=summary,
                        recommendation_safe=recommendation,
                    )
                )
                await uow.commit()
            explained.append(risk_id)

        return ExplanationOutcome(tuple(explained), tuple(skipped), tuple(failed))


__all__ = [
    "ExplanationOutcome",
    "RiskExplainer",
    "RiskExplanation",
    "RiskExplanationService",
]
