"""마운트 해제가 일시중지만큼은 정리하는가.

해제는 일시중지보다 **더 최종적**인데 정리는 덜 했다. 마운트 기록만 지우고 Risk 는 활성
목록에 남아, 이미 없는 마운트의 파일이 아직 추적 중인 것처럼 읽혔다.
"""

from __future__ import annotations

import inspect

from ip_risk_agent.application.workspace_admin.service import WorkspaceAdministrationService


def test_removing_a_mount_closes_its_risks_like_disabling_does() -> None:
    remove = inspect.getsource(WorkspaceAdministrationService.remove_mount)
    assert "exclude_mount_risks" in remove


def test_removal_uses_the_same_disposition_as_disabling() -> None:
    """사용자의 판단이 아니라 외적 요인으로 관리가 끝난 것이다. 둘이 같은 성질이다."""
    disable = inspect.getsource(WorkspaceAdministrationService.disable_mount)
    remove = inspect.getsource(WorkspaceAdministrationService.remove_mount)
    assert "exclude_mount_risks" in disable and "exclude_mount_risks" in remove


def test_removal_does_not_delete_the_risks() -> None:
    """지우지 않는다. "왜 그때 그렇게 판단했는가" 는 해제 뒤에도 답할 수 있어야 한다."""
    remove = inspect.getsource(WorkspaceAdministrationService.remove_mount)
    assert "risks.remove" not in remove and "clear_evidence" not in remove
