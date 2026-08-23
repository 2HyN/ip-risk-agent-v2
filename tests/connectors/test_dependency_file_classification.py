"""어떤 파일이 License 검사를 받는가.

한 문서는 License 검사와 Patent 검사 중 **하나만** 받는다. 보안 관문이
``artifact_kind`` 로 가르고, 그 종류는 커넥터가 **파일 이름만 보고** 정한다.

이 판정이 커넥터마다 달랐고, 읽지도 못할 이름을 의존성으로 분류하기도 했다.
그래서 여기서 세 가지를 함께 고정한다.

1. 세 커넥터가 같은 답을 낸다
2. 의존성으로 분류한 이름은 License 분석기가 **실제로 읽을 수 있다**
3. 경로는 보지 않는다 — 어느 폴더에 있든 이름이 같으면 같은 판정이다
"""

from __future__ import annotations

import pytest
from iprisk_contracts.common import ArtifactKind

from ip_risk_agent.connectors.github.adapter import GitHubAdapter
from ip_risk_agent.connectors.google_drive.adapter import GoogleDriveAdapter
from ip_risk_agent.connectors.local.adapter import LocalAdapter
from ip_risk_agent.core.artifacts.dependency_files import dependency_format
from ip_risk_agent.intelligence.license.analyzer import _select_parser

READABLE = (
    "requirements.txt",
    "requirements.lock",
    "constraints.txt",
    "requirements/base.txt",
    "requirements/dev.in",
    "requirements-dev.txt",
    "requirements.in",
    "pyproject.toml",
    "setup.cfg",
    "package.json",
    "package-lock.json",
    "uv.lock",
    "poetry.lock",
)

NOT_DEPENDENCIES = (
    "setup.py",  # 임의의 파이썬 코드다. 실행하지 않고서는 의존성을 알 수 없다
    "design.md",
    "main.py",
    "notes.txt",
)


def _kinds(name: str) -> dict[str, ArtifactKind]:
    return {
        "github": GitHubAdapter._infer_artifact_kind(name),
        "drive": GoogleDriveAdapter._infer_artifact_kind(name),
        "local": LocalAdapter._infer_artifact_kind(name),
    }


@pytest.mark.parametrize("name", READABLE)
def test_every_connector_agrees_a_dependency_file_is_one(name: str) -> None:
    """같은 pyproject.toml 이 Drive 에서는 Patent, GitHub 에서는 License 였다."""
    kinds = set(_kinds(name).values())
    assert len(kinds) == 1, _kinds(name)
    assert kinds.pop() in {ArtifactKind.MANIFEST, ArtifactKind.LOCKFILE}


@pytest.mark.parametrize("name", READABLE)
def test_what_a_connector_calls_a_dependency_the_analyzer_can_read(name: str) -> None:
    """읽지 못할 것을 의존성으로 분류하면 **어느 분석기도 맡지 못한다.**

    보안 관문은 종류를 보고 License 만 요청하는데, License 분석기는 파서가 없어
    거절한다. Patent 분석기는 종류가 맞지 않아 거절한다. 결과가 0 건이 되어 분석이
    계약 위반으로 실패한다 — setup.py 로 실제로 그랬다.
    """
    assert _select_parser(name) is not None


@pytest.mark.parametrize("name", NOT_DEPENDENCIES)
def test_a_file_we_cannot_read_is_not_called_a_dependency(name: str) -> None:
    assert dependency_format(name) is None
    for source, kind in _kinds(name).items():
        assert kind not in {ArtifactKind.MANIFEST, ArtifactKind.LOCKFILE}, source


def test_setup_py_is_source_code_where_the_repository_is_swept() -> None:
    """읽을 수 없다고 버리지는 않는다. 저장소에서는 소스 코드로 다뤄진다."""
    assert (
        GitHubAdapter._infer_artifact_kind("setup.py") is ArtifactKind.SOURCE_CODE
    )
    assert (
        LocalAdapter._infer_artifact_kind("setup.py") is ArtifactKind.SOURCE_CODE
    )


@pytest.mark.parametrize(
    "path",
    ("setup.cfg", "/setup.cfg", "a/b/setup.cfg", "deps/requirements.txt"),
)
def test_the_folder_does_not_change_the_answer(path: str) -> None:
    """경로는 보지 않는다. 어디에 있든 이름이 같으면 같은 판정이다."""
    assert dependency_format(path) is not None


def test_a_lockfile_is_told_apart_from_the_manifest_it_shadows() -> None:
    """``package-lock.json`` 은 ``package.json`` 을 이름 안에 품고 있다."""
    assert dependency_format("package-lock.json").is_lockfile
    assert not dependency_format("package.json").is_lockfile
    for kinds in (_kinds("package-lock.json"),):
        assert set(kinds.values()) == {ArtifactKind.LOCKFILE}


