"""workspace 의 활성 파일 전부를 파일 변경 없이 재검사한다 (검증용 ops).

배포 검증 절차의 마지막 단계 — 남겨 둔 검증 workspace 의 모든 ACTIVE
artifact 에 대해, 제품과 같은 경로(reanalyze 전이 + Cloud Tasks 인큐)로
재검사를 요청한다. worker 가 새 전략(fielded_v5 × hybrid)으로 처리한다.

    python scripts/rescan_workspace.py --workspace-id workspace-XXXX [--confirm]

기본은 dry-run 이다.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from ip_risk_agent.application.analysis_jobs.service import (
    AnalysisJobOrchestrationService,
)
from ip_risk_agent.gcp.cloud_tasks import CloudTasksEnqueuer
from ip_risk_agent.gcp_contract import (
    FIRESTORE_DATABASE,
    PROJECT_ID,
    REGION,
    TASK_QUEUE,
    WORKER_BASE_URL,
)
from ip_risk_agent.persistence.core_firestore import (
    FirestoreControlUnitOfWorkFactory,
)

TASKS_SERVICE_ACCOUNT = f"iprisk-v2-tasks@{PROJECT_ID}.iam.gserviceaccount.com"


async def main_async(workspace_id: str, confirm: bool, failed_only: bool = False) -> int:
    from google.cloud import firestore, tasks_v2

    firestore_client = firestore.AsyncClient(
        project=PROJECT_ID, database=FIRESTORE_DATABASE
    )
    uow_factory = FirestoreControlUnitOfWorkFactory.from_client(firestore_client)

    async with uow_factory() as uow:
        artifacts = await uow.artifacts.list_for_workspace(workspace_id)
        active = [a for a in artifacts if a.status.value == "ACTIVE"]
        events_by_artifact = {}
        for artifact in active:
            events = await uow.change_events.list_for_artifact(artifact.id)
            if not events:
                continue
            latest = max(events, key=lambda event: event.observed_at)
            if failed_only and latest.status.value != "FAILED":
                continue
            events_by_artifact[artifact.id] = latest
    print(
        f"workspace {workspace_id}: ACTIVE 파일 {len(active)}건,"
        f" 재검사 대상(변경 이벤트 보유) {len(events_by_artifact)}건"
    )
    if not confirm:
        print("dry-run — --confirm 을 붙이면 실행한다")
        firestore_client.close()
        return 0

    tasks_client = tasks_v2.CloudTasksAsyncClient()
    enqueuer = CloudTasksEnqueuer(
        client=tasks_client,
        project_id=PROJECT_ID,
        location=REGION,
        queue=TASK_QUEUE,
        worker_base_url=WORKER_BASE_URL,
        service_account_email=TASKS_SERVICE_ACCOUNT,
    )
    service = AnalysisJobOrchestrationService(
        unit_of_work_factory=uow_factory,
        task_enqueuer=enqueuer,
        clock=lambda: datetime.now(timezone.utc),
    )
    requested = skipped = 0
    for artifact_id, event in sorted(events_by_artifact.items()):
        try:
            if failed_only:
                await service.retry_failed(event.id)
            else:
                await service.request_reanalysis(event.id)
            requested += 1
        except Exception as exc:  # noqa: BLE001 — 진행 중이면 거부된다. 정상.
            print(f"  건너뜀 {artifact_id}: {type(exc).__name__}")
            skipped += 1
    print(f"재검사 요청 {requested}건 · 건너뜀 {skipped}건 — worker 처리를 기다린다")
    firestore_client.close()
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--failed-only", action="store_true",
                        help="FAILED 이벤트만 retry_failed 로 재시도")
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args.workspace_id, args.confirm, args.failed_only)))


if __name__ == "__main__":
    main()
