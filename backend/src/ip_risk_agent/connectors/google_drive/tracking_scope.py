"""Drive 마운트가 무엇을 추적하는가.

**공유받은 폴더 하나다.** 예전에는 Picker 에서 고른 file id 의 명단이었고, 그래서
"추적 대상인가" 가 "이 id 가 명단에 있는가" 였다. 마운트한 뒤에 폴더에 넣은 파일이
영영 잡히지 않았다 — 변경 피드에는 오는데 명단에 없다고 버려졌다 (§6.1 · 1-F).

이 서비스는 **추적할 파일을 지정 폴더에 넣어 두는** 방식으로 쓴다. 넣어도 안 잡히면
기능이 없는 것과 같다. 그래서 명단이 아니라 **폴더**를 들고, 소속은 그때그때 묻는다
(`folders.is_inside_folder`). GitHub 이 저장소를, Local 이 폴더를 다루는 것과 같다.
"""

from __future__ import annotations

from pydantic import Field

from iprisk_contracts.common import SafeMetadata, StrictModel


class DriveTrackingScope(StrictModel):
    mount_id: str
    #: 공유받은 폴더. 이 아래에 있는 것이 추적 대상이다.
    folder_id: str
    #: 폴더 이름 등 화면에 쓰는 값. 판정에는 쓰지 않는다.
    display_metadata_by_file: dict[str, SafeMetadata] = Field(default_factory=dict)


__all__ = ["DriveTrackingScope"]
