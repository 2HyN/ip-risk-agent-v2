"""Offline validation for repository-owned Google Cloud deployment inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from ip_risk_agent.persistence.core_firestore.schema import REQUIRED_COMPOSITE_INDEXES

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
TTL_COLLECTIONS = {
    "source_operational_oauth_states",
    "source_operational_pending_connections",
    "source_operational_device_challenges",
}
COMMON_ENVIRONMENT = {
    "APP_ENV",
    "APP_ROLE",
    "APP_PUBLIC_BASE_URL",
    "GCP_PROJECT_ID",
    "GCP_REGION",
    "FIRESTORE_DATABASE",
    "LOCAL_STAGING_BUCKET",
    "GOOGLE_DRIVE_CLIENT_ID",
    "GOOGLE_DRIVE_CLIENT_SECRET",
    "GITHUB_APP_ID",
    "GITHUB_APP_PRIVATE_KEY_SECRET_ID",
}
API_ENVIRONMENT = {
    "SESSION_SECRET",
    "FRONTEND_DIST_DIR",
    "GOOGLE_LOGIN_CLIENT_ID",
    "GOOGLE_LOGIN_CLIENT_SECRET",
    "GOOGLE_LOGIN_REDIRECT_URI",
    "GOOGLE_DRIVE_REDIRECT_URI",
    "GOOGLE_DRIVE_WEBHOOK_BASE_URL",
    "DRIVE_WATCH_CHANNEL_TOKEN",
    "GOOGLE_PICKER_API_KEY",
    "GOOGLE_CLOUD_PROJECT_NUMBER",
    "GITHUB_APP_SLUG",
    "GITHUB_WEBHOOK_SECRET_ID",
    "GITHUB_APP_CALLBACK_URL",
    "CLOUD_TASKS_LOCATION",
    "CLOUD_TASKS_QUEUE",
    "ANALYSIS_WORKER_URL",
    "CLOUD_TASKS_SERVICE_ACCOUNT",
    "SCHEDULER_SERVICE_ACCOUNT",
}
WORKER_ENVIRONMENT = {
    "ANALYSIS_WORKER_URL",
    "CLOUD_TASKS_SERVICE_ACCOUNT",
    "VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG",
    "KIPRIS_API_KEY_SECRET_ID",
    "PACKAGE_METADATA_BASE_URL",
}


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    deploy = root / "deploy"
    required = (
        root / "Dockerfile",
        root / ".dockerignore",
        deploy / "cloudbuild.yaml",
        deploy / "cloud-run-services.yaml",
        deploy / "cloud-tasks-queue.yaml",
        deploy / "scheduler-jobs.yaml",
        deploy / "firestore.indexes.json",
        deploy / "storage-lifecycle.json",
    )
    for path in required:
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"missing deployment input: {path.relative_to(root)}")

    if errors:
        return errors

    indexes = json.loads((deploy / "firestore.indexes.json").read_text("utf-8"))
    actual = {
        (
            item["collectionGroup"],
            tuple(field["fieldPath"] for field in item["fields"]),
        )
        for item in indexes["indexes"]
    }
    expected = {
        (item.collection, item.fields)
        for item in REQUIRED_COMPOSITE_INDEXES
        if len(item.fields) > 1
    }
    expected.add(
        (
            "source_operational_github_tracking",
            ("record.owner", "record.repo"),
        )
    )
    missing_indexes = sorted(expected - actual)
    if missing_indexes:
        errors.append(f"missing canonical composite indexes: {missing_indexes}")

    ttl = {
        item["collectionGroup"]
        for item in indexes["fieldOverrides"]
        if item.get("fieldPath") == "expires_at" and item.get("ttl") is True
    }
    if ttl != TTL_COLLECTIONS:
        errors.append(f"TTL collection mismatch: expected {sorted(TTL_COLLECTIONS)}")

    for name in (
        "cloudbuild.yaml",
        "cloud-run-services.yaml",
        "cloud-tasks-queue.yaml",
        "scheduler-jobs.yaml",
    ):
        document = yaml.safe_load((deploy / name).read_text("utf-8"))
        if not isinstance(document, dict) or not document:
            errors.append(f"{name} must contain a non-empty mapping")

    cloud_run = yaml.safe_load((deploy / "cloud-run-services.yaml").read_text("utf-8"))
    required_environment = cloud_run.get("requiredEnvironment", {})
    expected_environment = {
        "common": COMMON_ENVIRONMENT,
        "api": API_ENVIRONMENT,
        "worker": WORKER_ENVIRONMENT,
    }
    for role, expected_names in expected_environment.items():
        actual_names = set(required_environment.get(role, ()))
        if actual_names != expected_names:
            errors.append(
                f"Cloud Run {role} environment mismatch: "
                f"expected {sorted(expected_names)}, got {sorted(actual_names)}"
            )

    lifecycle = json.loads((deploy / "storage-lifecycle.json").read_text("utf-8"))
    rules = lifecycle.get("lifecycle", {}).get("rule", [])
    deletes_staging = any(
        rule.get("action", {}).get("type") == "Delete"
        and "staging/" in rule.get("condition", {}).get("matchesPrefix", [])
        for rule in rules
    )
    if not deletes_staging:
        errors.append("storage lifecycle must delete staging/ objects")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = validate(args.root.resolve())
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("GCP deployment inputs: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
