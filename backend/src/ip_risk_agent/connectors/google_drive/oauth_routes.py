from __future__ import annotations

import json
from typing import Callable, Protocol

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from iprisk_contracts.common import SourceType

from ..common.authz import AuthzDependency, deny_all_authz
from ..common.credential_vault import CredentialRef, CredentialScope, SourceCredentialVault
from ..common.errors import SourceConnectorError
from ..common.oauth_state import OAuthStateStore, generate_state
from .oauth import DriveOAuthClient, build_authorize_url, decode_identity_from_id_token


class DriveConnectionCreationCallback(Protocol):
    """Control의 canonical SourceConnection 생성. Agent 2는 provider
    identity/credential_ref만 넘기고 실제 저장은 Control이 담당한다."""

    async def create_drive_connection(
        self,
        request: Request,
        *,
        risk_workspace_id: str,
        provider_subject: str,
        provider_email: str,
        credential_ref: CredentialRef,
    ) -> str: ...


class DriveConnectionStartRequest(BaseModel):
    risk_workspace_id: str


class DriveConnectionStartResponse(BaseModel):
    authorize_url: str
    state: str


class DriveConnectionCallbackResponse(BaseModel):
    connection_id: str
    provider_email: str
    status: str


def create_drive_oauth_router(
    *,
    client_id: str,
    redirect_uri: str,
    state_store: OAuthStateStore,
    oauth_client: DriveOAuthClient,
    credential_vault: SourceCredentialVault,
    connection_creation_callback: DriveConnectionCreationCallback,
    authz_dependency: AuthzDependency = deny_all_authz,
    completion_redirect: Callable[..., str] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/source-connections/google-drive/start", response_model=DriveConnectionStartResponse)
    async def start(request: Request, body: DriveConnectionStartRequest) -> DriveConnectionStartResponse:
        await authz_dependency(request, body.risk_workspace_id)

        state = generate_state()
        await state_store.save(state, {"risk_workspace_id": body.risk_workspace_id})

        return DriveConnectionStartResponse(
            authorize_url=build_authorize_url(client_id=client_id, redirect_uri=redirect_uri, state=state),
            state=state,
        )

    @router.get(
        "/api/v1/source-connections/google-drive/callback", response_model=DriveConnectionCallbackResponse
    )
    async def callback(request: Request, code: str, state: str) -> Response:
        context = await state_store.consume(state)
        if context is None:
            raise HTTPException(status_code=400, detail="invalid or expired oauth state")

        try:
            token_response = await oauth_client.exchange_code(code)
        except SourceConnectorError as exc:
            raise HTTPException(
                status_code=400, detail="failed to complete google drive authorization"
            ) from exc

        provider_subject, provider_email = decode_identity_from_id_token(token_response.get("id_token", ""))

        cred_scope = CredentialScope(
            provider=SourceType.GOOGLE_DRIVE,
            connection_id=f"pending-{state}",
            secret_name="drive-oauth-token",
        )
        token_json = json.dumps(
            {
                "access_token": token_response.get("access_token"),
                "refresh_token": token_response.get("refresh_token"),
                "expires_at": None,
                "scope": token_response.get("scope", ""),
            }
        )
        credential_ref = await credential_vault.put(cred_scope, token_json)

        connection_id = await connection_creation_callback.create_drive_connection(
            request,
            risk_workspace_id=context["risk_workspace_id"],
            provider_subject=provider_subject,
            provider_email=provider_email,
            credential_ref=credential_ref,
        )

        result = DriveConnectionCallbackResponse(
            connection_id=connection_id, provider_email=provider_email, status="connected"
        )
        if completion_redirect is not None:
            return RedirectResponse(
                completion_redirect(
                    source_type=SourceType.GOOGLE_DRIVE,
                    risk_workspace_id=context["risk_workspace_id"],
                    connection_id=connection_id,
                ),
                status_code=303,
            )
        return JSONResponse(result.model_dump())

    return router
