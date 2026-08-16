"""Stable Risk identity functions owned by the Control Plane."""

from ip_risk_agent.core.common import stable_key


def risk_id_for(risk_key: str) -> str:
    return stable_key("risk", (risk_key,))


def risk_evidence_id_for(
    risk_id: str, analysis_job_id: str, evidence_id_from_result: str
) -> str:
    return stable_key(
        "risk-evidence",
        (risk_id, analysis_job_id, evidence_id_from_result),
    )


def risk_event_id_for(
    risk_id: str,
    result_fingerprint: str,
    event_type: str,
) -> str:
    return stable_key("risk-event", (risk_id, result_fingerprint, event_type))


def patent_risk_key(artifact_id: str, normalized_application_number: str) -> str:
    return stable_key("risk-patent", (artifact_id, normalized_application_number))


def license_risk_key(
    artifact_id: str,
    ecosystem: str,
    normalized_package_name: str,
    resolved_version: str | None,
    normalized_license_expression: str,
) -> str:
    version_state = "resolved" if resolved_version is not None else "unresolved"
    version_value = resolved_version if resolved_version is not None else "not-applicable"
    return stable_key(
        "risk-license",
        (
            artifact_id,
            ecosystem,
            normalized_package_name,
            version_state,
            version_value,
            normalized_license_expression,
        ),
    )
