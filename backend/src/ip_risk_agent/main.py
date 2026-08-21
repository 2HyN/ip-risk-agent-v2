"""Uvicorn factory entrypoint for the integrated public API."""

from __future__ import annotations

import os

from ip_risk_agent.composition.app import create_api_app
from ip_risk_agent.composition.container import build_container
from ip_risk_agent.composition.runtime import configure_logging
from ip_risk_agent.composition.production import build_google_cloud_runtime_composer
from ip_risk_agent.composition.settings import (
    AppRole,
    RuntimeProfile,
    Settings,
    SettingsError,
)
from ip_risk_agent.gcp.foundation import build_google_cloud_foundation


def create_app():
    settings = Settings.from_env(os.environ)
    configure_logging(settings.log_level)
    if settings.role is not AppRole.API:
        raise SettingsError("ip_risk_agent.main requires APP_ROLE=api")
    if settings.profile is RuntimeProfile.PRODUCTION:
        foundation = build_google_cloud_foundation(settings)
        overrides = foundation.container_overrides(
            runtime_composer=build_google_cloud_runtime_composer(foundation)
        )
        return create_api_app(build_container(settings, overrides=overrides))
    return create_api_app(build_container(settings))


__all__ = ["create_app"]

