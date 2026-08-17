"""Source Plane 공통 에러 계층.

Agent 2 Spec 42번(Error Semantics): provider-private exception을 외부로
누출하지 않고 8개의 safe category로 변환한다. 이 8개 밖의 에러는 없다.
"""

from __future__ import annotations

from enum import Enum


class SourceErrorCategory(str, Enum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    TEMPORARY_UNAVAILABLE = "TEMPORARY_UNAVAILABLE"
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"
    INVALID_WEBHOOK = "INVALID_WEBHOOK"
    SOURCE_OFFLINE = "SOURCE_OFFLINE"


class SourceConnectorError(Exception):
    """모든 connector 예외의 공통 베이스.

    provider 원본 예외 객체나 raw response body는 여기 담지 않는다
    (로그/Contract 유출 금지, Master Spec 49/59번 참고).
    `safe_message`는 사용자에게 그대로 보여줘도 안전한 문자열이어야 한다.
    """

    category: SourceErrorCategory
    retryable: bool = False

    def __init__(
        self,
        provider: str,
        safe_message: str,
        *,
        retryable: bool | None = None,
    ) -> None:
        self.provider = provider
        self.safe_message = safe_message
        if retryable is not None:
            self.retryable = retryable
        super().__init__(f"[{provider}] {self.category.value}: {safe_message}")


class AuthRequiredError(SourceConnectorError):
    """credential 만료/미연결. 사용자의 재인증이 필요하다."""

    category = SourceErrorCategory.AUTH_REQUIRED
    retryable = False


class PermissionDeniedError(SourceConnectorError):
    """provider가 명시적으로 접근을 거부했다."""

    category = SourceErrorCategory.PERMISSION_DENIED
    retryable = False


class NotFoundError(SourceConnectorError):
    """대상 artifact가 provider 쪽에 존재하지 않는다."""

    category = SourceErrorCategory.NOT_FOUND
    retryable = False


class RateLimitedError(SourceConnectorError):
    """provider rate limit에 걸렸다. 잠시 후 재시도 가능하다."""

    category = SourceErrorCategory.RATE_LIMITED
    retryable = True


class TemporaryUnavailableError(SourceConnectorError):
    """provider 쪽 일시 장애. 재시도 가능하다."""

    category = SourceErrorCategory.TEMPORARY_UNAVAILABLE
    retryable = True


class UnsupportedContentError(SourceConnectorError):
    """content type/format을 이 connector가 처리할 수 없다."""

    category = SourceErrorCategory.UNSUPPORTED_CONTENT
    retryable = False


class InvalidWebhookError(SourceConnectorError):
    """webhook signature/payload 검증 실패."""

    category = SourceErrorCategory.INVALID_WEBHOOK
    retryable = False


class SourceOfflineError(SourceConnectorError):
    """Local Desktop 등 source 자체가 오프라인이다. 재시도 가능하다."""

    category = SourceErrorCategory.SOURCE_OFFLINE
    retryable = True


def to_provider_failure_fields(error: SourceConnectorError) -> dict[str, object]:
    """shared contract의 ProviderFailure(provider, category, retryable, safe_message)에
    바로 풀어 넣을 수 있는 dict를 만든다. 필드명은 contract와 정확히 일치시킨다.
    """

    return {
        "provider": error.provider,
        "category": error.category.value,
        "retryable": error.retryable,
        "safe_message": error.safe_message,
    }
