"""Integration-owned boundary and runtime composition helpers."""

from .analyzer_completeness import AnalyzerCompletenessError, CompleteIntelligenceFacade
from .device_auth import (
    DesktopDeviceAuthService,
    DeviceSourceAuthorizer,
    DeviceWorkspaceAuthorizer,
)
from .source_auth import SessionSourceAuthorizer, SourceResourceScope
from .source_registration import SourceRegistrationService

__all__ = [
    "AnalyzerCompletenessError",
    "CompleteIntelligenceFacade",
    "DesktopDeviceAuthService",
    "DeviceSourceAuthorizer",
    "DeviceWorkspaceAuthorizer",
    "SessionSourceAuthorizer",
    "SourceRegistrationService",
    "SourceResourceScope",
]

