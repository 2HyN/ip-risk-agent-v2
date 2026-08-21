from __future__ import annotations

import pytest

from ip_risk_agent.composition.container import build_container
from ip_risk_agent.composition.settings import (
    AppRole,
    RuntimeProfile,
    Settings,
    SettingsError,
)
from ip_risk_agent.gcp_contract import (
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


def _production_common() -> dict[str, str]:
    return {
        "APP_ENV": "production",
        "APP_PUBLIC_BASE_URL": WORKER_BASE_URL,
        "GCP_PROJECT_ID": PROJECT_ID,
        "GCP_REGION": REGION,
        "FIRESTORE_DATABASE": FIRESTORE_DATABASE,
        "LOCAL_STAGING_BUCKET": STAGING_BUCKET,
        "GOOGLE_DRIVE_CLIENT_ID": "drive-client",
        "GOOGLE_DRIVE_CLIENT_SECRET": "drive-secret",
        "GITHUB_APP_ID": "app-1",
        "GITHUB_APP_PRIVATE_KEY_SECRET_ID": FIXED_SECRET_IDS[
            "github_private_key"
        ],
        "SOURCE_CREDENTIAL_SECRET_PREFIX": DYNAMIC_CREDENTIAL_SECRET_PREFIX,
    }


def test_settings_reject_partial_groups_and_short_api_session_secret() -> None:
    with pytest.raises(SettingsError, match="SESSION_SECRET"):
        Settings.from_env(
            {
                "APP_ENV": "local",
                "APP_ROLE": "api",
                "SESSION_SECRET": "short",
            }
        )
    with pytest.raises(SettingsError, match="Cloud Tasks publisher.*all set"):
        Settings.from_env(
            {
                "APP_ENV": "test",
                "APP_ROLE": "worker",
                "CLOUD_TASKS_QUEUE": "analysis",
            }
        )
    with pytest.raises(SettingsError, match="Google Picker.*all set"):
        Settings.from_env(
            {
                "APP_ENV": "test",
                "APP_ROLE": "worker",
                "GOOGLE_PICKER_API_KEY": "browser-key-without-project-number",
            }
        )


def test_local_worker_allows_absent_external_groups_but_production_never_falls_back() -> None:
    local = Settings.from_env(
        {
            "APP_ENV": "local",
            "APP_ROLE": "worker",
            "APP_PUBLIC_BASE_URL": "http://127.0.0.1:8000",
        }
    )
    assert local.profile is RuntimeProfile.LOCAL
    assert not local.drive_enabled and not local.github_enabled

    production = Settings.from_env(
        {
            **_production_common(),
            "APP_ROLE": "worker",
            "VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG": REGION,
            "KIPRIS_API_KEY_SECRET_ID": FIXED_SECRET_IDS["kipris"],
            "PACKAGE_METADATA_BASE_URL": "https://packages.example.com",
        }
    )
    with pytest.raises(SettingsError, match="explicit Firestore adapter"):
        build_container(production)


def test_production_settings_are_role_scoped() -> None:
    common = _production_common()
    worker = Settings.from_env(
        {
            **common,
            "APP_ROLE": "worker",
            "VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG": REGION,
            "KIPRIS_API_KEY_SECRET_ID": FIXED_SECRET_IDS["kipris"],
            "PACKAGE_METADATA_BASE_URL": "https://api.deps.dev/v3",
        }
    )
    assert worker.role is AppRole.WORKER
    assert worker.cloud_tasks_location is None
    assert worker.google_login_client_id is None
    assert worker.scheduler_service_account is None

    api = Settings.from_env(
        {
            **common,
            "APP_ROLE": "api",
            "SESSION_SECRET": "s" * 32,
            "FRONTEND_DIST_DIR": "/app/frontend/dist",
            "GOOGLE_LOGIN_CLIENT_ID": "login-client",
            "GOOGLE_LOGIN_CLIENT_SECRET": "login-secret",
            "GOOGLE_LOGIN_REDIRECT_URI": "https://api.example.com/api/v1/auth/google/callback",
            "GOOGLE_DRIVE_REDIRECT_URI": "https://api.example.com/api/v1/source-connections/google-drive/callback",
            "GOOGLE_DRIVE_WEBHOOK_BASE_URL": "https://api.example.com/webhooks/google-drive",
            "DRIVE_WATCH_CHANNEL_TOKEN": "channel-token",
            "GOOGLE_PICKER_API_KEY": "picker-key",
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
    assert api.role is AppRole.API
    assert api.vertex_config is None
    assert api.kipris_api_key_secret_id is None


def test_production_v2_rejects_default_database_and_non_v2_namespace() -> None:
    values = {
        **_production_common(),
        "APP_ROLE": "worker",
        "VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG": REGION,
        "KIPRIS_API_KEY_SECRET_ID": FIXED_SECRET_IDS["kipris"],
        "PACKAGE_METADATA_BASE_URL": "https://api.deps.dev/v3",
    }
    with pytest.raises(SettingsError, match="FIRESTORE_DATABASE='ip-risk-agent-v2'"):
        Settings.from_env({**values, "FIRESTORE_DATABASE": "(default)"})
    with pytest.raises(SettingsError, match="FIRESTORE_DATABASE='ip-risk-agent-v2'"):
        Settings.from_env({**values, "FIRESTORE_DATABASE": "ip-risk-agent-v3"})
    with pytest.raises(SettingsError, match="FIRESTORE_EMULATOR_HOST"):
        Settings.from_env(
            {**values, "FIRESTORE_EMULATOR_HOST": "127.0.0.1:8080"}
        )
    with pytest.raises(SettingsError, match="GCP_PROJECT_ID"):
        Settings.from_env({**values, "GCP_PROJECT_ID": "legacy-project"})
    with pytest.raises(SettingsError, match="GITHUB_APP_PRIVATE_KEY_SECRET_ID"):
        Settings.from_env(
            {**values, "GITHUB_APP_PRIVATE_KEY_SECRET_ID": "ipra-github-key"}
        )
    with pytest.raises(SettingsError, match="SOURCE_CREDENTIAL_SECRET_PREFIX"):
        Settings.from_env(
            {**values, "SOURCE_CREDENTIAL_SECRET_PREFIX": "iprisk-google-drive"}
        )


def test_production_worker_is_deployable_without_api_or_task_publisher_settings() -> None:
    values = {
        **_production_common(),
        "APP_ROLE": "worker",
        "VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG": REGION,
        "KIPRIS_API_KEY_SECRET_ID": FIXED_SECRET_IDS["kipris"],
        "PACKAGE_METADATA_BASE_URL": "https://api.deps.dev/v3",
    }
    worker = Settings.from_env(values)
    assert worker.analysis_worker_url is None
    assert worker.cloud_tasks_service_account is None
    assert worker.cloud_tasks_queue is None
    with pytest.raises(SettingsError, match="API-only"):
        Settings.from_env(
            {
                **values,
                "ANALYSIS_WORKER_URL": WORKER_BASE_URL,
                "CLOUD_TASKS_SERVICE_ACCOUNT": TASKS_SERVICE_ACCOUNT,
            }
        )
    with pytest.raises(SettingsError, match="API-only"):
        Settings.from_env(
            {
                **values,
                "FRONTEND_DIST_DIR": "/app/frontend/dist",
            }
        )


def test_production_rejects_role_reversal_and_partial_rag_configuration() -> None:
    worker_values = {
        **_production_common(),
        "APP_ROLE": "worker",
        "VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG": REGION,
        "KIPRIS_API_KEY_SECRET_ID": FIXED_SECRET_IDS["kipris"],
        "PACKAGE_METADATA_BASE_URL": "https://api.deps.dev/v3",
    }
    with pytest.raises(SettingsError, match="RAG.*all set"):
        Settings.from_env({**worker_values, "RAG_REGION": REGION})
    with pytest.raises(SettingsError, match="Worker-only"):
        Settings.from_env(
            {
                **worker_values,
                "APP_ROLE": "api",
                "SESSION_SECRET": "s" * 32,
                "FRONTEND_DIST_DIR": "/app/frontend/dist",
                "GOOGLE_LOGIN_CLIENT_ID": "login-client",
                "GOOGLE_LOGIN_CLIENT_SECRET": "login-secret",
                "GOOGLE_LOGIN_REDIRECT_URI": "https://api.example.com/api/v1/auth/google/callback",
                "GOOGLE_DRIVE_REDIRECT_URI": "https://api.example.com/api/v1/source-connections/google-drive/callback",
                "GOOGLE_DRIVE_WEBHOOK_BASE_URL": "https://api.example.com/webhooks/google-drive",
                "DRIVE_WATCH_CHANNEL_TOKEN": "channel-token",
                "GOOGLE_PICKER_API_KEY": "picker-key",
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


def test_configure_logging_emits_structured_diagnostics_to_stdout(capsys) -> None:
    """구조화 진단이 실제로 stdout 으로 나가야 한다.

    logging 설정이 없으면 root 기본 레벨이 WARNING 이라 StructuredLogger 의
    info() 기록이 전부 사라진다. 배포에서 4xx 의 diagnostic_code 를 볼 수 없어
    원인을 매번 추측해야 했다.
    """
    import json
    import logging

    from ip_risk_agent.application.observability import StructuredLogger
    from ip_risk_agent.composition.runtime import configure_logging

    logger = logging.getLogger("ip_risk_agent")
    previous_handlers = list(logger.handlers)
    previous_level = logger.level
    previous_propagate = logger.propagate
    try:
        logger.handlers.clear()
        configure_logging("INFO")
        configure_logging("INFO")  # 중복 배선은 handler 를 늘리지 않는다.
        assert len(logger.handlers) == 1

        StructuredLogger().event("probe_event", diagnostic_code="probe_code")
        written = capsys.readouterr().out.strip().splitlines()
        assert written, "structured diagnostics must reach stdout"
        record = json.loads(written[-1])
        assert record["event"] == "probe_event"
        assert record["diagnostic_code"] == "probe_code"
    finally:
        logger.handlers.clear()
        logger.handlers.extend(previous_handlers)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
