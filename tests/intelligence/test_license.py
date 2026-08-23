"""License Analyzer 회귀 테스트 (Agent 3 Spec 45).

외부 호출 없이 돈다. provider 는 전부 정해진 답을 주는 대역으로 바꾼다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from iprisk_contracts import AnalysisArtifact
from iprisk_contracts.common import (
    AnalysisCoverage,
    AnalysisStatus,
    AnalysisType,
    AnalysisSecurityContext,
    ArtifactKind,
    ContentScope,
    LicensePolicyOutcome,
    SegmentKind,
    TextSegment,
)

from ip_risk_agent.intelligence.common.errors import ArtifactRejectedError
from ip_risk_agent.intelligence.license import lockfiles, manifests, policy, spdx
from ip_risk_agent.intelligence.license.analyzer import LicenseAnalyzer
from ip_risk_agent.intelligence.license.dependency_models import (
    DependencySet,
    Ecosystem,
    ResolutionKind,
)
from ip_risk_agent.intelligence.license.explanation import (
    ReferenceChunk,
)
from ip_risk_agent.intelligence.license.package_metadata import (
    StaticPackageMetadataProvider,
)


def make_artifact(
    text: str,
    logical_path: str = "requirements.txt",
    *,
    approved: bool = True,
    kind: ArtifactKind = ArtifactKind.MANIFEST,
    analyzers: list[AnalysisType] | None = None,
) -> AnalysisArtifact:
    return AnalysisArtifact(
        contract_version="1",
        analysis_job_id="job-1",
        risk_workspace_id="vws-1",
        mount_id="mount-1",
        artifact_id="artifact-1",
        logical_path=logical_path,
        revision="rev-1",
        artifact_kind=kind,
        mime_type="text/plain",
        requested_analyzers=analyzers if analyzers is not None else [AnalysisType.LICENSE],
        content_scope=ContentScope.FULL_TEXT,
        text_segments=[
            TextSegment(segment_id="seg-1", text=text, segment_kind=SegmentKind.FULL)
        ],
        security_context=AnalysisSecurityContext(
            approved=approved,
            policy_version="gate-1",
            redaction_count=0,
            original_checksum="sha256:aaa",
            analysis_input_checksum="sha256:bbb",
        ),
        created_at=datetime.now(UTC),
    )


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------- 대역


class FakeRetriever:
    def __init__(self, chunks: list[ReferenceChunk] | None = None, *, fail: bool = False):
        self._chunks = chunks or [
            ReferenceChunk(
                source_id="agpl-3.0-obligations",
                chunk_id="agpl-3.0:obligations",
                text="네트워크를 통해 서비스를 제공하는 경우에도 소스코드를 제공해야 한다.",
                canonical_reference="https://spdx.org/licenses/AGPL-3.0-only.html",
            )
        ]
        self._fail = fail

    @property
    def corpus_version(self) -> str:
        return "2026-08-14.1"

    async def retrieve(self, query, *, filters=None, top_k=3):
        if self._fail:
            raise RuntimeError("rag engine unavailable")
        return self._chunks[:top_k]


PROVIDER = StaticPackageMetadataProvider(
    {
        ("pypi", "pymupdf"): "AGPL-3.0-only",
        ("pypi", "requests"): "Apache-2.0",
        ("pypi", "paramiko"): "LGPL-2.1-only",
        ("pypi", "mystery"): "non-standard",
        ("npm", "express"): "MIT",
    }
)


# --------------------------------------------------------------- 파서


def test_requirements_parser_distinguishes_pin_from_range():
    found = manifests.parse_requirements_txt(
        "requests>=2.32\nPyMuPDF==1.24.0\n-r other.txt\n# comment\n"
    )
    by_name = {d.name: d for d in found}
    assert by_name["pymupdf"].resolution is ResolutionKind.EXACT_PIN
    assert by_name["pymupdf"].version == "1.24.0"
    assert by_name["requests"].resolution is ResolutionKind.RANGE
    assert by_name["requests"].version is None
    assert "VERSION_RANGE_NOT_PINNED" in by_name["requests"].uncertainty_flags()


def test_package_json_parser():
    found = manifests.parse_package_json(
        '{"dependencies":{"express":"^4.19.2","left-pad":"1.3.0"}}'
    )
    by_name = {d.name: d for d in found}
    assert by_name["express"].resolution is ResolutionKind.RANGE
    assert by_name["left-pad"].version == "1.3.0"


def test_lockfile_version_wins_over_manifest_range():
    deps = DependencySet()
    deps.extend(manifests.parse_package_json('{"dependencies":{"express":"^4.19.2"}}'))
    deps.extend(
        lockfiles.parse_package_lock_json(
            '{"packages":{"":{"name":"app"},"node_modules/express":{"version":"4.19.2"}}}'
        )
    )
    express = deps.items()[0]
    assert express.version == "4.19.2"
    assert express.resolution is ResolutionKind.LOCKFILE
    assert express.uncertainty_flags() == []


def test_uv_lock_parser():
    found = lockfiles.parse_uv_lock(
        '[[package]]\nname = "requests"\nversion = "2.32.3"\n'
    )
    assert found[0].name == "requests"
    assert found[0].resolution is ResolutionKind.LOCKFILE


def test_a_file_we_could_not_read_is_not_a_file_with_no_dependencies():
    """이 시험은 예전에 반대를 고정하고 있었다.

    깨진 입력에 빈 목록을 돌려주는 것을 "예외를 안 낸다" 는 이름으로 지켜 주고 있었는데,
    그 빈 목록이 ``SUCCEEDED`` + ``COMPLETE`` 로 올라가 **그 파일의 Risk 를 전부
    해소했다.** 읽지 못한 것이 "위험이 사라졌다" 가 되는 경로였다.
    """
    from ip_risk_agent.intelligence.license.dependency_models import (
        DependencyParseError,
    )

    with pytest.raises(DependencyParseError):
        manifests.parse_package_json("{ not json")
    with pytest.raises(DependencyParseError):
        lockfiles.parse_uv_lock("[[[broken")
    with pytest.raises(DependencyParseError):
        manifests.parse_pyproject_toml("[[[broken")

    # "읽었는데 없었다" 는 그대로 빈 목록이다. 둘을 가르는 것이 요점이다.
    assert manifests.parse_package_json('{"name": "x"}') == []
    assert manifests.parse_pyproject_toml("[project]\nname = 'x'\n") == []


def test_an_unreadable_file_comes_back_partial_not_complete():
    """분석기가 그 예외를 삼키지 않는다.

    ``PARTIAL`` 은 해소 권한을 갖지 않으므로(§7.2) 못 읽은 파일이 기존 Risk 를 닫지
    못한다.
    """
    from iprisk_contracts.common import AnalysisCoverage, AnalysisStatus

    result = run(LicenseAnalyzer(PROVIDER).analyze(make_artifact("{ not json", "package.json")))
    assert result.status is AnalysisStatus.SUCCEEDED
    assert result.coverage is AnalysisCoverage.PARTIAL
    assert not result.candidates


# --------------------------------------------------------------- SPDX


def test_spdx_alias_normalization():
    assert spdx.canonicalize("apache 2.0") == "Apache-2.0"
    assert spdx.canonicalize("GPL-2.0") == "GPL-2.0-only"
    assert spdx.canonicalize("GPL-2.0+") == "GPL-2.0-or-later"
    assert spdx.canonicalize("Foo-9.9") == spdx.UNKNOWN_LICENSE


def test_free_text_recovers_license_missed_by_registry():
    # deps.dev 가 non-standard 로 답하는 실제 사례.
    recovered = spdx.from_free_text(
        "Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License"
    )
    assert recovered == "AGPL-3.0-only"


def test_and_applies_every_obligation_but_or_allows_a_choice():
    assert policy.evaluate_expression("MIT AND GPL-3.0-only") is LicensePolicyOutcome.POLICY_CONFLICT
    assert policy.evaluate_expression("MIT OR GPL-3.0-only") is LicensePolicyOutcome.NOTICE_REQUIRED


def test_with_exception_keeps_base_license():
    node = spdx.parse_expression("Apache-2.0 WITH LLVM-exception")
    assert isinstance(node, spdx.LicenseNode)
    assert node.identifier == "Apache-2.0"
    assert node.exception == "LLVM-exception"


def test_nested_expression_round_trips():
    assert spdx.normalize("(MIT OR Apache-2.0) AND BSD-3-Clause") == (
        "(MIT OR Apache-2.0) AND BSD-3-Clause"
    )


def test_unknown_license_is_never_auto_allowed():
    assert policy.evaluate_expression("Foo-9.9") is LicensePolicyOutcome.UNKNOWN
    # AND 에 섞이면 전체가 UNKNOWN 으로 올라간다.
    assert policy.evaluate_expression("MIT AND Foo-9.9") is LicensePolicyOutcome.UNKNOWN


# --------------------------------------------------------------- Analyzer


def test_unapproved_artifact_is_rejected_before_any_provider_call():
    analyzer = LicenseAnalyzer(PROVIDER)
    with pytest.raises(ArtifactRejectedError):
        run(analyzer.analyze(make_artifact("requests==2.32.3", approved=False)))


def test_analysis_type_not_requested_is_rejected():
    analyzer = LicenseAnalyzer(PROVIDER)
    with pytest.raises(ArtifactRejectedError):
        run(
            analyzer.analyze(
                make_artifact("requests==2.32.3", analyzers=[AnalysisType.PATENT])
            )
        )


def test_source_code_is_not_supported():
    analyzer = LicenseAnalyzer(PROVIDER)
    artifact = make_artifact("print('hi')", "src/app.py", kind=ArtifactKind.SOURCE_CODE)
    assert analyzer.supports(artifact) is False


def test_clean_manifest_succeeds_with_complete_coverage():
    analyzer = LicenseAnalyzer(PROVIDER)
    result = run(analyzer.analyze(make_artifact("requests==2.32.3")))
    assert result.status is AnalysisStatus.SUCCEEDED
    assert result.coverage is AnalysisCoverage.COMPLETE
    assert result.candidates[0].policy_outcome is LicensePolicyOutcome.NOTICE_REQUIRED
    assert result.versions.policy_version == policy.POLICY_VERSION


def test_empty_manifest_is_success_not_failure():
    analyzer = LicenseAnalyzer(PROVIDER)
    result = run(analyzer.analyze(make_artifact("# 주석만 있다\n")))
    assert result.status is AnalysisStatus.SUCCEEDED
    assert result.candidates == []


def test_copyleft_dependency_is_flagged_with_evidence():
    analyzer = LicenseAnalyzer(PROVIDER)
    result = run(analyzer.analyze(make_artifact("PyMuPDF==1.24.0")))
    candidate = result.candidates[0]
    assert candidate.policy_outcome is LicensePolicyOutcome.POLICY_CONFLICT
    assert candidate.evidence_ids
    # Contract 가 참조 무결성을 강제하므로 여기서도 확인한다.
    known = {e.evidence_id for e in result.evidence}
    assert set(candidate.evidence_ids) <= known


def test_metadata_failure_does_not_become_a_clean_result():
    provider = StaticPackageMetadataProvider({}, failures={("pypi", "requests")})
    result = run(LicenseAnalyzer(provider).analyze(make_artifact("requests==2.32.3")))
    assert result.status is AnalysisStatus.SUCCEEDED
    # 조회 실패는 COMPLETE 가 아니다. Control 이 이 결과로 Risk 를 해소하면 안 된다.
    assert result.coverage is AnalysisCoverage.PARTIAL
    assert result.provider_failures[0].provider == "PACKAGE_METADATA"
    assert result.candidates[0].policy_outcome is LicensePolicyOutcome.UNKNOWN
    assert "METADATA_LOOKUP_FAILED" in result.candidates[0].uncertainty_flags


def test_rag_failure_downgrades_coverage_but_keeps_policy_result():
    analyzer = LicenseAnalyzer(PROVIDER, retriever=FakeRetriever(fail=True))
    result = run(analyzer.analyze(make_artifact("PyMuPDF==1.24.0")))
    assert result.candidates[0].policy_outcome is LicensePolicyOutcome.POLICY_CONFLICT
    assert result.coverage is AnalysisCoverage.PARTIAL
    assert result.provider_failures[0].provider == "RAG_ENGINE"


def test_rag_reference_is_attached_as_evidence():
    """라이선스 분석은 근거만 붙이고 설명은 만들지 않는다.

    설명은 `RiskExplanationService` 가 **저장된 근거**에서 만든다. 분석기 안에서
    만들면 담을 곳이 없어 버려진다 — 실제로 그랬고, 후보마다 Gemini 를 부르고
    결과를 쓰지 않았다.
    """
    analyzer = LicenseAnalyzer(PROVIDER, retriever=FakeRetriever())
    result = run(analyzer.analyze(make_artifact("PyMuPDF==1.24.0")))
    assert result.coverage is AnalysisCoverage.COMPLETE
    assert result.versions.rag_corpus_version == "2026-08-14.1"
    # 라이선스 경로는 모델을 부르지 않는다. 부르지 않았으니 버전도 없다.
    assert result.versions.model_id is None
    assert any(e.evidence_id.startswith("rag:") for e in result.evidence)
    # 그 근거가 후보에 달려 있어야 설명기가 나중에 그것을 보고 쓴다.
    assert any(eid.startswith("rag:") for eid in result.candidates[0].evidence_ids)


def test_deterministic_policy_is_not_overridden_by_the_model():
    strict = run(LicenseAnalyzer(PROVIDER).analyze(make_artifact("PyMuPDF==1.24.0")))
    explained = run(
        LicenseAnalyzer(PROVIDER, retriever=FakeRetriever()).analyze(
            make_artifact("PyMuPDF==1.24.0")
        )
    )
    assert (
        strict.candidates[0].policy_outcome is explained.candidates[0].policy_outcome
    )


def test_unresolved_range_is_reported_as_uncertain():
    analyzer = LicenseAnalyzer(PROVIDER)
    result = run(analyzer.analyze(make_artifact("requests>=2.32")))
    assert "VERSION_RANGE_NOT_PINNED" in result.candidates[0].uncertainty_flags


def test_npm_lockfile_artifact_is_analyzed():
    analyzer = LicenseAnalyzer(PROVIDER)
    artifact = make_artifact(
        '{"packages":{"":{"name":"app"},"node_modules/express":{"version":"4.19.2"}}}',
        "package-lock.json",
        kind=ArtifactKind.LOCKFILE,
    )
    assert analyzer.supports(artifact)
    result = run(analyzer.analyze(artifact))
    assert result.candidates[0].normalized_package_name == "express"
    assert result.candidates[0].resolved_version == "4.19.2"
    assert result.candidates[0].ecosystem == Ecosystem.NPM.value


# ----------------------------------------------------------------- 0-I 로그


def test_the_license_path_reports_what_it_read(caplog):
    """이 경로에 로그가 한 줄도 없어서 20 → 3 손실이 운영에서 안 보였다.

    조각 수·선언 수·후보 수를 나란히 남기면 그 손실이 한 줄에서 드러난다.
    """
    import json

    with caplog.at_level("INFO", logger="ip_risk_agent.intelligence.license.analyzer"):
        run(LicenseAnalyzer(PROVIDER).analyze(make_artifact("requests==2.32.3")))

    lines = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{")
    ]
    diagnostics = [
        line for line in lines if line.get("event") == "license_analysis_diagnostic"
    ]
    assert len(diagnostics) == 1
    entry = diagnostics[0]
    assert entry["segment_count"] == 1
    assert entry["declaration_count"] == 1
    assert entry["candidate_count"] == 1
    assert entry["dependency_format"] == "REQUIREMENTS_TXT"
    assert entry["artifact_id"] == "artifact-1"
    assert entry["revision"] == "rev-1"


def test_a_file_that_declared_nothing_is_reported_before_it_returns(caplog):
    """0 건으로 나가는 자리가 조용한 오보가 시작되는 곳이다. 반드시 남긴다."""
    import json

    with caplog.at_level("INFO", logger="ip_risk_agent.intelligence.license.analyzer"):
        result = run(LicenseAnalyzer(PROVIDER).analyze(make_artifact("# 주석뿐이다\n")))

    assert not result.candidates
    entry = next(
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{")
        and json.loads(record.message).get("event") == "license_analysis_diagnostic"
    )
    assert entry["declaration_count"] == 0
    assert entry["candidate_count"] == 0


def test_the_diagnostic_carries_no_package_name_and_no_path(caplog):
    """패키지 이름도 파일 경로도 사용자 소스에서 온 내용이라 로그에 넣지 않는다.

    되짚을 수단은 남긴다 — ``artifact_id`` 와 ``revision`` 으로 canonical 저장소에서
    어느 파일인지 찾을 수 있고, 로그 자체는 내용을 담지 않는다.
    """
    with caplog.at_level("INFO", logger="ip_risk_agent.intelligence.license.analyzer"):
        run(
            LicenseAnalyzer(PROVIDER).analyze(
                make_artifact("requests==2.32.3", logical_path="deps/api/requirements.txt")
            )
        )

    emitted = " ".join(
        record.message for record in caplog.records if record.message.startswith("{")
    )
    assert "requests" not in emitted
    assert "deps/api" not in emitted
    assert "requirements.txt" not in emitted


# ----------------------------------------------------------------- 0-D


def test_a_truncated_manifest_is_not_reported_as_complete():
    """줄 지향 파일은 잘려도 파서가 아무 말을 안 한다.

    깨진 JSON·TOML 은 §6.6 이 잡는다. 그런데 ``requirements.txt`` 는 뒤가 잘려도 앞부분이
    멀쩡한 파일처럼 읽힌다 — 선언 스무 개 중 여덟만 나오고 그것이 `COMPLETE` 로 올라가
    나머지 열둘의 Risk 가 해소된다. `content_scope` 가 그 사실을 들고 있는데 분석기가
    읽지 않고 있었다.
    """
    from iprisk_contracts.common import AnalysisCoverage, ContentScope

    artifact = make_artifact("requests==2.32.3")
    cut = artifact.model_copy(
        update={"content_scope": ContentScope.CHANGESET_WITH_CONTEXT}
    )

    whole = run(LicenseAnalyzer(PROVIDER).analyze(artifact))
    partial = run(LicenseAnalyzer(PROVIDER).analyze(cut))

    assert whole.coverage is AnalysisCoverage.COMPLETE
    assert partial.coverage is AnalysisCoverage.PARTIAL
    # 후보는 그대로 나온다 — 읽은 것까지는 사실이다. 권위만 잃는다.
    assert len(partial.candidates) == len(whole.candidates)


def test_a_dependency_file_gets_room_that_prose_does_not():
    """락파일은 크다. 산문 상한으로 자르면 깨진 JSON 이라 한 건도 못 읽는다.

    산문 상한이 작은 것은 그 내용이 provider 로 나가기 때문인데, 라이선스 경로는 파일
    내용을 아무 데도 보내지 않는다 — 패키지 이름과 버전만 레지스트리에 묻는다.
    """
    from iprisk_contracts.common import ArtifactKind, ContentScope, SegmentKind, TextSegment

    from ip_risk_agent.application.security_gate.minimization import minimize_segments
    from ip_risk_agent.application.security_gate.policy import SecurityGatePolicy

    policy = SecurityGatePolicy(policy_version="test")
    big = "x" * 100_000
    segment = TextSegment(
        segment_id="full", text=big, line_start=1, line_end=1, segment_kind=SegmentKind.FULL
    )

    kept, scope = minimize_segments(
        artifact_kind=ArtifactKind.LOCKFILE,
        content_scope=ContentScope.FULL_TEXT,
        segments=[segment],
        source_byte_size=len(big),
        policy=policy,
    )
    assert len(kept[0].text) == len(big), "락파일이 잘리면 파싱이 통째로 실패한다"
    assert scope is ContentScope.FULL_TEXT

    cut, cut_scope = minimize_segments(
        artifact_kind=ArtifactKind.DOCUMENT_TEXT,
        content_scope=ContentScope.FULL_TEXT,
        segments=[segment],
        source_byte_size=len(big),
        policy=policy,
    )
    assert len(cut[0].text) < len(big), "산문에는 상한이 그대로 걸린다"
    assert cut_scope is not ContentScope.FULL_TEXT


# ----------------------------------------------------------------- 0-K


def _npm_registry(document):
    """npm 레지스트리 하나만 답하는 가짜 전송."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if "deps.dev" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, json=document)

    return httpx.MockTransport(handler)


