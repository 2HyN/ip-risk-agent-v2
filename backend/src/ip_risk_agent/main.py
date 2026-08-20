"""Uvicorn factory entrypoint for the integrated public API."""

from __future__ import annotations

import os

from ip_risk_agent.composition.app import create_api_app
from ip_risk_agent.composition.container import build_container
from ip_risk_agent.composition.settings import AppRole, Settings, SettingsError


def create_app():
    settings = Settings.from_env(os.environ)
    if settings.role is not AppRole.API:
        raise SettingsError("ip_risk_agent.main requires APP_ROLE=api")
    return create_api_app(build_container(settings))


__all__ = ["create_app"]

