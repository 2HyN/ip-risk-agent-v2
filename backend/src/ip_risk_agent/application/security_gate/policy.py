"""Typed Security Gate policy and source-scope decision inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ip_risk_agent.core.common import DomainInvariantError, require_non_empty


@dataclass(frozen=True, slots=True)
class SecurityGatePolicy:
    policy_version: str
    global_ignore_text: str = ""
    max_input_bytes: int = 2_000_000
    max_output_bytes: int = 256_000
    max_segments: int = 64
    max_segment_bytes: int = 32_000
    document_full_text_bytes: int = 128_000
    allow_text_patent: bool = True
    denied_mime_prefixes: tuple[str, ...] = (
        "audio/",
        "font/",
        "image/",
        "video/",
    )
    denied_mime_types: tuple[str, ...] = (
        "application/gzip",
        "application/octet-stream",
        "application/x-7z-compressed",
        "application/x-rar-compressed",
        "application/zip",
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_version",
            require_non_empty(self.policy_version, "security_gate_policy.policy_version"),
        )
        for field_name in (
            "max_input_bytes",
            "max_output_bytes",
            "max_segments",
            "max_segment_bytes",
            "document_full_text_bytes",
        ):
            if getattr(self, field_name) < 1:
                raise DomainInvariantError(f"security_gate_policy.{field_name} must be positive")
        if self.max_output_bytes > self.max_input_bytes:
            raise DomainInvariantError(
                "security_gate_policy.max_output_bytes cannot exceed max_input_bytes"
            )
        object.__setattr__(
            self,
            "denied_mime_prefixes",
            tuple(_normalize_mime(value) for value in self.denied_mime_prefixes),
        )
        object.__setattr__(
            self,
            "denied_mime_types",
            tuple(_normalize_mime(value) for value in self.denied_mime_types),
        )


@dataclass(frozen=True, slots=True)
class SourceScopeDecision:
    """Ephemeral source-owned deny input; it is never persisted by the Gate."""

    in_scope: bool = True
    ignore_text: str = ""
    denial_code_safe: str | None = None

    def __post_init__(self) -> None:
        if not self.in_scope and self.denial_code_safe is None:
            object.__setattr__(self, "denial_code_safe", "SOURCE_SCOPE_DENIED")
        elif self.denial_code_safe is not None:
            object.__setattr__(
                self,
                "denial_code_safe",
                require_non_empty(
                    self.denial_code_safe,
                    "source_scope_decision.denial_code_safe",
                ),
            )


class SecurityPolicyResolver(Protocol):
    def resolve(self, risk_workspace_id: str, policy_version: str) -> SecurityGatePolicy: ...


class InMemorySecurityPolicyResolver:
    def __init__(self, policies: tuple[tuple[str, SecurityGatePolicy], ...]) -> None:
        self._policies = {
            (
                require_non_empty(workspace_id, "security_policy.workspace_id"),
                policy.policy_version,
            ): policy
            for workspace_id, policy in policies
        }
        if len(self._policies) != len(policies):
            raise DomainInvariantError("duplicate workspace Security Gate policy version")

    def resolve(self, risk_workspace_id: str, policy_version: str) -> SecurityGatePolicy:
        key = (risk_workspace_id, policy_version)
        try:
            return self._policies[key]
        except KeyError as exc:
            raise SecurityPolicyResolutionError(
                "canonical workspace Security Gate policy was not found"
            ) from exc


class SecurityPolicyResolutionError(DomainInvariantError):
    pass


def _normalize_mime(value: str) -> str:
    return require_non_empty(value, "security_gate_policy.mime").casefold()


__all__ = [
    "InMemorySecurityPolicyResolver",
    "SecurityGatePolicy",
    "SecurityPolicyResolutionError",
    "SecurityPolicyResolver",
    "SourceScopeDecision",
]
