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
# 폴더 단위 감시에는 읽기 전용 전체 스코프가 필요하다. drive.file 은 Picker 로
# 고른 파일에만 접근이 열려, 폴더를 골라도 하위 파일 목록이 비어 나온다.
# 쓰기 권한은 여전히 요청하지 않는다.
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"
SELECTABLE_MIME_TYPES = (
    GOOGLE_DOC_MIME_TYPE,
    "text/plain",
    "text/markdown",
    "application/json",
)

# Drive 는 업로드 파일의 mime 을 신뢰할 수 있게 붙여 주지 않는다 — .md 가
# application/octet-stream 으로 오는 일이 흔하다. mime 만 믿으면 기획서가
# "미지원"으로 조용히 빠져 특허 분석이 아예 돌지 않는다(실제로 그랬다).
# 그래서 v1 과 같은 방식으로 확장자를 함께 본다. 진짜 바이너리는 어차피
# UTF-8 디코드에서 걸러진다.
TEXT_FILE_SUFFIXES = (
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".kt",
    ".go",
    ".rs",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".cfg",
    ".ini",
    ".xml",
    ".html",
    ".css",
    ".csv",
    ".sql",
    ".sh",
    ".bat",
    ".gradle",
    ".lock",
)


def is_probably_text(name: str, mime_type: str) -> bool:
    """내용을 읽어 볼 가치가 있는 파일인가.

    mime 이 알려진 텍스트이거나, 이름의 확장자가 텍스트 계열이면 참이다.
    """
    if mime_type in SELECTABLE_MIME_TYPES or mime_type.startswith("text/"):
        return True
    return name.lower().endswith(TEXT_FILE_SUFFIXES)


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


class DriveProvider(Protocol):
    """실제 client가 구현해야 하는 최소 계약. fake/실제 구현 모두 이 모양만
    맞추면 adapter.py는 어느 쪽이든 그대로 쓸 수 있다 (Agent 2 Spec 47번)."""

    def get_access_token(self) -> tuple[str, float | None]: ...

    def get_file(self, file_id: str) -> DriveFile: ...

    def get_start_page_token(self) -> str: ...

    def create_google_doc(self, name: str) -> DriveFile: ...

    def list_changes(self, page_token: str) -> DriveChangePage: ...

    def list_children(self, folder_id: str) -> list[DriveFile]: ...

    def read_text(self, file_id: str, mime_type: str) -> str: ...

    def export_token(self) -> dict: ...


def normalize_scopes(raw_scope: str | list[str] | None) -> set[str]:
    if raw_scope is None:
        return set()
    if isinstance(raw_scope, str):
        return set(raw_scope.split())
    return set(raw_scope)


def require_exact_drive_file_scope(token: dict) -> None:
    """읽기 범위를 벗어난 스코프를 거부한다.

    drive.file(예전 연결) 또는 drive.readonly(폴더 감시용) 하나만 허용한다.
    쓰기 스코프가 섞여 있으면 어딘가 잘못된 동의 화면을 탄 것이므로 막는다.
    """
    granted = normalize_scopes(token.get("scope"))
    if granted not in ({DRIVE_FILE_SCOPE}, {DRIVE_READONLY_SCOPE}):
        raise DriveScopeError(
            "Granted Google Drive scope must be exactly drive.file or drive.readonly"
        )
