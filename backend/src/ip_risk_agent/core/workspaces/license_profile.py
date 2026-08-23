"""workspace 의 배포 형태. 라이선스 의무가 여기에 달려 있다.

## 왜 필요한가

같은 라이선스가 **배포 형태에 따라 다른 의무**를 만든다. LGPL 은 동적으로 링크하면
고지로 끝나지만 정적으로 링크하면 결합 저작물이 걸린다. AGPL 은 사내 전용이면 조용하고
SaaS 면 네트워크 이용자에게 소스를 줘야 한다.

그래서 **workspace 설정 없이는 4·5 단계를 돌리면 안 된다.** 축이 정해지지 않았는데
등급을 매기면 그것은 판정이 아니라 짐작이다.

## 가장 무거운 쪽으로 가정하지 않는다 [결정]

"재배포함 · 수정함 · 정적 링크" 로 기본값을 두는 방법도 있으나 채택하지 않는다.
설정 전 workspace 의 라이선스 Risk 가 **전부 HIGH** 로 뜨고, 첫 화면이 전부 빨강이면
사용자는 진짜 HIGH 도 함께 무시한다. 안전한 방향의 기본값이 안전을 떨어뜨린다 (§5.10).

대신 1~3 단계(파싱 · 식별 · 전문 조회)는 그대로 돌리고 4~5 단계만 미룬다. 무엇을 쓰고
있는지는 설정과 무관하기 때문이다.

## 판정 버전에 들어간다

``{workspace}:{정책표 판본}:{축 해시}`` 세 조각이 모두 필요하다. 표가 바뀌어도, 사용자가
SaaS 를 사내 전용으로 바꿔도 판정이 달라지고, 원인 귀속(§7.4)이 그 차이를 읽어야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256


class DistributionForm(StrEnum):
    SAAS = "SAAS"
    BINARY = "BINARY"
    INTERNAL_ONLY = "INTERNAL_ONLY"
    LIBRARY_REDISTRIBUTION = "LIBRARY_REDISTRIBUTION"
    EMBEDDED = "EMBEDDED"


class ModificationState(StrEnum):
    UNMODIFIED = "UNMODIFIED"
    MODIFIED = "MODIFIED"


class LinkingMode(StrEnum):
    DYNAMIC = "DYNAMIC"
    STATIC = "STATIC"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class LicenseDeploymentProfile:
    """§5.7 의 기본 축 넷. 자유 질의는 유예했다 (§12.2)."""

    distribution_form: DistributionForm
    modification: ModificationState
    linking: LinkingMode
    redistributes: bool

    @property
    def axes_hash(self) -> str:
        """축을 판정 버전에 실을 수 있는 짧은 값으로 만든다.

        축 자체를 버전 문자열에 넣지 않는 이유는 길이 때문만이 아니다. 축이 늘어나면
        (§12.2 의 자유 질의) 버전 문자열의 모양이 바뀌어 옛 값과 비교할 수 없게 된다.
        해시는 늘어나도 모양이 같다.

        **순서를 고정해 적는다.** 필드 순서에 기대면 필드를 재배열하는 순간 같은 설정이
        다른 해시를 내고, 그것이 §7.4 에서 "사용자가 설정을 바꿨다" 로 읽힌다.
        """
        material = "|".join(
            (
                f"distribution_form={self.distribution_form.value}",
                f"modification={self.modification.value}",
                f"linking={self.linking.value}",
                f"redistributes={'yes' if self.redistributes else 'no'}",
            )
        )
        return sha256(material.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class WorkspaceLicensePolicy:
    """분석기가 workspace 에서 받아 가는 것 전부.

    Intelligence 는 이것이 어디서 오는지 모른다. Control 이 만들어 함수 하나로 넘긴다
    (§3 · §5.10).
    """

    risk_workspace_id: str
    #: 정책 표 자체의 판본. 표가 바뀌면 판정이 바뀐다.
    policy_table_version: str
    #: 설정되지 않았으면 ``None``. 그때는 4·5 단계를 돌리지 않는다.
    profile: LicenseDeploymentProfile | None = None

    @property
    def is_configured(self) -> bool:
        return self.profile is not None

    @property
    def version(self) -> str:
        """결과에 싣는 ``policy_version``.

        설정 전에도 값이 있어야 한다 — 그래야 "설정 전에 낸 결과" 와 "설정 후에 낸
        결과" 가 원인 귀속에서 구별된다 (§7.4).
        """
        axes = self.profile.axes_hash if self.profile is not None else "unset"
        return f"{self.risk_workspace_id}:{self.policy_table_version}:{axes}"


__all__ = [
    "DistributionForm",
    "LicenseDeploymentProfile",
    "LinkingMode",
    "ModificationState",
    "WorkspaceLicensePolicy",
]
