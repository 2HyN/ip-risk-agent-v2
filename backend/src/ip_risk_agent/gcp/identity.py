"""Google-signed OIDC verification for Cloud Tasks and Scheduler callers."""

from __future__ import annotations

import asyncio
import secrets

from fastapi import HTTPException, Request
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token


class GoogleOidcTaskAuthenticator:
    def __init__(
        self,
        *,
        audience: str,
        service_account_email: str,
        verifier=id_token.verify_oauth2_token,
    ) -> None:
        self._audience = audience.rstrip("/")
        self._service_account = service_account_email
        self._verifier = verifier

    async def __call__(self, request: Request) -> None:
        authorization = request.headers.get("Authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="OIDC bearer identity required")
        try:
            claims = await asyncio.to_thread(
                self._verifier,
                token,
                GoogleAuthRequest(),
                self._audience,
            )
        except Exception as exc:
            raise HTTPException(status_code=401, detail="invalid OIDC identity") from exc
        email = claims.get("email")
        verified = claims.get("email_verified")
        if (
            not isinstance(email, str)
            or not secrets.compare_digest(email, self._service_account)
            or verified is not True
        ):
            raise HTTPException(status_code=403, detail="unexpected workload identity")


__all__ = ["GoogleOidcTaskAuthenticator"]
