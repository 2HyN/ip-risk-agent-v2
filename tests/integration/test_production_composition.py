from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient
from iprisk_contracts import AnalysisType, SourceType

import ip_risk_agent.composition.production as production
import ip_risk_agent.gcp.foundation as foundation_module
import ip_risk_agent.main as api_entrypoint
import ip_risk_agent.worker as worker_entrypoint
from ip_risk_agent.composition.container import (
    ContainerOverrides,
    RuntimeComposition,
    build_container,
)
from ip_risk_agent.composition.providers import SourceRouterBundle
from ip_risk_agent.composition.settings import AppRole, Settings, SettingsError
from ip_risk_agent.gcp.foundation import (
    GoogleCloudClients,
    GoogleCloudFoundation,
    build_google_cloud_foundation,
)
from ip_risk_agent.gcp.identity import GoogleOidcTaskAuthenticator
from ip_risk_agent.gcp_contract import (
    DRIVE_SERVICE_ACCOUNT,
    DYNAMIC_CREDENTIAL_SECRET_PREFIX,
    FIRESTORE_DATABASE,
    FIXED_SECRET_IDS,
    PROJECT_ID,
    PROJECT_NUMBER,
    REGION,
    SCHEDULER_SERVICE_ACCOUNT,
    STAGING_BUCKET,
    TASK_QUEUE,
    TASKS_SERVICE_ACCOUNT,
    WORKER_BASE_URL,
)


class FakeSecretReader:
    def access(self, secret_id: str) -> str:
        return {
            FIXED_SECRET_IDS["github_private_key"]: "test-private-key",
            FIXED_SECRET_IDS["github_webhook"]: "test-webhook-secret",
            FIXED_SECRET_IDS["kipris"]: "test-kipris-key",
        }[secret_id]


class FakeAdapter:
    def __init__(self, source_type: SourceType) -> None:
        self.source_type = source_type


class FakeIntelligence:
    active_analysis_types = (AnalysisType.PATENT, AnalysisType.LICENSE)

    async def analyze(self, _artifact):
        return []


class FakeTaskAuthenticator:
    async def __call__(self, _request) -> None:
        return None


class FakeModelClient:
    model_id = "fake-vertex-model"

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def generate(self, _prompt, _output_model):
        raise AssertionError("startup must not call Gemini")


def _settings(role: AppRole, *, frontend_dist_dir: str = "/app/frontend/dist") -> Settings:
    common = {
        "APP_ENV": "production",
        "APP_ROLE": role.value,
        "APP_PUBLIC_BASE_URL": (
            "https://api.example.com" if role is AppRole.API else WORKER_BASE_URL
        ),
        "GCP_PROJECT_ID": PROJECT_ID,
        "GCP_REGION": REGION,
        "FIRESTORE_DATABASE": FIRESTORE_DATABASE,
        "LOCAL_STAGING_BUCKET": STAGING_BUCKET,
        "GOOGLE_DRIVE_SERVICE_ACCOUNT": DRIVE_SERVICE_ACCOUNT,
        "GITHUB_APP_ID": "app-1",
        "GITHUB_APP_PRIVATE_KEY_SECRET_ID": FIXED_SECRET_IDS[
            "github_private_key"
        ],
        "SOURCE_CREDENTIAL_SECRET_PREFIX": DYNAMIC_CREDENTIAL_SECRET_PREFIX,
    }
    if role is AppRole.API:
        common.update(
            {
                "SESSION_SECRET": "s" * 32,
                "FRONTEND_DIST_DIR": frontend_dist_dir,
                "GOOGLE_LOGIN_CLIENT_ID": "login-client",
                "GOOGLE_LOGIN_CLIENT_SECRET": "login-secret",
                "GOOGLE_LOGIN_REDIRECT_URI": "https://api.example.com/api/v1/auth/google/callback",
                "GOOGLE_DRIVE_SERVICE_ACCOUNT": DRIVE_SERVICE_ACCOUNT,
                "GOOGLE_DRIVE_WEBHOOK_BASE_URL": "https://api.example.com/webhooks/google-drive",
                "DRIVE_WATCH_CHANNEL_TOKEN": "channel-token",
                                "GOOGLE_CLOUD_PROJECT_NUMBER": PROJECT_NUMBER,
                "GITHUB_APP_SLUG": "ip-risk-agent-v2",
                "GITHUB_WEBHOOK_SECRET_ID": FIXED_SECRET_IDS["github_webhook"],
                "GITHUB_APP_CALLBACK_URL": "https://api.example.com/api/v1/source-connections/github/install/callback",
                "CLOUD_TASKS_LOCATION": REGION,
                "CLOUD_TASKS_QUEUE": TASK_QUEUE,
                "ANALYSIS_WORKER_URL": WORKER_BASE_URL,
                "CLOUD_TASKS_SERVICE_ACCOUNT": TASKS_SERVICE_ACCOUNT,
                "SCHEDULER_SERVICE_ACCOUNT": SCHEDULER_SERVICE_ACCOUNT,
            }
        )
    else:
        common.update(
            {
                "VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG": REGION,
                "KIPRIS_API_KEY_SECRET_ID": FIXED_SECRET_IDS["kipris"],
                "PACKAGE_METADATA_BASE_URL": "https://api.deps.dev/v3",
            }
        )
    return Settings.from_env(common)


