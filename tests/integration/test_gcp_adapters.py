from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from google.api_core import exceptions as google_exceptions
from iprisk_contracts import SourceType

from ip_risk_agent.composition.device_auth import (
    DesktopDevice,
    DeviceMountBinding,
    DeviceStatus,
    EnrollmentChallenge,
)
from ip_risk_agent.composition.source_registration import (
    PendingConnectionStatus,
    PendingSourceConnection,
    SourceMountBinding,
)
from ip_risk_agent.connectors.common.credential_vault import (
    CredentialRef,
    CredentialScope,
)
from ip_risk_agent.connectors.common.runtime_store import DriveRuntime
from ip_risk_agent.connectors.github.tracking_scope import GitHubTrackingScope
from ip_risk_agent.connectors.local.staging_store import StagingRef
from ip_risk_agent.gcp import (
    CloudStorageLocalStagingStore,
    CloudTasksEnqueuer,
    FirestoreDeviceAuthStore,
    FirestoreOAuthStateStore,
    FirestorePendingConnectionStore,
    FirestoreRuntimeStore,
    GoogleCloudFoundation,
    GoogleOidcTaskAuthenticator,
    SecretManagerCredentialVault,
    SecretManagerRuntimeSecretReader,
)
from ip_risk_agent.gcp_contract import DYNAMIC_CREDENTIAL_SECRET_PREFIX


class MemoryOperationalBackend:
    def __init__(self) -> None:
        self.documents: dict[tuple[str, str], dict] = {}

    async def get(self, collection, document_id):
        value = self.documents.get((collection, document_id))
        return None if value is None else dict(value)

    async def put(self, collection, document_id, data):
        self.documents[(collection, document_id)] = dict(data)

    async def delete(self, collection, document_id):
        self.documents.pop((collection, document_id), None)

    async def query_one(self, collection, field, value):
        for (candidate, _), document in self.documents.items():
            if candidate == collection and _nested(document, field) == value:
                return dict(document)
        return None

    async def query_many(self, collection, filters, *, limit):
        matches = []
        for (candidate, _), document in self.documents.items():
            if candidate == collection and all(
                _nested(document, field) == value
                for field, value in filters.items()
            ):
                matches.append(dict(document))
        return tuple(matches[:limit])

    async def consume_unexpired(self, collection, document_id, now):
        document = self.documents.get((collection, document_id))
        if (
            document is None
            or document.get("consumed_at") is not None
            or document["expires_at"] <= now
        ):
            return None
        document["consumed_at"] = now
        return dict(document)


def run(awaitable):
    return asyncio.run(awaitable)


def _nested(document: dict, field: str):
    value = document
    for component in field.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(component)
    return value


def test_google_cloud_foundation_exposes_durable_container_overrides() -> None:
    async def close_extra() -> None:
        return None

    foundation = GoogleCloudFoundation(
        clients=SimpleNamespace(firestore=object(), secret_manager=object(), cloud_tasks=object()),
        unit_of_work_factory=object(),
        operational_backend=object(),
        task_enqueuer=object(),
        credential_vault=object(),
        staging_store=object(),
        device_auth_store=object(),
    )
    overrides = foundation.container_overrides(close_callbacks=(close_extra,))
    assert overrides.unit_of_work_factory is foundation.unit_of_work_factory
    assert overrides.task_enqueuer is foundation.task_enqueuer
    assert overrides.device_auth_store is foundation.device_auth_store
    assert overrides.close_callbacks == (close_extra, foundation.close)


def test_firestore_operational_state_roundtrips_without_raw_lookup_keys() -> None:
    async def scenario() -> None:
        backend = MemoryOperationalBackend()
        now = datetime(2026, 8, 21, tzinfo=timezone.utc)
        oauth = FirestoreOAuthStateStore(backend, clock=lambda: now)
        await oauth.save("raw-oauth-state", {"risk_workspace_id": "vws-1"})
        assert "raw-oauth-state" not in repr(backend.documents)
        assert await oauth.consume("raw-oauth-state") == {"risk_workspace_id": "vws-1"}
        assert await oauth.consume("raw-oauth-state") is None

        runtime = FirestoreRuntimeStore(
            backend,
            collection="source_operational_drive_runtime",
            model=DriveRuntime,
        )
        await runtime.save("connection-1", DriveRuntime(connection_id="connection-1"))
        assert (await runtime.load("connection-1")).connection_id == "connection-1"

        pending_store = FirestorePendingConnectionStore(backend)
        credential = CredentialRef(
            provider=SourceType.GOOGLE_DRIVE,
            connection_id="pending-1",
            secret_name="oauth-token",
            key_id="projects/p/secrets/s",
        )
        pending = PendingSourceConnection(
            id="pending-1",
            idempotency_key="idempotency-1",
            source_type=SourceType.GOOGLE_DRIVE,
            risk_workspace_id="vws-1",
            owner_user_id="user-1",
            provider_subject="subject-1",
            provider_account_label="owner@example.com",
            credential_ref=credential,
            installation_id=None,
            status=PendingConnectionStatus.PENDING,
            created_at=now,
            expires_at=now + timedelta(minutes=30),
        )
        await pending_store.save_pending(pending)
        assert (await pending_store.get_pending_by_key("idempotency-1")) == pending
        binding = SourceMountBinding("pending-1", "connection-1", "source-1", "mount-1", "reg-1")
        await pending_store.save_binding(binding)
        assert await pending_store.get_binding_for_mount("mount-1") == binding

    run(scenario())


