"""추적을 벗어난 파일과 돌아온 파일 (§7.1 · 1-D).

Drive 실측(§2.1.1 `SOURCE_MEASUREMENT.md`)에서 **삭제 · 폴더 이탈 · 접근 상실이 피드에
같은 모양**으로 왔다. 그래서 셋을 구별하지 않고 한 경로로 받는다.
"""

from __future__ import annotations

import asyncio

from iprisk_contracts import AnalysisType, ChangeType
from iprisk_contracts.common import ReviewPriority

from ip_risk_agent.core.risk import (
    ReviewDisposition,
    Risk,
    RiskLifecycleState,
)

from test_source_change_intake import (
    NOW,
    AdvancingClock,
    InMemoryControlStore,
    InMemoryTaskEnqueuer,
    make_change,
    make_intake,
    seed_source_context,
)


async def _seed_with_risk(disposition: ReviewDisposition, *, revision="revision-1"):
    store = InMemoryControlStore()
    queue = InMemoryTaskEnqueuer()
    await seed_source_context(store)
    intake = make_intake(store, queue, AdvancingClock())
    created = await intake.register_source_change(make_change(revision=revision))
    async with store() as uow:
        await uow.risks.add(
            Risk(
                "risk-1",
                "vws-1",
                created.artifact_id,
                AnalysisType.PATENT,
                "risk-key-1",
                RiskLifecycleState.NEW,
                disposition,
                ReviewPriority.HIGH,
                "Potential overlap",
                NOW,
                NOW,
                created.analysis_job_id or "job",
                NOW,
                latest_evidence_revision=revision,
            )
        )
        await uow.commit()
    return store, intake


async def _leave(intake, *, previous="revision-1"):
    return await intake.register_source_change(
        make_change(
            fingerprint="fingerprint-gone",
            change_type=ChangeType.DELETE,
            revision=None,
            previous_revision=previous,
        )
    )


async def _return(intake, *, revision, fingerprint="fingerprint-back"):
    return await intake.register_source_change(
        make_change(fingerprint=fingerprint, revision=revision)
    )


def test_a_file_that_leaves_closes_its_risks() -> None:
    async def scenario():
        store, intake = await _seed_with_risk(ReviewDisposition.UNREVIEWED)
        await _leave(intake)
        async with store() as uow:
            return await uow.risks.get("risk-1")

    risk = asyncio.run(scenario())
    assert risk.lifecycle_state is RiskLifecycleState.RESOLVED
    assert risk.review_disposition is ReviewDisposition.EXCLUDED


def test_a_file_that_comes_back_unchanged_revives_without_any_analysis() -> None:
    """되살리기가 분석을 기다리면 이 경우에 영영 안 온다.

    판본이 그대로면 변경 지문이 겹쳐 **중복으로 처리되고 분석이 아예 돌지 않는다.**
    파일을 잠깐 옮겼다 되돌리는 흔한 일이 정확히 그 경우다.
    """

    async def scenario():
        store, intake = await _seed_with_risk(ReviewDisposition.UNREVIEWED)
        await _leave(intake)
        await _return(intake, revision="revision-1")
        async with store() as uow:
            return await uow.risks.get("risk-1")

    risk = asyncio.run(scenario())
    assert risk.lifecycle_state is RiskLifecycleState.EXISTING
    assert risk.review_disposition is not ReviewDisposition.EXCLUDED


def test_the_users_judgement_survives_a_round_trip() -> None:
    """이것이 1-D 에서 가장 성가신 것이었다.

    파일을 잠깐 옮겼다 되돌리는 것만으로 **사용자가 검토해 수용한 판단이 조용히
    지워졌다.** 판본이 그대로면 그 판단도 그대로 유효하다.
    """

    async def scenario():
        store, intake = await _seed_with_risk(ReviewDisposition.ACCEPTED_RISK)
        await _leave(intake)
        await _return(intake, revision="revision-1")
        async with store() as uow:
            risk = await uow.risks.get("risk-1")
            events = await uow.risks.list_events("risk-1")
        return risk, events

    risk, events = asyncio.run(scenario())
    assert risk.review_disposition is ReviewDisposition.ACCEPTED_RISK
    assert any(
        event.new_state_safe.get("disposition_restored") is True for event in events
    )


def test_a_file_that_comes_back_changed_starts_over() -> None:
    """"제외되어 있던 동안 세상이 달라졌다" 는 근거는 **판본이 달라진 경우에만** 선다.

    그때는 사용자가 그때 본 것과 지금 것이 다르므로 다시 검토해야 한다.
    """

    async def scenario():
        store, intake = await _seed_with_risk(ReviewDisposition.ACCEPTED_RISK)
        await _leave(intake)
        await _return(intake, revision="revision-2")
        async with store() as uow:
            return await uow.risks.get("risk-1")

    risk = asyncio.run(scenario())
    assert risk.review_disposition is ReviewDisposition.UNREVIEWED


def test_an_ordinary_update_revives_nothing() -> None:
    """되살리기는 **추적 밖에 있던 파일**에만 붙는다.

    평범한 변경마다 돌면 사용자가 방금 내린 제외 처분을 다음 저장이 되돌린다.
    """

    async def scenario():
        store, intake = await _seed_with_risk(ReviewDisposition.EXCLUDED)
        # 이탈 없이 그냥 새 판본이 온다.
        await _return(intake, revision="revision-2", fingerprint="fingerprint-plain")
        async with store() as uow:
            return await uow.risks.get("risk-1")

    risk = asyncio.run(scenario())
    assert risk.review_disposition is ReviewDisposition.EXCLUDED


def test_restoring_never_puts_back_an_exclusion() -> None:
    """되살리기는 제외를 **되돌리는** 것이지 제외를 복원하는 것이 아니다.

    실제로는 `exclude_risks` 가 이미 제외된 것을 건너뛰므로 이력에 제외→제외가
    남지 않는다. 그래도 막아 둔다 — 그 전제가 깨지면 되살리기가 제외를 되살린다.
    """
    import inspect

    from ip_risk_agent.application import risk_exclusion

    source = inspect.getsource(risk_exclusion._disposition_before_exclusion)
    assert "restored is ReviewDisposition.EXCLUDED" in source


def test_leaving_twice_does_not_pile_up_history() -> None:
    """같은 파일이 두 번 사라져도 이력이 부풀지 않는다."""

    async def scenario():
        store, intake = await _seed_with_risk(ReviewDisposition.UNREVIEWED)
        await _leave(intake)
        await intake.register_source_change(
            make_change(
                fingerprint="fingerprint-gone-again",
                change_type=ChangeType.DELETE,
                revision=None,
                previous_revision="revision-1",
            )
        )
        async with store() as uow:
            return await uow.risks.list_events("risk-1")

    events = asyncio.run(scenario())
    closed = [
        event
        for event in events
        if event.reason_safe == "SOURCE_ARTIFACT_UNTRACKED"
    ]
    assert len(closed) == 1
