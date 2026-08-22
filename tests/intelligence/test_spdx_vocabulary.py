"""어휘는 넓게, 판단은 좁게.

이 저장소는 오랫동안 **등록된 식별자 42 개만** 알았고, 그래서 `BUSL-1.1` 처럼 실재하는
식별자가 저장 경계 이전에 문자열 `UNKNOWN` 으로 소거됐다. 소거된 뒤에는 정책 표를 넓혀도
구제할 수 없다 — 원문이 어디에도 남지 않기 때문이다.

그래서 두 가지를 갈라 두고, 여기서 그 분리를 고정한다.

* :mod:`~ip_risk_agent.intelligence.license.spdx` 는 **SPDX 전부**를 안다.
* :mod:`~ip_risk_agent.intelligence.license.policy` 는 **분류한 것만** 안다.

둘을 같게 맞추려 들면 727 개를 전부 분류해야 하고, 그것은 근거 없는 단정을 700 개쯤
만드는 일이다.
"""

from __future__ import annotations

import pytest
from iprisk_contracts.common import LicensePolicyOutcome

from ip_risk_agent.intelligence.license import policy, spdx, spdx_data

_REGISTERED = frozenset(spdx_data.LICENSE_IDS)
_EXCEPTIONS = frozenset(spdx_data.EXCEPTION_IDS)


def test_the_vocabulary_is_the_whole_spdx_list() -> None:
    assert frozenset(spdx._CANONICAL) == _REGISTERED
    assert len(_REGISTERED) > 700, "목록이 갑자기 줄었다면 생성이 잘못된 것이다"
    assert spdx.SPDX_SNAPSHOT_VERSION == f"spdx-{spdx_data.SPDX_LIST_VERSION}"


@pytest.mark.parametrize("identifier", ["BUSL-1.1", "Elastic-2.0", "SSPL-1.0", "MIT-0"])
def test_a_registered_identifier_survives_the_storage_boundary(identifier: str) -> None:
    """등록된 것은 소거하지 않는다. 이것이 안 되면 원문 보존이 무의미해진다."""
    assert spdx.normalize(identifier) == identifier


def test_an_and_expression_does_not_lose_half_of_itself() -> None:
    """예전에는 `MIT AND BUSL-1.1` 이 `MIT AND UNKNOWN` 이 되어 절반이 사라졌다."""
    assert spdx.normalize("MIT AND BUSL-1.1") == "MIT AND BUSL-1.1"


@pytest.mark.parametrize(
    "written",
    ["LicenseRef-Proprietary", "LicenseRef-Acme-Internal", "DocumentRef-tool:LicenseRef-x"],
)
def test_a_user_defined_reference_is_kept(written: str) -> None:
    """`LicenseRef-*` 는 SPDX 문법이 인정하는 사용자 정의 참조다.

    소거하면 "우리가 쓰는 사내 라이선스" 와 "모르는 라이선스" 가 구별되지 않는다.
    """
    assert spdx.normalize(written) == written
    # 다만 등급은 매기지 않는다 — 사내 라이선스의 의무는 우리가 알 수 없다.
    assert policy.evaluate_expression(written) is LicensePolicyOutcome.UNKNOWN


@pytest.mark.parametrize(
    "written",
    ["", "unknown", "none", "other", "proprietary", "LicenseRef-", "정체불명"],
)
def test_what_is_not_an_identifier_still_becomes_unknown(written: str) -> None:
    assert spdx.canonicalize(written) == spdx.UNKNOWN_LICENSE


# ------------------------------------------------------------------- 폐기된 표기


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("GPL-2.0", "GPL-2.0-only"),
        ("GPL-2.0+", "GPL-2.0-or-later"),
        ("LGPL-2.1", "LGPL-2.1-only"),
        ("AGPL-3.0", "AGPL-3.0-only"),
        ("StandardML-NJ", "SMLNJ"),
        ("bzip2-1.0.5", "bzip2-1.0.6"),
    ],
)
def test_a_retired_spelling_moves_to_the_current_one(written: str, expected: str) -> None:
    """폐기 표기를 그대로 두면 현행 표기를 쓰는 정책 표와 어긋나 조용히 UNKNOWN 이 된다."""
    assert spdx.canonicalize(written) == expected


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("GPL-2.0-with-classpath-exception", "GPL-2.0-only WITH Classpath-exception-2.0"),
        ("GPL-3.0-with-GCC-exception", "GPL-3.0-only WITH GCC-exception-3.1"),
        ("eCos-2.0", "GPL-2.0-or-later WITH eCos-exception-2.0"),
        ("wxWindows", "LGPL-2.0-or-later WITH WxWindows-exception-3.1"),
    ],
)
def test_a_compound_retired_spelling_keeps_its_exception(written: str, expected: str) -> None:
    """옛 표기는 예외를 **이름 안에** 품고 있었다. 버리면 맨 GPL 과 같아진다."""
    assert spdx.normalize(written) == expected


def test_every_replacement_target_is_a_real_identifier() -> None:
    """표를 손으로 적었으므로 오타가 조용히 UNKNOWN 을 만들 수 있다."""
    for source, (identifier, exception) in spdx._DEPRECATED_REPLACEMENT.items():
        assert identifier in _REGISTERED, f"{source} -> {identifier}"
        if exception is not None:
            assert exception in _EXCEPTIONS, f"{source} -> WITH {exception}"


# ----------------------------------------------------------------- 정책 표의 무결성


def test_every_classified_identifier_is_a_real_one() -> None:
    """정책 표의 오타는 **영원히 UNKNOWN** 으로 나타나며 아무도 알아채지 못한다."""
    unknown = sorted(i for i in policy._OUTCOME_BY_ID if i not in _REGISTERED)
    assert unknown == []


def test_every_classified_exception_is_a_real_one() -> None:
    unknown = sorted(e for e in policy._EXCEPTION_EFFECT if e not in _EXCEPTIONS)
    assert unknown == []


def test_no_identifier_is_classified_twice() -> None:
    """같은 식별자가 두 등급에 있으면 뒤에 나온 것이 조용히 이긴다."""
    seen: dict[str, str] = {}
    for outcome, reason, identifiers in policy._POLICY:
        for identifier in identifiers:
            assert identifier not in seen, (
                f"{identifier} 가 {seen[identifier]} 와 {outcome.value} 에 함께 있다"
            )
            seen[identifier] = outcome.value


def test_every_classification_records_why() -> None:
    """근거 없는 분류는 나중에 되짚을 수 없다."""
    for identifier in policy._OUTCOME_BY_ID:
        assert policy.reason_for_identifier(identifier).strip()


def test_an_unclassified_but_registered_identifier_asks_for_a_human() -> None:
    """분류하지 않은 것은 "안전" 이 아니라 "아직 안 봤다" 는 뜻이다."""
    unclassified = sorted(_REGISTERED - set(policy._OUTCOME_BY_ID))
    assert unclassified, "전부 분류했다면 이 시험의 전제가 바뀐 것이다"
    sample = unclassified[0]
    assert policy.outcome_for_identifier(sample) is LicensePolicyOutcome.UNKNOWN
    assert policy.needs_review(LicensePolicyOutcome.UNKNOWN)
