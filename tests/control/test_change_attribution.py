"""판정이 왜 달라졌는가 (§7.4 · 3-B).

"등급이 바뀌었다" 는 알림은 값이 거의 없다. **"왜 바뀌었는가"** 가 값이다. 그리고 네
원인 중 **"당신은 가만있었는데 위험이 생겼다"** 가 이 제품이 파는 것이다.
"""

from __future__ import annotations

import inspect

import pytest

from ip_risk_agent.core.risk.attribution import (
    CauseAttribution,
    ChangeCause,
    VerdictFingerprint,
    attribute_change,
)

BASE = dict(
    analysis_input_checksum="input-1",
    policy_version="vws-1:table-1:axesA",
    rag_corpus_version="2026-08-23.4",
    model_id=None,
    prompt_version=None,
)


def fp(**overrides) -> VerdictFingerprint:
    return VerdictFingerprint(**{**BASE, **overrides})


def test_the_sentence_this_product_sells() -> None:
    """입력도 우리 쪽 지문도 그대로인데 판정이 달라졌다.

    바깥이 달라진 것이고, 달리 관측할 방법이 없다. §1.2 (A) 의 가운데 줄이다 —
    의존성은 그대로인데 그 패키지가 라이선스를 바꾼 경우.
    """
    found = attribute_change(fp(), fp())
    assert found.cause is ChangeCause.EXTERNAL_FACT
    assert found.is_external


def test_a_changed_input_ends_the_question() -> None:
    """다른 것을 보고 판단했으면 결과가 다른 것이 당연하다. 그 뒤는 볼 것이 없다."""
    found = attribute_change(fp(), fp(analysis_input_checksum="input-2"))
    assert found.cause is ChangeCause.INPUT


def test_the_user_setting_is_told_apart_from_our_table() -> None:
    """둘 다 ``policy_version`` 을 바꾼다. 세 조각으로 만들어 둔 이유가 이것이다.

    가운데가 바뀌면 "판단 기준이 좋아졌다", 끝이 바뀌면 **"당신이 배포 형태를 바꿨다"**
    다. 사용자에게는 전혀 다른 문장이다.
    """
    by_user = attribute_change(fp(), fp(policy_version="vws-1:table-1:axesB"))
    by_us = attribute_change(fp(), fp(policy_version="vws-1:table-2:axesA"))
    assert by_user.cause is ChangeCause.USER_POLICY
    assert by_us.cause is ChangeCause.OUR_KNOWLEDGE
    assert by_user.cause is not by_us.cause


@pytest.mark.parametrize(
    ("overrides", "expected"),
    (
        ({"rag_corpus_version": "2026-08-24.1"}, ChangeCause.OUR_KNOWLEDGE),
        ({"model_id": "gemini-4"}, ChangeCause.MODEL),
        ({"prompt_version": "v3"}, ChangeCause.MODEL),
    ),
)
def test_each_fingerprint_reaches_its_own_cause(overrides, expected) -> None:
    assert attribute_change(fp(), fp(**overrides)).cause is expected


def test_the_user_setting_wins_when_several_moved() -> None:
    """사용자가 스스로 바꾼 것이 가장 설명하기 쉬운 원인이다."""
    found = attribute_change(
        fp(), fp(policy_version="vws-1:table-2:axesB", rag_corpus_version="x")
    )
    assert found.cause is ChangeCause.USER_POLICY
    assert "deployment_axes" in found.moved


def test_not_knowing_is_not_the_same_as_nothing_changed() -> None:
    """이것이 이 판별식에서 가장 중요한 줄이다.

    비교할 직전 판정이 없거나 옛 기록에 지문이 없을 때 "외부 사실이 바뀌었다" 로
    적으면 **이 제품이 파는 문장이 거짓말이 된다.** 없는 것과 같은 것은 다르다.
    """
    assert attribute_change(None, fp()).cause is ChangeCause.UNKNOWN
    assert (
        attribute_change(fp(analysis_input_checksum=None), fp()).cause
        is ChangeCause.UNKNOWN
    )
    assert (
        attribute_change(fp(), fp(analysis_input_checksum=None)).cause
        is ChangeCause.UNKNOWN
    )


def test_an_old_flat_policy_version_cannot_be_split() -> None:
    """§5.10 이전 판정은 평평한 한 조각이다. 쪼갤 수 없으면 조각 비교를 하지 않는다."""
    old = fp(policy_version="global-license-policy-2026-08-14.1")
    assert old.policy_table_version is None
    assert old.deployment_axes is None


def test_the_wiring_is_covered_by_behaviour_not_by_reading_the_source() -> None:
    """이 파일은 판별식만 잰다. 배선은 이력을 실제로 읽어 확인한다.

    처음에는 여기서 `inspect.getsource` 로 소스에 문자열이 있는지 봤는데, 그것은
    **배선이 어긋나도 통과한다.** 실제로 어긋나 있었다 — 현재 판정의 지문을 저장소에서
    읽으려 했는데 이 실행의 판정은 아직 저장 전이라 `None` 이었고, 동작 시험을 쓰자마자
    터졌다.
    """
    from pathlib import Path

    ledger = (
        Path(__file__).with_name("test_attribution_ledger.py").read_text("utf-8")
    )
    assert "change_cause" in ledger
    assert "accept_analysis_result" in ledger, "이력을 실제로 만들어 봐야 한다"
