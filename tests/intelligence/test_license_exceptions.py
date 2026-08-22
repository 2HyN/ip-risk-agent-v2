"""`WITH` 예외를 평가에 반영한다.

파서는 예외를 제대로 읽어 `LicenseNode.exception` 에 담고 있었는데 **정책이 그 필드를 한
번도 보지 않았다.** 그래서 두 가지가 동시에 일어났다.

* `GPL-2.0-only WITH Classpath-exception-2.0` 이 맨 GPL 과 같은 `POLICY_CONFLICT` 였다.
  링크를 허용하려고 존재하는 예외인데 무시된 것이라, **오탐이 자바 생태계 전반에 걸렸다.**
* `MIT WITH totally-made-up` 처럼 **날조된 예외가 아무 검증 없이 통과**했다.

방향이 서로 반대인 두 오류다. 여기서 둘 다 고정한다.

그리고 이 표에서 가장 중요한 것은 완화하는 예외를 모으는 일이 아니라 **완화처럼 보이지만
완화가 아닌 것**을 가려내는 일이다. OpenSSL 예외들이 그렇다.
"""

from __future__ import annotations

import pytest
from iprisk_contracts.common import LicensePolicyOutcome

from ip_risk_agent.intelligence.license import policy

CONFLICT = LicensePolicyOutcome.POLICY_CONFLICT
REVIEW = LicensePolicyOutcome.REVIEW_REQUIRED
NOTICE = LicensePolicyOutcome.NOTICE_REQUIRED
NO_ACTION = LicensePolicyOutcome.NO_ACTION


# ------------------------------------------------------- 완화하는 예외는 완화한다


@pytest.mark.parametrize(
    "expression",
    [
        "GPL-2.0-only WITH Classpath-exception-2.0",
        "GPL-3.0-only WITH GCC-exception-3.1",
        "GPL-3.0-only WITH GPL-3.0-linking-exception",
        "GPL-2.0-only WITH Linux-syscall-note",
        "GPL-2.0-or-later WITH Bison-exception-2.2",
    ],
)
def test_a_linking_or_output_exception_lowers_the_grade(expression: str) -> None:
    assert policy.evaluate_expression(expression) is REVIEW


def test_the_classpath_exception_is_the_case_that_hurt_most() -> None:
    """OpenJDK 전체가 쓰는 예외다. 무시하면 자바 의존성이 통째로 오탐이 된다."""
    bare = policy.evaluate("GPL-2.0-only")
    relieved = policy.evaluate("GPL-2.0-only WITH Classpath-exception-2.0")
    assert bare.outcome is CONFLICT
    assert relieved.outcome is REVIEW
    assert relieved.leading[0].was_relieved
    assert relieved.leading[0].relieved_from is CONFLICT


def test_relief_never_goes_below_a_human_looking() -> None:
    """예외의 조건(수정 여부·링크 방식·무엇을 배포하는가)은 코드가 확인할 수 없다.

    그래서 사람이 볼 자리까지만 내리고 멈춘다. `NOTICE_REQUIRED` 로 내리면 "고지만 하면
    된다" 가 되어, 확인하지 않은 조건을 충족했다고 단정하게 된다.
    """
    for exception, (effect, _why) in policy._EXCEPTION_EFFECT.items():
        if effect not in policy._RELIEF:
            continue
        outcome = policy.evaluate_expression(f"GPL-3.0-only WITH {exception}")
        assert outcome is REVIEW, exception


# --------------------------------------------- 완화처럼 보이지만 완화가 아닌 것


@pytest.mark.parametrize(
    "exception",
    [
        "openvpn-openssl-exception",
        "cryptsetup-OpenSSL-exception",
        "kvirc-openssl-exception",
        "vsftpd-openssl-exception",
        "x11vnc-openssl-exception",
        "stunnel-exception",
        "GPL-CC-1.0",
    ],
)
def test_a_compatibility_exception_is_not_relief_for_us(exception: str) -> None:
    """GPL 과 OpenSSL 의 비양립을 푸는 장치이지 비공개 배포를 허락하는 것이 아니다.

    이것을 완화로 분류하면 **거짓 하향**이 되고, 거짓 하향은 알림도 없이 사라진다.
    """
    assert policy.evaluate_expression(f"GPL-2.0-only WITH {exception}") is CONFLICT


