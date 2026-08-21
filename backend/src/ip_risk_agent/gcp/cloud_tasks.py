"""ID-only Cloud Tasks enqueue adapter."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from google.cloud import tasks_v2
from google.protobuf import duration_pb2

from ip_risk_agent.application.process_change.queue import TaskEnqueueError
from ip_risk_agent.core.common import require_non_empty


class CloudTasksEnqueuer:
    def __init__(
        self,
        *,
        client,
        project_id: str,
        location: str,
        queue: str,
        worker_base_url: str,
        service_account_email: str,
        dispatch_deadline_seconds: int = 240,
    ) -> None:
        endpoint = worker_base_url.rstrip("/") + "/internal/tasks/analyze-change"
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username:
            raise ValueError("Cloud Tasks worker URL must be HTTPS without userinfo")
        if not 1 <= dispatch_deadline_seconds < 300:
            raise ValueError("dispatch deadline must be between 1 and 299 seconds")
        self._client = client
        self._parent = client.queue_path(project_id, location, queue)
        self._endpoint = endpoint
        self._audience = worker_base_url.rstrip("/")
        self._service_account = require_non_empty(
            service_account_email, "cloud_tasks.service_account"
        )
        self._deadline = dispatch_deadline_seconds

    async def enqueue_change(self, change_event_id: str) -> None:
        change_event_id = require_non_empty(
            change_event_id, "cloud_tasks.change_event_id"
        )
        body = json.dumps(
            {"change_event_id": change_event_id},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        # 작업 이름을 지정하지 않는다. Cloud Tasks 는 실행이 끝난 이름을 일정 기간
        # tombstone 으로 기억하므로, 결정적 이름을 쓰면 실패한 이벤트의 재큐잉이
        # AlreadyExists 로 조용히 버려진다 — 큐에는 없는데 "이미 있음"으로 처리되고
        # 오류는 어디에도 남지 않는다. "실패를 성공으로 바꾸지 않는다"는 불변조건과
        # 정면으로 충돌한다.
        #
        # 중복 투입 방어는 이 이름이 아니라 상위 계층이 이미 한다 — SourceChange
        # fingerprint 의 canonical idempotency 와 claim 단계의 lease 다. 같은 이벤트가
        # 두 번 디스패치되면 두 번째 claim 이 빈손으로 끝난다.
        task = tasks_v2.Task(
            dispatch_deadline=duration_pb2.Duration(seconds=self._deadline),
            http_request=tasks_v2.HttpRequest(
                http_method=tasks_v2.HttpMethod.POST,
                url=self._endpoint,
                headers={"Content-Type": "application/json"},
                body=body,
                oidc_token=tasks_v2.OidcToken(
                    service_account_email=self._service_account,
                    audience=self._audience,
                ),
            ),
        )
        try:
            await self._client.create_task(parent=self._parent, task=task)
        except Exception as exc:
            raise TaskEnqueueError("Cloud Tasks enqueue failed") from exc


__all__ = ["CloudTasksEnqueuer"]