# --------------------------------------- 관문이 보낸 곳에 받을 분석기가 있는가


def _artifact(path: str, kind: ArtifactKind, requested):
    from datetime import datetime, timezone

    from iprisk_contracts import AnalysisArtifact
    from iprisk_contracts.analysis_artifact import AnalysisSecurityContext
    from iprisk_contracts.common import ContentScope

    from ip_risk_agent.connectors.common.segmentation import split_document

    return AnalysisArtifact(
        contract_version="1",
        analysis_job_id="job",
        risk_workspace_id="vws",
        mount_id="mount",
        artifact_id="artifact",
        logical_path=path,
        revision="rev",
        artifact_kind=kind,
        mime_type="text/plain",
        requested_analyzers=list(requested),
        content_scope=ContentScope.FULL_TEXT,
        text_segments=split_document("본문이 있어야 조각이 생긴다.\n" * 8),
        security_context=AnalysisSecurityContext(
            approved=True,
            policy_version="p",
            redaction_count=0,
            original_checksum="sha256:o",
            analysis_input_checksum="sha256:i",
        ),
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.parametrize(
    "name",
    (*READABLE, *NOT_DEPENDENCIES, "app.ts", "README.rst", "diagram.png"),
)
@pytest.mark.parametrize("source", ("github", "drive", "local"))
def test_the_gate_never_sends_a_file_where_no_analyzer_will_take_it(
    name: str, source: str
) -> None:
    """이 결함의 일반형을 막는다.

    관문은 종류를 보고 분석기를 **요청**하는데, 그 분석기가 정작 그 파일을 맡지
    않으면 결과가 0 건이 되고 분석은 계약 위반으로 실패한다. 커넥터의 분류와
    분석기가 받는 조건이 어긋나면 언제든 다시 생긴다.

    요청이 비는 것은 괜찮다 — 관문이 거부 사유를 붙여 끝내고, 그건 실패가 아니다.
    """
    from iprisk_contracts.common import AnalysisType

    from ip_risk_agent.application.security_gate.service import _eligible_analyzers
    from ip_risk_agent.application.security_gate.policy import SecurityGatePolicy
    from ip_risk_agent.intelligence.license.analyzer import LicenseAnalyzer
    from ip_risk_agent.intelligence.patent.analyzer import PatentAnalyzer

    kind = _kinds(name)[source]
    requested = _eligible_analyzers(
        kind,
        (AnalysisType.PATENT, AnalysisType.LICENSE),
        SecurityGatePolicy(policy_version="test"),
    )
    if not requested:
        return

    analyzers = {
        AnalysisType.LICENSE: LicenseAnalyzer(metadata_provider=None),
        AnalysisType.PATENT: PatentAnalyzer(None, None),
    }
    artifact = _artifact(name, kind, requested)
    for analysis_type in requested:
        assert analyzers[analysis_type].supports(artifact), (
            f"{source} 가 {name!r} 을 {kind.value} 로 두어 관문이 "
            f"{analysis_type.value} 를 요청했는데 그 분석기가 맡지 않는다"
        )


# --------------------------------------------------------------------- 0-A


@pytest.mark.parametrize("name", READABLE)
def test_a_dependency_file_reaches_the_analyzer_whole(name: str) -> None:
    """조각내면 읽을 수 없다.

    ``pyproject.toml`` 을 빈 줄에서 자르면 ``[project]`` 표 밖에 떨어진 줄이 어느 표에
    속했는지 알 수 없고, ``package.json`` 조각은 그냥 깨진 JSON 이다. 실측에서 20 건이
    3 건으로, 1 건이 0 건으로 줄었다.
    """
    from iprisk_contracts.common import ArtifactKind

    from ip_risk_agent.connectors.common.segmentation import segments_for

    for kind in (ArtifactKind.MANIFEST, ArtifactKind.LOCKFILE):
        segments = segments_for("[project]\nname = 'x'\n\ndependencies = ['a==1']\n", kind)
        assert len(segments) == 1
        assert segments[0].segment_id == "full"


def test_prose_is_still_split_so_patent_evidence_can_point() -> None:
    """조각화 자체를 되돌리는 것이 아니다.

    특허 근거가 "이 문서 어딘가" 가 아니라 매칭된 문단을 가리키려면 산문은 나뉘어야
    한다. 종류로 가를 뿐이다.
    """
    from iprisk_contracts.common import ArtifactKind

    from ip_risk_agent.connectors.common.segmentation import segments_for

    # 조각이 MIN_SEGMENT_CHARS(160) 보다 작으면 앞 조각에 붙으므로 넉넉히 만든다.
    paragraph = "이것은 검토 단위가 될 만큼 충분히 긴 문단이다. " * 12
    prose = "\n\n".join(f"{index} 번째 문단. {paragraph}" for index in range(4))
    segments = segments_for(prose, ArtifactKind.DOCUMENT_TEXT)
    assert len(segments) > 1


def test_a_manifest_survives_the_round_trip_that_used_to_lose_it() -> None:
    """이 저장소 자신의 매니페스트로 잰다 — 재현에 쓴 것과 같은 파일이다."""
    from pathlib import Path

    from iprisk_contracts.common import ArtifactKind

    from ip_risk_agent.connectors.common.segmentation import segments_for, split_document
    from ip_risk_agent.intelligence.license.analyzer import _select_parser

    root = Path(__file__).resolve().parents[2]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    parser = _select_parser("pyproject.toml")

    from ip_risk_agent.intelligence.license.dependency_models import (
        DependencyParseError,
    )

    whole = len(parser(text, "pyproject.toml"))

    def _count(fragment: str) -> int:
        # 조각은 깨진 TOML 이라 이제 파서가 못 읽었다고 말한다. 예전에는 조용히
        # 0 을 돌려줬고, 그것이 손실이 안 보이던 이유다.
        try:
            return len(parser(fragment, "pyproject.toml"))
        except DependencyParseError:
            return 0

    through_segments = sum(_count(segment.text) for segment in split_document(text))
    now = sum(
        len(parser(segment.text, "pyproject.toml"))
        for segment in segments_for(text, ArtifactKind.MANIFEST)
    )

    assert whole > through_segments, "재현 조건이 사라졌다면 이 시험은 뜻이 없다"
    assert now == whole


# --------------------------------------------------------------------- 0-J


def test_a_lockfile_that_reads_like_a_manifest_is_still_a_lockfile() -> None:
    """``requirements.lock`` 은 문법이 ``requirements.txt`` 와 같다.

    그래서 같은 파서로 읽히는데, **신뢰도는 다르다.** 잠금 파일은 도구가 해석을 끝내고
    적어 둔 값이라 매니페스트의 ``==`` 보다 강하다. 같은 값으로 두면 중복 제거에서
    **먼저 온 쪽이 이겨** 결과가 파일 읽는 순서에 달린다.
    """
    from ip_risk_agent.core.artifacts.dependency_files import DependencyFormat
    from ip_risk_agent.intelligence.license.analyzer import _select_parser
    from ip_risk_agent.intelligence.license.dependency_models import ResolutionKind

    assert dependency_format("requirements.lock") is DependencyFormat.REQUIREMENTS_LOCK
    assert dependency_format("requirements.lock").is_lockfile

    text = "requests==2.32.3\nflask==3.0.0\n"
    locked = _select_parser("requirements.lock")(text, "requirements.lock")
    plain = _select_parser("requirements.txt")(text, "requirements.txt")

    assert [d.resolution for d in locked] == [ResolutionKind.LOCKFILE] * 2
    assert [d.resolution for d in plain] == [ResolutionKind.EXACT_PIN] * 2


def test_the_requirements_folder_convention_is_recognised() -> None:
    """``requirements/base.txt`` 는 이름만 보면 ``base.txt`` 라 알아볼 수 없다.

    폴더로 나누는 관행이 넓어서 부모 폴더 하나만 함께 본다. 이 규칙은 알아보는 것을
    늘릴 뿐 줄이지 않는다 — 아래 시험이 그것을 고정한다.
    """
    assert dependency_format("requirements/base.txt") is not None
    assert dependency_format("requirements/dev.in") is not None
    # 폴더 안이어도 읽을 수 있는 형식이어야 한다.
    assert dependency_format("requirements/README.md") is None
    # 폴더 이름이 다르면 걸리지 않는다.
    assert dependency_format("docs/notes.txt") is None


def test_this_repository_s_own_lockfile_is_no_longer_invisible() -> None:
    """실종된 68 건이 이 저장소 자신의 파일이었다."""
    from pathlib import Path

    from ip_risk_agent.intelligence.license.analyzer import _select_parser

    root = Path(__file__).resolve().parents[2]
    lock = root / "requirements.lock"
    if not lock.is_file():  # pragma: no cover - 저장소 구성이 바뀌면
        return

    parser = _select_parser("requirements.lock")
    assert parser is not None, "인식 목록에 없으면 아무 분석기도 맡지 않는다"
    found = parser(lock.read_text(encoding="utf-8"), "requirements.lock")
    assert len(found) > 50
