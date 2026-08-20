"""GitHub webhook 라우터. Agent 2 Spec 37번 namespace(/webhooks/github)를
구현한다. Agent 2 Spec 3번: auth/control dependency는 injection한다 —
이 라우터는 Agent 1(Control) 내부를 import하지 않는다.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from ..common.change_sink import SourceChangeSink
from ..common.errors import InvalidWebhookError, NotFoundError
from .mount_resolver import GitHubMountResolver
from .webhook_processor import GitHubWebhookProcessor


def create_github_webhook_router(
    *,
    webhook_processor: GitHubWebhookProcessor,
    mount_resolver: GitHubMountResolver,
    change_sink: SourceChangeSink,
) -> APIRouter:
    router = APIRouter()

    @router.post("/webhooks/github")
    async def handle_github_webhook(request: Request) -> dict:
        raw_body = await request.body()
        signature_header = request.headers.get("X-Hub-Signature-256")
        delivery_id = request.headers.get("X-GitHub-Delivery", "")
        event_name = request.headers.get("X-GitHub-Event", "")

        if event_name != "push":
            return {"status": "ignored", "reason": "unsupported_event"}

        try:
            payload = json.loads(raw_body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON payload") from exc

        repo_full_name = payload.get("repository", {}).get("full_name", "")
        owner, _, repo = repo_full_name.partition("/")
        if not owner or not repo:
            raise HTTPException(status_code=400, detail="missing repository information")

        mounts = await mount_resolver.resolve_mounts(owner, repo)

        processed_counts: list[int] = []
        for mount in mounts:
            try:
                changes = await webhook_processor.process_push_event(
                    mount,
                    raw_body=raw_body,
                    signature_header=signature_header,
                    delivery_id=delivery_id,
                    payload=payload,
                )
            except InvalidWebhookError as exc:
                raise HTTPException(status_code=401, detail="invalid webhook signature") from exc
            except NotFoundError:
                continue

            for change in changes:
                await change_sink.persist(change)
            processed_counts.append(len(changes))

        return {
            "status": "ok",
            "mounts_processed": len(processed_counts),
            "changes_persisted": sum(processed_counts),
        }

    return router
