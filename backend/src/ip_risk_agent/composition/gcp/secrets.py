"""Secret Manager 기반 ``SourceCredentialVault``.

Drive OAuth 토큰은 매 호출마다 갱신되어 ``update()`` 가 자주 불린다. Secret
Manager 는 갱신할 때마다 버전이 쌓이므로, 새 버전을 추가한 뒤 직전 버전을
파기해 무한히 늘어나지 않게 한다.

secret 값 자체는 로그·예외 메시지에 넣지 않는다. 실패해도 남기는 것은
secret **이름**뿐이다.
"""

from __future__ import annotations

import asyncio
import re

from iprisk_contracts.common import SourceType

from ip_risk_agent.connectors.common.credential_vault import (
    CredentialRef,
    CredentialScope,
)
from ip_risk_agent.connectors.common.errors import (
    NotFoundError,
    TemporaryUnavailableError,
)

PROVIDER = "secret-manager"

# Secret Manager 이름 규칙: 영문/숫자/하이픈/언더스코어, 255자 이하.
_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def secret_id_for(scope: CredentialScope) -> str:
    """provider·connection·용도를 합쳐 안정적인 secret 이름을 만든다.

    같은 scope 는 항상 같은 이름이 되어야 한다. 그래야 재시도가 새 secret 을
    만들지 않고 기존 것을 갱신한다.
    """
    raw = f"src-{scope.provider.value}-{scope.connection_id}-{scope.secret_name}"
    return _UNSAFE.sub("-", raw).lower()[:255]


class SecretManagerCredentialVault:
    """``SourceCredentialVault`` Protocol 의 운영 구현.

    SDK 는 동기 클라이언트다. Protocol 이 async 이므로 ``asyncio.to_thread`` 로
    감싼다. 호출 빈도가 낮아(연결 시점과 토큰 갱신 시점) 스레드 비용이 문제되지
    않는다.
    """

    def __init__(self, project_id: str, *, client: object | None = None) -> None:
        if not project_id:
            raise ValueError("project_id is required for Secret Manager")
        self._project_id = project_id
        self._client = client

    # ------------------------------------------------------------------ 내부

    def _sdk(self):
        if self._client is None:
            from google.cloud import secretmanager  # noqa: PLC0415 - 지연 import

            self._client = secretmanager.SecretManagerServiceClient()
        return self._client

    def _parent(self) -> str:
        return f"projects/{self._project_id}"

    def _secret_path(self, secret_id: str) -> str:
        return f"{self._parent()}/secrets/{secret_id}"

    @staticmethod
    def _version_id(version_name: str) -> str:
        return version_name.rsplit("/", 1)[-1]

    def _put_sync(self, secret_id: str, secret: str) -> str:
        from google.api_core import exceptions  # noqa: PLC0415

        client = self._sdk()
        try:
            client.create_secret(
                request={
                    "parent": self._parent(),
                    "secret_id": secret_id,
                    "secret": {"replication": {"automatic": {}}},
                }
            )
        except exceptions.AlreadyExists:
            # 같은 scope 로 다시 저장하는 정상 경로다. 버전만 추가한다.
            pass
        version = client.add_secret_version(
            request={
                "parent": self._secret_path(secret_id),
                "payload": {"data": secret.encode("utf-8")},
            }
        )
        return self._version_id(version.name)

    # ------------------------------------------------------------------ 공개

    async def put(self, scope: CredentialScope, secret: str) -> CredentialRef:
        secret_id = secret_id_for(scope)
        try:
            await asyncio.to_thread(self._put_sync, secret_id, secret)
        except Exception as exc:  # noqa: BLE001 - SDK 예외 종류가 넓다
            raise TemporaryUnavailableError(
                PROVIDER, f"failed to store secret {secret_id}"
            ) from exc
        # key_id 는 secret 이름이다. 버전은 항상 latest 를 읽으므로 고정하지 않는다.
        return CredentialRef(
            provider=scope.provider,
            connection_id=scope.connection_id,
            secret_name=scope.secret_name,
            key_id=secret_id,
        )

    async def get(self, ref: CredentialRef) -> str:
        from google.api_core import exceptions  # noqa: PLC0415

        def _call() -> str:
            client = self._sdk()
            response = client.access_secret_version(
                request={"name": f"{self._secret_path(ref.key_id)}/versions/latest"}
            )
            return response.payload.data.decode("utf-8")

        try:
            return await asyncio.to_thread(_call)
        except exceptions.NotFound as exc:
            raise NotFoundError(
                PROVIDER, f"credential not found: {ref.key_id}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise TemporaryUnavailableError(
                PROVIDER, f"failed to read secret {ref.key_id}"
            ) from exc

    async def update(self, ref: CredentialRef, secret: str) -> None:
        def _call() -> None:
            from google.api_core import exceptions  # noqa: PLC0415

            client = self._sdk()
            path = self._secret_path(ref.key_id)
            previous = None
            try:
                current = client.access_secret_version(
                    request={"name": f"{path}/versions/latest"}
                )
                previous = current.name
            except exceptions.NotFound:
                previous = None

            client.add_secret_version(
                request={"parent": path, "payload": {"data": secret.encode("utf-8")}}
            )
            if previous is not None:
                # 토큰 갱신이 잦으므로 직전 버전을 파기해 버전이 무한히 쌓이지
                # 않게 한다. 실패해도 갱신 자체는 이미 성공했으므로 삼킨다.
                try:
                    client.destroy_secret_version(request={"name": previous})
                except Exception:  # noqa: BLE001, S110
                    pass

        try:
            await asyncio.to_thread(_call)
        except Exception as exc:  # noqa: BLE001
            raise TemporaryUnavailableError(
                PROVIDER, f"failed to update secret {ref.key_id}"
            ) from exc

    async def delete(self, ref: CredentialRef) -> None:
        def _call() -> None:
            from google.api_core import exceptions  # noqa: PLC0415

            try:
                self._sdk().delete_secret(
                    request={"name": self._secret_path(ref.key_id)}
                )
            except exceptions.NotFound:
                # 이미 없는 것을 지우는 것은 성공으로 본다.
                pass

        try:
            await asyncio.to_thread(_call)
        except Exception as exc:  # noqa: BLE001
            raise TemporaryUnavailableError(
                PROVIDER, f"failed to delete secret {ref.key_id}"
            ) from exc


__all__ = ["SecretManagerCredentialVault", "secret_id_for"]
