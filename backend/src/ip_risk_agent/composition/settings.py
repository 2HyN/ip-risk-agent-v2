"""Strict runtime settings with profile and configuration-group validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping
from urllib.parse import urlsplit

from iprisk_contracts import AnalysisType


class SettingsError(ValueError):
    pass


class RuntimeProfile(StrEnum):
    TEST = "test"
    LOCAL = "local"
    PRODUCTION = "production"


class AppRole(StrEnum):
    API = "api"
    WORKER = "worker"
    SCHEDULER = "scheduler"


@dataclass(frozen=True, slots=True)
class Settings:
    profile: RuntimeProfile
    role: AppRole
    log_level: str
    public_base_url: str
    session_secret: str = field(repr=False)
    gcp_project_id: str | None = None
    gcp_region: str | None = None
    firestore_database: str | None = None
    frontend_dist_dir: str | None = None
    google_login_client_id: str | None = None
    google_login_client_secret: str | None = field(default=None, repr=False)
    google_login_redirect_uri: str | None = None
    drive_client_id: str | None = None
    drive_client_secret: str | None = field(default=None, repr=False)
    drive_redirect_uri: str | None = None
    drive_webhook_base_url: str | None = None
    drive_watch_channel_token: str | None = field(default=None, repr=False)
    google_picker_api_key: str | None = field(default=None, repr=False)
    google_cloud_project_number: str | None = None
    github_app_id: str | None = None
    github_app_slug: str | None = None
    github_private_key_secret_id: str | None = None
    github_webhook_secret_id: str | None = None
    github_app_callback_url: str | None = None
    local_staging_bucket: str | None = None
    cloud_tasks_location: str | None = None
    cloud_tasks_queue: str | None = None
    analysis_worker_url: str | None = None
    cloud_tasks_service_account: str | None = None
    scheduler_service_account: str | None = None
    gemini_model_id: str = "gemini-3.6-flash"
    gemini_api_key: str | None = field(default=None, repr=False)
    vertex_config: str | None = None
    kipris_api_key_secret_id: str | None = None
    kipris_access_key: str | None = field(default=None, repr=False)
    rag_region: str | None = None
    rag_corpus_id: str | None = None
    rag_corpus_version: str | None = None
    package_metadata_base_url: str | None = None
    requested_analysis_types: tuple[AnalysisType, ...] = (
        AnalysisType.PATENT,
        AnalysisType.LICENSE,
    )

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        def value(name: str) -> str | None:
            item = env.get(name)
            if item is None or not item.strip():
                return None
            return item.strip()

        try:
            profile = RuntimeProfile(value("APP_ENV") or "")
        except ValueError as exc:
            raise SettingsError("APP_ENV must be test, local, or production") from exc
        try:
            role = AppRole(value("APP_ROLE") or "")
        except ValueError as exc:
            raise SettingsError("APP_ROLE must be api, worker, or scheduler") from exc

        settings = cls(
            profile=profile,
            role=role,
            log_level=(value("LOG_LEVEL") or "INFO").upper(),
            public_base_url=value("APP_PUBLIC_BASE_URL") or "http://127.0.0.1:8000",
            session_secret=value("SESSION_SECRET") or "",
            gcp_project_id=value("GCP_PROJECT_ID"),
            gcp_region=value("GCP_REGION"),
            firestore_database=value("FIRESTORE_DATABASE"),
            frontend_dist_dir=value("FRONTEND_DIST_DIR"),
            google_login_client_id=value("GOOGLE_LOGIN_CLIENT_ID"),
            google_login_client_secret=value("GOOGLE_LOGIN_CLIENT_SECRET"),
            google_login_redirect_uri=value("GOOGLE_LOGIN_REDIRECT_URI"),
            drive_client_id=value("GOOGLE_DRIVE_CLIENT_ID"),
            drive_client_secret=value("GOOGLE_DRIVE_CLIENT_SECRET"),
            drive_redirect_uri=value("GOOGLE_DRIVE_REDIRECT_URI"),
            drive_webhook_base_url=value("GOOGLE_DRIVE_WEBHOOK_BASE_URL"),
            drive_watch_channel_token=value("DRIVE_WATCH_CHANNEL_TOKEN"),
            google_picker_api_key=value("GOOGLE_PICKER_API_KEY"),
            google_cloud_project_number=value("GOOGLE_CLOUD_PROJECT_NUMBER"),
            github_app_id=value("GITHUB_APP_ID"),
            github_app_slug=value("GITHUB_APP_SLUG"),
            github_private_key_secret_id=value("GITHUB_APP_PRIVATE_KEY_SECRET_ID"),
            github_webhook_secret_id=value("GITHUB_WEBHOOK_SECRET_ID"),
            github_app_callback_url=value("GITHUB_APP_CALLBACK_URL"),
            local_staging_bucket=value("LOCAL_STAGING_BUCKET"),
            cloud_tasks_location=value("CLOUD_TASKS_LOCATION"),
            cloud_tasks_queue=value("CLOUD_TASKS_QUEUE"),
            analysis_worker_url=value("ANALYSIS_WORKER_URL"),
            cloud_tasks_service_account=value("CLOUD_TASKS_SERVICE_ACCOUNT"),
            scheduler_service_account=value("SCHEDULER_SERVICE_ACCOUNT"),
            gemini_model_id=value("GEMINI_MODEL_ID") or "gemini-3.6-flash",
            gemini_api_key=value("GEMINI_API_KEY"),
            vertex_config=value("VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG"),
            kipris_api_key_secret_id=value("KIPRIS_API_KEY_SECRET_ID"),
            kipris_access_key=value("KIPRIS_ACCESS_KEY"),
            rag_region=value("RAG_REGION"),
            rag_corpus_id=value("RAG_CORPUS_ID"),
            rag_corpus_version=value("RAG_CORPUS_VERSION"),
            package_metadata_base_url=value("PACKAGE_METADATA_BASE_URL"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise SettingsError("LOG_LEVEL is invalid")
        _require_http_url("APP_PUBLIC_BASE_URL", self.public_base_url)
        if self.role is AppRole.API and len(self.session_secret) < 32:
            raise SettingsError("SESSION_SECRET must contain at least 32 characters for API")

        login = (
            self.google_login_client_id,
            self.google_login_client_secret,
            self.google_login_redirect_uri,
        )
        drive_credentials = (self.drive_client_id, self.drive_client_secret)
        drive_api = (
            self.drive_redirect_uri,
            self.drive_webhook_base_url,
            self.drive_watch_channel_token,
        )
        github_credentials = (
            self.github_app_id,
            self.github_private_key_secret_id,
        )
        github_api = (
            self.github_app_slug,
            self.github_webhook_secret_id,
            self.github_app_callback_url,
        )
        picker = (self.google_picker_api_key, self.google_cloud_project_number)
        task_target = (
            self.analysis_worker_url,
            self.cloud_tasks_service_account,
        )
        task_publisher = (
            self.cloud_tasks_location,
            self.cloud_tasks_queue,
        )
        rag = (self.rag_region, self.rag_corpus_id, self.rag_corpus_version)
        _all_or_none("Google login", login)
        _all_or_none("Google Drive credentials", drive_credentials)
        _all_or_none("Google Drive API", drive_api)
        _all_or_none("GitHub App credentials", github_credentials)
        _all_or_none("GitHub App API", github_api)
        _all_or_none("Google Picker", picker)
        _all_or_none("Cloud Tasks target", task_target)
        _all_or_none("Cloud Tasks publisher", task_publisher)
        _all_or_none("RAG", rag)

        for name, url in (
            ("GOOGLE_LOGIN_REDIRECT_URI", self.google_login_redirect_uri),
            ("GOOGLE_DRIVE_REDIRECT_URI", self.drive_redirect_uri),
            ("GOOGLE_DRIVE_WEBHOOK_BASE_URL", self.drive_webhook_base_url),
            ("GITHUB_APP_CALLBACK_URL", self.github_app_callback_url),
            ("ANALYSIS_WORKER_URL", self.analysis_worker_url),
            ("PACKAGE_METADATA_BASE_URL", self.package_metadata_base_url),
        ):
            if url is not None:
                _require_http_url(name, url)

        if self.profile is RuntimeProfile.PRODUCTION:
            if urlsplit(self.public_base_url).scheme != "https":
                raise SettingsError("production APP_PUBLIC_BASE_URL must use HTTPS")
            common_required = {
                "GCP_PROJECT_ID": self.gcp_project_id,
                "GCP_REGION": self.gcp_region,
                "FIRESTORE_DATABASE": self.firestore_database,
                "LOCAL_STAGING_BUCKET": self.local_staging_bucket,
            }
            if self.role is AppRole.API:
                role_required = {
                    "Google login group": login[0] if all(login) else None,
                    "Google Drive credentials": (
                        drive_credentials[0] if all(drive_credentials) else None
                    ),
                    "Google Drive API group": drive_api[0] if all(drive_api) else None,
                    "Google Picker group": picker[0] if all(picker) else None,
                    "GitHub App credentials": (
                        github_credentials[0] if all(github_credentials) else None
                    ),
                    "GitHub App API group": github_api[0] if all(github_api) else None,
                    "Cloud Tasks target": task_target[0] if all(task_target) else None,
                    "Cloud Tasks publisher": (
                        task_publisher[0] if all(task_publisher) else None
                    ),
                    "FRONTEND_DIST_DIR": self.frontend_dist_dir,
                    "SCHEDULER_SERVICE_ACCOUNT": self.scheduler_service_account,
                }
            elif self.role is AppRole.WORKER:
                role_required = {
                    "Google Drive credentials": (
                        drive_credentials[0] if all(drive_credentials) else None
                    ),
                    "GitHub App credentials": (
                        github_credentials[0] if all(github_credentials) else None
                    ),
                    "Cloud Tasks target": task_target[0] if all(task_target) else None,
                    "VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG": self.vertex_config,
                    "KIPRIS_API_KEY_SECRET_ID": self.kipris_api_key_secret_id,
                    "PACKAGE_METADATA_BASE_URL": self.package_metadata_base_url,
                }
            else:
                role_required = {}
            missing = sorted(
                name
                for name, item in {**common_required, **role_required}.items()
                if item is None
            )
            if missing:
                raise SettingsError(
                    "production configuration is incomplete: " + ", ".join(missing)
                )
            if self.gemini_api_key or self.kipris_access_key:
                raise SettingsError(
                    "production provider secrets must use attached identity/Secret Manager"
                )

    @property
    def drive_enabled(self) -> bool:
        return self.drive_client_id is not None

    @property
    def github_enabled(self) -> bool:
        return self.github_app_id is not None

    @property
    def drive_picker_enabled(self) -> bool:
        return (
            self.google_picker_api_key is not None
            and self.google_cloud_project_number is not None
        )

    @property
    def rag_enabled(self) -> bool:
        return self.rag_corpus_id is not None


def _all_or_none(name: str, values: tuple[str | None, ...]) -> None:
    present = sum(item is not None for item in values)
    if present not in {0, len(values)}:
        raise SettingsError(f"{name} configuration must be all set or all absent")


def _require_http_url(name: str, value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username:
        raise SettingsError(f"{name} must be an HTTP(S) URL without userinfo")


__all__ = ["AppRole", "RuntimeProfile", "Settings", "SettingsError"]
