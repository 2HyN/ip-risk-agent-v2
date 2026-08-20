"""Agent 2 Spec 10번 DriveTrackingScope. Drive SourceWorkspace는 directory
mirror가 아니라 Picker에서 선택된 file id의 collection이다."""

from __future__ import annotations

from pydantic import Field

from iprisk_contracts.common import SafeMetadata, StrictModel


class DriveTrackingScope(StrictModel):
    mount_id: str
    selected_file_ids: list[str]
    display_metadata_by_file: dict[str, SafeMetadata] = Field(default_factory=dict)

    def contains(self, file_id: str) -> bool:
        return file_id in self.selected_file_ids
