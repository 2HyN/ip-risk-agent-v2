"""배포 형태가 저장되고 다시 읽힌다 (§5.10 · 2-E).

이 필드는 나중에 추가됐다. **이미 저장된 workspace 문서에는 없다.** 없다는 것이 "아직
정하지 않았다" 를 정확히 뜻하므로 이행이 필요 없지만, 그 사실이 시험으로 고정되어 있지
않으면 다음 사람이 필수 필드로 만들어 옛 문서를 읽지 못하게 한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ip_risk_agent.core.workspaces import RiskWorkspace
from ip_risk_agent.core.workspaces.license_profile import (
    DistributionForm,
    LicenseDeploymentProfile,
    LinkingMode,
    ModificationState,
    WorkspaceLicensePolicy,
)
from ip_risk_agent.persistence.core_firestore.mappers import (
    workspace_from_document,
    workspace_to_document,
)

NOW = datetime(2026, 8, 23, tzinfo=timezone.utc)
PROFILE = LicenseDeploymentProfile(
    distribution_form=DistributionForm.SAAS,
    modification=ModificationState.MODIFIED,
    linking=LinkingMode.STATIC,
    redistributes=True,
)


def _workspace(profile: LicenseDeploymentProfile | None) -> RiskWorkspace:
    return RiskWorkspace(
        id="vws-1",
        name="w",
        owner_user_id="u",
        security_policy_version="s",
        retention_policy_version="r",
        created_at=NOW,
        updated_at=NOW,
        license_profile=profile,
    )


def test_the_profile_survives_a_round_trip() -> None:
    document = workspace_to_document(_workspace(PROFILE))
    assert workspace_from_document(document).license_profile == PROFILE


def test_a_workspace_saved_before_this_field_existed_still_loads() -> None:
    """배포가 곧 데이터 손실이 되면 안 된다."""
    document = dict(workspace_to_document(_workspace(None)))
    document.pop("license_profile")
    assert workspace_from_document(document).license_profile is None


def test_an_unset_profile_round_trips_as_unset() -> None:
    document = workspace_to_document(_workspace(None))
    assert workspace_from_document(document).license_profile is None


def test_the_version_distinguishes_before_and_after_configuration() -> None:
    """설정 전에 낸 결과와 설정 후에 낸 결과가 원인 귀속에서 구별되어야 한다 (§7.4)."""
    unset = WorkspaceLicensePolicy("vws-1", "table-1").version
    configured = WorkspaceLicensePolicy("vws-1", "table-1", PROFILE).version
    assert unset.endswith(":unset")
    assert unset != configured


def test_the_axes_hash_does_not_depend_on_field_order() -> None:
    """필드를 재배열하는 순간 같은 설정이 다른 해시를 내면, §7.4 가 그것을
    "사용자가 설정을 바꿨다" 로 읽는다."""
    same = LicenseDeploymentProfile(
        redistributes=True,
        linking=LinkingMode.STATIC,
        modification=ModificationState.MODIFIED,
        distribution_form=DistributionForm.SAAS,
    )
    assert same.axes_hash == PROFILE.axes_hash


@pytest.mark.parametrize(
    "changed",
    (
        {"distribution_form": DistributionForm.INTERNAL_ONLY},
        {"modification": ModificationState.UNMODIFIED},
        {"linking": LinkingMode.DYNAMIC},
        {"redistributes": False},
    ),
)
def test_every_axis_moves_the_hash(changed: dict) -> None:
    """축 하나가 빠지면 그 축을 바꿔도 판정 버전이 그대로다 — 원인을 못 읽는다."""
    from dataclasses import replace

    assert replace(PROFILE, **changed).axes_hash != PROFILE.axes_hash
