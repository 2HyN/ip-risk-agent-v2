"""One-time desktop enrollment and revocable bearer device credentials."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ip_risk_agent.api.common import CsrfGuard, CsrfValidationError
from ip_risk_agent.application.public_facade import PublicVwsAction
from ip_risk_agent.core.common import normalize_utc


class DeviceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class EnrollmentChallenge:
    token_hash: str
    owner_user_id: str
    session_version: int
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DesktopDevice:
    device_id: str
    device_label: str
    owner_user_id: str
    session_version: int
    credential_hash: str
    status: DeviceStatus
    created_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DeviceMountBinding:
    device_id: str
    risk_workspace_id: str
    mount_id: str


class DeviceAuthStore(Protocol):
    async def save_challenge(self, challenge: EnrollmentChallenge) -> None: ...
    async def get_challenge(self, token_hash: str) -> EnrollmentChallenge | None: ...
    async def save_device(self, device: DesktopDevice) -> None: ...
    async def get_device_by_credential(self, credential_hash: str) -> DesktopDevice | None: ...
    async def get_device(self, device_id: str) -> DesktopDevice | None: ...
    async def save_mount_binding(self, binding: DeviceMountBinding) -> None: ...
    async def get_mount_binding(self, mount_id: str) -> DeviceMountBinding | None: ...


class InMemoryDeviceAuthStore:
    def __init__(self) -> None:
        self.challenges: dict[str, EnrollmentChallenge] = {}
        self.devices: dict[str, DesktopDevice] = {}
        self.credentials: dict[str, str] = {}
        self.mounts: dict[str, DeviceMountBinding] = {}
        self.lock = asyncio.Lock()

    async def save_challenge(self, challenge: EnrollmentChallenge) -> None:
        self.challenges[challenge.token_hash] = challenge

    async def get_challenge(self, token_hash: str) -> EnrollmentChallenge | None:
        return self.challenges.get(token_hash)

    async def save_device(self, device: DesktopDevice) -> None:
        previous = self.devices.get(device.device_id)
        if previous is not None:
            self.credentials.pop(previous.credential_hash, None)
        self.devices[device.device_id] = device
        self.credentials[device.credential_hash] = device.device_id

    async def get_device_by_credential(self, credential_hash: str) -> DesktopDevice | None:
        device_id = self.credentials.get(credential_hash)
        return self.devices.get(device_id) if device_id else None

    async def get_device(self, device_id: str) -> DesktopDevice | None:
        return self.devices.get(device_id)

    async def save_mount_binding(self, binding: DeviceMountBinding) -> None:
        self.mounts[binding.mount_id] = binding

    async def get_mount_binding(self, mount_id: str) -> DeviceMountBinding | None:
        return self.mounts.get(mount_id)


class SessionVersionValidator(Protocol):
    async def __call__(self, user_id: str, session_version: int) -> bool: ...


class DesktopDeviceAuthService:
    def __init__(
        self,
        *,
        store: DeviceAuthStore,
        session_version_validator: SessionVersionValidator,
        clock: Callable[[], datetime],
        challenge_ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        if challenge_ttl <= timedelta(0) or challenge_ttl > timedelta(minutes=15):
            raise ValueError("challenge TTL must be between 0 and 15 minutes")
        self._store = store
        self._validate_session = session_version_validator
        self._clock = clock
        self._ttl = challenge_ttl
        self._lock = getattr(store, "lock", asyncio.Lock())

    async def issue_challenge(self, *, owner_user_id: str, session_version: int) -> str:
        token = secrets.token_urlsafe(48)
        now = normalize_utc(self._clock(), "device_auth.clock")
        await self._store.save_challenge(
            EnrollmentChallenge(
                token_hash=_hash(token),
                owner_user_id=owner_user_id,
                session_version=session_version,
                created_at=now,
                expires_at=now + self._ttl,
            )
        )
        return token

    async def exchange_challenge(
        self,
        *,
        challenge: str,
        device_id: str,
        device_label: str,
    ) -> str:
        now = normalize_utc(self._clock(), "device_auth.clock")
        token_hash = _hash(challenge)
        async with self._lock:
            record = await self._store.get_challenge(token_hash)
            if record is None or record.consumed_at is not None or record.expires_at <= now:
                raise HTTPException(status_code=401, detail="invalid enrollment challenge")
            if not await self._validate_session(
                record.owner_user_id,
                record.session_version,
            ):
                raise HTTPException(status_code=401, detail="enrollment session is invalid")
            existing = await self._store.get_device(device_id.strip())
            if existing is not None and existing.owner_user_id != record.owner_user_id:
                raise HTTPException(
                    status_code=409,
                    detail="device identity is already bound to another owner",
                )
            credential = secrets.token_urlsafe(48)
            device = DesktopDevice(
                device_id=device_id.strip(),
                device_label=device_label.strip(),
                owner_user_id=record.owner_user_id,
                session_version=record.session_version,
                credential_hash=_hash(credential),
                status=DeviceStatus.ACTIVE,
                created_at=now,
            )
            if not device.device_id or not device.device_label:
                raise HTTPException(status_code=422, detail="device identity is required")
            await self._store.save_challenge(replace(record, consumed_at=now))
            await self._store.save_device(device)
            return credential

    async def authenticate(self, request: Request) -> DesktopDevice:
        authorization = request.headers.get("Authorization", "")
        scheme, separator, credential = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not credential:
            raise HTTPException(status_code=401, detail="device bearer credential required")
        device = await self._store.get_device_by_credential(_hash(credential))
        if device is None or device.status is not DeviceStatus.ACTIVE:
            raise HTTPException(status_code=401, detail="invalid device credential")
        if not await self._validate_session(device.owner_user_id, device.session_version):
            raise HTTPException(status_code=401, detail="device session is no longer valid")
        return device

    async def bind_mount(
        self,
        *,
        device_id: str,
        risk_workspace_id: str,
        mount_id: str,
    ) -> None:
        device = await self._store.get_device(device_id)
        if device is None or device.status is not DeviceStatus.ACTIVE:
            raise HTTPException(status_code=404, detail="active device not found")
        await self._store.save_mount_binding(
            DeviceMountBinding(device_id, risk_workspace_id, mount_id)
        )

    async def revoke(self, device_id: str) -> None:
        device = await self._store.get_device(device_id)
        if device is None:
            return
        await self._store.save_device(
            replace(
                device,
                status=DeviceStatus.REVOKED,
                revoked_at=normalize_utc(self._clock(), "device_auth.clock"),
            )
        )

    async def revoke_owned(self, *, device_id: str, owner_user_id: str) -> None:
        device = await self._store.get_device(device_id)
        if device is None or device.owner_user_id != owner_user_id:
            raise HTTPException(status_code=404, detail="desktop device not found")
        await self.revoke(device_id)

    async def resolve_mount_binding(self, mount_id: str) -> DeviceMountBinding | None:
        return await self._store.get_mount_binding(mount_id)


class DeviceSourceAuthorizer:
    def __init__(self, *, devices: DesktopDeviceAuthService, control_facade) -> None:
        self._devices = devices
        self._control = control_facade

    async def __call__(self, request: Request, resource_id: str) -> None:
        device = await self._devices.authenticate(request)
        binding = await self._devices.resolve_mount_binding(resource_id)
        if binding is None or binding.device_id != device.device_id:
            raise HTTPException(status_code=403, detail="device is not bound to mount")
        decision = await self._control.authorize_vws_action(
            actor_user_id=device.owner_user_id,
            risk_workspace_id=binding.risk_workspace_id,
            action=PublicVwsAction.MOUNT_SOURCE_OPERATION,
            mount_id=binding.mount_id,
        )
        if not decision.allowed:
            raise HTTPException(status_code=403, detail="desktop source operation denied")


class DeviceWorkspaceAuthorizer:
    """Authorize a bearer-authenticated device before creating its local mount."""

    def __init__(self, *, devices: DesktopDeviceAuthService, control_facade) -> None:
        self._devices = devices
        self._control = control_facade

    async def __call__(self, request: Request, risk_workspace_id: str) -> None:
        device = await self._devices.authenticate(request)
        decision = await self._control.authorize_vws_action(
            actor_user_id=device.owner_user_id,
            risk_workspace_id=risk_workspace_id,
            action=PublicVwsAction.SOURCE_MOUNT,
        )
        if not decision.allowed:
            raise HTTPException(status_code=403, detail="desktop mount creation denied")


class ChallengeResponse(BaseModel):
    challenge: str
    expires_in_seconds: int


class EnrollmentRequest(BaseModel):
    challenge: str
    device_id: str
    device_label: str


class EnrollmentResponse(BaseModel):
    device_credential: str


def create_device_enrollment_router(
    *,
    devices: DesktopDeviceAuthService,
    principal_resolver,
    csrf_guard: CsrfGuard | None = None,
) -> APIRouter:
    router = APIRouter()
    csrf = csrf_guard or CsrfGuard()

    @router.post("/api/v1/desktop/enrollment-challenges", response_model=ChallengeResponse)
    async def issue(request: Request) -> ChallengeResponse:
        principal = await principal_resolver(request)
        try:
            await csrf(request, x_csrf_token=request.headers.get("X-CSRF-Token"))
        except CsrfValidationError as exc:
            raise HTTPException(status_code=403, detail="CSRF validation failed") from exc
        challenge = await devices.issue_challenge(
            owner_user_id=principal.user.id,
            session_version=principal.session.session_version,
        )
        return ChallengeResponse(challenge=challenge, expires_in_seconds=300)

    @router.post("/desktop/devices/enroll", response_model=EnrollmentResponse)
    async def enroll(body: EnrollmentRequest) -> EnrollmentResponse:
        credential = await devices.exchange_challenge(
            challenge=body.challenge,
            device_id=body.device_id,
            device_label=body.device_label,
        )
        return EnrollmentResponse(device_credential=credential)

    @router.post("/api/v1/desktop/devices/{device_id}/revoke", status_code=204)
    async def revoke(request: Request, device_id: str) -> Response:
        principal = await principal_resolver(request)
        try:
            await csrf(request, x_csrf_token=request.headers.get("X-CSRF-Token"))
        except CsrfValidationError as exc:
            raise HTTPException(status_code=403, detail="CSRF validation failed") from exc
        await devices.revoke_owned(
            device_id=device_id,
            owner_user_id=principal.user.id,
        )
        return Response(status_code=204)

    return router


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


__all__ = [
    "DesktopDevice",
    "DesktopDeviceAuthService",
    "DeviceAuthStore",
    "DeviceMountBinding",
    "DeviceSourceAuthorizer",
    "DeviceWorkspaceAuthorizer",
    "DeviceStatus",
    "EnrollmentChallenge",
    "InMemoryDeviceAuthStore",
    "create_device_enrollment_router",
]
