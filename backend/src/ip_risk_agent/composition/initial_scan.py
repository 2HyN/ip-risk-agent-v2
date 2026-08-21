"""Mount 를 만든 순간, 이미 존재하는 파일을 파이프라인에 넣는다.

이 시스템의 파이프라인은 SourceChange(변경 이벤트)에서 시작한다. 그래서
연결 시점에 **이미 있던** 파일은 입구가 없다 — 사용자는 "기획서가 있는
폴더를 연결했는데 아무 위험도 안 뜬다"는 상태를 만난다. 여기서 확장된
파일들에 대해 CREATE 변경을 합성해 그 입구를 만들어 준다.

이 경로는 webhook 도 Scheduler 도 필요로 하지 않는다. Mount 생성 요청을
처리하는 그 자리에서 정상적인 SourceChange 를 sink 로 밀어 넣을 뿐이므로,
이후의 idempotency 판정·큐 투입·Security Gate 는 평소의 변경과 완전히 같은
길을 탄다.

입력은 selection expander 가 걷는 동안 만든 ``ExpandedFile`` 이다. 경로가
여기 실려 있어 화면의 artifact 이름이 "requirements.txt" 가 아니라
"1-blatant/requirements.txt" 가 된다 — 페르소나 폴더마다 같은 이름의 파일이
있을 때 이것이 유일한 구분 정보다.

스캔은 **최선 노력**이다. Mount 는 이미 만들어진 사실이므로, 스캔 실패가
생성 성공을 실패로 둔갑시키면 안 되고, 파일 하나의 실패가 나머지를 막아도
안 된다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timezone

from iprisk_contracts.common import (
    ChangeType,
    SourceArtifactRef,
    SourceType,
)
from iprisk_contracts.source_change import SourceChange

from .drive_selection import FOLDER_MIME_TYPE, ExpandedFile

logger = logging.getLogger(__name__)


class DriveInitialScanner:
    """확장된 Drive 파일들을 CREATE 변경으로 합성해 sink 에 넣는다."""

    def __init__(self, *, change_sink) -> None:
        self._change_sink = change_sink

    async def scan(
        self,
        *,
        risk_workspace_id: str,
        mount_id: str,
        source_workspace_id: str,
        files: Sequence[ExpandedFile],
    ) -> int:
        """분석 파이프라인에 넣은 파일 수를 돌려준다."""
        from ip_risk_agent.connectors.common.fingerprint import (  # noqa: PLC0415
            drive_change_fingerprint,
        )

        submitted = 0
        now = datetime.now(timezone.utc)
        for item in files:
            file = item.file
            if getattr(file, "mime_type", None) == FOLDER_MIME_TYPE:
                # expander 가 이미 걸렀어야 하지만, 빈 분석이 파이프라인에
                # 들어가지 않도록 여기서도 막는다.
                continue

            # 재시도해도 같은 파일·같은 판이면 같은 fingerprint 가 되어야
            # Control 의 idempotency 가 중복 분석을 막는다.
            revision = (
                getattr(file, "revision_id", None)
                or getattr(file, "modified_time", None)
                or "initial"
            )
            fingerprint = drive_change_fingerprint(
                file_id=item.file_id, resolved_revision=revision
            )
            change = SourceChange(
                contract_version="1",
                event_id=fingerprint,
                provider_event_id=None,
                event_fingerprint=fingerprint,
                risk_workspace_id=risk_workspace_id,
                mount_id=mount_id,
                source_workspace_id=source_workspace_id,
                source_type=SourceType.GOOGLE_DRIVE,
                artifact=SourceArtifactRef(
                    source_artifact_id=item.file_id,
                    # 경로가 화면의 artifact 이름이 된다. 이름만 남기면
                    # 폴더마다 있는 같은 이름의 파일을 구분할 수 없다.
                    display_name=item.path or item.file_id,
                ),
                change_type=ChangeType.CREATE,
                revision=getattr(file, "revision_id", None),
                previous_revision=None,
                observed_at=now,
                safe_metadata={},
            )
            try:
                await self._change_sink.persist(change)
            except Exception:
                # 이 파일만 잃는다. 하나의 실패가 나머지 기획서까지 분석에서
                # 빼면 사용자가 이유를 알 수 없다.
                logger.exception(
                    "initial scan: persist failed (mount=%s)", mount_id
                )
                continue
            submitted += 1
        return submitted


__all__ = ["DriveInitialScanner"]
