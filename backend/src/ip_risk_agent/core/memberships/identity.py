"""Deterministic membership and invitation identity."""

from ip_risk_agent.core.common import DomainInvariantError, require_non_empty, stable_key


def normalize_invitation_email(email: str) -> str:
    """Normalize identity comparison without provider-specific mailbox rewriting."""

    normalized = require_non_empty(email, "invitation.email").casefold()
    local, separator, domain = normalized.rpartition("@")
    if not separator or not local or not domain:
        raise DomainInvariantError("invitation.email must contain a local part and domain")
    return normalized


def membership_id_for(risk_workspace_id: str, user_id: str) -> str:
    return stable_key("membership", (risk_workspace_id, user_id))


def invitation_id_for(risk_workspace_id: str, email: str) -> str:
    return stable_key("membership-invitation", (risk_workspace_id, normalize_invitation_email(email)))
