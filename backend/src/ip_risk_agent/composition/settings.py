"""Strict runtime settings with profile and configuration-group validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping
from urllib.parse import urlsplit

from iprisk_contracts import AnalysisType

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
    firestore_emulator_host: str | None = None
    frontend_dist_dir: str | None = None
    google_login_client_id: str | None = None
    google_login_client_secret: str | None = field(default=None, repr=False)
    google_login_redirect_uri: str | None = None
    #: D1 — Drive 접근을 대신하는 서비스 계정 주소. 사용자가 이 주소로 폴더를
    #: 공유한다. 비밀이 아니다 — 이것을 알아도 접근이 생기지 않는다.
    drive_service_account: str | None = None
    drive_webhook_base_url: str | None = None
    drive_watch_channel_token: str | None = field(default=None, repr=False)
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
    #: 특허 고도화 전략 스위치 (docs/PATENT_RAG_ENHANCEMENT_PLAN.md §3·§7.2).
    #: 기본값 baseline — 설정하지 않으면 현행 그대로다. 이름은 분석기 조립에서
    #: 화이트리스트로 검증된다 (오타가 조용히 베이스라인으로 떨어지지 않게).
    patent_search_strategy: str = "baseline"
    patent_compare_strategy: str = "baseline"
    #: KIPRIS 초당 호출 상한 (유료 등급·공용 키의 남은 제약). 미설정이면 버킷
    #: 없음. 키를 여러 주체가 나눠 쓰므로 인스턴스 수 × 이 값이 합산 상한이다.
    kipris_max_rps: float | None = None
    rag_region: str | None = None
    rag_corpus_id: str | None = None
    rag_corpus_version: str | None = None
    package_metadata_base_url: str | None = None
    source_credential_secret_prefix: str = DYNAMIC_CREDENTIAL_SECRET_PREFIX
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
            firestore_emulator_host=value("FIRESTORE_EMULATOR_HOST"),
            frontend_dist_dir=value("FRONTEND_DIST_DIR"),
            google_login_client_id=value("GOOGLE_LOGIN_CLIENT_ID"),
            google_login_client_secret=value("GOOGLE_LOGIN_CLIENT_SECRET"),
            google_login_redirect_uri=value("GOOGLE_LOGIN_REDIRECT_URI"),
            drive_service_account=value("GOOGLE_DRIVE_SERVICE_ACCOUNT"),
            drive_webhook_base_url=value("GOOGLE_DRIVE_WEBHOOK_BASE_URL"),
            drive_watch_channel_token=value("DRIVE_WATCH_CHANNEL_TOKEN"),
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
            patent_search_strategy=value("PATENT_SEARCH_STRATEGY") or "baseline",
            patent_compare_strategy=value("PATENT_COMPARE_STRATEGY") or "baseline",
            kipris_max_rps=(
                float(value("KIPRIS_MAX_RPS")) if value("KIPRIS_MAX_RPS") else None
            ),
            rag_region=value("RAG_REGION"),
            rag_corpus_id=value("RAG_CORPUS_ID"),
            rag_corpus_version=value("RAG_CORPUS_VERSION"),
            package_metadata_base_url=value("PACKAGE_METADATA_BASE_URL"),
            source_credential_secret_prefix=(
                value("SOURCE_CREDENTIAL_SECRET_PREFIX")
                or DYNAMIC_CREDENTIAL_SECRET_PREFIX
            ),
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
        # D1 — 서비스 계정은 **두 역할이 다 쓴다** (worker 가 대조·스냅샷에서
        # Drive 를 읽는다). 감시 채널을 거는 것은 API 뿐이므로 웹훅 주소와 채널
        # 토큰만 API 묶음이다.
        drive_watch = (
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
        _all_or_none("Google Drive watch", drive_watch)
        _all_or_none("GitHub App credentials", github_credentials)
        _all_or_none("GitHub App API", github_api)
        _all_or_none("Cloud Tasks target", task_target)
        _all_or_none("Cloud Tasks publisher", task_publisher)
        _all_or_none("RAG", rag)

        for name, url in (
            ("GOOGLE_LOGIN_REDIRECT_URI", self.google_login_redirect_uri),
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
                "GOOGLE_DRIVE_SERVICE_ACCOUNT": self.drive_service_account,
            }
            if self.role is AppRole.API:
                role_required = {
                    "Google login group": login[0] if all(login) else None,
                    "Google Drive watch group": drive_watch[0] if all(drive_watch) else None,
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
                    "GitHub App credentials": (
                        github_credentials[0] if all(github_credentials) else None
                    ),
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
            expected_values = {
                "GCP_PROJECT_ID": (self.gcp_project_id, PROJECT_ID),
                "GCP_REGION": (self.gcp_region, REGION),
                "FIRESTORE_DATABASE": (
                    self.firestore_database,
                    FIRESTORE_DATABASE,
                ),
                "LOCAL_STAGING_BUCKET": (
                    self.local_staging_bucket,
                    STAGING_BUCKET,
                ),
                "SOURCE_CREDENTIAL_SECRET_PREFIX": (
                    self.source_credential_secret_prefix,
                    DYNAMIC_CREDENTIAL_SECRET_PREFIX,
                ),
                "GITHUB_APP_PRIVATE_KEY_SECRET_ID": (
                    self.github_private_key_secret_id,
                    FIXED_SECRET_IDS["github_private_key"],
                ),
            }
            if self.role is AppRole.API:
                expected_values.update(
                    {
                        "GOOGLE_CLOUD_PROJECT_NUMBER": (
                            self.google_cloud_project_number,
                            PROJECT_NUMBER,
                        ),
                        "GITHUB_WEBHOOK_SECRET_ID": (
                            self.github_webhook_secret_id,
                            FIXED_SECRET_IDS["github_webhook"],
                        ),
                        "CLOUD_TASKS_LOCATION": (
                            self.cloud_tasks_location,
                            REGION,
                        ),
                        "CLOUD_TASKS_QUEUE": (
                            self.cloud_tasks_queue,
                            TASK_QUEUE,
                        ),
                        "CLOUD_TASKS_SERVICE_ACCOUNT": (
                            self.cloud_tasks_service_account,
                            TASKS_SERVICE_ACCOUNT,
                        ),
                        "ANALYSIS_WORKER_URL": (
                            self.analysis_worker_url,
                            WORKER_BASE_URL,
                        ),
                        "SCHEDULER_SERVICE_ACCOUNT": (
                            self.scheduler_service_account,
                            SCHEDULER_SERVICE_ACCOUNT,
                        ),
                    }
                )
            elif self.role is AppRole.WORKER:
                expected_values["KIPRIS_API_KEY_SECRET_ID"] = (
                    self.kipris_api_key_secret_id,
                    FIXED_SECRET_IDS["kipris"],
                )
                expected_values["APP_PUBLIC_BASE_URL"] = (
                    self.public_base_url,
                    WORKER_BASE_URL,
                )
            mismatched = sorted(
                name
                for name, (actual, expected) in expected_values.items()
                if actual != expected
            )
            if mismatched:
                details = ", ".join(
                    f"{name}={expected!r}"
                    for name, (_actual, expected) in expected_values.items()
                    if name in mismatched
                )
                raise SettingsError(
                    "production v2 namespace contract mismatch: " + details
                )
            if self.firestore_emulator_host is not None:
                raise SettingsError("production must not use FIRESTORE_EMULATOR_HOST")
            if self.role is AppRole.WORKER and any(
                (
                    self.session_secret or None,
                    self.frontend_dist_dir,
                    *login,
                    *drive_watch,
                    *github_api,
                    self.analysis_worker_url,
                    self.cloud_tasks_service_account,
                    self.cloud_tasks_location,
                    self.cloud_tasks_queue,
                    self.scheduler_service_account,
                )
            ):
                raise SettingsError(
                    "production Worker must not receive API-only settings"
                )
            if self.role is AppRole.API and any(
                (
                    self.vertex_config,
                    self.kipris_api_key_secret_id,
                    self.rag_region,
                    self.rag_corpus_id,
                    self.rag_corpus_version,
                    self.package_metadata_base_url,
                )
            ):
                raise SettingsError(
                    "production API must not receive Worker-only intelligence settings"
                )
            if self.gemini_api_key or self.kipris_access_key:
                raise SettingsError(
                    "production provider secrets must use attached identity/Secret Manager"
                )

    @property
    def drive_enabled(self) -> bool:
        return self.drive_service_account is not None

    @property
    def github_enabled(self) -> bool:
        return self.github_app_id is not None


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
