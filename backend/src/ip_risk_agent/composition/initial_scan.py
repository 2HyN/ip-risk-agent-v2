"""Mount 를 만든 순간, 이미 존재하는 파일을 파이프라인에 넣는다.

이 시스템의 파이프라인은 SourceChange(변경 이벤트)에서 시작한다. 그래서
연결 시점에 **이미 있던** 파일은 입구가 없다 — 사용자는 "기획서가 있는
폴더를 연결했는데 아무 위험도 안 뜬다"는 상태를 만난다. 여기서 고른
파일들에 대해 CREATE 변경을 합성해 그 입구를 만들어 준다.

이 경로는 webhook 도 Scheduler 도 필요로 하지 않는다. Mount 생성 요청을
처리하는 그 자리에서 정상적인 SourceChange 를 sink 로 밀어 넣을 뿐이므로,
이후의 idempotency 판정·큐 투입·Security Gate 는 평소의 변경과 완전히 같은
길을 탄다. 파이프라인 계약(Master Spec 21)을 우회하는 것이 아니라 입구를
하나 더 두는 것이다.

스캔은 **최선 노력**이다. Mount 는 이미 만들어졌고 그것이 사실이다. 스캔이
실패했다고 Mount 생성을 실패로 돌리면, 사용자는 "연결 실패"로 오해하고
같은 연결을 반복하게 된다. 파일 하나의 실패도 나머지를 막지 않는다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from iprisk_contracts.common import (
    ChangeType,
    MountRef,
    SourceArtifactRef,
    SourceType,
)
from iprisk_contracts.source_change import SourceChange

from ip_risk_agent.connectors.common.errors import SourceConnectorError
from ip_risk_agent.connectors.common.fingerprint import drive_change_fingerprint

logger = logging.getLogger(__name__)

# 폴더는 내용물이 없어 분석할 수 없다. 폴더의 하위 확장은 Mount 생성
# 전에 DriveSelectionExpander 가 끝내므로 여기 오는 폴더는 예외 상황이지만,
# 그래도 조용히 걸러서 파이프라인에 빈 분석이 들어가지 않게 한다.
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


class DriveInitialScanner:
    """고른 Drive 파일들을 CREATE 변경으로 합성해 sink 에 넣는다."""

    def __init__(
        self,
        *,
        connection_lookup,
        credential_vault,
        provider_factory,
        change_sink,
    ) -> None:
        self._connection_lookup = connection_lookup
        self._credential_vault = credential_vault
        self._provider_factory = provider_factory
        self._change_sink = change_sink

    async def scan(self, mount: MountRef, selected_file_ids: list[str]) -> int:
        """분석 파이프라인에 넣은 파일 수를 돌려준다."""
        import json  # noqa: PLC0415 - 표준 라이브러리 지연 import

        connection = await self._connection_lookup.resolve(mount.mount_id)
        raw_token = await self._credential_vault.get(connection.credential_ref)
        provider = self._provider_factory.create(json.loads(raw_token))

        submitted = 0
        now = datetime.now(timezone.utc)
        for file_id in selected_file_ids:
            try:
                file = provider.get_file(file_id)
            except SourceConnectorError:
                # 이 파일만 건너뛴다. 하나가 막혔다고 나머지 기획서까지
                # 분석에서 빠지면 사용자가 이유를 알 수 없다.
                logger.warning(
                    "initial scan: file lookup failed (mount=%s)", mount.mount_id
                )
                continue

            if file.mime_type == FOLDER_MIME_TYPE:
                continue

            # 재시도해도 같은 파일·같은 판이면 같은 fingerprint 가 되어야
            # Control 의 idempotency 가 중복 분석을 막는다.
            revision = file.revision_id or file.modified_time or "initial"
            fingerprint = drive_change_fingerprint(
                file_id=file_id, resolved_revision=revision
            )
            change = SourceChange(
                contract_version="1",
                event_id=fingerprint,
                provider_event_id=None,
                event_fingerprint=fingerprint,
                risk_workspace_id=mount.risk_workspace_id,
                mount_id=mount.mount_id,
                source_workspace_id=mount.source_workspace_id,
                source_type=SourceType.GOOGLE_DRIVE,
                artifact=SourceArtifactRef(
                    source_artifact_id=file_id,
                    display_name=file.name or file_id,
                ),
                change_type=ChangeType.CREATE,
                revision=file.revision_id,
                previous_revision=None,
                observed_at=now,
                safe_metadata={},
            )
            await self._change_sink.persist(change)
            submitted += 1

        # 조회 과정에서 access token 이 갱신됐을 수 있다. 버리면 다음 사용자가
        # 만료된 토큰으로 시작한다.
        await self._credential_vault.update(
            connection.credential_ref, json.dumps(provider.export_token())
        )
        return submitted


__all__ = ["DriveInitialScanner", "FOLDER_MIME_TYPE"]
