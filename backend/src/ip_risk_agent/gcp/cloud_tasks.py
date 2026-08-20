"""ID-only Cloud Tasks enqueue adapter with deterministic de-duplication."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit

from google.api_core import exceptions as google_exceptions
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
        digest = hashlib.sha256(change_event_id.encode("utf-8")).hexdigest()
        body = json.dumps(
            {"change_event_id": change_event_id},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        task = tasks_v2.Task(
            name=f"{self._parent}/tasks/change-{digest}",
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
        except google_exceptions.AlreadyExists:
            return
        except Exception as exc:
            raise TaskEnqueueError("Cloud Tasks enqueue failed") from exc


__all__ = ["CloudTasksEnqueuer"]
