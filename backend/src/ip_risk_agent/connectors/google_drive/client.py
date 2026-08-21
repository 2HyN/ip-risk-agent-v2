"""GoogleDriveProvider: 실제 Google Drive API(v3)를 호출하는 client 구현.

2HyN/ip-risk-agent (팀 저장소, public)의 connectors/google_drive.py를
바탕으로 이식했다. google-api-python-client / google-auth가 설치되어
있어야 import 가능하다 (docs/DEPENDENCIES.md 참고).
설치 전까지 이 모듈을 쓰는 테스트는 importorskip으로 건너뛴다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .models import (
    DRIVE_FILE_SCOPE,
    GOOGLE_DOC_MIME_TYPE,
    DriveChange,
    DriveChangePage,
    DriveFile,
)


class GoogleDriveProvider:
    """DriveProvider 계약의 production 구현."""

    def __init__(self, token: dict, client_id: str, client_secret: str) -> None:
        expiry = token.get("expires_at")
        expiry_datetime = (
            datetime.fromtimestamp(expiry, tz=UTC).replace(tzinfo=None) if expiry else None
        )
        self._credentials = Credentials(
            token=token.get("access_token"),
            refresh_token=token.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=[DRIVE_FILE_SCOPE],
            expiry=expiry_datetime,
        )
        self._service = build("drive", "v3", credentials=self._credentials, cache_discovery=False)

    def get_access_token(self) -> tuple[str, float | None]:
        if not self._credentials.valid:
            self._credentials.refresh(Request())
        expiry = self._credentials.expiry
        return (
            self._credentials.token,
            expiry.replace(tzinfo=UTC).timestamp() if expiry else None,
        )

    def get_file(self, file_id: str) -> DriveFile:
        response = (
            self._service.files()
            .get(fileId=file_id, fields="id,name,mimeType,modifiedTime,version,webViewLink")
            .execute()
        )
        return self._to_file(response)

    def get_start_page_token(self) -> str:
        response = self._service.changes().getStartPageToken().execute()
        return response["startPageToken"]

    def create_google_doc(self, name: str) -> DriveFile:
        response = (
            self._service.files()
            .create(
                body={"name": name, "mimeType": GOOGLE_DOC_MIME_TYPE},
                fields="id,name,mimeType,modifiedTime,version,webViewLink",
            )
            .execute()
        )
        return self._to_file(response)

    def list_changes(self, page_token: str) -> DriveChangePage:
        response = (
            self._service.changes()
            .list(
                pageToken=page_token,
                spaces="drive",
                includeRemoved=True,
                fields=(
                    "nextPageToken,newStartPageToken,"
                    "changes(fileId,removed,file(modifiedTime,version))"
                ),
            )
            .execute()
        )
        changes = [
            DriveChange(
                file_id=item["fileId"],
                removed=item.get("removed", False),
                modified_time=item.get("file", {}).get("modifiedTime"),
                revision_id=item.get("file", {}).get("version"),
            )
            for item in response.get("changes", [])
        ]
        return DriveChangePage(
            changes=changes,
            next_page_token=response.get("nextPageToken"),
            new_start_page_token=response.get("newStartPageToken"),
        )

    def list_children(self, folder_id: str) -> list[DriveFile]:
        """폴더 바로 아래 항목들. 페이지를 모두 걷는다.

        drive.file 스코프에서는 Picker 로 고른 폴더의 하위 항목까지 접근이
        열린다. 접근이 없는 항목은 응답에서 빠질 뿐 오류가 나지 않는다.
        """
        children: list[DriveFile] = []
        page_token: str | None = None
        while True:
            response = (
                self._service.files()
                .list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    spaces="drive",
                    fields=(
                        "nextPageToken,"
                        "files(id,name,mimeType,modifiedTime,version,webViewLink)"
                    ),
                    pageToken=page_token,
                )
                .execute()
            )
            children.extend(self._to_file(item) for item in response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return children

    def read_text(self, file_id: str, mime_type: str) -> str:
        files = self._service.files()
        if mime_type == GOOGLE_DOC_MIME_TYPE:
            content = files.export(fileId=file_id, mimeType="text/plain").execute()
        else:
            content = files.get_media(fileId=file_id).execute()
        return content.decode("utf-8-sig") if isinstance(content, bytes) else str(content)

    def export_token(self) -> dict:
        expiry = self._credentials.expiry
        return {
            "access_token": self._credentials.token,
            "refresh_token": self._credentials.refresh_token,
            "expires_at": expiry.replace(tzinfo=UTC).timestamp() if expiry else None,
            "scope": DRIVE_FILE_SCOPE,
            "token_type": "Bearer",
        }

    @staticmethod
    def _to_file(response: dict) -> DriveFile:
        return DriveFile(
            file_id=response["id"],
            name=response["name"],
            mime_type=response["mimeType"],
            modified_time=response.get("modifiedTime"),
            revision_id=response.get("version"),
            web_view_link=response.get("webViewLink"),
        )


class GoogleDriveProviderFactory:
    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret

    def create(self, token: dict) -> GoogleDriveProvider:
        return GoogleDriveProvider(token, self._client_id, self._client_secret)
