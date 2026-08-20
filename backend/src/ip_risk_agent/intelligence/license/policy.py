"""전역 라이선스 정책 v1.

정책은 법적 결론이 아니라 **검토 분류**다 (Agent 3 Spec 28). 조직마다 기준이 다르고
Frozen Contract 에는 VWS 별 정책을 실을 자리가 없으므로, MVP 는 버전이 붙은 전역
정책 하나만 쓴다.

판정은 전적으로 결정론적이다. 모델이 이 결과를 바꾸지 못한다.
"""

from __future__ import annotations

from iprisk_contracts.common import LicensePolicyOutcome

from .spdx import (
    UNKNOWN_LICENSE,
    AndNode,
    ExpressionNode,
    LicenseNode,
    OrNode,
    parse_expression,
)

# 정책 표나 SPDX 스냅샷을 바꾸면 반드시 올린다. 과거 판정을 설명하는 근거가 된다.
POLICY_VERSION = "global-license-policy-2026-08-14.1"

# 심각도 순서. 값이 클수록 검토 부담이 크다.
_SEVERITY: dict[LicensePolicyOutcome, int] = {
    LicensePolicyOutcome.NO_ACTION: 0,
    LicensePolicyOutcome.NOTICE_REQUIRED: 1,
    LicensePolicyOutcome.UNKNOWN: 2,
    LicensePolicyOutcome.REVIEW_REQUIRED: 3,
    LicensePolicyOutcome.POLICY_CONFLICT: 4,
}

# 비공개 상용 배포를 기준으로 한 분류.
#
# POLICY_CONFLICT   결합 저작물 전체의 소스 공개를 요구한다. 비공개 배포와 양립하지 않는다.
# REVIEW_REQUIRED   조건부다. 분리·수정 여부에 따라 의무가 달라져 사람이 판단해야 한다.
# NOTICE_REQUIRED   고지와 사본 첨부로 충족된다.
# NO_ACTION         사실상 제약이 없다.
_POLICY: tuple[tuple[LicensePolicyOutcome, tuple[str, ...]], ...] = (
    (
        LicensePolicyOutcome.POLICY_CONFLICT,
        (
            "AGPL-3.0-only", "AGPL-3.0-or-later",
            "GPL-2.0-only", "GPL-2.0-or-later",
            "GPL-3.0-only", "GPL-3.0-or-later",
            "OSL-3.0", "EUPL-1.2", "SSPL-1.0",
        ),
    ),
    (
        LicensePolicyOutcome.REVIEW_REQUIRED,
        (
            "LGPL-2.1-only", "LGPL-2.1-or-later",
            "LGPL-3.0-only", "LGPL-3.0-or-later",
            "MPL-1.1", "MPL-2.0",
            "EPL-1.0", "EPL-2.0",
            "CDDL-1.0", "CDDL-1.1", "CPL-1.0",
            "MS-RL", "OFL-1.1",
        ),
    ),
    (
        LicensePolicyOutcome.NOTICE_REQUIRED,
        (
            "Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC",
            "Zlib", "NCSA", "PostgreSQL", "Python-2.0", "X11", "W3C",
            "MS-PL", "AFL-3.0", "Artistic-2.0", "BSL-1.0", "ZPL-2.1",
        ),
    ),
    (
        LicensePolicyOutcome.NO_ACTION,
        ("0BSD", "CC0-1.0", "Unlicense", "WTFPL"),
    ),
)

_OUTCOME_BY_ID: dict[str, LicensePolicyOutcome] = {
    identifier: outcome for outcome, identifiers in _POLICY for identifier in identifiers
}


def outcome_for_identifier(identifier: str) -> LicensePolicyOutcome:
    """단일 식별자의 분류. 표에 없으면 UNKNOWN 이다.

    모르는 라이선스를 통과시키지 않는다 (Agent 3 Spec 28).
    """
    if identifier == UNKNOWN_LICENSE:
        return LicensePolicyOutcome.UNKNOWN
    return _OUTCOME_BY_ID.get(identifier, LicensePolicyOutcome.UNKNOWN)


def _evaluate(node: ExpressionNode) -> LicensePolicyOutcome:
    if isinstance(node, LicenseNode):
        return outcome_for_identifier(node.identifier)

    outcomes = [_evaluate(operand) for operand in node.operands]
    if isinstance(node, AndNode):
        # 모든 의무가 동시에 적용된다. 가장 무거운 것이 결과다.
        return max(outcomes, key=_SEVERITY.__getitem__)

    # OR 은 수취인이 고른다. 가장 가벼운 쪽을 택할 수 있으므로 그것이 결과다.
    # 다만 UNKNOWN 만 있는 선택지는 완화 근거가 되지 못한다.
    known = [o for o in outcomes if o is not LicensePolicyOutcome.UNKNOWN]
    if not known:
        return LicensePolicyOutcome.UNKNOWN
    return min(known, key=_SEVERITY.__getitem__)


def evaluate_expression(expression: str) -> LicensePolicyOutcome:
    """정규화된 SPDX 표현식의 검토 분류."""
    return _evaluate(parse_expression(expression))


def needs_review(outcome: LicensePolicyOutcome) -> bool:
    """사람이 봐야 하는 분류인지. 알림 여부 판단에 쓴다."""
    return _SEVERITY[outcome] >= _SEVERITY[LicensePolicyOutcome.UNKNOWN]


def describe(outcome: LicensePolicyOutcome) -> str:
    """설명 생성이 실패했을 때 쓰는 고정 문구. 모델 없이도 결과는 읽혀야 한다."""
    return {
        LicensePolicyOutcome.NO_ACTION: "별도 의무가 확인되지 않았다.",
        LicensePolicyOutcome.NOTICE_REQUIRED: "배포 시 라이선스 사본과 저작권 고지가 필요하다.",
        LicensePolicyOutcome.REVIEW_REQUIRED: "결합 방식에 따라 의무가 달라진다. 사람이 확인해야 한다.",
        LicensePolicyOutcome.POLICY_CONFLICT: "결합 저작물의 소스 공개를 요구한다. 비공개 배포와 충돌한다.",
        LicensePolicyOutcome.UNKNOWN: "라이선스를 식별하지 못했다. 자동 허용하지 않는다.",
    }[outcome]
