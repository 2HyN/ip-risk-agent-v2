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
    #: 의존성 파일에만 쓰는 상한. 산문 상한과 따로 두는 이유가 있다.
    #:
    #: 산문 상한(``max_output_bytes``)이 작은 것은 **그 내용이 provider 로 나가기**
    #: 때문이다 — Gemini 추출과 KIPRIS 대조가 원문을 받는다. 그런데 라이선스 경로는
    #: 파일 내용을 아무 데도 보내지 않는다. 로컬에서 파싱해 **패키지 이름과 버전만**
    #: 레지스트리에 묻고, RAG 질의도 표현식과 판정으로만 만든다. 그러니 그 상한이
    #: 지키려는 것이 여기에는 해당하지 않는다.
    #:
    #: 그리고 잘린 락파일은 쓸모가 없다. ``package-lock.json`` 은 메가바이트 단위이고
    #: 32KB 에서 자르면 깨진 JSON 이라 **한 건도 못 읽는다.** 이 저장소의
    #: ``pnpm-lock.yaml`` 만 해도 51,862 바이트다.
    dependency_output_bytes: int = 2_000_000
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
            "dependency_output_bytes",
            "document_full_text_bytes",
        ):
            if getattr(self, field_name) < 1:
                raise DomainInvariantError(f"security_gate_policy.{field_name} must be positive")
        if self.max_output_bytes > self.max_input_bytes:
            raise DomainInvariantError(
                "security_gate_policy.max_output_bytes cannot exceed max_input_bytes"
            )
        # 오류가 아니라 깎는다. 게이트가 받은 것보다 많이 내보낼 수는 없으므로 이 값이
        # 입력 상한을 넘는 것은 잘못된 설정이 아니라 **의미가 없는 것**이다. 작은 상한으로
        # 게이트를 만드는 자리(시험·부분 정책)를 이 기본값이 깨뜨리지 않게 한다.
        if self.dependency_output_bytes > self.max_input_bytes:
            object.__setattr__(self, "dependency_output_bytes", self.max_input_bytes)
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
