"""Risk Workspace 를 지울 때 실제로 데이터를 없애는 경계.

삭제 정책은 **전체 말소**다 (2026-08-22 결정). soft delete 로 상태만 바꾸면 지웠다고
말한 데이터가 계속 남는다. 소유권 인계 기능이 없는 지금은 workspace 를 지운 사용자가
그 데이터에 다시 닿을 방법도 없으므로, 남겨 두는 것은 이득 없이 위험만 남긴다.

되돌릴 수 없다. export/import 가 생기기 전까지는 지우기 전에 사용자가 확인하는 것이
유일한 안전장치다.

canonical 과 operational 은 저장 위치도 수명도 다르므로 지우는 주체를 나눈다. 이
모듈은 그 둘이 공유할 **포트**만 정의하고, 어떤 컬렉션을 어떻게 지울지는 각
저장소 구현이 안다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class WorkspaceDataEraser(Protocol):
    """한 workspace 에 속한 데이터를 지운다.

    같은 workspace 로 두 번 불려도 안전해야 한다. 지우다 실패하면 workspace 는
    ``DELETING`` 으로 남고 사용자가 다시 시도하게 되기 때문이다.

    돌려주는 값은 "무엇을 몇 건 지웠는가" 다. 로그와 응답에 쓰이므로 값이 아니라
    **분류와 개수만** 담는다.
    """

    async def erase(self, risk_workspace_id: str) -> Mapping[str, int]: ...


def merge_counts(reports: list[Mapping[str, int]]) -> dict[str, int]:
    """여러 eraser 의 보고를 하나로 합친다."""
    merged: dict[str, int] = {}
    for report in reports:
        for name, count in report.items():
            merged[name] = merged.get(name, 0) + count
    return merged


__all__ = ["WorkspaceDataEraser", "merge_counts"]
