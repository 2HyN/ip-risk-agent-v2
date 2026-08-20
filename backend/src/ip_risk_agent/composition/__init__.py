"""Integration Agent 소유 조립 계층.

세 Plane 의 public surface 만 import 한다. 어떤 Plane 의 내부 모듈도 직접
건드리지 않는다 (Master Spec 5, README 4).
"""

from .app import create_app
from .container import Container, SourcePorts, UnavailableOidcClient, build_container
from .pipeline import AnalysisPipeline, PipelineOutcome
from .runtime import id_factory, utc_clock
from .settings import (
    ControlSettings,
    IntelligenceSettings,
    Settings,
    SourceSettings,
)
from .sinks import ControlSourceChangeSink
from .source_callbacks import (
    ConnectionRegistry,
    DeviceRegistry,
    SourceRegistrationService,
)

__all__ = [
    "AnalysisPipeline",
    "ConnectionRegistry",
    "Container",
    "ControlSettings",
    "ControlSourceChangeSink",
    "DeviceRegistry",
    "IntelligenceSettings",
    "PipelineOutcome",
    "Settings",
    "SourcePorts",
    "SourceRegistrationService",
    "SourceSettings",
    "UnavailableOidcClient",
    "build_container",
    "create_app",
    "id_factory",
    "utc_clock",
]
