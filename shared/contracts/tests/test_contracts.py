from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from iprisk_contracts import (
    AnalysisArtifact,
    AnalysisCoverage,
    AnalysisResult,
    AnalysisStatus,
    AnalysisVersions,
    Evidence,
    LicenseCandidate,
    LicensePolicyOutcome,
    PatentCandidate,
    ProviderFailure,
    SourceAccessType,
    SourceChange,
    SourceSnapshot,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "shared" / "contracts" / "fixtures"
SCHEMAS = ROOT / "shared" / "contracts" / "schemas"
GENERATED_TS = ROOT / "shared" / "contracts" / "typescript" / "generated" / "contracts.ts"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("name", "model"),
    [
        ("source-change-drive.json", SourceChange),
        ("source-change-github.json", SourceChange),
        ("source-change-local.json", SourceChange),
        ("source-snapshot-changed-context.json", SourceSnapshot),
        ("analysis-artifact-approved.json", AnalysisArtifact),
        ("analysis-result-patent-succeeded.json", AnalysisResult),
        ("analysis-result-license-succeeded.json", AnalysisResult),
        ("analysis-result-failed.json", AnalysisResult),
        ("analysis-result-partial.json", AnalysisResult),
    ],
)
def test_fixture_round_trip(name: str, model: type) -> None:
    payload = load_fixture(name)
    parsed = model.model_validate(payload)
    serialized = json.loads(parsed.model_dump_json())
    assert model.model_validate(serialized) == parsed


def test_unknown_and_sensitive_extra_fields_are_rejected() -> None:
    payload = load_fixture("source-change-drive.json")
    for field_name in ("raw_content", "oauth_token", "credential", "local_absolute_path"):
        invalid = deepcopy(payload)
        invalid[field_name] = "must-not-pass"
        with pytest.raises(ValidationError):
            SourceChange.model_validate(invalid)


def test_source_change_shape_is_content_free() -> None:
    forbidden = {"content", "text", "bytes", "token", "credential", "local_absolute_path"}
    assert forbidden.isdisjoint(SourceChange.model_fields)


def test_contract_version_is_exactly_one() -> None:
    payload = load_fixture("source-change-drive.json")
    payload["contract_version"] = "2"
    with pytest.raises(ValidationError):
        SourceChange.model_validate(payload)


def test_timezone_aware_datetime_is_required() -> None:
    payload = load_fixture("source-change-drive.json")
    payload["observed_at"] = datetime(2026, 8, 14, 1, 0, 0).isoformat()
    with pytest.raises(ValidationError):
        SourceChange.model_validate(payload)


def test_fixed_enum_values() -> None:
    assert {item.value for item in SourceAccessType} == {
        "METADATA",
        "DIFF",
        "PARTIAL_CONTENT",
        "FULL_CONTENT",
    }
    assert {item.value for item in AnalysisStatus} == {
        "SUCCEEDED",
        "FAILED",
        "INCONCLUSIVE",
        "SKIPPED",
    }
    assert {item.value for item in AnalysisCoverage} == {"COMPLETE", "PARTIAL", "NONE"}


def test_recursive_metadata_accepts_only_json_values() -> None:
    payload = load_fixture("source-change-drive.json")
    payload["safe_metadata"] = {"nested": [1, True, None, {"ok": "value"}]}
    SourceChange.model_validate(payload)
    payload["safe_metadata"] = {"bad": object()}
    with pytest.raises(ValidationError):
        SourceChange.model_validate(payload)


def test_access_receipt_and_content_scope_are_independent() -> None:
    snapshot = SourceSnapshot.model_validate(load_fixture("source-snapshot-changed-context.json"))
    assert snapshot.content_scope.value == "CHANGESET_WITH_CONTEXT"
    assert snapshot.source_access_receipt.access_type is SourceAccessType.FULL_CONTENT


