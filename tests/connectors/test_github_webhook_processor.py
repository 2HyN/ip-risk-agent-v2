from __future__ import annotations

import asyncio
import hashlib
import hmac

import pytest

from iprisk_contracts.common import ChangeType, MountRef, SourceType

from ip_risk_agent.connectors.common.errors import InvalidWebhookError, NotFoundError
from ip_risk_agent.connectors.common.runtime_store import InMemoryRuntimeStore
from ip_risk_agent.connectors.github.connection_lookup import (
    GitHubConnectionContext,
    InMemoryGitHubConnectionLookup,
)
from ip_risk_agent.connectors.github.models import GitHubCommit, GitHubCommitFile, GitHubFileContent
from ip_risk_agent.connectors.github.tracking_scope import GitHubTrackingScope
from ip_risk_agent.connectors.github.webhook_processor import GitHubWebhookProcessor

SECRET = "test-webhook-secret"


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


class FakeGitHubProvider:
    def __init__(self, commits: dict[str, GitHubCommit], ipriskignore_text: str | None = None) -> None:
        self._commits = commits
        self._ipriskignore_text = ipriskignore_text

    async def get_installation_token(self):
        raise NotImplementedError

    async def get_default_branch(self, owner, repo):
        raise NotImplementedError

    async def get_commit(self, owner: str, repo: str, sha: str) -> GitHubCommit:
        return self._commits[sha]

    async def get_file_content(self, owner, repo, path, ref):
        if path == ".ipriskignore":
            if self._ipriskignore_text is None:
                from ip_risk_agent.connectors.common.errors import NotFoundError

                raise NotFoundError(provider="github", safe_message=".ipriskignore not found")
            return GitHubFileContent(path=path, sha="ignore-sha", text=self._ipriskignore_text, size=0)
        raise NotImplementedError


class FakeGitHubProviderFactory:
    def __init__(self, provider: FakeGitHubProvider) -> None:
        self._provider = provider

    def create(self, installation_id: str) -> FakeGitHubProvider:
        return self._provider


async def _build_processor(provider: FakeGitHubProvider, *, include_patterns=None, exclude_patterns=None):
    lookup = InMemoryGitHubConnectionLookup()
    lookup.register("mount-1", GitHubConnectionContext(installation_id="inst-1"))
    scope_store = InMemoryRuntimeStore()
    await scope_store.save(
        "mount-1",
        GitHubTrackingScope(
            mount_id="mount-1", owner="acme", repo="widgets", default_branch="main", tracked_branch="main",
            include_patterns=include_patterns or [], exclude_patterns=exclude_patterns or [],
        ),
    )
    runtime_store = InMemoryRuntimeStore()
    processor = GitHubWebhookProcessor(
        provider_factory=FakeGitHubProviderFactory(provider),
        connection_lookup=lookup,
        tracking_scope_store=scope_store,
        runtime_store=runtime_store,
        webhook_secret=SECRET,
    )
    return processor, runtime_store


def _mount() -> MountRef:
    return MountRef(risk_workspace_id="rw1", mount_id="mount-1", source_workspace_id="sw1", source_type=SourceType.GITHUB)


def _push_payload(*, ref: str = "refs/heads/main", commit_shas: list[str] = ["sha1"]) -> dict:
    return {"ref": ref, "commits": [{"id": sha} for sha in commit_shas]}


def test_valid_push_creates_update_change():
    async def scenario():
        commit = GitHubCommit(sha="sha1", files=[GitHubCommitFile(filename="src/a.py", status="modified", previous_filename=None)])
        provider = FakeGitHubProvider(commits={"sha1": commit})
        processor, _ = await _build_processor(provider, include_patterns=["src/**"])

        body = b'{"test": true}'
        changes = await processor.process_push_event(
            _mount(), raw_body=body, signature_header=_sign(body), delivery_id="d1", payload=_push_payload()
        )

        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.UPDATE
        assert changes[0].revision == "sha1"

    asyncio.run(scenario())


def test_invalid_signature_raises():
    async def scenario():
        provider = FakeGitHubProvider(commits={})
        processor, _ = await _build_processor(provider)

        body = b'{"test": true}'
        with pytest.raises(InvalidWebhookError):
            await processor.process_push_event(
                _mount(), raw_body=body, signature_header="sha256=wrong", delivery_id="d1", payload=_push_payload()
            )

    asyncio.run(scenario())


def test_untracked_branch_returns_empty_list():
    async def scenario():
        provider = FakeGitHubProvider(commits={})
        processor, _ = await _build_processor(provider, include_patterns=["src/**"])

        body = b'{"test": true}'
        changes = await processor.process_push_event(
            _mount(), raw_body=body, signature_header=_sign(body), delivery_id="d1",
            payload=_push_payload(ref="refs/heads/feature-branch"),
        )

        assert changes == []

    asyncio.run(scenario())


def test_duplicate_delivery_id_returns_empty_list():
    async def scenario():
        commit = GitHubCommit(sha="sha1", files=[GitHubCommitFile(filename="src/a.py", status="modified", previous_filename=None)])
        provider = FakeGitHubProvider(commits={"sha1": commit})
        processor, runtime_store = await _build_processor(provider, include_patterns=["src/**"])

        body = b'{"test": true}'
        sig = _sign(body)
        first = await processor.process_push_event(
            _mount(), raw_body=body, signature_header=sig, delivery_id="same-delivery", payload=_push_payload()
        )
        second = await processor.process_push_event(
            _mount(), raw_body=body, signature_header=sig, delivery_id="same-delivery", payload=_push_payload()
        )

        assert len(first) == 1
        assert second == []

    asyncio.run(scenario())


