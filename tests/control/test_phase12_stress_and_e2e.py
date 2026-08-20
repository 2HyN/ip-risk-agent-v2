from __future__ import annotations

import asyncio
from datetime import timedelta

from iprisk_contracts import (
    AnalysisCoverage,
    AnalysisResult,
    AnalysisStatus,
    AnalysisType,
    AnalysisVersions,
    ArtifactKind,
    ContentScope,
    Evidence,
    EvidenceType,
    PatentCandidate,
    ReviewPriority,
    SegmentKind,
    SourceAccessReceipt,
    SourceAccessType,
    SourceSnapshot,
    TextSegment,
)
from ip_risk_agent.application.observability import StructuredLogger
from ip_risk_agent.application.process_change import InMemoryTaskEnqueuer
from ip_risk_agent.application.public_facade import (
    ControlPlaneFacade,
    ControlPlaneFacadeConfig,
    SourceAccessReceiptContext,
)
from ip_risk_agent.application.repositories import (
    ConcurrencyConflictError,
    InMemoryControlStore,
)
from ip_risk_agent.application.risk_review import (
    RiskReviewConflictError,
    RiskReviewDisposition as ReviewResultDisposition,
    RiskReviewService,
)
from ip_risk_agent.core.risk import ReviewDisposition, RiskEventType
from test_public_facade import (
    NOW,
    MutableClock,
    SequentialIds,
    make_change,
    seed_workspace,
    source_command,
)


class MemorySink:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def write(self, record: dict[str, object]) -> None:
        self.records.append(record)