def test_unapproved_analysis_artifact_guard_rejects() -> None:
    payload = load_fixture("analysis-artifact-approved.json")
    payload["security_context"]["approved"] = False
    artifact = AnalysisArtifact.model_validate(payload)
    with pytest.raises(PermissionError):
        artifact.require_approved()


def test_analysis_versions_exact_fields() -> None:
    assert set(AnalysisVersions.model_fields) == {
        "analyzer_version",
        "model_id",
        "prompt_version",
        "policy_version",
        "rag_corpus_version",
    }
    assert "model_version" not in AnalysisVersions.model_fields
    assert "corpus_version" not in AnalysisVersions.model_fields


def test_patent_candidate_exact_identity_and_shape() -> None:
    assert set(PatentCandidate.model_fields) == {
        "normalized_application_number",
        "title",
        "suggested_review_priority",
        "matched_elements",
        "evidence_ids",
        "provider_metadata_safe",
    }
    assert "publication_number" not in PatentCandidate.model_fields
    assert "risk_id" not in PatentCandidate.model_fields


def test_license_candidate_exact_shape_and_policy_taxonomy() -> None:
    assert set(LicenseCandidate.model_fields) == {
        "ecosystem",
        "normalized_package_name",
        "resolved_version",
        "normalized_license_expression",
        "policy_outcome",
        "evidence_ids",
        "uncertainty_flags",
    }
    assert {item.value for item in LicensePolicyOutcome} == {
        "NO_ACTION",
        "NOTICE_REQUIRED",
        "REVIEW_REQUIRED",
        "POLICY_CONFLICT",
        "UNKNOWN",
    }


def test_candidate_references_existing_evidence_and_evidence_has_no_candidate_id() -> None:
    assert "candidate_id" not in Evidence.model_fields
    payload = load_fixture("analysis-result-patent-succeeded.json")
    payload["candidates"][0]["evidence_ids"].append("missing-evidence")
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(payload)


def test_duplicate_evidence_id_is_rejected() -> None:
    payload = load_fixture("analysis-result-patent-succeeded.json")
    payload["evidence"].append(deepcopy(payload["evidence"][0]))
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(payload)


def test_non_success_cannot_claim_complete_coverage() -> None:
    payload = load_fixture("analysis-result-failed.json")
    payload["coverage"] = "COMPLETE"
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(payload)


def test_provider_failure_safe_shape() -> None:
    assert set(ProviderFailure.model_fields) == {"provider", "category", "retryable", "safe_message"}
    with pytest.raises(ValidationError):
        ProviderFailure.model_validate(
            {
                "provider": "KIPRIS",
                "category": "TIMEOUT",
                "retryable": True,
                "safe_message": "Timed out.",
                "raw_response": "sensitive",
            }
        )


def digest_generated_files() -> dict[str, str]:
    paths = sorted(SCHEMAS.glob("*.json")) + [GENERATED_TS]
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def test_schema_and_typescript_generation_is_deterministic() -> None:
    from scripts.generate_contracts import generate

    generate()
    first = digest_generated_files()
    generate()
    second = digest_generated_files()
    assert first == second
    assert {path.name for path in SCHEMAS.glob("*.json")} == {
        "source-change.v1.json",
        "source-snapshot.v1.json",
        "analysis-artifact.v1.json",
        "analysis-result.v1.json",
    }
    generated = GENERATED_TS.read_text(encoding="utf-8")
    assert "export type JsonValue" in generated
    assert "| { [key: string]: JsonValue };" in generated


def pnpm_command(*args: str) -> list[str]:
    executable = os.environ.get("PNPM_EXECUTABLE") or shutil.which("pnpm")
    if not executable:
        pytest.fail("pnpm is required for the TypeScript package resolution contract test")
    if os.name == "nt" and executable.lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", executable, *args]
    return [executable, *args]


@pytest.mark.parametrize("workspace", ["@iprisk/frontend", "@iprisk/desktop"])
def test_typescript_workspace_package_resolution(workspace: str) -> None:
    result = subprocess.run(
        pnpm_command("--filter", workspace, "typecheck"),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

