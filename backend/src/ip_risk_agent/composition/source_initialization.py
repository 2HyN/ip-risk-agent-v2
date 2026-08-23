"""Initial source discovery bridges a completed mount to canonical intake."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class DriveInitialChangePublisher:
    """마운트 직후 한 번 훑고, **그 자리에서 감시 채널을 건다.**

    채널 갱신은 6 시간마다 도는 작업이 한다. 그것만 있으면 방금 붙인 폴더가 최대
    6 시간 동안 밀어주는 알림 없이 남는다 — 15 분 주기 대조만이 유일한 경로가 되어
    "지속 추적" 의 지연이 설계값과 달라진다 (결함 39).

    ``renew_watch`` 는 이미 살아 있는 채널을 보면 아무것도 하지 않으므로, 여기서
    불러도 같은 연결에 채널이 겹쳐 쌓이지 않는다.
    """

    def __init__(
        self,
        *,
        control_facade,
        adapter,
        change_sink,
        watch_address: str | None = None,
        watch_channel_token: str | None = None,
        clock=None,
    ) -> None:
        self._control = control_facade
        self._adapter = adapter
        self._sink = change_sink
        self._watch_address = watch_address
        self._watch_channel_token = watch_channel_token
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def initialize(
        self,
        *,
        mount_id: str,
        selected_file_ids: list[str],
    ) -> None:
        mount = await self._control.get_mount_ref(mount_id)
        changes = await self._adapter.initial_changes(mount, selected_file_ids)
        for change in changes:
            await self._sink.persist(change)
        await self._start_watch(mount)

    async def _start_watch(self, mount) -> None:
        """채널을 못 걸어도 마운트는 성공이다.

        훑기는 이미 끝났고 15 분 주기 대조가 살아 있다. 여기서 던지면 붙은 폴더가
        안 붙은 것이 된다 — 잃는 것이 알림 지연보다 크다. 대신 조용히 넘기지 않는다.
        """
        if self._watch_address is None or self._watch_channel_token is None:
            return
        try:
            await self._adapter.renew_watch(
                mount,
                address=self._watch_address,
                channel_token=self._watch_channel_token,
                now=self._clock(),
            )
        except Exception as exc:  # noqa: BLE001 - 마운트를 깨뜨리지 않는다
            logger.warning(
                json.dumps(
                    {
                        "schema_version": 1,
                        "event": "drive_mount_watch_registration_failed",
                        "mount_id": mount.mount_id,
                        "failure": type(exc).__name__,
                    },
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )


class GitHubInitialChangePublisher:
    def __init__(self, *, control_facade, adapter, change_sink) -> None:
        self._control = control_facade
        self._adapter = adapter
        self._sink = change_sink

    async def initialize(self, *, mount_id: str) -> None:
        mount = await self._control.get_mount_ref(mount_id)
        changes = await self._adapter.initial_changes(mount)
        for change in changes:
            await self._sink.persist(change)


__all__ = ["DriveInitialChangePublisher", "GitHubInitialChangePublisher"]
