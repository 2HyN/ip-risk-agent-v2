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
    with pytest.raises(SettingsError, match="Cloud Tasks.*all set"):
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
    with pytest.raises(SettingsError, match="explicit Firestore and Cloud Tasks"):
        build_container(production)
