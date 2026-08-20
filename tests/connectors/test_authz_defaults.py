from __future__ import annotations

from inspect import signature

from ip_risk_agent.connectors.common.authz import deny_all_authz
from ip_risk_agent.connectors.github.install_routes import create_github_install_router
from ip_risk_agent.connectors.github.mounts_routes import create_github_mounts_router
from ip_risk_agent.connectors.google_drive.mounts_routes import create_drive_mounts_router
from ip_risk_agent.connectors.google_drive.oauth_routes import create_drive_oauth_router
from ip_risk_agent.connectors.local.routes import create_local_desktop_router


def test_every_browser_and_desktop_router_authz_slot_defaults_to_deny() -> None:
    expected = {
        create_drive_oauth_router: ("authz_dependency",),
        create_github_install_router: ("authz_dependency",),
        create_drive_mounts_router: (
            "connection_authz_dependency",
            "workspace_authz_dependency",
        ),
        create_github_mounts_router: (
            "connection_authz_dependency",
            "workspace_authz_dependency",
        ),
        create_local_desktop_router: (
            "device_registration_authz_dependency",
            "workspace_authz_dependency",
            "mount_authz_dependency",
        ),
    }
    for factory, parameter_names in expected.items():
        parameters = signature(factory).parameters
        assert all(parameters[name].default is deny_all_authz for name in parameter_names)
