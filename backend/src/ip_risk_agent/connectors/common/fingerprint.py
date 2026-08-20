"""Source 변경 이벤트의 deterministic fingerprint 생성 헬퍼.

Master Spec 10번(Idempotency), Agent 2 Spec 12/20/31번(각 provider별
SourceChange fingerprint 재료)을 코드로 옮긴 것.

핵심 요구사항: 같은 입력 -> 항상 같은 지문. provider가 다르면 재료가
우연히 같은 문자열이어도 지문은 달라야 한다 (그래서 provider tag를
맨 앞에 항상 포함시킨다).
"""

from __future__ import annotations

import hashlib

# ASCII Unit Separator. 사람이 입력할 일 없는 제어문자라서 구분자로 쓰면
# "ab"+"c" 와 "a"+"bc" 가 같은 지문이 되는 경계 문제를 피할 수 있다.
_SEPARATOR = "\x1f"


def compute_fingerprint(*parts: str) -> str:
    """parts를 순서대로 결합해 SHA-256 hexdigest(64자)를 반환한다.

    parts가 비어있으면 안 된다 (실수로 빈 지문이 나오는 걸 방지).
    """

    if not parts:
        raise ValueError("compute_fingerprint requires at least one part")
    joined = _SEPARATOR.join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def github_change_fingerprint(
    *,
    repository_id: str,
    tracked_branch: str,
    commit_sha: str,
    changed_path: str,
) -> str:
    """Agent 2 Spec 20번: repo + tracked branch + commit SHA + changed path."""

    return compute_fingerprint(
        "GITHUB", repository_id, tracked_branch, commit_sha, changed_path
    )


def drive_change_fingerprint(*, file_id: str, resolved_revision: str) -> str:
    """Agent 2 Spec 12번: file_id + resolved revision/version."""

    return compute_fingerprint("GOOGLE_DRIVE", file_id, resolved_revision)


def local_change_fingerprint(
    *,
    device_id: str,
    mount_id: str,
    relative_path: str,
    content_fingerprint: str,
) -> str:
    """Agent 2 Spec 31번: device_id + mount_id + relative_path + content fingerprint."""

    return compute_fingerprint(
        "LOCAL", device_id, mount_id, relative_path, content_fingerprint
    )