def test_firestore_runtime_store_supports_bounded_operational_lookup() -> None:
    async def scenario() -> None:
        backend = MemoryOperationalBackend()
        store = FirestoreRuntimeStore(
            backend,
            collection="source_operational_github_tracking",
            model=GitHubTrackingScope,
        )
        scope = GitHubTrackingScope(
            mount_id="mount-1",
            owner="owner",
            repo="repo",
            default_branch="main",
            tracked_branch="main",
        )
        await store.save(scope.mount_id, scope)
        assert await store.find_one("mount_id", "mount-1") == scope
        assert await store.find_many({"owner": "owner", "repo": "repo"}) == (
            scope,
        )

    run(scenario())


def test_firestore_device_store_rotates_credential_lookup() -> None:
    async def scenario() -> None:
        backend = MemoryOperationalBackend()
        store = FirestoreDeviceAuthStore(backend)
        now = datetime(2026, 8, 21, tzinfo=timezone.utc)
        challenge = EnrollmentChallenge(
            "token-hash", "owner-1", 2, now, now + timedelta(minutes=5)
        )
        await store.save_challenge(challenge)
        assert await store.get_challenge("token-hash") == challenge
        first = DesktopDevice(
            "device-1", "Laptop", "owner-1", 2, "credential-a", DeviceStatus.ACTIVE, now
        )
        second = DesktopDevice(
            "device-1", "Laptop", "owner-1", 2, "credential-b", DeviceStatus.ACTIVE, now
        )
        await store.save_device(first)
        await store.save_device(second)
        assert await store.get_device_by_credential("credential-a") is None
        assert await store.get_device_by_credential("credential-b") == second
        binding = DeviceMountBinding("device-1", "vws-1", "mount-1")
        await store.save_mount_binding(binding)
        assert await store.get_mount_binding("mount-1") == binding

    run(scenario())


class FakeTasksClient:
    def __init__(self) -> None:
        self.calls = []

    def queue_path(self, project, location, queue):
        return f"projects/{project}/locations/{location}/queues/{queue}"

    async def create_task(self, *, parent, task):
        self.calls.append((parent, task))


def test_cloud_tasks_payload_is_id_only_oidc_and_deterministic() -> None:
    async def scenario() -> None:
        client = FakeTasksClient()
        queue = CloudTasksEnqueuer(
            client=client,
            project_id="project-1",
            location="asia-northeast3",
            queue="analysis",
            worker_base_url="https://worker.example.run.app",
            service_account_email="tasks@example.iam.gserviceaccount.com",
        )
        await queue.enqueue_change("change-1")
        await queue.enqueue_change("change-1")
        first = client.calls[0][1]
        second = client.calls[1][1]
        assert first.name == second.name
        assert json.loads(first.http_request.body) == {"change_event_id": "change-1"}
        assert first.http_request.oidc_token.audience == "https://worker.example.run.app"
        assert first.dispatch_deadline.seconds == 240

    run(scenario())


class FakeSecretClient:
    def __init__(self) -> None:
        self.secrets: set[str] = set()
        self.versions: dict[str, list[bytes]] = {}
        self.disabled: list[str] = []
        self.created: list[dict] = []

    async def create_secret(self, *, parent, secret_id, secret):
        name = f"{parent}/secrets/{secret_id}"
        if name in self.secrets:
            raise google_exceptions.AlreadyExists("exists")
        self.secrets.add(name)
        self.created.append(secret)

    async def add_secret_version(self, *, parent, payload):
        self.versions.setdefault(parent, []).append(payload["data"])

    async def access_secret_version(self, *, name):
        parent = name.removesuffix("/versions/latest")
        if parent not in self.versions:
            raise google_exceptions.NotFound("missing")
        return SimpleNamespace(payload=SimpleNamespace(data=self.versions[parent][-1]))

    async def disable_secret_version(self, *, name):
        self.disabled.append(name)


class FakeRuntimeSecretClient:
    def __init__(self) -> None:
        self.names: list[str] = []

    def access_secret_version(self, *, name):
        self.names.append(name)
        return SimpleNamespace(payload=SimpleNamespace(data=b"runtime-secret"))


