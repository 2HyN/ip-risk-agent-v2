from __future__ import annotations

import inspect
from dataclasses import fields

from ip_risk_agent.api import ControlApiDependencies, create_control_api_bundle
from ip_risk_agent.application.process_change import TaskEnqueuer
from ip_risk_agent.application.public_facade import (
    ControlPlaneFacade,
    CorrelationIds,
    StructuredEventSink,
    StructuredLogger,
)
from ip_risk_agent.persistence.core_firestore import (
    FirestoreControlUnitOfWorkFactory,
    REQUIRED_COMPOSITE_INDEXES,
)


def _parameter_names(callable_object: object) -> tuple[str, ...]:
    return tuple(inspect.signature(callable_object).parameters)


def test_facade_public_wiring_signatures_are_stable() -> None:
    assert _parameter_names(ControlPlaneFacade) == (
        "unit_of_work_factory",
        "task_enqueuer",
        "clock",
        "id_factory",
        "config",
        "observer",
    )
    assert _parameter_names(ControlPlaneFacade.authorize_vws_action) == (
        "self",
        "actor_user_id",
        "risk_workspace_id",
        "action",
        "mount_id",
        "provider_credential_owner_user_id",
    )
    assert _parameter_names(ControlPlaneFacade.register_source_metadata) == (
        "self",
        "command",
    )
    assert _parameter_names(ControlPlaneFacade.get_original_source_request) == (
        "self",
        "actor_user_id",
        "risk_workspace_id",
        "artifact_id",
    )


def test_integration_ports_and_factories_keep_content_free_signatures() -> None:
    assert _parameter_names(TaskEnqueuer.enqueue_change) == (
        "self",
        "change_event_id",
    )
    assert _parameter_names(FirestoreControlUnitOfWorkFactory.from_client) == (
        "client",
        "max_attempts",
    )
    assert _parameter_names(create_control_api_bundle) == ("dependencies",)
    assert tuple(field.name for field in fields(ControlApiDependencies)) == (
        "auth",
        "workspaces",
        "risks",
        "history",
        "security",
        "notifications",
        "session",
        "hardening",
        "observer",
    )


def test_observability_is_available_from_the_stable_public_facade() -> None:
    assert CorrelationIds.__module__ == "ip_risk_agent.application.observability"
    assert StructuredEventSink.__module__ == "ip_risk_agent.application.observability"
    assert StructuredLogger.__module__ == "ip_risk_agent.application.observability"


def test_firestore_index_wiring_manifest_is_stable() -> None:
    assert tuple(
        (index.collection, index.fields) for index in REQUIRED_COMPOSITE_INDEXES
    ) == (
        ("memberships", ("record_kind", "risk_workspace_id")),
        ("memberships", ("record_kind", "user_id", "status")),
        ("memberships", ("record_kind", "email")),
        ("workspace_mounts", ("record_kind", "risk_workspace_id")),
        (
            "workspace_mounts",
            ("record_kind", "risk_workspace_id", "mounted_by_user_id"),
        ),
        (
            "risks",
            ("record_kind", "artifact_id", "analysis_type", "lifecycle_state"),
        ),
        ("risks", ("record_kind", "risk_workspace_id")),
        ("change_events", ("risk_workspace_id",)),
    )
