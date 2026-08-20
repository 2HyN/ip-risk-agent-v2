from __future__ import annotations

import pytest

from ip_risk_agent.connectors.local.identity import (
    decode_local_artifact_id,
    encode_local_artifact_id,
)


def test_identity_roundtrip():
    encoded = encode_local_artifact_id(device_id="dev-1", mount_id="mount-1", relative_path="src/a.py")
    decoded = decode_local_artifact_id(encoded)
    assert decoded.device_id == "dev-1"
    assert decoded.mount_id == "mount-1"
    assert decoded.relative_path == "src/a.py"


def test_identity_decode_malformed_raises_value_error():
    with pytest.raises(ValueError):
        decode_local_artifact_id("not-a-valid-encoded-id!!!")


def test_identity_preserves_nested_relative_path():
    encoded = encode_local_artifact_id(device_id="d", mount_id="m", relative_path="a/b/c.py")
    decoded = decode_local_artifact_id(encoded)
    assert decoded.relative_path == "a/b/c.py"
