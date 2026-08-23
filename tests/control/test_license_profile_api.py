"""배포 형태를 받는 자리 (§13-9).

이것이 정해지기 전에는 라이선스 4·5 단계가 돌지 않아 Risk 가 전부 확인 필요다 (§5.10).
받는 곳이 없으면 그 상태에서 벗어날 방법이 없다.
"""

from __future__ import annotations

import inspect

from ip_risk_agent.api.security.router import (
    LicenseProfileRequest,
    create_security_router,
)
from ip_risk_agent.application.security_policy.service import WorkspaceSecurityService
from ip_risk_agent.core.workspaces.license_profile import (
    DistributionForm,
    LinkingMode,
    ModificationState,
)


def test_the_route_exists() -> None:
    from dataclasses import dataclass

    @dataclass
    class _Deps:
        security: object
        authentication: object

    router = create_security_router(_Deps(security=object(), authentication=None))
    paths = {(route.path, tuple(sorted(route.methods))) for route in router.routes}
    assert any(
        path.endswith("/license-profile") and "PUT" in methods
        for path, methods in paths
    )


def test_the_request_has_no_defaults() -> None:
    """정하지 않은 것과 "SaaS 라고 골랐다" 는 다르다.

    기본값이 있으면 화면을 넘기기만 해도 정해진 것이 되고, 그러면 §5.10 이 막으려던
    "근거 없는 축으로 매긴 등급" 이 그대로 돌아온다.
    """
    for name in ("distribution_form", "modification", "linking", "redistributes"):
        assert LicenseProfileRequest.model_fields[name].is_required(), name


def test_every_axis_is_accepted() -> None:
    """§5.7 이 정한 축 넷이 다 들어가야 한다. 하나가 빠지면 그 축을 정할 수 없다."""
    fields = set(LicenseProfileRequest.model_fields)
    assert fields == {"distribution_form", "modification", "linking", "redistributes"}
    assert (
        LicenseProfileRequest.model_fields["distribution_form"].annotation
        is DistributionForm
    )
    assert LicenseProfileRequest.model_fields["linking"].annotation is LinkingMode
    assert (
        LicenseProfileRequest.model_fields["modification"].annotation
        is ModificationState
    )


def test_changing_the_form_re_evaluates_rather_than_only_saving() -> None:
    """SaaS 를 사내 전용으로 바꾸면 AGPL 의 의무가 사라지고, 동적을 정적으로 바꾸면
    LGPL 의 의무가 생긴다.

    저장으로 끝내면 화면의 등급이 **이미 바뀐 설정과 어긋난 채로** 남는다.
    """
    source = inspect.getsource(WorkspaceSecurityService.update_license_profile)
    assert "_license_revalidator" in source


def test_an_unchanged_form_does_not_re_evaluate() -> None:
    """같은 값을 다시 보내는 것만으로 전체 재평가가 돌면 비용이 사용자 손에 달린다."""
    source = inspect.getsource(WorkspaceSecurityService.update_license_profile)
    assert "if workspace.license_profile == profile:" in source
    assert source.index("== profile:") < source.index("_license_revalidator")


def test_setting_the_form_needs_the_security_permission() -> None:
    """``global_ignore_text`` 와 같은 성격의 workspace 정책이다."""
    source = inspect.getsource(WorkspaceSecurityService.update_license_profile)
    assert "VwsAction.VWS_SECURITY_MANAGE" in source


def test_the_axis_values_are_not_written_to_the_audit_record() -> None:
    """해시로 충분하고, 판정 버전에 실리는 것도 해시다 (§5.10)."""
    source = inspect.getsource(WorkspaceSecurityService.update_license_profile)
    assert "license_axes_hash" in source
    assert "distribution_form" not in source.split("metadata_safe")[1]