@pytest.mark.parametrize(
    "exception",
    ["Universal-FOSS-exception-1.0", "RRDtool-FLOSS-exception-2.0", "DigiRule-FOSS-exception"],
)
def test_an_open_source_only_exception_does_not_help_a_closed_release(exception: str) -> None:
    """결합물을 오픈소스로 배포할 때만 쓸 수 있는 예외다."""
    assert policy.evaluate_expression(f"GPL-2.0-only WITH {exception}") is CONFLICT


# ------------------------------------------------------------- 검증되지 않은 예외


@pytest.mark.parametrize(
    "exception",
    [
        "totally-made-up",
        "Classpath-exception-2.O",  # 숫자 0 이 아니라 문자 O 다
        "classpath",
        "GPL-linking-exception",
    ],
)
def test_an_unregistered_exception_earns_no_relief(exception: str) -> None:
    assert policy.evaluate_expression(f"GPL-2.0-only WITH {exception}") is CONFLICT


def test_an_unregistered_exception_is_visible(recwarn: pytest.WarningsRecorder) -> None:
    """조용히 무시하면 그 오타가 맨 라이선스 판정으로 굳는다.

    등록되지 않은 예외는 대개 패키지 메타데이터의 오타다. 사람이 보면 고칠 수 있다.
    """
    result = policy.evaluate("GPL-2.0-only WITH Classpath-exception-2.O")
    assert result.notes, "등록되지 않은 예외가 기록에 남지 않는다"
    assert "등록되지 않은" in result.notes[0]


def test_an_exception_we_have_not_classified_says_so() -> None:
    """등록은 됐지만 효과를 아직 분류하지 않은 것. 완화하지 않고, 그 사실을 밝힌다."""
    effect, why = policy.exception_effect("SHL-2.0")
    assert effect is None
    assert "분류하지" in why


def test_every_exception_effect_records_why() -> None:
    for exception, (_effect, why) in policy._EXCEPTION_EFFECT.items():
        assert why.strip(), exception


# --------------------------------------------------------------- OR 의 선택을 남긴다


def test_or_records_which_branch_it_took() -> None:
    """값은 예전과 같아도 **무엇을 버렸는지**가 남아야 한다 (§7.3 의 보이는 하향)."""
    result = policy.evaluate("AGPL-3.0-only OR MIT")
    assert result.outcome is NOTICE
    assert [leaf.identifier for leaf in result.leading] == ["MIT"]
    assert any("AGPL-3.0-only" in note for note in result.notes)


def test_or_with_nothing_dropped_says_nothing() -> None:
    """두 갈래가 같은 무게면 버린 것이 없다. 없는 하향을 적지 않는다."""
    result = policy.evaluate("MIT OR ISC")
    assert result.outcome is NOTICE
    assert not any("버린 선택지" in note for note in result.notes)


def test_and_leads_with_the_heaviest_leaf() -> None:
    """게이트가 '판정을 이끈 leaf' 만 보려면 그것이 무엇인지 나와야 한다."""
    result = policy.evaluate("Apache-2.0 AND GPL-3.0-only")
    assert result.outcome is CONFLICT
    assert [leaf.identifier for leaf in result.leading] == ["GPL-3.0-only"]


def test_an_or_of_only_unknowns_stays_unknown() -> None:
    """모르는 것들 중에서 고른다고 가벼워지지 않는다."""
    result = policy.evaluate("LicenseRef-A OR LicenseRef-B")
    assert result.outcome is LicensePolicyOutcome.UNKNOWN


# ------------------------------------------------------------------- 회귀 고정
#
# `DEVELOPMENT_SPEC.md` §5.3 의 표. 다섯 줄이 전부 의도한 값이어야 2-B 가 끝난다.


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("GPL-2.0-only", CONFLICT),
        ("GPL-2.0-only WITH Classpath-exception-2.0", REVIEW),
        ("MIT WITH totally-made-up", NOTICE),
        ("0BSD OR GPL-3.0-only", NO_ACTION),
        ("AGPL-3.0-only OR MIT", NOTICE),
    ],
)
def test_the_specification_table(expression: str, expected: LicensePolicyOutcome) -> None:
    assert policy.evaluate_expression(expression) is expected
