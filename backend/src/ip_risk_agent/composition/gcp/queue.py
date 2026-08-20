"""Cloud Tasks 기반 ``TaskEnqueuer``.

Protocol 이 요구하는 것은 두 가지다 (application/process_change/queue.py).

1. payload 는 canonical ID 하나뿐이다. 원본이나 자격증명을 싣지 않는다.
2. **같은 ID 는 de-duplicate 해야 한다.**

2번을 Cloud Tasks 의 ``name`` 으로 구현한다. task 이름을 change_event_id 에서
결정론적으로 만들면 같은 ID 로 두 번 넣을 때 ``AlreadyExists`` 가 나고, 그것을
정상으로 처리하면 중복 실행이 사라진다.

주의 — Cloud Tasks 는 삭제된 task 이름을 약 1시간 재사용하지 못한다. 이는
"짧은 시간 안의 중복만 막는다"는 뜻이며, 그 이상 지난 뒤의 재시도는 정상적으로
새 task 가 된다. Control 쪽 idempotency 가 최종 방어선이다.
"""

from __future__ import annotations

import asyncio
import hashlib

from ip_risk_agent.application.process_change.queue import TaskEnqueueError

_TASK_PREFIX = "change-"


def task_name_for(change_event_id: str) -> str:
    """change_event_id 를 Cloud Tasks task 이름으로 바꾼다.

    canonical ID 는 길고 ``:`` 를 포함하는데 task 이름은 영숫자·하이픈·언더스코어
    500자 이하만 허용한다. 해시로 고정 길이 안전 문자열을 만든다.
    같은 입력은 항상 같은 이름이 되어야 de-dup 이 성립한다.
    """
    digest = hashlib.sha256(change_event_id.encode("utf-8")).hexdigest()
    return f"{_TASK_PREFIX}{digest}"


class CloudTasksEnqueuer:
    """``TaskEnqueuer`` Protocol 의 운영 구현."""

    def __init__(
        self,
        *,
        project_id: str,
        location: str,
        queue: str,
        worker_url: str,
        service_account_email: str,
        client: object | None = None,
    ) -> None:
        for name, value in (
            ("project_id", project_id),
            ("location", location),
            ("queue", queue),
            ("worker_url", worker_url),
            ("service_account_email", service_account_email),
        ):
            if not value:
                raise ValueError(f"cloud tasks {name} is required")
        self._project_id = project_id
        self._location = location
        self._queue = queue
        self._worker_url = worker_url
        self._service_account_email = service_account_email
        self._client = client

    def _sdk(self):
        if self._client is None:
            from google.cloud import tasks_v2  # noqa: PLC0415 - 지연 import

            self._client = tasks_v2.CloudTasksClient()
        return self._client

    @property
    def queue_path(self) -> str:
        return (
            f"projects/{self._project_id}/locations/{self._location}"
            f"/queues/{self._queue}"
        )

    def _enqueue_sync(self, change_event_id: str) -> None:
        import json  # noqa: PLC0415

        from google.api_core import exceptions  # noqa: PLC0415

        parent = self.queue_path
        body = json.dumps({"change_event_id": change_event_id}).encode("utf-8")
        task = {
            "name": f"{parent}/tasks/{task_name_for(change_event_id)}",
            "http_request": {
                "http_method": "POST",
                "url": self._worker_url,
                "headers": {"Content-Type": "application/json"},
                "body": body,
                # 워커는 이 토큰으로 호출자가 Cloud Tasks 임을 확인한다.
                "oidc_token": {
                    "service_account_email": self._service_account_email,
                    "audience": self._worker_url,
                },
            },
        }
        try:
            self._sdk().create_task(request={"parent": parent, "task": task})
        except exceptions.AlreadyExists:
            # 같은 change_event_id 가 이미 큐에 있다. 이것이 de-dup 이며 정상이다.
            return

    async def enqueue_change(self, change_event_id: str) -> None:
        if not change_event_id:
            raise TaskEnqueueError("change_event_id must not be empty")
        try:
            await asyncio.to_thread(self._enqueue_sync, change_event_id)
        except TaskEnqueueError:
            raise
        except Exception as exc:  # noqa: BLE001 - SDK 예외 종류가 넓다
            # 큐 적재 실패를 성공으로 바꾸지 않는다. 여기서 삼키면 변경이
            # 조용히 분석되지 않은 채 사라진다.
            raise TaskEnqueueError(
                f"failed to enqueue change event: {type(exc).__name__}"
            ) from exc


__all__ = ["CloudTasksEnqueuer", "task_name_for"]
