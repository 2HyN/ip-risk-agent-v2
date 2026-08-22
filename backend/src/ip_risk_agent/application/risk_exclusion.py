"""추적이 외적으로 끝난 Risk 를 제외 처리한다.

사용자가 스스로 내리는 처분(``ACCEPTED_RISK`` 등)과 달리, ``EXCLUDED`` 는 파일 추적
중단이나 mount 일시중지처럼 **사용자 판단 밖의 요인**으로 관리가 끝났음을 뜻한다.
추적이 이미 끊긴 Risk 를 두고 계속 지켜볼지 사람이 고르는 것은 뜻이 통하지 않으므로,
그 처분은 여기서만 붙는다.

지우지 않는다. Risk 도 근거도 이력도 그대로 남기고 상태만 닫는다. 나중에 같은 파일이
다시 추적 대상이 되면 ``should_revive`` 가 이것을 되살린다.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Callable

from ip_risk_agent.core.common import ActorType
from ip_risk_agent.core.risk import (
    ReviewDisposition,
    Risk,
    RiskEvent,
    RiskEventType,
    RiskLifecycleState,
    decide_exclusion,
)


def _exclusion_event(
    *,
    risk: Risk,
    previous_state: RiskLifecycleState,
    previous_disposition: ReviewDisposition,
    occurred_at: datetime,
    reason_safe: str,
    event_id: str,
) -> RiskEvent:
    return RiskEvent(
        id=event_id,
        risk_id=risk.id,
        event_type=RiskEventType.REVIEW_DISPOSITION_CHANGED,
        actor_type=ActorType.SYSTEM,
        occurred_at=occurred_at,
        previous_state_safe={
            "lifecycle_state": previous_state.value,
            "review_disposition": previous_disposition.value,
        },
        new_state_safe={
            "lifecycle_state": risk.lifecycle_state.value,
            "review_disposition": risk.review_disposition.value,
        },
        reason_safe=reason_safe,
    )


async def exclude_risks(
    uow,
    risks: list[Risk],
    *,
    occurred_at: datetime,
    reason_safe: str,
    id_factory: Callable[[str], str],
) -> list[str]:
    """주어진 Risk 들을 ``RESOLVED`` / ``EXCLUDED`` 로 닫고 이력을 남긴다.

    이미 제외된 것은 건너뛴다. 같은 mount 를 두 번 일시중지해도 이력이 부풀지 않는다.
    """
    excluded_ids: list[str] = []
    for risk in risks:
        if risk.review_disposition is ReviewDisposition.EXCLUDED:
            continue
        decision = decide_exclusion(risk.lifecycle_state, risk.review_disposition)
        if not decision.changed:
            continue
        # RESOLVED 는 resolved_at 을 요구하고, 그 값은 first_seen_at 보다 앞설 수 없다.
        resolved_at = max(occurred_at, risk.first_seen_at, risk.last_seen_at)
        updated = replace(
            risk,
            lifecycle_state=decision.next_state,
            review_disposition=decision.next_disposition,
            # 처분이 바뀌면 review_version 을 정확히 하나 올려야 한다. 저장소가 그
            # 규칙을 강제하므로, 시스템이 붙이는 처분도 예외가 아니다. 화면의 ETag 도
            # 이 값으로 만들어지니 올리지 않으면 낡은 값이 유효해 보인다.
            review_version=risk.review_version + 1,
            resolved_at=resolved_at,
            updated_at=resolved_at,
        )
        await uow.risks.save(updated)
        await uow.risks.append_event(
            _exclusion_event(
                risk=updated,
                previous_state=decision.previous_state,
                previous_disposition=decision.previous_disposition,
                occurred_at=resolved_at,
                reason_safe=reason_safe,
                event_id=id_factory("risk-event"),
            )
        )
        excluded_ids.append(updated.id)
    return excluded_ids


async def exclude_artifact_risks(
    uow,
    *,
    risk_workspace_id: str,
    artifact_id: str,
    occurred_at: datetime,
    reason_safe: str,
    id_factory: Callable[[str], str],
) -> list[str]:
    """한 artifact 의 Risk 를 모두 제외한다. 파일 추적을 끊을 때 쓴다."""
    risks = [
        risk
        for risk in await uow.risks.list_for_workspace(risk_workspace_id)
        if risk.artifact_id == artifact_id
    ]
    return await exclude_risks(
        uow,
        risks,
        occurred_at=occurred_at,
        reason_safe=reason_safe,
        id_factory=id_factory,
    )


async def exclude_mount_risks(
    uow,
    *,
    risk_workspace_id: str,
    mount_id: str,
    occurred_at: datetime,
    reason_safe: str,
    id_factory: Callable[[str], str],
) -> list[str]:
    """한 mount 에 속한 모든 artifact 의 Risk 를 제외한다. mount 일시중지에 쓴다."""
    artifacts = await uow.artifacts.list_for_workspace(risk_workspace_id)
    artifact_ids = {
        artifact.id for artifact in artifacts if artifact.mount_id == mount_id
    }
    if not artifact_ids:
        return []
    risks = [
        risk
        for risk in await uow.risks.list_for_workspace(risk_workspace_id)
        if risk.artifact_id in artifact_ids
    ]
    return await exclude_risks(
        uow,
        risks,
        occurred_at=occurred_at,
        reason_safe=reason_safe,
        id_factory=id_factory,
    )


__all__ = [
    "exclude_artifact_risks",
    "exclude_mount_risks",
    "exclude_risks",
]
