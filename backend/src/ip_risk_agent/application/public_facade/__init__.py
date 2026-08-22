"""Stable Integration-facing Control Plane API."""

from ip_risk_agent.application.observability import (
    CorrelationIds,
    ErrorCategory,
    PythonLoggingSink,
    SafeErrorDescriptor,
    StructuredEventSink,
    StructuredLogger,
)

from .models import (
    AnalysisArtifactBuildResult,
    AnalysisExecutionClaim,
    AnalysisResultReceipt,
    ControlPlaneFacadeConfig,
    EvidenceRetentionConfig,
    FacadeAuthorizationDecision,
    OriginalSourceRequest,
    PublicVwsAction,
    SecurityGatePolicyConfig,
    SourceAccessReceiptContext,
    SourceAccessRegistration,
    SourceChangeReceipt,
    SourceMetadataRegistration,
    SourceMetadataRegistrationCommand,
    SourceScopeInput,
    SourceWorkspaceContext,
    UntrackedArtifact,
)
from .ports import SourceAuthorizationCallback, SourceMetadataRegistrationCallback
from .service import ControlPlaneFacade

__all__ = [
    "AnalysisArtifactBuildResult",
    "AnalysisExecutionClaim",
    "AnalysisResultReceipt",
    "ControlPlaneFacade",
    "ControlPlaneFacadeConfig",
    "CorrelationIds",
    "ErrorCategory",
    "EvidenceRetentionConfig",
    "FacadeAuthorizationDecision",
    "OriginalSourceRequest",
    "PublicVwsAction",
    "PythonLoggingSink",
    "SafeErrorDescriptor",
    "SecurityGatePolicyConfig",
    "SourceAccessReceiptContext",
    "SourceAccessRegistration",
    "SourceAuthorizationCallback",
    "SourceChangeReceipt",
    "SourceMetadataRegistration",
    "SourceMetadataRegistrationCommand",
    "SourceMetadataRegistrationCallback",
    "SourceScopeInput",
    "SourceWorkspaceContext",
    "UntrackedArtifact",
    "StructuredEventSink",
    "StructuredLogger",
]

