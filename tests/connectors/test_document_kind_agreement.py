"""세 소스가 같은 파일을 같은 종류로 본다 (§6.2 · 1-C).

종류가 갈리면 **분석 경로가 갈린다.** 같은 `main.py` 가 한쪽에서는 소스 코드로 특허
검사를 받고 다른 쪽에서는 문서로 받으면, 무엇을 검사했는지 말할 수 없게 된다.

이 시험이 붙잡는 것은 값이 아니라 **한 곳에서 온다는 사실**이다. 예전에는 GitHub 과
Local 이 같은 표를 각자 복사해 들고 있었고 Drive 에는 아예 없었다. 값이 같을 때
복사본은 조용하다 — 한쪽만 고칠 때 갈라진다.
"""

from __future__ import annotations

import pytest
from iprisk_contracts.common import ArtifactKind

from ip_risk_agent.connectors.github.adapter import GitHubAdapter
from ip_risk_agent.connectors.google_drive.adapter import (
    GoogleDriveAdapter,
    _is_readable,
)
from ip_risk_agent.connectors.local.adapter import LocalAdapter
from ip_risk_agent.core.artifacts.text_files import is_text_like, text_kind

_INFER = (
    GitHubAdapter._infer_artifact_kind,
    LocalAdapter._infer_artifact_kind,
    GoogleDriveAdapter._infer_artifact_kind,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    (
        ("main.py", ArtifactKind.SOURCE_CODE),
        ("app.ts", ArtifactKind.SOURCE_CODE),
        ("design.md", ArtifactKind.DOCUMENT_TEXT),
        # §6.2 가 이름으로 지목한 것들. 예전에는 셋 다 종류가 없어 사라졌다.
        ("config.yaml", ArtifactKind.DOCUMENT_TEXT),
        ("rows.csv", ArtifactKind.DOCUMENT_TEXT),
        ("notes.txt", ArtifactKind.DOCUMENT_TEXT),
        ("pyproject.toml", ArtifactKind.MANIFEST),
        ("uv.lock", ArtifactKind.LOCKFILE),
        ("logo.png", ArtifactKind.UNKNOWN),
    ),
)
def test_the_three_sources_agree(name: str, expected: ArtifactKind) -> None:
    assert [infer(name) for infer in _INFER] == [expected] * 3


@pytest.mark.parametrize(
    "name", ("LICENSE", "LICENSE.txt", "LICENCE.md", "COPYING", "NOTICE")
)
def test_a_licence_text_is_not_sent_down_the_patent_path(name: str) -> None:
    """라이선스 전문은 코드도 산문도 아니다 (결함 26).

    ``LICENSE`` 는 확장자가 없어 `UNKNOWN` 이었고 ``LICENSE.txt`` 는 ``.txt`` 라
    **문서로 분류되어 특허 검사**를 받았다. 이름 하나 차이로 KIPRIS 를 11 회쯤 쓰고,
    나오는 것은 라이선스 전문에서 찾은 특허 유사도다.

    원문 대조는 유예했으므로 (§5.9) 지금 할 말이 없는 것이 맞다.
    """
    assert [infer(name) for infer in _INFER] == [ArtifactKind.UNKNOWN] * 3
    assert not is_text_like(name), "읽어 올 이유도 없다"


def test_a_drive_file_is_read_when_its_type_says_text():
    """예전에는 고정 목록 네 개만 통과했다. `.py` 는 `text/x-python` 으로 와도 떨어졌다."""
    assert _is_readable("text/x-python", "main.py")
    assert _is_readable("text/csv", "rows.csv")
    assert _is_readable("application/vnd.google-apps.document", "설계 메모")
    assert _is_readable("application/json", "package.json")


def test_a_drive_file_is_read_when_the_type_declines_to_say():
    """`application/octet-stream` 은 "모르겠다" 이지 "바이너리다" 가 아니다."""
    assert _is_readable("application/octet-stream", "config.yaml")
    assert not _is_readable("application/octet-stream", "logo.png")


def test_a_type_that_claims_to_be_binary_is_not_overruled_by_a_name():
    """이름 추측이 적극적인 주장을 덮으면, 확장자만 바꿔 게이트를 지나갈 수 있다."""
    assert not _is_readable("image/png", "notes.md")
    assert not _is_readable("video/mp4", "readme.txt")


def test_the_gate_and_drive_answer_the_same_question_the_same_way():
    """두 곳이 갈라지면 Drive 가 읽어 온 것을 게이트가 버린다."""
    from ip_risk_agent.application.security_gate.policy import SecurityGatePolicy
    from ip_risk_agent.application.security_gate.service import _mime_is_denied

    policy = SecurityGatePolicy(policy_version="security-v1")
    for mime, name in (
        ("application/octet-stream", "design.md"),
        ("application/octet-stream", "logo.png"),
        ("image/png", "notes.md"),
        ("text/csv", "rows.csv"),
    ):
        denied = _mime_is_denied(
            mime, ArtifactKind.DOCUMENT_TEXT, policy, logical_path=name
        )
        assert denied is not _is_readable(mime, name), (mime, name)


def test_the_extension_table_is_not_narrower_than_the_kinds_it_serves():
    """``is_text_like`` 와 ``text_kind`` 가 어긋나면 읽어 온 것을 분류하지 못한다."""
    for name in ("main.py", "design.md", "config.yaml", "rows.csv", "Dockerfile"):
        assert is_text_like(name) and text_kind(name) is not None
    for name in ("logo.png", "archive.zip", "LICENSE"):
        assert not is_text_like(name) and text_kind(name) is None
