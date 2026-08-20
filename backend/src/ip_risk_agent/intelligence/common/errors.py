"""Typed failures for the Risk Intelligence plane.

Provider 장애를 "결과 없음"으로 바꾸지 않는 것이 이 plane 의 핵심 규약이다
(Master Spec 59-9). 그래서 실패는 전부 typed exception 으로 올리고,
Contract 로 나갈 때만 :class:`ProviderFailure` 로 축약한다.

축약할 때 raw response, token, credential 은 절대 싣지 않는다.
"""

from __future__ import annotations

from enum import Enum

from iprisk_contracts.common import ProviderFailure


class FailureCategory(str, Enum):
    """재시도 가능 여부를 판단하는 기준이자 Contract 의 ``category`` 값."""

    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    AUTH = "AUTH"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION = "VALIDATION"
    UNSUPPORTED = "UNSUPPORTED"


# 네트워크 성격의 실패만 재시도한다. 인증·검증 실패는 다시 해도 같은 결과다.
_RETRYABLE = frozenset(
    {
        FailureCategory.TIMEOUT,
        FailureCategory.UNAVAILABLE,
        FailureCategory.RATE_LIMITED,
    }
)


class IntelligenceError(Exception):
    """이 plane 이 올리는 모든 예외의 뿌리."""


class ArtifactRejectedError(IntelligenceError):
    """Security Gate 를 통과하지 못했거나 Contract 가 깨진 입력.

    Provider 를 호출하기 전에 올라와야 한다. Analyzer 가 아니라 호출자의 결함이므로
    ``AnalysisResult`` 로 감싸지 않고 Integration 까지 그대로 전달한다.
    """


class ProviderFailureError(IntelligenceError):
    """외부 provider 호출 실패.

    ``safe_message`` 만 Contract 로 나간다. 원문 응답은 여기서 끝난다.
    """

    def __init__(
        self,
        provider: str,
        category: FailureCategory,
        safe_message: str,
        *,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(f"{provider}: {category.value}: {safe_message}")
        self.provider = provider
        self.category = category
        self.safe_message = safe_message
        self.retryable = _RETRYABLE.__contains__(category) if retryable is None else retryable

    def as_contract(self) -> ProviderFailure:
        return ProviderFailure(
            provider=self.provider,
            category=self.category.value,
            retryable=self.retryable,
            safe_message=self.safe_message,
        )


class MalformedProviderOutputError(ProviderFailureError):
    """스키마는 맞지만 내용이 신뢰할 수 없는 응답.

    모델이 존재하지 않는 evidence ID 를 지어낸 경우가 대표적이다. 이때는 해당 항목만
    버리지 않고 비교 전체를 무효로 본다 (Agent 3 Spec 19).
    """

    def __init__(self, provider: str, safe_message: str, *, retryable: bool = True) -> None:
        super().__init__(
            provider,
            FailureCategory.MALFORMED_OUTPUT,
            safe_message,
            retryable=retryable,
        )
