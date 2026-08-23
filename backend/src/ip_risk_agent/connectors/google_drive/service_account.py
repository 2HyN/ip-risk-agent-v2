"""D1 — Drive 접근은 IAM 이 아니라 **폴더 공유**에서 온다.

사용자 OAuth(`drive.file`) 를 대신한다. 그 범위로는 **폴더를 골라도 폴더 객체만**
받는다. 안은 못 읽는다 — 운영 실측에서 사용자 소유 폴더가 `canListChildren=True` 인데
파일 5 개가 `files.list` 에 0 개로 왔다(결함 41). `files.list` 가 폴더 소속이 아니라
건별 승인으로 거르기 때문이고, 그래서 폴더 마운트가 원리상 불가능했다.

서비스 계정은 사람과 같은 방식으로 폴더를 공유받는다. 도메인 전체 위임이 필요 없고,
**범위 계산에 버그가 있어도 공유되지 않은 것을 요청하면 Google 이 거절한다.** 봉쇄가
우리 신뢰 경계 밖에 남는다 (§2.1).

## 보관할 자격증명이 없다

토큰을 파일에도 Secret Manager 에도 두지 않는다. 호출할 때마다 실행 중인 신원(Cloud Run
에 붙은 SA)으로 Drive 전용 SA 를 **가장**해 짧은 수명의 토큰을 받는다. workspace 를 전부
지운 뒤에도 Drive refresh token 19 개가 남아 있던 사고가 구조적으로 재발하지 않는다.

## Drive 전용 SA 는 프로젝트 역할이 0 이다

일부러 0 이다. 접근이 공유에서만 오므로 역할이 필요 없고, 역할이 없으므로 그 신원이
새더라도 우리 데이터에 닿지 않는다. 운영 신원(`iprisk-v2-api` · `iprisk-v2-worker`)에는
이 SA 하나에 대한 `roles/iam.serviceAccountTokenCreator` 만 붙어 있다.
"""

from __future__ import annotations

from datetime import UTC

import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from .client import GoogleDriveProvider
from .models import DRIVE_READONLY_SCOPE

#: 가장에 쓰는 범위. Drive 범위가 아니라 **가장할 권한**을 얻기 위한 것이다.
_IMPERSONATION_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

#: 토큰 수명. 짧게 두고 매번 새로 받는다 — 보관하지 않는 것이 요점이다.
_TOKEN_LIFETIME_SECONDS = 3600


class ServiceAccountDriveProvider(GoogleDriveProvider):
    """`GoogleDriveProvider` 와 같은 계약을, 가장한 신원으로 수행한다.

    호출 계약(`get_file` · `list_folder_children` · `list_changes` · `watch_changes`
    · `read_text`)은 그대로다. 바뀌는 것은 자격증명을 어디서 얻는가 하나뿐이다.
    """

    def __init__(self, credentials) -> None:
        # 기반 클래스의 OAuth 전용 생성자를 타지 않는다. 우리에게는 client_id 도
        # refresh token 도 없다 — 그것이 D1 의 요점이다.
        self._credentials = credentials
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def get_access_token(self) -> tuple[str, float | None]:
        if not self._credentials.valid:
            self._credentials.refresh(Request())
        expiry = self._credentials.expiry
        return (
            self._credentials.token,
            expiry.replace(tzinfo=UTC).timestamp() if expiry else None,
        )

    def export_token(self) -> dict:
        """보관할 것이 없다.

        빈 사전을 돌려주는 것이 정직하다. 가장 토큰은 수명이 짧고 다음 호출에 다시
        받는다 — 저장하면 오히려 D1 이 없애려던 것을 되살린다.
        """
        return {}


class ServiceAccountDriveProviderFactory:
    """Drive 전용 SA 를 가장해 provider 를 만든다.

    ADC(Cloud Run 의 메타데이터 서버, 로컬에서는 `gcloud` 사용자 자격)를 출발점으로
    삼는다. 어느 쪽이든 **키 파일은 없다.**
    """

    def __init__(self, service_account_email: str, *, source_credentials=None) -> None:
        if not service_account_email:
            raise ValueError("drive service account email is required")
        self._email = service_account_email
        self._source = source_credentials

    @property
    def sharing_address(self) -> str:
        """사용자가 폴더를 공유할 주소. 화면이 이것을 그대로 보여준다."""
        return self._email

    def _source_credentials(self):
        if self._source is not None:
            return self._source
        credentials, _ = google.auth.default(scopes=[_IMPERSONATION_SCOPE])
        return credentials

    def create(self) -> ServiceAccountDriveProvider:
        credentials = impersonated_credentials.Credentials(
            source_credentials=self._source_credentials(),
            target_principal=self._email,
            target_scopes=[DRIVE_READONLY_SCOPE],
            lifetime=_TOKEN_LIFETIME_SECONDS,
        )
        return ServiceAccountDriveProvider(credentials)


__all__ = [
    "ServiceAccountDriveProvider",
    "ServiceAccountDriveProviderFactory",
]
