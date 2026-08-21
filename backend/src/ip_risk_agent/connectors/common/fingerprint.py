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
    mount_id: str,
    repository_id: str,
    tracked_branch: str,
    commit_sha: str,
    changed_path: str,
) -> str:
    """repo + tracked branch + commit SHA + changed path, **mount 범위 안에서**.

    mount 를 넣지 않으면 같은 repository 를 두 Risk Workspace 에 연결했을 때 두
    mount 가 같은 fingerprint 를 만든다. canonical intake 는 fingerprint 로 기존
    ChangeEvent 를 찾은 뒤 workspace/mount 일치를 요구하므로 그대로 실패한다.
    Local 은 처음부터 mount 를 포함하고 있었다.
    """

    return compute_fingerprint(
        "GITHUB", mount_id, repository_id, tracked_branch, commit_sha, changed_path
    )


def drive_change_fingerprint(
    *, mount_id: str, file_id: str, resolved_revision: str
) -> str:
    """file_id + resolved revision/version, **mount 범위 안에서**.

    mount 를 넣지 않으면 같은 Drive 파일이 어느 workspace 에 붙든 같은 fingerprint
    가 된다. 그래서 한 번 분석한 파일은 **다른 workspace 에서 다시 연결할 수
    없었다** — 운영에서 mount 는 만들어지고 초기 스캔의 intake 가
    SourceChangeIntakeError 로 422 를 냈다.

    같은 mount 안에서의 중복 전달(webhook 재시도 + reconciliation)은 여전히 같은
    fingerprint 로 수렴하므로 멱등성은 그대로다.
    """

    return compute_fingerprint("GOOGLE_DRIVE", mount_id, file_id, resolved_revision)


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
