"""판정이 왜 달라졌는가 (§7.4 · 3-B).

## 왜 이것이 이 제품이다

§1.2 (A) 는 판정이 달라지는 원인을 넷으로 나눈다. 사용자에게 "등급이 바뀌었다" 는
알림은 값이 거의 없다. **"왜 바뀌었는가"** 가 값이다.

| 원인 | 사용자에게 |
|---|---|
| 입력 | 당신이 파일을 바꿨다 |
| 우리 지식 | 우리 판단 기준이 좋아졌다 |
| 사용자 설정 | **당신이 배포 형태를 바꿨다** |
| 모델 | 우리 모델이 바뀌었다 |
| **외부 사실** | **당신은 가만있었는데 위험이 생겼다** |

마지막 줄이 이 제품이 파는 것이다. 의존성은 그대로인데 그 패키지가 라이선스를 바꾼
경우다.

## 어떻게 가르는가

**입력부터 본다.** ``analysis_input_checksum`` 이 다르면 그 뒤는 볼 것이 없다 — 다른
것을 보고 판단했으므로 결과가 다른 것이 당연하다. 이 값은 파일 내용만이 아니라
redaction · 분석기 라우팅 · ``content_scope`` 까지 반영하므로, 같으면 **분석기가 본 것이
정말 같았다** 는 뜻이다.

입력이 같으면 우리 쪽 지문을 하나씩 본다. **어느 것도 안 달라졌는데 결과가 달라졌으면
바깥이 달라진 것이다.** 그것이 외부 사실 변화의 정의이고, 달리 관측할 방법이 없다.

## 사용자 설정과 우리 표를 가른다

둘 다 ``policy_version`` 을 바꾼다. §5.10 이 그 값을 세 조각으로 만들어 둔 이유가
여기다 — ``{workspace}:{정책표 판본}:{배포형태축 해시}``. 가운데가 바뀌면 "판단 기준이
좋아졌다", 끝이 바뀌면 **"당신이 배포 형태를 바꿨다"** 다. 사용자에게는 전혀 다른
문장이고, 뒤쪽은 §1.2 의 네 원인 어디에도 없던 다섯 번째다.

## 모르는 것을 안다고 하지 않는다

직전 판정이 없거나 (처음 본 Risk), 옛 기록에 지문이 없으면 ``UNKNOWN`` 이다. 그때
"외부 사실이 바뀌었다" 로 적으면 **이 제품이 파는 문장이 거짓말이 된다.** 없는 것과
같은 것은 다르다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChangeCause(StrEnum):
    """§1.2 (A) 의 네 원인 + 사용자 설정."""

    #: 당신이 파일을 바꿨다.
    INPUT = "INPUT"
    #: 우리 판단 기준이 좋아졌다 (정책 표 · corpus).
    OUR_KNOWLEDGE = "OUR_KNOWLEDGE"
    #: 당신이 배포 형태를 바꿨다.
    USER_POLICY = "USER_POLICY"
    #: 우리 모델이 바뀌었다.
    MODEL = "MODEL"
    #: **당신은 가만있었는데 위험이 생겼다.** 이 제품이 파는 것이다.
    EXTERNAL_FACT = "EXTERNAL_FACT"
    #: 비교할 직전 판정이 없다. 처음 본 Risk 이거나 옛 기록에 지문이 없다.
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class VerdictFingerprint:
    """한 판정이 무엇을 보고 무엇으로 내려졌는가."""

    analysis_input_checksum: str | None
    policy_version: str | None
    rag_corpus_version: str | None
    model_id: str | None
    prompt_version: str | None
    result_fingerprint: str | None = None

    @property
    def policy_table_version(self) -> str | None:
        """``{workspace}:{정책표}:{축}`` 의 가운데 조각."""
        return _policy_piece(self.policy_version, 1)

    @property
    def deployment_axes(self) -> str | None:
        """세 번째 조각. 사용자가 배포 형태를 바꾸면 이것이 달라진다."""
        return _policy_piece(self.policy_version, 2)


def _policy_piece(value: str | None, index: int) -> str | None:
    if value is None:
        return None
    pieces = value.split(":")
    # 옛 판정은 평평한 한 조각이었다 (§5.10 이전). 그때 것은 쪼갤 수 없다.
    return pieces[index] if len(pieces) == 3 else None


@dataclass(frozen=True, slots=True)
class CauseAttribution:
    cause: ChangeCause
    #: 실제로 달라진 지문 이름들. 화면이 문장을 만들 재료다.
    moved: tuple[str, ...] = ()

    @property
    def is_external(self) -> bool:
        return self.cause is ChangeCause.EXTERNAL_FACT


def attribute_change(
    previous: VerdictFingerprint | None,
    current: VerdictFingerprint | None,
) -> CauseAttribution:
    """판정이 달라진 원인. 비교할 것이 없으면 ``UNKNOWN``."""
    if previous is None or current is None:
        return CauseAttribution(ChangeCause.UNKNOWN)

    # 입력이 없으면 같은지 다른지를 **모른다.** 모르는 것을 같다고 읽으면 그 위의
    # 모든 판단이 근거를 잃는다 — 특히 "외부 사실이 바뀌었다" 가 거짓말이 된다.
    if previous.analysis_input_checksum is None or current.analysis_input_checksum is None:
        return CauseAttribution(ChangeCause.UNKNOWN)

    if previous.analysis_input_checksum != current.analysis_input_checksum:
        return CauseAttribution(ChangeCause.INPUT, ("analysis_input_checksum",))

    # 여기서부터는 **분석기가 본 것이 같았다.** 달라진 것은 우리 쪽이거나 바깥이다.
    moved: list[str] = []
    if previous.deployment_axes != current.deployment_axes:
        moved.append("deployment_axes")
    if previous.policy_table_version != current.policy_table_version:
        moved.append("policy_table_version")
    if previous.rag_corpus_version != current.rag_corpus_version:
        moved.append("rag_corpus_version")
    if previous.model_id != current.model_id:
        moved.append("model_id")
    if previous.prompt_version != current.prompt_version:
        moved.append("prompt_version")

    if "deployment_axes" in moved:
        # 사용자가 스스로 바꾼 것이 가장 설명하기 쉬운 원인이다. 다른 것이 함께
        # 달라졌어도 사용자에게는 이 문장이 먼저다.
        return CauseAttribution(ChangeCause.USER_POLICY, tuple(moved))
    if "model_id" in moved or "prompt_version" in moved:
        return CauseAttribution(ChangeCause.MODEL, tuple(moved))
    if moved:
        return CauseAttribution(ChangeCause.OUR_KNOWLEDGE, tuple(moved))

    # 입력도 우리 쪽 지문도 그대로인데 판정이 달라졌다. 바깥이 달라진 것이고,
    # 달리 관측할 방법이 없다 (§1.2 (A)).
    return CauseAttribution(ChangeCause.EXTERNAL_FACT)


__all__ = [
    "CauseAttribution",
    "ChangeCause",
    "VerdictFingerprint",
    "attribute_change",
]
