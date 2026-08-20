"""Offline validation for repository-owned Google Cloud deployment inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from ip_risk_agent.gcp_contract import (
    API_SERVICE,
    API_SERVICE_ACCOUNT,
    ARTIFACT_REPOSITORY,
    DEPLOY_SERVICE_ACCOUNT,
    DYNAMIC_CREDENTIAL_SECRET_PREFIX,
    FIRESTORE_DATABASE,
    FIXED_SECRET_IDS,
    IMAGE_NAME,
    PROJECT_ID,
    PROJECT_NUMBER,
    RAG_CORPUS_DISPLAY_NAME,
    REGION,
    SCHEDULER_JOBS,
    SCHEDULER_SERVICE_ACCOUNT,
    STAGING_BUCKET,
    TASK_QUEUE,
    TASKS_SERVICE_ACCOUNT,
    WORKER_SERVICE,
    WORKER_BASE_URL,
    WORKER_SERVICE_ACCOUNT,
)
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
    "SOURCE_CREDENTIAL_SECRET_PREFIX",
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
        deploy / "v2-resource-contract.yaml",
        deploy / "iam-policy-contract.yaml",
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
        "v2-resource-contract.yaml",
        "iam-policy-contract.yaml",
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

    _validate_v2_namespace(deploy, cloud_run, errors)

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


def _validate_v2_namespace(deploy: Path, cloud_run: dict, errors: list[str]) -> None:
    contract = yaml.safe_load((deploy / "v2-resource-contract.yaml").read_text("utf-8"))
    expected_contract = {
        "contractVersion": 2,
        "project": {"id": PROJECT_ID, "number": PROJECT_NUMBER, "region": REGION},
        "firestore": {"database": FIRESTORE_DATABASE},
        "cloudRun": {"api": API_SERVICE, "worker": WORKER_SERVICE},
        "cloudTasks": {"queue": TASK_QUEUE},
        "artifactRegistry": {
            "repository": ARTIFACT_REPOSITORY,
            "image": IMAGE_NAME,
        },
        "serviceAccounts": {
            "api": API_SERVICE_ACCOUNT,
            "worker": WORKER_SERVICE_ACCOUNT,
            "tasks": TASKS_SERVICE_ACCOUNT,
            "scheduler": SCHEDULER_SERVICE_ACCOUNT,
            "deploy": DEPLOY_SERVICE_ACCOUNT,
        },
        "schedulerJobs": list(SCHEDULER_JOBS),
        "storage": {"stagingBucket": STAGING_BUCKET},
        "secrets": {
            "fixed": {
                "session": FIXED_SECRET_IDS["session"],
                "googleLoginClient": FIXED_SECRET_IDS["google_login_client"],
                "driveClient": FIXED_SECRET_IDS["drive_client"],
                "driveChannel": FIXED_SECRET_IDS["drive_channel"],
                "githubPrivateKey": FIXED_SECRET_IDS["github_private_key"],
                "githubWebhook": FIXED_SECRET_IDS["github_webhook"],
                "kipris": FIXED_SECRET_IDS["kipris"],
            },
            "dynamicCredentialPrefix": DYNAMIC_CREDENTIAL_SECRET_PREFIX,
        },
        "rag": {"corpusDisplayName": RAG_CORPUS_DISPLAY_NAME},
    }
    if contract != expected_contract:
        errors.append("v2 resource contract does not match the canonical shared-project namespace")

    services = cloud_run.get("services", {})
    expected_image = (
        f"{REGION}-docker.pkg.dev/{PROJECT_ID}/{ARTIFACT_REPOSITORY}/"
        f"{IMAGE_NAME}:${{IMAGE_TAG}}"
    )
    expected_services = {
        "api": (API_SERVICE, API_SERVICE_ACCOUNT, True),
        "worker": (WORKER_SERVICE, WORKER_SERVICE_ACCOUNT, False),
    }
    for role, (name, account, unauthenticated) in expected_services.items():
        service = services.get(role, {})
        if service.get("name") != name:
            errors.append(f"Cloud Run {role} must use v2 service name {name}")
        if service.get("serviceAccount") != account:
            errors.append(f"Cloud Run {role} must use v2 service account {account}")
        if service.get("image") != expected_image:
            errors.append(f"Cloud Run {role} must use canonical v2 application image")
        if service.get("allowUnauthenticated") is not unauthenticated:
            errors.append(f"Cloud Run {role} authentication policy mismatch")
    if services.get("api", {}).get("image") != services.get("worker", {}).get("image"):
        errors.append("API and Worker must use the same immutable image contract")

    canonical_environment = cloud_run.get("canonicalEnvironment", {})
    expected_canonical_environment = {
        "common": {
            "APP_ENV": "production",
            "GCP_PROJECT_ID": PROJECT_ID,
            "GCP_REGION": REGION,
            "FIRESTORE_DATABASE": FIRESTORE_DATABASE,
            "LOCAL_STAGING_BUCKET": STAGING_BUCKET,
            "GITHUB_APP_PRIVATE_KEY_SECRET_ID": FIXED_SECRET_IDS[
                "github_private_key"
            ],
            "SOURCE_CREDENTIAL_SECRET_PREFIX": DYNAMIC_CREDENTIAL_SECRET_PREFIX,
        },
        "api": {
            "APP_ROLE": "api",
            "GOOGLE_CLOUD_PROJECT_NUMBER": PROJECT_NUMBER,
            "GITHUB_WEBHOOK_SECRET_ID": FIXED_SECRET_IDS["github_webhook"],
            "CLOUD_TASKS_LOCATION": REGION,
            "CLOUD_TASKS_QUEUE": TASK_QUEUE,
            "CLOUD_TASKS_SERVICE_ACCOUNT": TASKS_SERVICE_ACCOUNT,
            "ANALYSIS_WORKER_URL": WORKER_BASE_URL,
            "SCHEDULER_SERVICE_ACCOUNT": SCHEDULER_SERVICE_ACCOUNT,
        },
        "worker": {
            "APP_ROLE": "worker",
            "APP_PUBLIC_BASE_URL": WORKER_BASE_URL,
            "KIPRIS_API_KEY_SECRET_ID": FIXED_SECRET_IDS["kipris"],
        },
    }
    if canonical_environment != expected_canonical_environment:
        errors.append("Cloud Run canonical environment violates the v2 namespace")

    expected_secret_environment = {
        "api": {
            "SESSION_SECRET": FIXED_SECRET_IDS["session"],
            "GOOGLE_LOGIN_CLIENT_SECRET": FIXED_SECRET_IDS[
                "google_login_client"
            ],
            "GOOGLE_DRIVE_CLIENT_SECRET": FIXED_SECRET_IDS["drive_client"],
            "DRIVE_WATCH_CHANNEL_TOKEN": FIXED_SECRET_IDS["drive_channel"],
        },
        "worker": {
            "GOOGLE_DRIVE_CLIENT_SECRET": FIXED_SECRET_IDS["drive_client"],
        },
    }
    if cloud_run.get("secretEnvironment") != expected_secret_environment:
        errors.append("Cloud Run fixed secret mapping violates the v2 namespace")

    cloudbuild = yaml.safe_load((deploy / "cloudbuild.yaml").read_text("utf-8"))
    substitutions = cloudbuild.get("substitutions", {})
    if substitutions.get("_REGION") != REGION:
        errors.append("Cloud Build region must use the canonical v2 region")
    if substitutions.get("_REPOSITORY") != ARTIFACT_REPOSITORY:
        errors.append("Cloud Build must not use the legacy Artifact Registry repository")
    if substitutions.get("_IMAGE") != IMAGE_NAME:
        errors.append("Cloud Build image name contract mismatch")

    queue = yaml.safe_load((deploy / "cloud-tasks-queue.yaml").read_text("utf-8"))[
        "queue"
    ]
    if queue.get("name") != TASK_QUEUE or queue.get("location") != REGION:
        errors.append("Cloud Tasks queue violates the v2 namespace")

    scheduler = yaml.safe_load((deploy / "scheduler-jobs.yaml").read_text("utf-8"))
    if tuple(job.get("name") for job in scheduler.get("jobs", ())) != SCHEDULER_JOBS:
        errors.append("Cloud Scheduler jobs violate the v2 namespace")
    defaults = scheduler.get("defaults", {})
    if defaults.get("serviceAccountEmail") != "${SCHEDULER_SERVICE_ACCOUNT}":
        errors.append("Cloud Scheduler caller service account contract mismatch")

    iam = yaml.safe_load((deploy / "iam-policy-contract.yaml").read_text("utf-8"))
    _validate_iam_contract(iam, errors)


def _validate_iam_contract(iam: dict, errors: list[str]) -> None:
    bindings = iam.get("runtimeBindings", {})
    expected_resources = {
        "firestore": f"projects/{PROJECT_ID}/databases/{FIRESTORE_DATABASE}",
        "taskEnqueue": (
            f"projects/{PROJECT_ID}/locations/{REGION}/queues/{TASK_QUEUE}"
        ),
        "taskCallerActAs": (
            f"projects/{PROJECT_ID}/serviceAccounts/{TASKS_SERVICE_ACCOUNT}"
        ),
        "workerInvoke": (
            f"projects/{PROJECT_ID}/locations/{REGION}/services/{WORKER_SERVICE}"
        ),
        "schedulerInvoke": (
            f"projects/{PROJECT_ID}/locations/{REGION}/services/{API_SERVICE}"
        ),
        "stagingObjects": f"projects/_/buckets/{STAGING_BUCKET}",
        "artifactRepository": (
            f"projects/{PROJECT_ID}/locations/{REGION}/repositories/"
            f"{ARTIFACT_REPOSITORY}"
        ),
    }
    for name, expected in expected_resources.items():
        binding = bindings.get(name, {})
        actual = (
            _condition_resource(binding.get("condition", {}).get("expression"))
            if name == "firestore"
            else binding.get("resource")
        )
        if actual != expected:
            errors.append(f"IAM {name} binding is not scoped to its v2 resource")

    expected_principals = {
        "firestore": {"members": [API_SERVICE_ACCOUNT, WORKER_SERVICE_ACCOUNT]},
        "taskEnqueue": {"member": API_SERVICE_ACCOUNT},
        "taskCallerActAs": {"member": API_SERVICE_ACCOUNT},
        "workerInvoke": {"member": TASKS_SERVICE_ACCOUNT},
        "schedulerInvoke": {"member": SCHEDULER_SERVICE_ACCOUNT},
        "stagingObjects": {
            "members": [API_SERVICE_ACCOUNT, WORKER_SERVICE_ACCOUNT]
        },
        "artifactRepository": {"member": DEPLOY_SERVICE_ACCOUNT},
    }
    expected_roles = {
        "firestore": "roles/datastore.user",
        "taskEnqueue": "roles/cloudtasks.enqueuer",
        "taskCallerActAs": "roles/iam.serviceAccountUser",
        "workerInvoke": "roles/run.invoker",
        "schedulerInvoke": "roles/run.invoker",
        "stagingObjects": "roles/storage.objectUser",
        "artifactRepository": "roles/artifactregistry.writer",
    }
    for name, principals in expected_principals.items():
        binding = bindings.get(name, {})
        if binding.get("role") != expected_roles[name] or any(
            binding.get(field) != value for field, value in principals.items()
        ):
            errors.append(f"IAM {name} role/principal contract mismatch")

    vertex = bindings.get("vertexRag", {})
    if (
        vertex.get("role") != "roles/aiplatform.user"
        or vertex.get("member") != WORKER_SERVICE_ACCOUNT
        or vertex.get("project") != PROJECT_ID
        or vertex.get("corpusDisplayName") != RAG_CORPUS_DISPLAY_NAME
    ):
        errors.append("Worker Vertex/RAG IAM contract is not v2-scoped")

    expected_fixed_access = {
        FIXED_SECRET_IDS["session"]: [API_SERVICE_ACCOUNT],
        FIXED_SECRET_IDS["google_login_client"]: [API_SERVICE_ACCOUNT],
        FIXED_SECRET_IDS["drive_client"]: [
            API_SERVICE_ACCOUNT,
            WORKER_SERVICE_ACCOUNT,
        ],
        FIXED_SECRET_IDS["drive_channel"]: [API_SERVICE_ACCOUNT],
        FIXED_SECRET_IDS["github_private_key"]: [
            API_SERVICE_ACCOUNT,
            WORKER_SERVICE_ACCOUNT,
        ],
        FIXED_SECRET_IDS["github_webhook"]: [API_SERVICE_ACCOUNT],
        FIXED_SECRET_IDS["kipris"]: [WORKER_SERVICE_ACCOUNT],
    }
    if iam.get("fixedSecretAccess") != expected_fixed_access:
        errors.append("fixed Secret Manager access matrix violates the v2 role contract")

    runtime_roles = {
        binding.get("role") for binding in bindings.values() if isinstance(binding, dict)
    }
    forbidden = {"roles/owner", "roles/editor", "roles/secretmanager.admin"}
    if runtime_roles & forbidden:
        errors.append("IAM contract grants a forbidden broad runtime role")

    dynamic = iam.get("dynamicCredentialPermissions", {})
    if dynamic.get("creator", {}).get("permissions") != [
        "secretmanager.secrets.create"
    ]:
        errors.append("dynamic credential creator must use the minimal create permission")
    expected_prefix = f"projects/{PROJECT_ID}/secrets/{DYNAMIC_CREDENTIAL_SECRET_PREFIX}-"
    for name, permission in (
        ("versionManager", "secretmanager.versions.add"),
        ("accessor", "secretmanager.versions.access"),
    ):
        entry = dynamic.get(name, {})
        if entry.get("conditionPrefix") != expected_prefix:
            errors.append(f"dynamic credential {name} condition uses a non-v2 prefix")
        if entry.get("conditionExpression") != (
            f'resource.name.startsWith("{expected_prefix}")'
        ):
            errors.append(
                f"dynamic credential {name} IAM condition expression mismatch"
            )
        if entry.get("permissions") != [permission]:
            errors.append(f"dynamic credential {name} permissions mismatch")
    if dynamic.get("disable") != {"members": [], "permissions": []}:
        errors.append("unused dynamic credential disable permission must not be granted")


def _condition_resource(expression: object) -> str | None:
    if not isinstance(expression, str):
        return None
    prefix = 'resource.name == "'
    if not expression.startswith(prefix) or not expression.endswith('"'):
        return None
    return expression[len(prefix) : -1]


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