def test_a_version_the_registry_does_not_have_is_not_the_latest_one():
    """예전에는 문서 전체로 폴백해 **최신 버전의 라이선스를 그 버전의 것으로 기록**했다.

    라이선스는 버전마다 달라지고, **실제로 라이선스를 바꾼 패키지들이 이 제품이 잡으려는
    대상**이다. 그 순간에 최신 값으로 덮으면 바뀌었다는 사실 자체가 사라진다.
    """
    import httpx

    from ip_risk_agent.intelligence.license.dependency_models import Ecosystem
    from ip_risk_agent.intelligence.license.package_metadata import (
        HttpPackageMetadataProvider,
    )
    from ip_risk_agent.intelligence.license import spdx as _spdx

    # 문서 전체는 최신이 MIT 라고 말하고, 2.0.0 만 BUSL-1.1 이다.
    document = {"license": "MIT", "versions": {"2.0.0": {"license": "BUSL-1.1"}}}

    async def scenario():
        client = httpx.AsyncClient(transport=_npm_registry(document))
        provider = HttpPackageMetadataProvider(client=client)
        try:
            present = await provider.get_license(Ecosystem.NPM, "x", "2.0.0")
            missing = await provider.get_license(Ecosystem.NPM, "x", "9.9.9")
        finally:
            await client.aclose()
        return present, missing

    present, missing = run(scenario())

    # 있는 버전은 그 버전의 값이다.
    assert present.license_expression == "BUSL-1.1"
    assert present.version_not_found is False

    # 없는 버전은 최신으로 덮지 않는다.
    assert missing.license_expression == _spdx.UNKNOWN_LICENSE
    assert missing.version_not_found is True
    assert missing.version == "9.9.9", "요청한 버전은 그대로 남는다"