def test_concurrent_control_pipeline_is_idempotent_and_observable() -> None:
    async def scenario() -> None:
        store = InMemoryControlStore()
        queue = InMemoryTaskEnqueuer()
        clock = MutableClock()
        sink = MemorySink()
        await seed_workspace(store)
        facade = ControlPlaneFacade(
            unit_of_work_factory=store,
            task_enqueuer=queue,
            clock=clock,
            id_factory=SequentialIds(),
            config=ControlPlaneFacadeConfig(
                requested_analysis_types=(AnalysisType.PATENT,),
                concurrency_attempts=64,
            ),
            observer=StructuredLogger(sink),
        )
        source = await facade.register_source_metadata(source_command())
        change = make_change(source)

        registrations = await asyncio.gather(
            *(facade.register_source_change(change) for _ in range(32))
        )
        assert sum(item.disposition == "CREATED" for item in registrations) == 1
        assert len({item.change_event_id for item in registrations}) == 1
        assert len({item.analysis_job_id for item in registrations}) == 1
        assert queue.pending_ids == (registrations[0].change_event_id,)

        clock.current = NOW + timedelta(seconds=2)
        claims = await asyncio.gather(
            *(facade.claim_analysis(registrations[0].change_event_id) for _ in range(32))
        )
        claimed = [item for item in claims if item is not None]
        assert len(claimed) == 1
        claim = claimed[0]

        receipt = SourceAccessReceipt(
            access_type=SourceAccessType.FULL_CONTENT,
            provider_request_id="provider-request-stress-1",
            content_bytes=23,
            occurred_at=NOW + timedelta(seconds=3),
        )
        await facade.register_source_access(
            SourceAccessReceiptContext(
                risk_workspace_id="vws-1",
                mount_id=source.mount_id,
                source_workspace_id=source.source_workspace_id,
                source_type=change.source_type,
                source_artifact_id=change.artifact.source_artifact_id,
                revision="revision-failure",
                receipt=receipt,
                analysis_job_id=claim.analysis_job_id,
            )
        )
        snapshot = SourceSnapshot(
            contract_version="1",
            risk_workspace_id="vws-1",
            mount_id=source.mount_id,
            source_workspace_id=source.source_workspace_id,
            source_type=change.source_type,
            source_artifact_id=change.artifact.source_artifact_id,
            resolved_revision="revision-failure",
            retrieved_at=NOW + timedelta(seconds=3),
            display_name="failure.py",
            logical_path_hint="src/failure.py",
            mime_type="text/x-python",
            artifact_kind=ArtifactKind.SOURCE_CODE,
            content_scope=ContentScope.FULL_TEXT,
            text_segments=[
                TextSegment(
                    segment_id="segment-1",
                    text="def candidate_rank(): return True",
                    line_start=1,
                    line_end=1,
                    segment_kind=SegmentKind.CHANGED,
                )
            ],
            checksum="sha256:revision-failure",
            byte_size=23,
            source_access_receipt=receipt,
        )
        clock.current = NOW + timedelta(seconds=3)
        artifact = await facade.build_analysis_artifact(snapshot, claim.analysis_job_id)
        assert artifact.approved and artifact.analysis_artifact is not None

        result = AnalysisResult(
            contract_version="1",
            analysis_job_id=claim.analysis_job_id,
            artifact_id=registrations[0].artifact_id,
            revision="revision-failure",
            analysis_type=AnalysisType.PATENT,
            status=AnalysisStatus.SUCCEEDED,
            coverage=AnalysisCoverage.COMPLETE,
            candidates=[
                PatentCandidate(
                    normalized_application_number="KR-10-2026-000012",
                    title="Concurrent candidate ranking",
                    suggested_review_priority=ReviewPriority.HIGH,
                    matched_elements=["candidate ranking"],
                    evidence_ids=["evidence-1"],
                    provider_metadata_safe={"jurisdiction": "KR"},
                )
            ],
            evidence=[
                Evidence(
                    evidence_id="evidence-1",
                    evidence_type=EvidenceType.PATENT_CLAIM,
                    excerpt="A bounded matching claim excerpt.",
                    reference="https://example.invalid/patents/12#claim-1",
                    metadata_safe={"claim": 1},
                )
            ],
            provider_failures=[],
            versions=AnalysisVersions(
                analyzer_version="patent-v1",
                prompt_version="prompt-v1",
            ),
            started_at=NOW + timedelta(seconds=2),
            completed_at=NOW + timedelta(seconds=4),
        )
        clock.current = NOW + timedelta(seconds=5)
        accepted = await asyncio.gather(
            *(facade.accept_analysis_result(result) for _ in range(32))
        )
        assert sum(item.disposition == "ACCEPTED" for item in accepted) == 1
        assert sum(item.disposition == "DUPLICATE" for item in accepted) == 31

        async with store() as uow:
            risks = await uow.risks.list_for_workspace("vws-1")
        assert len(risks) == 1
        risk = risks[0]
        review = RiskReviewService(unit_of_work_factory=store, clock=clock)
        review_results = await asyncio.gather(
            *(
                review.change_disposition(
                    risk_workspace_id="vws-1",
                    actor_user_id="owner-1",
                    risk_id=risk.id,
                    expected_review_version=0,
                    new_disposition=ReviewDisposition.MONITORING,
                    comment="stress review",
                )
                for _ in range(32)
            ),
            return_exceptions=True,
        )
        applied = [
            item
            for item in review_results
            if not isinstance(item, BaseException)
            and item.disposition is ReviewResultDisposition.APPLIED
        ]
        conflicts = [item for item in review_results if isinstance(item, BaseException)]
        assert len(applied) == 1
        assert all(
            isinstance(item, (RiskReviewConflictError, ConcurrencyConflictError))
            for item in conflicts
        )

        async with store() as uow:
            canonical = await uow.risks.get(risk.id)
            events = await uow.risks.list_events(risk.id)
        assert canonical is not None
        assert canonical.review_version == 1
        assert canonical.review_disposition is ReviewDisposition.MONITORING
        assert sum(
            event.event_type is RiskEventType.REVIEW_DISPOSITION_CHANGED
            for event in events
        ) == 1

        completed_records = [
            record
            for record in sink.records
            if record.get("event") == "analysis_result_accepted"
        ]
        assert len(completed_records) == 32
        assert all(record.get("analysis_job_id") == claim.analysis_job_id for record in completed_records)
        assert all(record.get("artifact_id") == registrations[0].artifact_id for record in completed_records)

    asyncio.run(scenario())
