from __future__ import annotations

import pytest

from ip_risk_agent.composition.container import build_container
from ip_risk_agent.composition.settings import (
    AppRole,
    RuntimeProfile,
    Settings,
    SettingsError,
)


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

    production = Settings(
        profile=RuntimeProfile.PRODUCTION,
        role=AppRole.WORKER,
        log_level="INFO",
        public_base_url="https://worker.example.com",
        session_secret="",
        gcp_project_id="project-1",
        gcp_region="asia-northeast3",
        firestore_database="(default)",
        google_login_client_id="login-client",
        google_login_client_secret="login-secret",
        google_login_redirect_uri="https://api.example.com/api/v1/auth/google/callback",
        drive_client_id="drive-client",
        drive_client_secret="drive-secret",
        drive_redirect_uri="https://api.example.com/drive/callback",
        drive_webhook_base_url="https://api.example.com/webhooks/google-drive",
        drive_watch_channel_token="channel-token",
        google_picker_api_key="restricted-browser-key",
        google_cloud_project_number="123456789012",
        github_app_id="app-1",
        github_app_slug="ip-risk-agent",
        github_private_key_secret_id="github-key",
        github_webhook_secret_id="github-webhook",
        github_app_callback_url="https://api.example.com/github/callback",
        local_staging_bucket="staging-bucket",
        cloud_tasks_location="asia-northeast3",
        cloud_tasks_queue="analysis",
        analysis_worker_url="https://worker.example.com/internal/tasks/analyze-change",
        cloud_tasks_service_account="worker-invoker@example.iam.gserviceaccount.com",
        vertex_config="asia-northeast3",
        kipris_api_key_secret_id="kipris-key",
        package_metadata_base_url="https://packages.example.com",
    )
    with pytest.raises(SettingsError, match="explicit Firestore adapter"):
        build_container(production)


def test_production_settings_are_role_scoped() -> None:
    common = {
        "APP_ENV": "production",
        "APP_PUBLIC_BASE_URL": "https://api.example.com",
        "GCP_PROJECT_ID": "project-1",
        "GCP_REGION": "asia-northeast3",
        "FIRESTORE_DATABASE": "(default)",
        "LOCAL_STAGING_BUCKET": "staging-bucket",
        "GOOGLE_DRIVE_CLIENT_ID": "drive-client",
        "GOOGLE_DRIVE_CLIENT_SECRET": "drive-secret",
        "GITHUB_APP_ID": "app-1",
        "GITHUB_APP_PRIVATE_KEY_SECRET_ID": "github-key",
        "ANALYSIS_WORKER_URL": "https://worker.example.com",
        "CLOUD_TASKS_SERVICE_ACCOUNT": "tasks@example.iam.gserviceaccount.com",
    }
    worker = Settings.from_env(
        {
            **common,
            "APP_ROLE": "worker",
            "VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG": "asia-northeast3",
            "KIPRIS_API_KEY_SECRET_ID": "kipris-key",
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
            "GOOGLE_CLOUD_PROJECT_NUMBER": "123456789012",
            "GITHUB_APP_SLUG": "ip-risk-agent",
            "GITHUB_WEBHOOK_SECRET_ID": "github-webhook",
            "GITHUB_APP_CALLBACK_URL": "https://api.example.com/api/v1/source-connections/github/install/callback",
            "CLOUD_TASKS_LOCATION": "asia-northeast3",
            "CLOUD_TASKS_QUEUE": "analysis-changes",
            "SCHEDULER_SERVICE_ACCOUNT": "scheduler@example.iam.gserviceaccount.com",
        }
    )
    assert api.role is AppRole.API
    assert api.vertex_config is None
    assert api.kipris_api_key_secret_id is None
