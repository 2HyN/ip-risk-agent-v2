"""Stable Risk identity functions owned by the Control Plane."""

from ip_risk_agent.core.common import stable_key


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
