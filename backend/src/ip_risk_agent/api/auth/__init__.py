"""Agent 1 authentication API namespace."""

from .oidc import (
    AuthlibGoogleOidcClient,
    GOOGLE_DISCOVERY_URL,
    GoogleOidcClient,
    GoogleOidcConfig,
)
from .router import AuthRouterDependencies, UserResponse, create_auth_router

__all__ = [
    "AuthRouterDependencies",
    "AuthlibGoogleOidcClient",
    "GOOGLE_DISCOVERY_URL",
    "GoogleOidcClient",
    "GoogleOidcConfig",
    "UserResponse",
    "create_auth_router",
]