def _foundation(role: AppRole) -> GoogleCloudFoundation:
    return GoogleCloudFoundation(
        clients=SimpleNamespace(
            firestore=object(),
            secret_manager=object(),
            cloud_tasks=object() if role is AppRole.API else None,
            storage=object(),
            runtime_secrets=FakeSecretReader(),
        ),
        unit_of_work_factory=object(),
        operational_backend=object(),
        task_enqueuer=object() if role is AppRole.API else None,
        credential_vault=object(),
        staging_store=object(),
        device_auth_store=object(),
    )


def test_real_production_composer_builds_role_specific_complete_containers(monkeypatch) -> None:
    api_settings = _settings(AppRole.API)
    api_foundation = _foundation(AppRole.API)
    api = build_container(
        api_settings,
        overrides=api_foundation.container_overrides(
            runtime_composer=production.build_google_cloud_runtime_composer(api_foundation)
        ),
    )
    assert set(api.adapters.source_types) == set(SourceType)
    assert api.pipeline is None
    assert {check.name: check.detail_safe for check in api.health.checks}[
        "task_queue"
    ] == "configured"
    assert api.source_routers.web and api.source_routers.webhooks
    assert api.source_routers.desktop
    assert {
        "/internal/scheduler/drive-watch-renewal",
        "/internal/scheduler/drive-reconciliation",
        "/internal/scheduler/expired-state-cleanup",
        "/internal/scheduler/source-health-refresh",
    } <= {
        route.path
        for router in api.extra_api_routers
        for route in router.routes
    }

    monkeypatch.setattr(production, "GoogleGenAIClient", FakeModelClient)
    worker_settings = _settings(AppRole.WORKER)
    worker_foundation = _foundation(AppRole.WORKER)
    worker = build_container(
        worker_settings,
        overrides=worker_foundation.container_overrides(
            runtime_composer=production.build_google_cloud_runtime_composer(
                worker_foundation
            )
        ),
    )
    assert set(worker.adapters.source_types) == set(SourceType)
    assert worker.pipeline is not None
    assert {check.name: check.detail_safe for check in worker.health.checks}[
        "task_queue"
    ] == "not_applicable"
    assert isinstance(worker.task_authenticator, GoogleOidcTaskAuthenticator)
    assert worker.task_authenticator._audience == WORKER_BASE_URL
    assert worker.task_authenticator._service_account == TASKS_SERVICE_ACCOUNT
    assert worker_foundation.task_enqueuer is None


def test_google_cloud_foundation_creates_cloud_tasks_only_for_api() -> None:
    storage = SimpleNamespace(bucket=lambda _name: object())
    api = build_google_cloud_foundation(
        _settings(AppRole.API),
        clients=GoogleCloudClients(
            firestore=object(),
            secret_manager=object(),
            cloud_tasks=SimpleNamespace(
                queue_path=lambda project, location, queue: (
                    f"projects/{project}/locations/{location}/queues/{queue}"
                )
            ),
            storage=storage,
            runtime_secrets=FakeSecretReader(),
        ),
    )
    assert api.task_enqueuer is not None

    worker = build_google_cloud_foundation(
        _settings(AppRole.WORKER),
        clients=GoogleCloudClients(
            firestore=object(),
            secret_manager=object(),
            cloud_tasks=None,
            storage=storage,
            runtime_secrets=FakeSecretReader(),
        ),
    )
    assert worker.task_enqueuer is None


