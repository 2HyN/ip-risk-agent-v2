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
    should_revive,
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
            # 되살릴 때 비교한다. 판본이 그대로면 사용자의 판단도 그대로 유효하다
            # (§7.1). 이 값이 없으면 복원할지 말지를 정할 근거가 없다.
            "latest_evidence_revision": risk.latest_evidence_revision,
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


async def revive_artifact_risks(
    uow,
    *,
    risk_workspace_id: str,
    artifact_id: str,
    revision: str | None,
    occurred_at: datetime,
    reason_safe: str,
    id_factory: Callable[[str], str],
) -> list[str]:
    """제외됐던 Risk 를 되살린다. 파일이 다시 추적 대상이 될 때 쓴다 (§7.1 · 1-D).

    ## 왜 분석을 기다리지 않는가

    되살리기는 지금까지 ``should_revive`` 하나뿐이었고 그 자리는 ``_reconcile`` 안,
    즉 **분석 결과가 있어야 닿는 곳**이다. 그런데 판본이 그대로인 채 돌아오면 변경
    지문이 겹쳐 중복으로 처리되고 분석이 아예 돌지 않는다. 파일을 잠깐 옮겼다
    되돌리는 흔한 일이 정확히 그 경우다.

    ## 판본이 같으면 사람의 판단을 되돌린다

    예전에는 되살아난 Risk 가 ``NEW`` / ``UNREVIEWED`` 로 돌아갔다. 방아쇠가 수동
    "추적 해제" 하나뿐일 때는 옳았다 — 사용자가 스스로 그만둔 것이니 다시 시작하는
    것이 맞다. 방아쇠가 **삭제 · 폴더 이탈**로 넓어지면 전제가 깨진다. 파일을 잠깐
    옮겼다 되돌린 것만으로 **검토해 수용한 판단이 조용히 지워진다.**

    판본이 달라졌으면 그대로 ``NEW`` / ``UNREVIEWED`` 다. "제외되어 있던 동안 세상이
    달라졌다" 는 근거가 그때만 성립한다.
    """
    revived_ids: list[str] = []
    for risk in await uow.risks.list_for_workspace(risk_workspace_id):
        if risk.artifact_id != artifact_id:
            continue
        if not should_revive(risk.review_disposition):
            continue

        previous = await _disposition_before_exclusion(uow, risk, revision)
        moment = max(occurred_at, risk.last_seen_at, risk.updated_at)
        updated = replace(
            risk,
            lifecycle_state=RiskLifecycleState.EXISTING,
            review_disposition=previous or ReviewDisposition.UNREVIEWED,
            review_version=risk.review_version + 1,
            resolved_at=None,
            last_seen_at=moment,
            updated_at=moment,
        )
        await uow.risks.save(updated)
        await uow.risks.append_event(
            RiskEvent(
                id=id_factory("risk-event"),
                risk_id=updated.id,
                event_type=RiskEventType.REOPENED,
                actor_type=ActorType.SYSTEM,
                occurred_at=moment,
                previous_state_safe={
                    "lifecycle_state": risk.lifecycle_state.value,
                    "review_disposition": risk.review_disposition.value,
                },
                new_state_safe={
                    "lifecycle_state": updated.lifecycle_state.value,
                    "review_disposition": updated.review_disposition.value,
                    "disposition_restored": previous is not None,
                },
                reason_safe=reason_safe,
            )
        )
        revived_ids.append(updated.id)
    return revived_ids


async def _disposition_before_exclusion(
    uow, risk: Risk, revision: str | None
) -> ReviewDisposition | None:
    """제외되기 직전의 처분. 되돌릴 수 없으면 ``None``.

    값은 이미 이력에 있다 — 제외할 때 적어 두었다. 새 필드를 만들지 않는 이유가
    이것이고, 원장이 답을 들고 있는 편이 낫다.

    판본이 다르면 되돌리지 않는다. 그 사이에 파일이 바뀌었으면 사용자가 그때 본 것과
    지금 것이 다르다.
    """
    if revision is None or risk.latest_evidence_revision != revision:
        return None
    for event in reversed(await uow.risks.list_events(risk.id)):
        if event.event_type is not RiskEventType.REVIEW_DISPOSITION_CHANGED:
            continue
        if event.new_state_safe.get("review_disposition") != ReviewDisposition.EXCLUDED.value:
            continue
        if event.previous_state_safe.get("latest_evidence_revision") != revision:
            # 제외될 때의 판본이 지금과 다르다. 그 사이에 내용이 바뀌었다.
            return None
        found = event.previous_state_safe.get("review_disposition")
        if not isinstance(found, str):
            return None
        try:
            restored = ReviewDisposition(found)
        except ValueError:
            return None
        # 제외를 되돌리는 것이지 제외를 복원하는 것이 아니다.
        return None if restored is ReviewDisposition.EXCLUDED else restored
    return None
