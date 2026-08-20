"""Integration-owned boundary and runtime composition helpers."""

from .analyzer_completeness import AnalyzerCompletenessError, CompleteIntelligenceFacade
from .app import create_api_app, create_worker_app
from .container import ContainerOverrides, RuntimeContainer, build_container
from .device_auth import (
    DesktopDeviceAuthService,
    DeviceSourceAuthorizer,
    DeviceWorkspaceAuthorizer,
)
from .source_auth import SessionSourceAuthorizer, SourceResourceScope
from .source_registration import SourceRegistrationService
from .source_completion import ProductSourceCompletionRedirect
from .pipeline import AnalysisPipeline, PipelineDisposition, RetryablePipelineError
from .providers import SourceAdapterRegistry, SourceRouterBundle
from .settings import AppRole, RuntimeProfile, Settings, SettingsError

__all__ = [
    "AnalyzerCompletenessError",
    "AnalysisPipeline",
    "AppRole",
    "CompleteIntelligenceFacade",
    "ContainerOverrides",
    "DesktopDeviceAuthService",
    "DeviceSourceAuthorizer",
    "DeviceWorkspaceAuthorizer",
    "PipelineDisposition",
    "RetryablePipelineError",
    "RuntimeContainer",
    "RuntimeProfile",
    "SessionSourceAuthorizer",
    "SourceRegistrationService",
    "ProductSourceCompletionRedirect",
    "SourceResourceScope",
    "SourceAdapterRegistry",
    "SourceRouterBundle",
    "Settings",
    "SettingsError",
    "build_container",
    "create_api_app",
    "create_worker_app",
]

