"""이력이 원인을 실제로 적는가 (§7.4 · 3-B 합격 기준).

판별식만 재는 시험은 **배선이 어긋나도 통과한다.** 코드에 `_cause_state(attribution)`
이라 적혀 있다는 사실과, 조정을 두 번 돌렸을 때 이력에 `change_cause` 가 남는다는 것은
다르다. 여기서는 조정을 실제로 두 번 돌리고 저장된 이력을 읽는다.

명세의 합격 기준은 하나다 — **파일을 건드리지 않고 corpus 만 올렸을 때 이력이 원인을
"우리 지식" 으로 적는다** (§11.5).
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

from iprisk_contracts import AnalysisType
from iprisk_contracts.analysis_result import AnalysisVersions
from iprisk_contracts.common import ReviewPriority

from ip_risk_agent.core.risk.attribution import ChangeCause

from test_analysis_result_reconciliation import (
    NOW,
    add_running_job,
    make_service,
    patent_result,
    seed_artifact_context,
)

CHECKSUM = "sha256:analysis-input-1"


async def _job_with_checksum(store, *, suffix, offset, checksum=CHECKSUM):
    job_id, started_at = await add_running_job(
        store, suffix=suffix, revision="revision-1", offset_seconds=offset
    )
    async with store() as uow:
        job = await uow.analysis_jobs.get(job_id)
        assert job is not None
        await uow.analysis_jobs.save(
            replace(job, analysis_input_checksum=checksum)
        )
        await uow.commit()
    return job_id, started_at


def _versions(**overrides) -> AnalysisVersions:
    base = dict(
        analyzer_version="patent-v1",
        model_id="model-v1",
        prompt_version="prompt-v1",
        policy_version="vws-1:table-1:axesA",
        rag_corpus_version="2026-08-23.4",
    )
    base.update(overrides)
    return AnalysisVersions(**base)


async def _causes(store, job_id):
    """이 작업이 남긴 이력들의 원인."""
    found = []
    async with store() as uow:
        risks = await uow.risks.list_for_artifact("artifact-1", AnalysisType.PATENT)
        for risk in risks:
            for event in await uow.risks.list_events(risk.id):
                if event.analysis_job_id == job_id:
                    found.append(event.new_state_safe.get("change_cause"))
    return found


async def _two_runs(second_versions, *, second_priority, second_checksum=CHECKSUM):
    """같은 파일을 두 번 판정한다. 두 번째 판정이 남긴 원인을 돌려준다."""
    store = await seed_artifact_context()
    service = make_service(store)

    first_job, first_started = await _job_with_checksum(store, suffix="one", offset=0)
    first = patent_result(first_job, "revision-1", first_started)
    await service.accept_analysis_result(
            first.model_copy(update={"versions": _versions()})
        )

    second_job, second_started = await _job_with_checksum(
        store, suffix="two", offset=60, checksum=second_checksum
    )
    second = patent_result(
        second_job, "revision-1", second_started, priority=second_priority
    )
    await service.accept_analysis_result(
        second.model_copy(update={"versions": second_versions})
    )
    return await _causes(store, second_job)


def test_bumping_the_corpus_without_touching_the_file_reads_as_our_knowledge() -> None:
    """§11.5 의 3-B 합격 기준 그대로다."""
    causes = asyncio.run(
        _two_runs(
            _versions(rag_corpus_version="2026-08-24.1"),
            second_priority=ReviewPriority.MEDIUM,
        )
    )
    assert causes, "이력이 남지 않았다"
    assert ChangeCause.OUR_KNOWLEDGE.value in causes


def test_nothing_of_ours_moved_reads_as_an_external_fact() -> None:
    """이 제품이 파는 문장이다 — 당신은 가만있었는데 위험이 생겼다.

    입력도 우리 쪽 지문도 그대로인데 등급이 달라졌다.
    """
    causes = asyncio.run(
        _two_runs(_versions(), second_priority=ReviewPriority.MEDIUM)
    )
    assert ChangeCause.EXTERNAL_FACT.value in causes


def test_a_changed_input_reads_as_the_user_changing_the_file() -> None:
    causes = asyncio.run(
        _two_runs(
            _versions(),
            second_priority=ReviewPriority.MEDIUM,
            second_checksum="sha256:analysis-input-2",
        )
    )
    assert ChangeCause.INPUT.value in causes


def test_a_changed_deployment_form_reads_as_the_user_changing_a_setting() -> None:
    """우리 표가 좋아진 것과 사용자가 설정을 바꾼 것은 전혀 다른 문장이다."""
    causes = asyncio.run(
        _two_runs(
            _versions(policy_version="vws-1:table-1:axesB"),
            second_priority=ReviewPriority.MEDIUM,
        )
    )
    assert ChangeCause.USER_POLICY.value in causes


def test_an_older_record_without_a_checksum_reads_as_unknown() -> None:
    """이행 없이 배포하면 옛 작업에는 체크섬이 없다.

    그때 "외부 사실이 바뀌었다" 로 적으면 이 제품이 파는 문장이 거짓말이 된다.
    """

    async def scenario():
        store = await seed_artifact_context()
        service = make_service(store)

        # 첫 판정은 체크섬 없이 남는다 — 이 기능 이전에 저장된 작업이다.
        first_job, first_started = await add_running_job(
            store, suffix="one", revision="revision-1"
        )
        first = patent_result(first_job, "revision-1", first_started)
        await service.accept_analysis_result(
            first.model_copy(update={"versions": _versions()})
        )

        second_job, second_started = await _job_with_checksum(
            store, suffix="two", offset=60
        )
        second = patent_result(
            second_job, "revision-1", second_started, priority=ReviewPriority.MEDIUM
        )
        await service.accept_analysis_result(
            second.model_copy(update={"versions": _versions()})
        )
        return await _causes(store, second_job)

    assert ChangeCause.UNKNOWN.value in asyncio.run(scenario())


def test_the_checksum_survives_a_round_trip_through_firestore() -> None:
    """저장되지 않으면 위의 모든 판별이 배포에서 `UNKNOWN` 이 된다."""
    from ip_risk_agent.application.analysis_jobs import AnalysisJob, AnalysisJobStatus
    from ip_risk_agent.persistence.core_firestore.mappers import (
        analysis_job_from_document,
        analysis_job_to_document,
    )

    job = AnalysisJob(
        id="job-1",
        change_event_id="change-1",
        artifact_id="artifact-1",
        revision="revision-1",
        requested_analysis_types=(AnalysisType.LICENSE,),
        status=AnalysisJobStatus.QUEUED,
        created_at=NOW,
        analysis_input_checksum=CHECKSUM,
    )
    document = analysis_job_to_document(job)
    assert analysis_job_from_document(document).analysis_input_checksum == CHECKSUM

    # 이 필드가 없던 시절의 문서도 읽혀야 한다. 배포가 곧 데이터 손실이면 안 된다.
    older = dict(document)
    older.pop("analysis_input_checksum")
    assert analysis_job_from_document(older).analysis_input_checksum is None
