"""Local artifact identity 인코딩/디코딩.

SourceArtifactRef에는 device_id를 담을 필드가 없는데, resolve_original()의
반환값(OriginalSourceLocator, LOCAL_DEVICE 타입)은 device_id를 반드시
포함해야 한다 (frozen validator). 이 간극을 메우기 위해 Agent2 Spec 20번
(GitHub의 "stable logical key = repo_id+branch+path" 패턴)을 Local에도
동일하게 적용한다: source_artifact_id 자체에 device_id를 심고 나중에 꺼낸다.
"""

from __future__ import annotations

import base64

from iprisk_contracts.common import StrictModel

_SEPARATOR = "\x1f"


class LocalArtifactIdentity(StrictModel):
    device_id: str
    mount_id: str
    relative_path: str


def encode_local_artifact_id(*, device_id: str, mount_id: str, relative_path: str) -> str:
    raw = _SEPARATOR.join([device_id, mount_id, relative_path])
    encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def decode_local_artifact_id(source_artifact_id: str) -> LocalArtifactIdentity:
    padding = "=" * (-len(source_artifact_id) % 4)
    raw = base64.urlsafe_b64decode((source_artifact_id + padding).encode("ascii")).decode("utf-8")
    parts = raw.split(_SEPARATOR, 2)
    if len(parts) != 3:
        raise ValueError("malformed local artifact id")
    device_id, mount_id, relative_path = parts
    return LocalArtifactIdentity(device_id=device_id, mount_id=mount_id, relative_path=relative_path)
