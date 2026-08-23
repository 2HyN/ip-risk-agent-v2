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