def test_skips_files_outside_tracking_scope():
    async def scenario():
        commit = GitHubCommit(
            sha="sha1",
            files=[
                GitHubCommitFile(filename="src/a.py", status="modified", previous_filename=None),
                GitHubCommitFile(filename="customer-data/secret.csv", status="modified", previous_filename=None),
            ],
        )
        provider = FakeGitHubProvider(commits={"sha1": commit})
        processor, _ = await _build_processor(
            provider, include_patterns=["**"], exclude_patterns=["customer-data/**"]
        )

        body = b'{"test": true}'
        changes = await processor.process_push_event(
            _mount(), raw_body=body, signature_header=_sign(body), delivery_id="d1", payload=_push_payload()
        )

        assert len(changes) == 1
        assert changes[0].artifact.display_name == "src/a.py"

    asyncio.run(scenario())


def test_renamed_file_becomes_move_with_previous_artifact():
    async def scenario():
        commit = GitHubCommit(
            sha="sha1",
            files=[GitHubCommitFile(filename="src/new_name.py", status="renamed", previous_filename="src/old_name.py")],
        )
        provider = FakeGitHubProvider(commits={"sha1": commit})
        processor, _ = await _build_processor(provider, include_patterns=["src/**"])

        body = b'{"test": true}'
        changes = await processor.process_push_event(
            _mount(), raw_body=body, signature_header=_sign(body), delivery_id="d1", payload=_push_payload()
        )

        assert len(changes) == 1
        assert changes[0].change_type == ChangeType.MOVE
        assert changes[0].previous_artifact is not None
        assert changes[0].previous_artifact.display_name == "src/old_name.py"

    asyncio.run(scenario())


def test_removed_file_becomes_delete():
    async def scenario():
        commit = GitHubCommit(sha="sha1", files=[GitHubCommitFile(filename="src/gone.py", status="removed", previous_filename=None)])
        provider = FakeGitHubProvider(commits={"sha1": commit})
        processor, _ = await _build_processor(provider, include_patterns=["src/**"])

        body = b'{"test": true}'
        changes = await processor.process_push_event(
            _mount(), raw_body=body, signature_header=_sign(body), delivery_id="d1", payload=_push_payload()
        )

        assert changes[0].change_type == ChangeType.DELETE

    asyncio.run(scenario())


def test_missing_tracking_scope_raises_not_found():
    async def scenario():
        lookup = InMemoryGitHubConnectionLookup()
        scope_store = InMemoryRuntimeStore()
        runtime_store = InMemoryRuntimeStore()
        processor = GitHubWebhookProcessor(
            provider_factory=FakeGitHubProviderFactory(FakeGitHubProvider(commits={})),
            connection_lookup=lookup,
            tracking_scope_store=scope_store,
            runtime_store=runtime_store,
            webhook_secret=SECRET,
        )
        body = b'{"test": true}'
        with pytest.raises(NotFoundError):
            await processor.process_push_event(
                _mount(), raw_body=body, signature_header=_sign(body), delivery_id="d1", payload=_push_payload()
            )

    asyncio.run(scenario())


def test_multiple_commits_are_all_processed():
    async def scenario():
        commit1 = GitHubCommit(sha="sha1", files=[GitHubCommitFile(filename="src/a.py", status="modified", previous_filename=None)])
        commit2 = GitHubCommit(sha="sha2", files=[GitHubCommitFile(filename="src/b.py", status="added", previous_filename=None)])
        provider = FakeGitHubProvider(commits={"sha1": commit1, "sha2": commit2})
        processor, _ = await _build_processor(provider, include_patterns=["src/**"])

        body = b'{"test": true}'
        changes = await processor.process_push_event(
            _mount(), raw_body=body, signature_header=_sign(body), delivery_id="d1",
            payload=_push_payload(commit_shas=["sha1", "sha2"]),
        )

        assert len(changes) == 2

    asyncio.run(scenario())


def test_source_level_ipriskignore_filters_out_matching_files():
    async def scenario():
        commit = GitHubCommit(
            sha="sha1",
            files=[
                GitHubCommitFile(filename="src/a.py", status="modified", previous_filename=None),
                GitHubCommitFile(filename="secrets/key.pem", status="modified", previous_filename=None),
            ],
        )
        provider = FakeGitHubProvider(commits={"sha1": commit}, ipriskignore_text="secrets/**\n")
        processor, _ = await _build_processor(provider, include_patterns=["**"])

        body = b'{"test": true}'
        changes = await processor.process_push_event(
            _mount(), raw_body=body, signature_header=_sign(body), delivery_id="d1", payload=_push_payload()
        )

        assert len(changes) == 1
        assert changes[0].artifact.display_name == "src/a.py"

    asyncio.run(scenario())


def test_no_ipriskignore_present_does_not_block_processing():
    async def scenario():
        commit = GitHubCommit(sha="sha1", files=[GitHubCommitFile(filename="src/a.py", status="modified", previous_filename=None)])
        provider = FakeGitHubProvider(commits={"sha1": commit}, ipriskignore_text=None)
        processor, _ = await _build_processor(provider, include_patterns=["src/**"])

        body = b'{"test": true}'
        changes = await processor.process_push_event(
            _mount(), raw_body=body, signature_header=_sign(body), delivery_id="d1", payload=_push_payload()
        )

        assert len(changes) == 1

    asyncio.run(scenario())
