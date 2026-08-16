"""Deterministic Artifact identity helpers."""

from ip_risk_agent.core.common import stable_key


def artifact_id_for(source_workspace_id: str, source_artifact_id: str) -> str:
    return stable_key("artifact", (source_workspace_id, source_artifact_id))
