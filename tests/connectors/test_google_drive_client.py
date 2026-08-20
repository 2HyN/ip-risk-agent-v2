"""google_drive/client.py 확인. google-api-python-client/google-auth가
설치되어 있어야 실행된다 (agent-deliverables/agent-2-dependencies.md 참고).
아직 설치 전이라면 이 파일 전체가 SKIPPED로 표시되는 게 정상이다."""

from __future__ import annotations

import pytest

pytest.importorskip("googleapiclient")
pytest.importorskip("google.oauth2.credentials")

from ip_risk_agent.connectors.google_drive.client import (
    GoogleDriveProvider,
    GoogleDriveProviderFactory,
)


def test_to_file_maps_all_fields():
    response = {
        "id": "file-1",
        "name": "spec.docx",
        "mimeType": "application/vnd.google-apps.document",
        "modifiedTime": "2026-08-01T00:00:00Z",
        "version": "7",
        "webViewLink": "https://drive.google.com/file-1",
    }
    drive_file = GoogleDriveProvider._to_file(response)
    assert drive_file.file_id == "file-1"
    assert drive_file.revision_id == "7"
    assert drive_file.web_view_link == "https://drive.google.com/file-1"


def test_to_file_handles_missing_optional_fields():
    response = {"id": "file-2", "name": "notes.txt", "mimeType": "text/plain"}
    drive_file = GoogleDriveProvider._to_file(response)
    assert drive_file.modified_time is None
    assert drive_file.revision_id is None
    assert drive_file.web_view_link is None


def test_factory_creates_provider_instance():
    factory = GoogleDriveProviderFactory(client_id="client-x", client_secret="secret-y")
    token = {"access_token": "at", "refresh_token": "rt", "expires_at": None}
    provider = factory.create(token)
    assert isinstance(provider, GoogleDriveProvider)
