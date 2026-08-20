"""Secret Manager implementation of the Source credential vault port."""

from __future__ import annotations

import hashlib
import re

from google.api_core import exceptions as google_exceptions

from ip_risk_agent.connectors.common.credential_vault import (
    CredentialRef,
    CredentialScope,
)
from ip_risk_agent.connectors.common.errors import NotFoundError


class SecretManagerCredentialVault:
    def __init__(self, *, client, project_id: str, secret_prefix: str) -> None:
        if re.fullmatch(r"[a-z][a-z0-9-]{2,63}", secret_prefix) is None:
            raise ValueError("credential secret prefix is invalid")
        self._client = client
        self._parent = f"projects/{project_id}"
        self._secret_prefix = secret_prefix

    async def put(self, scope: CredentialScope, secret: str) -> CredentialRef:
        secret_name = self._secret_resource(scope)
        secret_id = secret_name.rsplit("/", 1)[-1]
        try:
            await self._client.create_secret(
                parent=self._parent,
                secret_id=secret_id,
                secret={
                    "replication": {"automatic": {}},
                    "labels": {
                        "owner": "ip-risk-agent-v2",
                        "environment": "v2",
                        "provider": scope.provider.value.lower(),
                    },
                },
            )
        except google_exceptions.AlreadyExists:
            pass
        await self._add_version(secret_name, secret)
        return CredentialRef(
            provider=scope.provider,
            connection_id=scope.connection_id,
            secret_name=scope.secret_name,
            key_id=secret_name,
        )

    async def get(self, ref: CredentialRef) -> str:
        try:
            response = await self._client.access_secret_version(
                name=f"{self._validate_ref(ref)}/versions/latest"
            )
            return bytes(response.payload.data).decode("utf-8")
        except google_exceptions.NotFound as exc:
            raise NotFoundError(
                provider=ref.provider.value,
                safe_message="credential version was not found",
            ) from exc

    async def update(self, ref: CredentialRef, secret: str) -> None:
        await self._add_version(self._validate_ref(ref), secret)

    async def delete(self, ref: CredentialRef) -> None:
        name = self._validate_ref(ref)
        try:
            await self._client.disable_secret_version(
                name=f"{name}/versions/latest"
            )
        except google_exceptions.NotFound:
            return

    async def _add_version(self, secret_name: str, secret: str) -> None:
        if not secret:
            raise ValueError("credential payload must not be empty")
        await self._client.add_secret_version(
            parent=secret_name,
            payload={"data": secret.encode("utf-8")},
        )

    def _secret_resource(self, scope: CredentialScope) -> str:
        digest = hashlib.sha256(
            "\x00".join(
                (scope.provider.value, scope.connection_id, scope.secret_name)
            ).encode("utf-8")
        ).hexdigest()[:40]
        return (
            f"{self._parent}/secrets/{self._secret_prefix}-"
            f"{scope.provider.value.lower()}-{digest}"
        )

    def _validate_ref(self, ref: CredentialRef) -> str:
        prefix = (
            f"{self._parent}/secrets/{self._secret_prefix}-"
            f"{ref.provider.value.lower()}-"
        )
        if re.fullmatch(re.escape(prefix) + r"[0-9a-f]{40}", ref.key_id) is None:
            raise ValueError("credential reference is outside the configured project")
        return ref.key_id


__all__ = ["SecretManagerCredentialVault"]
