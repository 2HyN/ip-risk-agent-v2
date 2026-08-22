"""고아 자격증명 정리 도구의 안전장치.

가장 큰 위험은 **아직 쓰이는 자격증명을 지우는 것**이다. 지우면 그 연결의
Drive 감시가 조용히 끊기고, 사용자는 다시 OAuth 를 해야 한다. 그 다음 위험은
v1 자격증명(``ipra-*``)이나 배포용 고정 Secret 을 건드리는 것이다.

GCP 에 접속하지 않는다. 선별 규칙과 접두사 방어만 확인한다.
"""

from __future__ import annotations

import pytest

from ip_risk_agent.gcp_contract import DYNAMIC_CREDENTIAL_SECRET_PREFIX, PROJECT_ID
from scripts.purge_orphan_credentials import delete_secret, orphans

SECRETS = f"projects/{PROJECT_ID}/secrets"
LIVE = f"{SECRETS}/{DYNAMIC_CREDENTIAL_SECRET_PREFIX}-google_drive-" + "a" * 40
STRAY = f"{SECRETS}/{DYNAMIC_CREDENTIAL_SECRET_PREFIX}-google_drive-" + "b" * 40


def test_a_credential_a_connection_still_points_at_is_kept() -> None:
    assert orphans([LIVE, STRAY], {LIVE}) == [STRAY]


def test_everything_is_orphaned_when_no_connection_remains() -> None:
    # workspace 를 전부 지운 상태다. 남은 Secret 을 가리키는 기록이 없다.
    assert orphans([LIVE, STRAY], set()) == [LIVE, STRAY]


@pytest.mark.parametrize(
    "name",
    (
        f"{SECRETS}/ipra-drive-token",  # v1 운영 자격증명
        f"{SECRETS}/iprisk-v2-kipris-access-key",  # 배포용 고정 Secret
        f"{SECRETS}/iprisk-v2-session-secret",
        "projects/other-project/secrets/iprisk-v2-cred-google_drive-" + "a" * 40,
    ),
)
def test_deletion_refuses_anything_outside_the_v2_credential_prefix(name: str) -> None:
    """호출부의 필터를 믿지 않는다. 같은 project 에 v1 자격증명이 함께 있다."""
    with pytest.raises(ValueError, match="refusing to delete"):
        delete_secret(name)
