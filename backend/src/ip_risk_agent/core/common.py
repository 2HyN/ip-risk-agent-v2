"""Shared Control Plane domain primitives without infrastructure dependencies."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from typing import Iterable, Mapping


class DomainInvariantError(ValueError):
    """Raised when constructing or transitioning an invalid domain value.

    메시지는 **불변조건과 필드 이름만** 담는다. 값은 담지 않는다 — 보간하는 경우도
    `field_name` 처럼 개발자가 쓴 상수뿐이다. 그 성질 덕분에 진단 로그에 사유를
    노출해도 사용자 데이터나 provider 페이로드가 새지 않는다.

    클래스 이름만 남기면 121 곳의 서로 다른 불변조건이 하나로 뭉뚱그려져 배포에서
    원인을 좁힐 수 없다. 실제로 `CONTRACT:CANONICAL_INTAKE_REJECTED` 만 보고 세 번
    추측해야 했다. 새 메시지를 쓸 때도 값이 아니라 이름을 쓴다.
    """

    @property
    def safe_reason(self) -> str:
        return str(self)


class ActorType(StrEnum):
    SYSTEM = "SYSTEM"
    USER = "USER"


def require_non_empty(value: str, field_name: str) -> str:
    """Return a trimmed non-empty value or raise a domain error."""

    normalized = value.strip()
    if not normalized:
        raise DomainInvariantError(f"{field_name} must not be empty")
    return normalized


def normalize_utc(value: datetime, field_name: str) -> datetime:
    """Require a timezone-aware timestamp and normalize it to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainInvariantError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def require_chronological(
    earlier: datetime,
    later: datetime,
    *,
    earlier_name: str,
    later_name: str,
) -> None:
    """Require ``later`` to be at or after ``earlier``."""

    if later < earlier:
        raise DomainInvariantError(f"{later_name} cannot precede {earlier_name}")


def stable_key(namespace: str, parts: Iterable[str]) -> str:
    """Build a versioned deterministic key with unambiguous component encoding."""

    normalized_namespace = require_non_empty(namespace, "namespace")
    normalized_parts = tuple(require_non_empty(part, "identity component") for part in parts)
    payload = json.dumps(
        ["v1", normalized_namespace, *normalized_parts],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{normalized_namespace}:v1:{sha256(payload).hexdigest()}"


def freeze_json_value(value: object, field_name: str = "value") -> object:
    """Validate and recursively freeze a JSON-safe domain value."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DomainInvariantError(f"{field_name} must contain finite JSON numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise DomainInvariantError(f"{field_name} keys must be strings")
            frozen[key] = freeze_json_value(nested, f"{field_name}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            freeze_json_value(nested, f"{field_name}[{index}]")
            for index, nested in enumerate(value)
        )
    raise DomainInvariantError(f"{field_name} must contain only JSON-safe values")


def freeze_safe_mapping(value: Mapping[str, object], field_name: str) -> Mapping[str, object]:
    """Validate and freeze a mapping whose values must be JSON-safe."""

    frozen = freeze_json_value(value, field_name)
    if not isinstance(frozen, Mapping):  # pragma: no cover - guarded by the parameter type
        raise DomainInvariantError(f"{field_name} must be a mapping")
    return frozen
