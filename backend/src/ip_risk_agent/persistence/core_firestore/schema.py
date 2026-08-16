"""Canonical Firestore collection names and query-index declarations."""

from __future__ import annotations

from dataclasses import dataclass

USERS = "users"
RISK_WORKSPACES = "risk_workspaces"
MEMBERSHIPS = "memberships"
SOURCE_CONNECTIONS = "source_connections"
SOURCE_WORKSPACES = "source_workspaces"
WORKSPACE_MOUNTS = "workspace_mounts"
ARTIFACTS = "artifacts"
ARTIFACT_STATES = "artifact_states"
CHANGE_EVENTS = "change_events"
ANALYSIS_JOBS = "analysis_jobs"
RISKS = "risks"
RISK_EVIDENCE = "risk_evidence"
RISK_EVENTS = "risk_events"
AUDIT_EVENTS = "audit_events"
SOURCE_ACCESS_EVENTS = "source_access_events"
NOTIFICATIONS = "notifications"

CANONICAL_COLLECTIONS = (
    USERS,
    RISK_WORKSPACES,
    MEMBERSHIPS,
    SOURCE_CONNECTIONS,
    SOURCE_WORKSPACES,
    WORKSPACE_MOUNTS,
    ARTIFACTS,
    ARTIFACT_STATES,
    CHANGE_EVENTS,
    ANALYSIS_JOBS,
    RISKS,
    RISK_EVIDENCE,
    RISK_EVENTS,
    AUDIT_EVENTS,
    SOURCE_ACCESS_EVENTS,
    NOTIFICATIONS,
)

DOCUMENT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class CompositeIndex:
    collection: str
    fields: tuple[str, ...]


# Queries are sorted in application memory; these declarations contain only
# equality/IN lookup fields and are wiring inputs, not deploy configuration.
REQUIRED_COMPOSITE_INDEXES = (
    CompositeIndex(MEMBERSHIPS, ("record_kind", "risk_workspace_id")),
    CompositeIndex(MEMBERSHIPS, ("record_kind", "user_id", "status")),
    CompositeIndex(WORKSPACE_MOUNTS, ("record_kind", "risk_workspace_id")),
    CompositeIndex(
        WORKSPACE_MOUNTS,
        ("record_kind", "risk_workspace_id", "mounted_by_user_id"),
    ),
    CompositeIndex(
        RISKS,
        ("record_kind", "artifact_id", "analysis_type", "lifecycle_state"),
    ),
)


__all__ = [
    "ANALYSIS_JOBS",
    "ARTIFACTS",
    "ARTIFACT_STATES",
    "AUDIT_EVENTS",
    "CANONICAL_COLLECTIONS",
    "CHANGE_EVENTS",
    "CompositeIndex",
    "DOCUMENT_SCHEMA_VERSION",
    "MEMBERSHIPS",
    "NOTIFICATIONS",
    "REQUIRED_COMPOSITE_INDEXES",
    "RISKS",
    "RISK_EVIDENCE",
    "RISK_EVENTS",
    "RISK_WORKSPACES",
    "SOURCE_ACCESS_EVENTS",
    "SOURCE_CONNECTIONS",
    "SOURCE_WORKSPACES",
    "USERS",
    "WORKSPACE_MOUNTS",
]