def test_not_knowing_the_version_is_said_out_loud():
    """왜 모르는지가 후보에 남아야 사용자가 조회 실패와 구분한다."""
    import httpx

    from ip_risk_agent.intelligence.license.package_metadata import (
        HttpPackageMetadataProvider,
    )

    document = {"license": "MIT", "versions": {"2.0.0": {"license": "MIT"}}}

    async def scenario():
        client = httpx.AsyncClient(transport=_npm_registry(document))
        provider = HttpPackageMetadataProvider(client=client)
        try:
            return await LicenseAnalyzer(provider).analyze(
                make_artifact('{"dependencies": {"x": "9.9.9"}}', "package.json")
            )
        finally:
            await client.aclose()

    result = run(scenario())
    assert len(result.candidates) == 1
    assert "VERSION_NOT_IN_REGISTRY" in result.candidates[0].uncertainty_flags



# ----------------------------------------------------------------- PEP 639


def _pypi_registry(info):
    """PyPI 하나만 답하는 가짜 전송. deps.dev 는 모른다고 답한다."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if "deps.dev" in str(request.url):
            return httpx.Response(200, json={"licenses": ["non-standard"]})
        return httpx.Response(200, json={"info": info})

    return httpx.MockTransport(handler)


def _pypi_license(info):
    import httpx

    from ip_risk_agent.intelligence.license.dependency_models import Ecosystem
    from ip_risk_agent.intelligence.license.package_metadata import (
        HttpPackageMetadataProvider,
    )

    async def scenario():
        client = httpx.AsyncClient(transport=_pypi_registry(info))
        provider = HttpPackageMetadataProvider(client=client)
        try:
            return await provider.get_license(Ecosystem.PYPI, "p", "1.0.0")
        finally:
            await client.aclose()

    return run(scenario())


def test_the_declared_spdx_expression_is_read_not_only_the_free_text_one():
    """PyPI 가 SPDX 로 명시한 것을 "모른다" 로 내리지 않는다.

    PEP 639 가 ``license_expression`` 을 들여오면서 ``license`` 는 폐기됐다. 옮긴
    패키지는 ``license`` 가 빈문자열이 되는데, 예전에는 그쪽만 읽었다. 그래서
    ``chardet==7.6.0`` (실제로 ``0BSD`` 를 명시한다) 이 검토 필요로 떨어졌다.

    조회된 SPDX 는 **추정이 아니다.** 추정으로 표시하면 조회해 온 사실을 우리
    짐작으로 낮춰 적는 것이 된다.
    """
    fact = _pypi_license({"license": "", "license_expression": "0BSD"})
    assert fact.license_expression == "0BSD"
    assert fact.inferred_from_free_text is False
    assert fact.is_unknown is False


def test_a_declared_copyleft_obligation_does_not_vanish():
    """``paramiko==5.0.0`` 이 명시하는 ``LGPL-2.1`` 은 약한 반대급부다.

    이것을 놓치면 등급이 하나 낮아지는 것이 아니라 **의무가 통째로 사라진다** —
    검토 필요는 "무엇을 지켜야 하는지 모른다" 이지 "지킬 것이 있다" 가 아니다.
    """
    fact = _pypi_license({"license": "", "license_expression": "LGPL-2.1"})
    assert fact.license_expression == "LGPL-2.1-only"
    assert fact.inferred_from_free_text is False


def test_the_free_text_field_still_answers_for_packages_that_never_moved():
    """옛 필드만 있는 패키지는 그대로 읽고, 추정이라는 사실도 그대로 남긴다.

    새 필드를 먼저 보는 것이 옛 경로를 막지 않아야 한다 — PyPI 에는 아직
    옮기지 않은 패키지가 훨씬 많다.
    """
    fact = _pypi_license(
        {
            "license": "Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial",
            "license_expression": "",
        }
    )
    assert fact.license_expression == "AGPL-3.0-only"
    assert fact.inferred_from_free_text is True, "짐작한 것은 짐작이라고 말한다"


def test_a_declared_expression_wins_over_a_vaguer_free_text_one():
    """둘 다 있으면 정규 표현식을 쓴다. ``license`` 는 버전을 흐린다.

    ``LGPL`` 만 보고는 2.0 인지 2.1 인지 or-later 인지 알 수 없어 짐작해야 하는데,
    옆에 ``LGPL-3.0-only`` 가 적혀 있으면 짐작할 이유가 없다.
    """
    fact = _pypi_license({"license": "LGPL", "license_expression": "LGPL-3.0-only"})
    assert fact.license_expression == "LGPL-3.0-only"
    assert fact.inferred_from_free_text is False


def test_a_package_that_declares_nothing_anywhere_stays_unknown():
    """``nvidia-cudnn-cu12`` 처럼 어디에도 SPDX 가 없으면 검토 필요가 맞다."""
    from ip_risk_agent.intelligence.license import spdx as _spdx

    fact = _pypi_license(
        {"license": "NVIDIA Proprietary Software", "license_expression": ""}
    )
    assert fact.license_expression == _spdx.UNKNOWN_LICENSE
    assert fact.is_unknown is True


def test_a_bundled_licence_text_is_not_scanned_for_a_name():
    """``license`` 에 전문이 실리면 훑지 않는다. 남의 라이선스가 나오기 때문이다.

    matplotlib 의 합의문은 품고 있는 FreeType 이 "FTL OR GPL-2.0-or-later" 라고
    적어 두었고, 예전 훑기는 그 GPL 을 matplotlib 의 것으로 읽었다. PSF 라이선스인
    패키지가 **최고 위험**으로 올라갔다는 뜻이다 — 이 제품에서 가장 나쁜 종류의
    오답이다. pandas 도 Apache 코드를 품고 있어 Apache 로 읽혔다.

    라이선스 문서는 원래 다른 라이선스를 이름으로 언급한다. 훑어서 될 일이 아니다.
    """
    from ip_risk_agent.intelligence.license import spdx as _spdx

    bundled = (
        "License agreement for matplotlib. " + ("x" * 3000)
        + " The FreeType 2 font engine is licensed FTL OR GPL-2.0-or-later."
    )
    assert _spdx.from_free_text(bundled) == _spdx.UNKNOWN_LICENSE
    assert _spdx.is_name_like(bundled) is False
    # 이름 길이면 지금도 훑는다 — 거절은 전문에만 걸린다.
    assert _spdx.is_name_like("GPLv2-or-later with a special exception") is True


def test_the_classifiers_answer_when_the_free_text_will_not():
    """자유 서술을 거절하기로 한 이상 분류자가 있어야 한다.

    ``weasyprint`` 는 ``license`` 가 비어 있고 분류자에만 BSD 가 있다. pandas 와
    matplotlib 은 전문이 실려 거절되지만 분류자는 각각 BSD 와 PSF 를 정확히 말한다.
    닫힌 어휘라 훑지 않고 맞춰 볼 수 있다.
    """
    from ip_risk_agent.intelligence.license.package_metadata import (
        HttpPackageMetadataProvider,
    )

    resolve = HttpPackageMetadataProvider._resolve_declaration

    # weasyprint: 자유 서술이 비어 있다.
    assert resolve("", "", ["License :: OSI Approved :: BSD License"]) == (
        "BSD-3-Clause",
        True,
    )
    # matplotlib: 전문은 거절되고 분류자가 답한다. 1:1 이라 추정이 아니다.
    assert resolve(
        "", "y" * 3000, ["License :: OSI Approved :: Python Software Foundation License"]
    ) == ("PSF-2.0", False)


def test_a_classifier_that_says_nothing_does_not_veto_one_that_does():
    """"License :: OSI Approved" 처럼 아무것도 말하지 않는 항목이 흔하다.

    그것을 반대 의견으로 세면 옆에 있는 정확한 항목까지 무효가 된다. wxPython 이
    실제로 이 둘을 함께 달고 있다.
    """
    from ip_risk_agent.intelligence.license import spdx as _spdx

    found, narrowed = _spdx.from_trove_classifiers(
        [
            "License :: OSI Approved",
            "License :: OSI Approved :: MIT License",
            "Programming Language :: Python :: 3",
        ]
    )
    assert (found, narrowed) == ("MIT", False)


def test_classifiers_that_disagree_are_not_resolved_for_the_user():
    """대개 이중 라이선스다. 어느 쪽을 고를지는 우리가 정할 일이 아니다."""
    from ip_risk_agent.intelligence.license import spdx as _spdx

    found, _ = _spdx.from_trove_classifiers(
        [
            "License :: OSI Approved :: MIT License",
            "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        ]
    )
    assert found == _spdx.UNKNOWN_LICENSE


def test_an_exact_declaration_is_never_downgraded_to_a_guess():
    """조회해 온 SPDX 를 추정으로 표시하면 사실을 짐작으로 낮춰 적는 것이 된다."""
    from ip_risk_agent.intelligence.license.package_metadata import (
        HttpPackageMetadataProvider,
    )

    resolve = HttpPackageMetadataProvider._resolve_declaration
    # 흐린 분류자가 옆에 있어도 명시된 표현식이 이긴다.
    assert resolve(
        "MPL-2.0", "", ["License :: OSI Approved :: BSD License"]
    ) == ("MPL-2.0", False)
    # 자유 서술이 그대로 표현식이면 그것도 사실이다.
    assert resolve("", "BSD-2-Clause", []) == ("BSD-2-Clause", False)


def test_a_vaguer_free_text_loses_to_a_precise_classifier():
    """``LGPL`` 로는 판을 알 수 없다. 분류자가 "v2 or later" 라고 적어 둔다."""
    from ip_risk_agent.intelligence.license.package_metadata import (
        HttpPackageMetadataProvider,
    )

    found, inferred = HttpPackageMetadataProvider._resolve_declaration(
        "",
        "LGPL",
        [
            "License :: OSI Approved :: GNU Lesser General Public License v2 or later"
            " (LGPLv2+)"
        ],
    )
    assert found == "LGPL-2.0-or-later"
    assert inferred is False, "닫힌 어휘가 판까지 말했으면 짐작이 아니다"


# ----------------------------------------------------------------- BOM · 건너뛴 줄


def test_a_byte_order_mark_does_not_erase_the_first_dependency():
    """윈도우가 붙이는 BOM 하나가 파일을 "선언 없음" 으로 만들었다.

    ``\ufeffrequests==2.31.0`` 은 이름 패턴에 걸리지 않아 **조용히** 건너뛰어졌고,
    결과는 `SUCCEEDED` + `COMPLETE` + 0 건이었다. 그것은 해소 권한을 가지므로
    **지우지도 않은 의존성의 Risk 가 해소됐다.** 운영에서 실제로 일어났다.

    BOM 은 인코딩 표시이지 내용이 아니다. 메모장도 PowerShell 의
    ``Set-Content -Encoding utf8`` 도 붙이므로 드문 일이 아니다.
    """
    from ip_risk_agent.intelligence.license import lockfiles as _lockfiles
    from ip_risk_agent.intelligence.license import manifests as _manifests

    found = _manifests.parse_requirements_txt("\ufeffrequests==2.31.0\n", "r.txt")
    assert [item.name for item in found] == ["requests"]

    # 다른 형식도 같다. 이쪽은 예외를 던져 시끄럽게 죽었지만, 죽을 이유가 없다.
    assert _manifests.parse_package_json(
        '\ufeff{"dependencies": {"chalk": "5.3.0"}}', "package.json"
    )
    assert _manifests.parse_pyproject_toml(
        '\ufeff[project]\ndependencies = ["requests==2.31.0"]', "pyproject.toml"
    )
    assert _manifests.parse_setup_cfg(
        "\ufeff[options]\ninstall_requires =\n    requests==2.31.0", "setup.cfg"
    )
    assert _lockfiles.parse_uv_lock(
        '\ufeff[[package]]\nname = "x"\nversion = "1.0"', "uv.lock"
    )
    assert _lockfiles.parse_package_lock_json(
        '\ufeff{"packages": {"node_modules/chalk": {"version": "5.3.0"}}}',
        "package-lock.json",
    )


def test_a_line_we_could_not_read_is_reported_not_swallowed():
    """관대한 것과 조용한 것은 다르다.

    한 줄이 깨졌다고 파일을 버리면 나머지 의존성을 놓치므로 넘어가는 것은 맞다.
    그런데 넘어간 사실을 말하지 않으면 그 결과가 `COMPLETE` 로 올라가고, `COMPLETE`
    에는 **해소 권한**이 있다. 읽지 못한 것은 "없다" 가 아니다.
    """
    from ip_risk_agent.intelligence.license import manifests as _manifests

    text = "requests==2.31.0\n!!! 이건 무엇도 아니다\n# 주석\n-r other.txt\n"
    found = _manifests.parse_requirements_txt(text, "r.txt")
    assert [item.name for item in found] == ["requests"], "읽은 것은 그대로 남는다"

    skipped = _manifests.unreadable_requirement_lines(text)
    assert skipped == ("!!! 이건 무엇도 아니다",)
    assert "# 주석" not in skipped and "-r other.txt" not in skipped, (
        "주석과 지시자는 못 읽은 것이 아니다"
    )


def test_a_file_with_an_unreadable_line_cannot_claim_to_be_complete():
    """`COMPLETE` 는 해소 권한이다. 다 읽지 못했으면 줄 수 없다."""
    result = run(
        LicenseAnalyzer(PROVIDER).analyze(
            make_artifact("requests==2.31.0\n!!! 무엇도 아니다\n", "requirements.txt")
        )
    )
    assert result.coverage is AnalysisCoverage.PARTIAL
    assert [c.normalized_package_name for c in result.candidates] == ["requests"], (
        "읽어 낸 것은 버리지 않는다"
    )


def test_a_file_whose_every_line_was_skipped_is_not_an_empty_file():
    """0 건과 "한 줄도 못 읽었다" 를 가른다.

    예전에는 둘 다 `SUCCEEDED` + `COMPLETE` + 0 건이었다.
    """
    result = run(
        LicenseAnalyzer(PROVIDER).analyze(
            make_artifact("!!! 무엇도 아니다\n@@@ 이것도\n", "requirements.txt")
        )
    )
    assert result.coverage is AnalysisCoverage.PARTIAL
    assert not result.candidates


def test_a_genuinely_empty_requirements_file_still_reads_as_complete():
    """거절이 지나치면 정상적인 빈 파일까지 미결로 만든다."""
    result = run(
        LicenseAnalyzer(PROVIDER).analyze(
            make_artifact("# 아직 의존성이 없다\n\n", "requirements.txt")
        )
    )
    assert result.coverage is AnalysisCoverage.COMPLETE
    assert not result.candidates

# ----------------------------------------------------------------- 0-H


class _EmptyRetriever:
    """살아 있지만 붙일 것을 못 찾는 검색기."""

    corpus_version = "2026-08-23.4"

    async def retrieve(self, query, *, filters=None, top_k=None):
        return []


def test_the_corpus_version_is_recorded_even_when_nothing_attaches():
    """예전에는 조각이 **붙었을 때만** 기록했다.

    그래서 주제 불일치로 전부 버린 경우와 조회 실패가 `None` 으로 같아졌다. corpus 갱신이
    판정을 바꾸는 구조에서 이 필드가 **감사의 전부**다 — 어느 판본을 보고 내린 판단인지
    모르면, corpus 를 올린 뒤 판정이 달라졌을 때 그것이 corpus 때문인지 가를 수 없다.
    """
    analyzer = LicenseAnalyzer(PROVIDER, retriever=_EmptyRetriever())
    # PROVIDER 가 아는 패키지 중 needs_review 를 내는 것이어야 RAG 를 부른다.
    result = run(analyzer.analyze(make_artifact("pymupdf==1.24.0")))

    assert not any(
        evidence.evidence_type.value == "LICENSE_REFERENCE" for evidence in result.evidence
    ), "붙은 것이 없어야 이 시험이 뜻을 갖는다"
    assert result.versions.rag_corpus_version == "2026-08-23.4"


def test_a_licence_that_never_calls_rag_records_no_corpus_version():
    """부르지도 않은 검색의 판본을 적으면 그것도 거짓말이다."""
    analyzer = LicenseAnalyzer(PROVIDER, retriever=_EmptyRetriever())
    result = run(analyzer.analyze(make_artifact("requests==2.32.3")))

    from ip_risk_agent.intelligence.license import policy

    assert not policy.needs_review(result.candidates[0].policy_outcome)
    assert result.versions.rag_corpus_version is None
