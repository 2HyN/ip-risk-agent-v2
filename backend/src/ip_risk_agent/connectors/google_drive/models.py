"""Google Drive provider-private models 및 DriveAdapter가 의존하는 최소 계약.

2HyN/ip-risk-agent (팀 저장소, public)의 connectors/google_drive.py를
바탕으로 이식했다. shared contract가 아니라 provider-private 모델이므로
(Agent 2 Spec 4번), SourceChange/SourceSnapshot 변환은 adapter.py가 맡는다.
google-api-python-client 등 외부 라이브러리에 의존하지 않아 dependency
설치 전에도 단독으로 테스트 가능하다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"
SELECTABLE_MIME_TYPES = (
    GOOGLE_DOC_MIME_TYPE,
    "text/plain",
    "text/markdown",
    "application/json",
)


class DriveScopeError(ValueError):
    """연결된 Drive OAuth scope가 drive.file 정확히 하나가 아닐 때."""


@dataclass(frozen=True, slots=True)
class DriveFile:
    file_id: str
    name: str
    mime_type: str
    modified_time: str | None
    revision_id: str | None
    web_view_link: str | None
    #: 부모 폴더 id. Drive 는 여러 개를 허용하지만 우리는 첫 번째만 따라간다 —
    #: 경로가 하나여야 트리가 하나가 된다.
    parents: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DriveChange:
    file_id: str
    removed: bool
    modified_time: str | None
    revision_id: str | None


@dataclass(frozen=True, slots=True)
class DriveChangePage:
    changes: list[DriveChange]
    next_page_token: str | None
    new_start_page_token: str | None


@dataclass(frozen=True, slots=True)
class DriveWatchChannel:
    channel_id: str
    resource_id: str
    expiration_millis: int


class DriveProvider(Protocol):
    """실제 client가 구현해야 하는 최소 계약. fake/실제 구현 모두 이 모양만
    맞추면 adapter.py는 어느 쪽이든 그대로 쓸 수 있다 (Agent 2 Spec 47번)."""

    def get_access_token(self) -> tuple[str, float | None]: ...

    def get_file(self, file_id: str) -> DriveFile: ...

    def get_start_page_token(self) -> str: ...

    def create_google_doc(self, name: str) -> DriveFile: ...

    def list_changes(self, page_token: str) -> DriveChangePage: ...

    def watch_changes(
        self,
        *,
        page_token: str,
        channel_id: str,
        address: str,
        channel_token: str,
        expiration_millis: int,
    ) -> DriveWatchChannel: ...

    def read_text(self, file_id: str, mime_type: str) -> str: ...

    def export_token(self) -> dict: ...


def normalize_scopes(raw_scope: str | list[str] | None) -> set[str]:
    if raw_scope is None:
        return set()
    if isinstance(raw_scope, str):
        return set(raw_scope.split())
    return set(raw_scope)


def require_exact_drive_file_scope(token: dict) -> None:
    if normalize_scopes(token.get("scope")) != {DRIVE_FILE_SCOPE}:
        raise DriveScopeError("Granted Google Drive scope must be exactly drive.file")