def test_secret_manager_vault_uses_opaque_project_scoped_reference() -> None:
    async def scenario() -> None:
        client = FakeSecretClient()
        vault = SecretManagerCredentialVault(
            client=client,
            project_id="project-1",
            secret_prefix=DYNAMIC_CREDENTIAL_SECRET_PREFIX,
        )
        scope = CredentialScope(
            provider=SourceType.GOOGLE_DRIVE,
            connection_id="connection-with-private-identity",
            secret_name="oauth-token",
        )
        ref = await vault.put(scope, "token-a")
        assert "connection-with-private-identity" not in ref.key_id
        assert f"/secrets/{DYNAMIC_CREDENTIAL_SECRET_PREFIX}-google_drive-" in ref.key_id
        assert client.created[0]["labels"] == {
            "owner": "ip-risk-agent-v2",
            "environment": "v2",
            "provider": "google_drive",
        }
        assert await vault.get(ref) == "token-a"
        await vault.update(ref, "token-b")
        assert await vault.get(ref) == "token-b"
        await vault.delete(ref)
        assert client.disabled == [f"{ref.key_id}/versions/latest"]

    run(scenario())


def test_secret_manager_vault_rejects_v1_and_non_v2_references() -> None:
    async def scenario() -> None:
        vault = SecretManagerCredentialVault(
            client=FakeSecretClient(),
            project_id="project-1",
            secret_prefix=DYNAMIC_CREDENTIAL_SECRET_PREFIX,
        )
        for secret_id in (
            "ipra-drive-token",
            "iprisk-google_drive-" + "a" * 40,
            "iprisk-v2-other-google_drive-" + "a" * 40,
        ):
            ref = CredentialRef(
                provider=SourceType.GOOGLE_DRIVE,
                connection_id="connection-1",
                secret_name="oauth-token",
                key_id=f"projects/project-1/secrets/{secret_id}",
            )
            with pytest.raises(ValueError, match="outside"):
                await vault.get(ref)

    run(scenario())


def test_runtime_secret_reader_uses_project_scoped_latest_version() -> None:
    client = FakeRuntimeSecretClient()
    reader = SecretManagerRuntimeSecretReader(client=client, project_id="project-1")
    assert reader.access("github-private-key") == "runtime-secret"
    assert client.names == [
        "projects/project-1/secrets/github-private-key/versions/latest"
    ]
    with pytest.raises(ValueError, match="secret ID"):
        reader.access("../outside-project")


class FakeBlob:
    def __init__(self, name: str) -> None:
        self.name = name
        self.data: bytes | None = None
        self.metadata = None
        self.cache_control = None

    def upload_from_string(self, data, **_kwargs):
        self.data = bytes(data)

    def download_as_bytes(self):
        if self.data is None:
            raise google_exceptions.NotFound("missing")
        return self.data

    def delete(self):
        self.data = None


class FakeBucket:
    def __init__(self) -> None:
        self.blobs: dict[str, FakeBlob] = {}
        self.iam_configuration = SimpleNamespace(uniform_bucket_level_access_enabled=True)

    def blob(self, name):
        return self.blobs.setdefault(name, FakeBlob(name))

    def reload(self):
        return None


class FakeStorageClient:
    def __init__(self) -> None:
        self.value = FakeBucket()

    def bucket(self, _name):
        return self.value


def test_gcs_staging_is_private_bounded_and_rejects_path_metadata() -> None:
    async def scenario() -> None:
        client = FakeStorageClient()
        staging = CloudStorageLocalStagingStore(client=client, bucket_name="private")
        await staging.validate_bucket()
        ref = await staging.put("print(1)", {"revision": "r1"})
        assert ref.object_name.startswith("staging/")
        assert await staging.get(ref) == "print(1)"
        with pytest.raises(ValueError):
            await staging.put("print(2)", {"local_path": "C:/private"})
        await staging.delete(ref)

    run(scenario())


def request_with_bearer(token: str):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/internal/tasks/analyze-change",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
    )


def test_oidc_authenticator_checks_exact_verified_service_account() -> None:
    async def scenario() -> None:
        def verify(token, _request, audience):
            assert token == "signed-token"
            assert audience == "https://worker.example.run.app"
            return {"email": "tasks@example.iam.gserviceaccount.com", "email_verified": True}

        auth = GoogleOidcTaskAuthenticator(
            audience="https://worker.example.run.app",
            service_account_email="tasks@example.iam.gserviceaccount.com",
            verifier=verify,
        )
        await auth(request_with_bearer("signed-token"))

        denied = GoogleOidcTaskAuthenticator(
            audience="https://worker.example.run.app",
            service_account_email="other@example.iam.gserviceaccount.com",
            verifier=verify,
        )
        with pytest.raises(HTTPException) as error:
            await denied(request_with_bearer("signed-token"))
        assert error.value.status_code == 403

    run(scenario())
