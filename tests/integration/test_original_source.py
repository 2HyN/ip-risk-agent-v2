from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException
from iprisk_contracts import (
    MountRef,
    OriginalSourceLocator,
    OriginalSourceType,
    SourceArtifactRef,
    SourceType,
)

from ip_risk_agent.application.public_facade import (
    FacadeAuthorizationDecision,
    OriginalSourceRequest,
    PublicVwsAction,
)
from ip_risk_agent.composition.originals import OriginalSourceService
from ip_risk_agent.composition.providers import SourceAdapterRegistry


class FakeControl:
    def __init__(self, source_type: SourceType, *, allowed: bool = True) -> None:
        self.source_type = source_type
        self.allowed = allowed
        self.auth_calls = []

    async def get_original_source_request(self, **_values):
        return OriginalSourceRequest(
            requested_by_user_id="owner-1",
            mount=MountRef(
                risk_workspace_id="vws-1",
                mount_id="mount-1",
                source_workspace_id="source-1",
                source_type=self.source_type,
            ),
            artifact=SourceArtifactRef(
                source_artifact_id="artifact-source-id",
                display_name="main.py",
            ),
        )

    async def authorize_vws_action(self, **values):
        self.auth_calls.append(values)
        return FacadeAuthorizationDecision(self.allowed, "ALLOWED", True)


class FakeAdapter:
    def __init__(self, source_type: SourceType, locator: OriginalSourceLocator) -> None:
        self.source_type = source_type
        self.locator = locator

    async def resolve_original(self, _artifact):
        return self.locator


def test_open_original_rechecks_mount_authority_and_allows_only_provider_host() -> None:
    async def scenario() -> None:
        control = FakeControl(SourceType.GITHUB)
        service = OriginalSourceService(
            control_facade=control,
            adapters=SourceAdapterRegistry(
                (
                    FakeAdapter(
                        SourceType.GITHUB,
                        OriginalSourceLocator(
                            original_source_type=OriginalSourceType.PROVIDER_URL,
                            provider_url="https://github.com/acme/repo/blob/main/src/main.py",
                            metadata_safe={},
                        ),
                    ),
                )
            ),
        )
        locator = await service.resolve(
            actor_user_id="owner-1",
            risk_workspace_id="vws-1",
            artifact_id="artifact-1",
        )
        assert locator.provider_url.startswith("https://github.com/")
        assert control.auth_calls[-1]["action"] is PublicVwsAction.MOUNT_SOURCE_OPERATION
        assert control.auth_calls[-1]["mount_id"] == "mount-1"

        evil = OriginalSourceService(
            control_facade=control,
            adapters=SourceAdapterRegistry(
                (
                    FakeAdapter(
                        SourceType.GITHUB,
                        OriginalSourceLocator(
                            original_source_type=OriginalSourceType.PROVIDER_URL,
                            provider_url="https://github.com.evil.example/repository",
                            metadata_safe={},
                        ),
                    ),
                )
            ),
        )
        with pytest.raises(HTTPException) as error:
            await evil.resolve(
                actor_user_id="owner-1",
                risk_workspace_id="vws-1",
                artifact_id="artifact-1",
            )
        assert error.value.status_code == 502

        control.allowed = False
        with pytest.raises(HTTPException) as error:
            await service.resolve(
                actor_user_id="owner-1",
                risk_workspace_id="vws-1",
                artifact_id="artifact-1",
            )
        assert error.value.status_code == 403

    asyncio.run(scenario())


def test_local_original_returns_only_opaque_device_and_artifact_identity() -> None:
    async def scenario() -> None:
        service = OriginalSourceService(
            control_facade=FakeControl(SourceType.LOCAL),
            adapters=SourceAdapterRegistry(
                (
                    FakeAdapter(
                        SourceType.LOCAL,
                        OriginalSourceLocator(
                            original_source_type=OriginalSourceType.LOCAL_DEVICE,
                            device_id="device-1",
                            source_artifact_id="opaque-local-artifact",
                            metadata_safe={},
                        ),
                    ),
                )
            ),
        )
        locator = await service.resolve(
            actor_user_id="owner-1",
            risk_workspace_id="vws-1",
            artifact_id="artifact-1",
        )
        assert locator.provider_url is None
        assert locator.device_id == "device-1"
        assert locator.source_artifact_id == "opaque-local-artifact"

    asyncio.run(scenario())
