"""Integration-owned environment binding.

각 Plane 은 환경변수를 직접 읽지 않는다. 이 모듈이 유일하게 읽고, 검증한 뒤
생성자 인자로 넘긴다 (Master Spec 61).

GCP 자원이 없어도 앱이 뜨도록 설계했다. `backend` 속성이 어떤 저장소를 쓸지
결정하며, 값이 없으면 in-memory 로 내려간다. in-memory 는 프로세스 재시작 시
상태가 사라지므로 개발/통합 검증 전용이다.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

Backend = Literal["in-memory", "firestore"]

DEV_BASE_URL = "http://127.0.0.1:8000"


def _clean(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


@dataclass(frozen=True, slots=True)
class ControlSettings:
    """Control Plane 과 애플리케이션 세션."""

    session_secret: str = field(repr=False)
    app_public_base_url: str
    google_login_client_id: str | None = None
    google_login_client_secret: str | None = field(default=None, repr=False)
    google_login_redirect_uri: str | None = None
    gcp_project_id: str | None = None
    firestore_database: str | None = None

    @property
    def backend(self) -> Backend:
        if self.gcp_project_id and self.firestore_database:
            return "firestore"
        return "in-memory"

    @property
    def google_login_configured(self) -> bool:
        return bool(
            self.google_login_client_id
            and self.google_login_client_secret
            and self.google_login_redirect_uri
        )

    @property
    def https_only(self) -> bool:
        """로컬 HTTP 개발에서 세션 쿠키가 버려지지 않게 한다."""
        return urlsplit(self.app_public_base_url).scheme == "https"

    @property
    def trusted_hosts(self) -> tuple[str, ...]:
        host = urlsplit(self.app_public_base_url).hostname
        if host is None:
            return ("*",)
        # 로컬 개발에서는 127.0.0.1 과 localhost 를 함께 허용한다.
        if host in {"127.0.0.1", "localhost"}:
            return ("127.0.0.1", "localhost", "testserver")
        return (host,)

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return (self.app_public_base_url,)


@dataclass(frozen=True, slots=True)
class SourceSettings:
    """Source Plane provider 자격/엔드포인트."""

    drive_client_id: str | None = None
    drive_client_secret: str | None = field(default=None, repr=False)
    drive_redirect_uri: str | None = None
    drive_webhook_base_url: str | None = None
    drive_watch_channel_token: str | None = field(default=None, repr=False)
    github_app_id: str | None = None
    github_app_slug: str | None = None
    github_app_private_key_secret_id: str | None = None
    github_webhook_secret_id: str | None = None
    github_app_callback_url: str | None = None
    local_staging_bucket: str | None = None
    # 아래 둘은 Secret Manager 에 보관하고 배포가 실제 값을 주입한다.
    # `*_SECRET_ID` 는 그 secret 을 가리키는 참조이고, 여기 담기는 것은 값이다.
    github_app_private_key: str | None = field(default=None, repr=False)
    github_webhook_secret: str | None = field(default=None, repr=False)

    @property
    def drive_configured(self) -> bool:
        return bool(self.drive_client_id and self.drive_client_secret and self.drive_redirect_uri)

    @property
    def github_configured(self) -> bool:
        return bool(self.github_app_id and self.github_app_slug)


@dataclass(frozen=True, slots=True)
class QueueSettings:
    """Cloud Tasks. 값이 없으면 in-memory 큐로 하강한다.

    in-memory 큐는 같은 프로세스 안에서만 유효하므로 워커를 따로 띄우는 배포
    구성에서는 반드시 설정해야 한다.
    """

    project_id: str | None = None
    location: str | None = None
    queue: str | None = None
    worker_url: str | None = None
    service_account_email: str | None = None

    @property
    def configured(self) -> bool:
        return all(
            (
                self.project_id,
                self.location,
                self.queue,
                self.worker_url,
                self.service_account_email,
            )
        )


@dataclass(frozen=True, slots=True)
class IntelligenceSettings:
    """Risk Intelligence Plane. 값이 없으면 해당 분석 경로만 비활성화된다."""

    gemini_model_id: str | None = None
    gemini_api_key: str | None = field(default=None, repr=False)
    kipris_access_key: str | None = field(default=None, repr=False)
    gcp_project_id: str | None = None
    rag_region: str | None = None
    rag_corpus_id: str | None = None
    rag_corpus_version: str | None = None

    @property
    def enabled(self) -> bool:
        """Analyzer registry 를 만들 수 있는 최소 조건."""
        return bool(self.gemini_model_id)

    @property
    def rag_configured(self) -> bool:
        return bool(self.gcp_project_id and self.rag_region and self.rag_corpus_id)

    def as_env(self) -> dict[str, str]:
        """`IntelligenceConfig.from_env` 가 읽는 형태로 되돌린다."""
        values = {
            "GEMINI_MODEL_ID": self.gemini_model_id,
            "GEMINI_API_KEY": self.gemini_api_key,
            "KIPRIS_ACCESS_KEY": self.kipris_access_key,
            "GCP_PROJECT_ID": self.gcp_project_id,
            "RAG_REGION": self.rag_region,
            "RAG_CORPUS_ID": self.rag_corpus_id,
            "RAG_CORPUS_VERSION": self.rag_corpus_version,
        }
        return {key: value for key, value in values.items() if value}


@dataclass(frozen=True, slots=True)
class Settings:
    control: ControlSettings
    source: SourceSettings
    intelligence: IntelligenceSettings
    queue: QueueSettings

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        base_url = _clean(env, "APP_PUBLIC_BASE_URL") or DEV_BASE_URL
        secret = _clean(env, "SESSION_SECRET")
        if secret is None:
            # 개발 편의를 위한 임시 비밀값이다. 프로세스마다 달라지므로 재시작하면
            # 세션이 무효화된다. 배포에서는 반드시 주입해야 한다.
            secret = secrets.token_urlsafe(48)
        elif len(secret) < 32:
            raise ValueError("SESSION_SECRET must contain at least 32 characters")

        return cls(
            control=ControlSettings(
                session_secret=secret,
                app_public_base_url=base_url,
                google_login_client_id=_clean(env, "GOOGLE_LOGIN_CLIENT_ID"),
                google_login_client_secret=_clean(env, "GOOGLE_LOGIN_CLIENT_SECRET"),
                google_login_redirect_uri=_clean(env, "GOOGLE_LOGIN_REDIRECT_URI"),
                gcp_project_id=_clean(env, "GCP_PROJECT_ID"),
                firestore_database=_clean(env, "FIRESTORE_DATABASE"),
            ),
            source=SourceSettings(
                drive_client_id=_clean(env, "GOOGLE_DRIVE_CLIENT_ID"),
                drive_client_secret=_clean(env, "GOOGLE_DRIVE_CLIENT_SECRET"),
                drive_redirect_uri=_clean(env, "GOOGLE_DRIVE_REDIRECT_URI"),
                drive_webhook_base_url=_clean(env, "GOOGLE_DRIVE_WEBHOOK_BASE_URL"),
                drive_watch_channel_token=_clean(env, "DRIVE_WATCH_CHANNEL_TOKEN"),
                github_app_id=_clean(env, "GITHUB_APP_ID"),
                github_app_slug=_clean(env, "GITHUB_APP_SLUG"),
                github_app_private_key_secret_id=_clean(env, "GITHUB_APP_PRIVATE_KEY_SECRET_ID"),
                github_webhook_secret_id=_clean(env, "GITHUB_WEBHOOK_SECRET_ID"),
                github_app_callback_url=_clean(env, "GITHUB_APP_CALLBACK_URL"),
                local_staging_bucket=_clean(env, "LOCAL_STAGING_BUCKET"),
                github_app_private_key=_clean(env, "GITHUB_APP_PRIVATE_KEY"),
                github_webhook_secret=_clean(env, "GITHUB_WEBHOOK_SECRET"),
            ),
            queue=QueueSettings(
                project_id=_clean(env, "GCP_PROJECT_ID"),
                location=_clean(env, "CLOUD_TASKS_LOCATION"),
                queue=_clean(env, "CLOUD_TASKS_QUEUE"),
                worker_url=_clean(env, "ANALYSIS_WORKER_URL"),
                service_account_email=_clean(env, "CLOUD_TASKS_SERVICE_ACCOUNT"),
            ),
            intelligence=IntelligenceSettings(
                gemini_model_id=_clean(env, "GEMINI_MODEL_ID"),
                gemini_api_key=_clean(env, "GEMINI_API_KEY"),
                kipris_access_key=_clean(env, "KIPRIS_ACCESS_KEY"),
                gcp_project_id=_clean(env, "GCP_PROJECT_ID"),
                rag_region=_clean(env, "RAG_REGION"),
                rag_corpus_id=_clean(env, "RAG_CORPUS_ID"),
                rag_corpus_version=_clean(env, "RAG_CORPUS_VERSION"),
            ),
        )


__all__ = [
    "Backend",
    "ControlSettings",
    "IntelligenceSettings",
    "QueueSettings",
    "Settings",
    "SourceSettings",
]
