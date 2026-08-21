from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import pytest
import yaml

from scripts.prepare_rag_ingestion import prepare
from scripts.validate_gcp_deployment import validate


ROOT = Path(__file__).resolve().parents[2]


def test_repository_owned_gcp_inputs_are_self_consistent() -> None:
    assert validate(ROOT) == []


@pytest.mark.parametrize(
    "violation",
    (
        "default-firestore",
        "legacy-cloud-run",
        "legacy-task-queue",
        "legacy-artifact-repository",
        "legacy-scheduler-job",
        "v1-fixed-secret",
        "non-v2-credential-prefix",
        "public-worker",
        "split-image",
        "worker-api-setting",
        "shared-image-api-setting",
        "missing-build-identity",
        "missing-build-source-bucket-read",
        "scheduler-route-mismatch",
        "index-count-mismatch",
    ),
)
def test_deployment_validator_rejects_v1_namespace_regressions(
    tmp_path: Path,
    violation: str,
) -> None:
    root = tmp_path / violation
    root.mkdir()
    shutil.copy(ROOT / "Dockerfile", root / "Dockerfile")
    shutil.copy(ROOT / ".dockerignore", root / ".dockerignore")
    shutil.copytree(ROOT / "deploy", root / "deploy")
    shutil.copytree(ROOT / "rag-corpus", root / "rag-corpus")
    scheduler_parent = root / "backend" / "src" / "ip_risk_agent" / "composition"
    scheduler_parent.mkdir(parents=True)
    shutil.copy(
        ROOT / "backend" / "src" / "ip_risk_agent" / "composition" / "scheduler_routes.py",
        scheduler_parent / "scheduler_routes.py",
    )
    shutil.copy(
        ROOT / "backend" / "src" / "ip_risk_agent" / "composition" / "production.py",
        scheduler_parent / "production.py",
    )
    tasks_parent = root / "backend" / "src" / "ip_risk_agent" / "gcp"
    tasks_parent.mkdir(parents=True)
    shutil.copy(
        ROOT / "backend" / "src" / "ip_risk_agent" / "gcp" / "cloud_tasks.py",
        tasks_parent / "cloud_tasks.py",
    )
    _inject_namespace_violation(root, violation)
    errors = validate(root)
    assert errors, f"validator accepted {violation}"
    expected_error = {
        "shared-image-api-setting": "shared runtime image must not define",
        "missing-build-source-bucket-read": "Cloud Build execution/logging/source IAM",
    }.get(violation)
    if expected_error is not None:
        assert any(expected_error in error for error in errors)


def _inject_namespace_violation(root: Path, violation: str) -> None:
    deploy = root / "deploy"
    if violation == "shared-image-api-setting":
        path = root / "Dockerfile"
        dockerfile = path.read_text("utf-8")
        path.write_text(
            dockerfile.replace(
                "    PORT=8080",
                "    PORT=8080 \\\n    FRONTEND_DIST_DIR=/app/frontend/dist",
            ),
            encoding="utf-8",
        )
        return
    if violation == "missing-build-source-bucket-read":
        path = deploy / "iam-policy-contract.yaml"
        document = yaml.safe_load(path.read_text("utf-8"))
        document["buildBindings"].pop("buildSourceBucketRead")
        path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return
    if violation in {"legacy-artifact-repository", "missing-build-identity"}:
        path = deploy / "cloudbuild.yaml"
        document = yaml.safe_load(path.read_text("utf-8"))
        if violation == "legacy-artifact-repository":
            document["substitutions"]["_REPOSITORY"] = "cloud-run-source-deploy"
        else:
            document.pop("serviceAccount")
    elif violation == "index-count-mismatch":
        path = deploy / "firestore.indexes.json"
        import json

        document = json.loads(path.read_text("utf-8"))
        document["indexes"].pop()
        path.write_text(json.dumps(document), encoding="utf-8")
        return
    elif violation == "legacy-task-queue":
        path = deploy / "cloud-tasks-queue.yaml"
        document = yaml.safe_load(path.read_text("utf-8"))
        document["queue"]["name"] = "analysis-changes"
    elif violation in {"legacy-scheduler-job", "scheduler-route-mismatch"}:
        path = deploy / "scheduler-jobs.yaml"
        document = yaml.safe_load(path.read_text("utf-8"))
        if violation == "legacy-scheduler-job":
            document["jobs"][0]["name"] = "ip-risk-agent-drive-poll"
        else:
            document["jobs"][0]["path"] = "/internal/scheduler/not-production"
    else:
        path = deploy / "cloud-run-services.yaml"
        document = yaml.safe_load(path.read_text("utf-8"))
        if violation == "default-firestore":
            document["canonicalEnvironment"]["common"]["FIRESTORE_DATABASE"] = (
                "(default)"
            )
        elif violation == "legacy-cloud-run":
            document["services"]["api"]["name"] = "ip-risk-agent"
        elif violation == "v1-fixed-secret":
            document["secretEnvironment"]["api"]["SESSION_SECRET"] = (
                "ipra-session-secret"
            )
        elif violation == "non-v2-credential-prefix":
            document["canonicalEnvironment"]["common"][
                "SOURCE_CREDENTIAL_SECRET_PREFIX"
            ] = "iprisk-google-drive"
        elif violation == "public-worker":
            document["services"]["worker"]["allowUnauthenticated"] = True
        elif violation == "split-image":
            document["services"]["worker"]["image"] = (
                "asia-northeast3-docker.pkg.dev/proj-aj22-211200020328/"
                "ip-risk-agent-v2/worker:${IMAGE_TAG}"
            )
        elif violation == "worker-api-setting":
            document["requiredEnvironment"]["worker"].append("CLOUD_TASKS_QUEUE")
        else:  # pragma: no cover - parametrization invariant
            raise AssertionError(violation)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_rag_ingestion_dry_run_is_manifest_bounded_and_write_free() -> None:
    report = asyncio.run(prepare(ROOT / "rag-corpus" / "manifest.yaml"))
    assert report == {
        "corpus_version": "2026-08-14.1",
        "document_count": 3,
        "uploaded": 3,
        "source_ids": [
            "agpl-3.0-obligations",
            "lgpl-2.1-obligations",
            "permissive-notice",
        ],
        "checksums_verified": True,
        "external_write_performed": False,
    }