def test_google_cloud_clients_use_explicit_v2_named_database_for_worker(
    monkeypatch,
) -> None:
    firestore_calls: list[dict] = []
    monkeypatch.setattr(
        foundation_module.firestore,
        "AsyncClient",
        lambda **kwargs: firestore_calls.append(kwargs) or object(),
    )
    monkeypatch.setattr(
        foundation_module.secretmanager,
        "SecretManagerServiceAsyncClient",
        lambda: object(),
    )
    monkeypatch.setattr(
        foundation_module.secretmanager,
        "SecretManagerServiceClient",
        lambda: object(),
    )
    monkeypatch.setattr(
        foundation_module.storage,
        "Client",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        foundation_module.tasks_v2,
        "CloudTasksAsyncClient",
        lambda: (_ for _ in ()).throw(
            AssertionError("Worker must not create a Cloud Tasks client")
        ),
    )
    clients = GoogleCloudClients.create(_settings(AppRole.WORKER))
    assert firestore_calls == [
        {"project": PROJECT_ID, "database": FIRESTORE_DATABASE}
    ]
    assert clients.cloud_tasks is None


def test_production_entrypoints_use_foundation_and_runtime_composer(
    monkeypatch,
    tmp_path,
) -> None:
    (tmp_path / "index.html").write_text("<main>production</main>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    calls: list[tuple[str, AppRole]] = []

    class EntrypointFoundation:
        def __init__(self, role: AppRole) -> None:
            self.role = role

        def container_overrides(self, *, runtime_composer):
            calls.append(("overrides", self.role))
            return ContainerOverrides(
                unit_of_work_factory=object(),
                task_enqueuer=object() if self.role is AppRole.API else None,
                device_auth_store=object(),
                runtime_composer=runtime_composer,
            )

    def fake_foundation(settings):
        calls.append(("foundation", settings.role))
        return EntrypointFoundation(settings.role)

    def fake_composer(foundation):
        calls.append(("composer", foundation.role))

        def compose(_context):
            adapters = tuple(FakeAdapter(source_type) for source_type in SourceType)
            if foundation.role is AppRole.API:
                return RuntimeComposition(
                    source_adapters=adapters,
                    source_routers=SourceRouterBundle(
                        web=(APIRouter(),),
                        webhooks=(APIRouter(),),
                        desktop=(APIRouter(),),
                    ),
                )
            return RuntimeComposition(
                source_adapters=adapters,
                intelligence=FakeIntelligence(),
                task_authenticator=FakeTaskAuthenticator(),
            )

        return compose

    for module in (api_entrypoint, worker_entrypoint):
        monkeypatch.setattr(module, "build_google_cloud_foundation", fake_foundation)
        monkeypatch.setattr(module, "build_google_cloud_runtime_composer", fake_composer)

    api_values = _environment(AppRole.API, frontend_dist_dir=str(tmp_path))
    with monkeypatch.context() as scoped:
        for key, value in api_values.items():
            scoped.setenv(key, value)
        api_app = api_entrypoint.create_app()
        assert "/health/ready" in api_app.openapi()["paths"]
        product = TestClient(api_app).get("/app")
        assert product.status_code == 200
        assert product.text == "<main>production</main>"

    with monkeypatch.context() as scoped:
        worker_values = _environment(AppRole.WORKER)
        assert "FRONTEND_DIST_DIR" not in worker_values
        scoped.delenv("FRONTEND_DIST_DIR", raising=False)
        for key, value in worker_values.items():
            scoped.setenv(key, value)
        worker_app = worker_entrypoint.create_app()
        assert "/internal/tasks/analyze-change" in worker_app.openapi()["paths"]

    assert calls == [
        ("foundation", AppRole.API),
        ("composer", AppRole.API),
        ("overrides", AppRole.API),
        ("foundation", AppRole.WORKER),
        ("composer", AppRole.WORKER),
        ("overrides", AppRole.WORKER),
    ]


def test_production_worker_entrypoint_rejects_inherited_api_image_environment(
    monkeypatch,
) -> None:
    values = {
        **_environment(AppRole.WORKER),
        "FRONTEND_DIST_DIR": "/app/frontend/dist",
    }
    with monkeypatch.context() as scoped:
        for key, value in values.items():
            scoped.setenv(key, value)
        with pytest.raises(SettingsError, match="API-only"):
            worker_entrypoint.create_app()


def test_local_entrypoints_keep_in_memory_path(monkeypatch) -> None:
    def unexpected_foundation(_settings):
        raise AssertionError("local entrypoint must not create Google Cloud clients")

    monkeypatch.setattr(
        api_entrypoint,
        "build_google_cloud_foundation",
        unexpected_foundation,
    )
    monkeypatch.setattr(
        worker_entrypoint,
        "build_google_cloud_foundation",
        unexpected_foundation,
    )
    with monkeypatch.context() as scoped:
        scoped.setenv("APP_ENV", "local")
        scoped.setenv("APP_ROLE", "api")
        scoped.setenv("SESSION_SECRET", "l" * 32)
        scoped.setenv("APP_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
        assert "/health/ready" in api_entrypoint.create_app().openapi()["paths"]
    with monkeypatch.context() as scoped:
        scoped.setenv("APP_ENV", "local")
        scoped.setenv("APP_ROLE", "worker")
        scoped.setenv("APP_PUBLIC_BASE_URL", "http://127.0.0.1:8000")
        assert (
            "/internal/tasks/analyze-change"
            in worker_entrypoint.create_app().openapi()["paths"]
        )


def _environment(
    role: AppRole,
    *,
    frontend_dist_dir: str = "/app/frontend/dist",
) -> dict[str, str]:
    settings = _settings(role, frontend_dist_dir=frontend_dist_dir)
    values = {
        "APP_ENV": settings.profile.value,
        "APP_ROLE": settings.role.value,
        "APP_PUBLIC_BASE_URL": settings.public_base_url,
        "GCP_PROJECT_ID": settings.gcp_project_id or "",
        "GCP_REGION": settings.gcp_region or "",
        "FIRESTORE_DATABASE": settings.firestore_database or "",
        "LOCAL_STAGING_BUCKET": settings.local_staging_bucket or "",
        "GOOGLE_DRIVE_SERVICE_ACCOUNT": settings.drive_service_account or "",
        "GITHUB_APP_ID": settings.github_app_id or "",
        "GITHUB_APP_PRIVATE_KEY_SECRET_ID": settings.github_private_key_secret_id or "",
        "SOURCE_CREDENTIAL_SECRET_PREFIX": settings.source_credential_secret_prefix,
    }
    role_values = {
        field: value
        for field, value in {
            "SESSION_SECRET": settings.session_secret,
            "FRONTEND_DIST_DIR": settings.frontend_dist_dir,
            "GOOGLE_LOGIN_CLIENT_ID": settings.google_login_client_id,
            "GOOGLE_LOGIN_CLIENT_SECRET": settings.google_login_client_secret,
            "GOOGLE_LOGIN_REDIRECT_URI": settings.google_login_redirect_uri,
            "GOOGLE_DRIVE_WEBHOOK_BASE_URL": settings.drive_webhook_base_url,
            "DRIVE_WATCH_CHANNEL_TOKEN": settings.drive_watch_channel_token,
            "GOOGLE_CLOUD_PROJECT_NUMBER": settings.google_cloud_project_number,
            "GITHUB_APP_SLUG": settings.github_app_slug,
            "GITHUB_WEBHOOK_SECRET_ID": settings.github_webhook_secret_id,
            "GITHUB_APP_CALLBACK_URL": settings.github_app_callback_url,
            "CLOUD_TASKS_LOCATION": settings.cloud_tasks_location,
            "CLOUD_TASKS_QUEUE": settings.cloud_tasks_queue,
            "ANALYSIS_WORKER_URL": settings.analysis_worker_url,
            "CLOUD_TASKS_SERVICE_ACCOUNT": settings.cloud_tasks_service_account,
            "SCHEDULER_SERVICE_ACCOUNT": settings.scheduler_service_account,
            "VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG": settings.vertex_config,
            "KIPRIS_API_KEY_SECRET_ID": settings.kipris_api_key_secret_id,
            "PACKAGE_METADATA_BASE_URL": settings.package_metadata_base_url,
        }.items()
        if value is not None
    }
    return {**values, **role_values}
