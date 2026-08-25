"""Offline validation for repository-owned Google Cloud deployment inputs."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shlex
import tomllib
from pathlib import Path

import yaml

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from ip_risk_agent.gcp_contract import (
    API_SERVICE,
    API_SERVICE_ACCOUNT,
    ARTIFACT_REPOSITORY,
    CLOUD_BUILD_SOURCE_BUCKET,
    DEPLOY_SERVICE_ACCOUNT,
    DRIVE_SERVICE_ACCOUNT,
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
from ip_risk_agent.intelligence.license.reference_gate import CORPUS_SUBJECT_COVERAGE
from ip_risk_agent.persistence.core_firestore.schema import REQUIRED_COMPOSITE_INDEXES

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy"
TTL_COLLECTIONS = {
    "source_operational_oauth_states",
    "source_operational_device_challenges",
}
SCHEDULER_ROUTES = (
    "/internal/scheduler/drive-watch-renewal",
    "/internal/scheduler/drive-reconciliation",
    "/internal/scheduler/expired-state-cleanup",
    "/internal/scheduler/source-health-refresh",
    "/internal/scheduler/license-revalidation",
)
COMMON_ENVIRONMENT = {
    "APP_ENV",
    "APP_ROLE",
    "APP_PUBLIC_BASE_URL",
    "GCP_PROJECT_ID",
    "GCP_REGION",
    "FIRESTORE_DATABASE",
    "LOCAL_STAGING_BUCKET",
    "GOOGLE_DRIVE_SERVICE_ACCOUNT",
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
    "GOOGLE_DRIVE_WEBHOOK_BASE_URL",
    "DRIVE_WATCH_CHANNEL_TOKEN",
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
ROLE_EXCLUSIVE_ENVIRONMENT = API_ENVIRONMENT | WORKER_ENVIRONMENT | {
    "GEMINI_MODEL_ID",
    "RAG_REGION",
    "RAG_CORPUS_ID",
    "RAG_CORPUS_VERSION",
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
        root / "rag-corpus" / "manifest.yaml",
        root
        / "backend"
        / "src"
        / "ip_risk_agent"
        / "composition"
        / "scheduler_routes.py",
        root
        / "backend"
        / "src"
        / "ip_risk_agent"
        / "composition"
        / "production.py",
        root / "backend" / "src" / "ip_risk_agent" / "gcp" / "cloud_tasks.py",
    )
    for path in required:
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f"missing deployment input: {path.relative_to(root)}")

    if errors:
        return errors

    scheduler_source = (
        root
        / "backend"
        / "src"
        / "ip_risk_agent"
        / "composition"
        / "scheduler_routes.py"
    ).read_text("utf-8")
    scheduler_suffixes = tuple(
        route.removeprefix("/internal/scheduler") for route in SCHEDULER_ROUTES
    )
    if 'prefix="/internal/scheduler"' not in scheduler_source or any(
        f'@router.post("{suffix}"' not in scheduler_source
        for suffix in scheduler_suffixes
    ):
        errors.append(
            "production scheduler router does not expose the four canonical routes"
        )
    production_source = (
        root / "backend" / "src" / "ip_risk_agent" / "composition" / "production.py"
    ).read_text("utf-8")
    if (
        "ProductionSchedulerOperations(" not in production_source
        or "create_scheduler_router(" not in production_source
        or "extra_api_routers=(scheduler,)" not in production_source
    ):
        errors.append("production API composition does not mount SchedulerOperations")

    tasks_source = (
        root / "backend" / "src" / "ip_risk_agent" / "gcp" / "cloud_tasks.py"
    ).read_text("utf-8")
    if (
        '"/internal/tasks/analyze-change"' not in tasks_source
        or '{"change_event_id": change_event_id}' not in tasks_source
    ):
        errors.append("Cloud Tasks endpoint/payload contract mismatch")

    dockerfile = (root / "Dockerfile").read_text("utf-8")
    dockerignore = (root / ".dockerignore").read_text("utf-8").splitlines()
    required_docker_tokens = (
        "COPY --from=web /workspace/frontend/dist frontend/dist",
        "COPY backend backend",
        "COPY shared/contracts/python shared/contracts/python",
        "USER 10001:10001",
        "ip_risk_agent.main:create_app",
    )
    if any(token not in dockerfile for token in required_docker_tokens):
        errors.append("Dockerfile is missing a shared-image production invariant")
    image_environment = _docker_stage_environment(dockerfile, stage="runtime")
    leaked_role_environment = sorted(image_environment & ROLE_EXCLUSIVE_ENVIRONMENT)
    if leaked_role_environment:
        errors.append(
            "shared runtime image must not define role-exclusive environment: "
            + ", ".join(leaked_role_environment)
        )
    if ".venv" not in dockerignore or ".env.*" not in dockerignore:
        errors.append("Docker build context must exclude virtualenv and environment files")
    if any(line.startswith("!") and ".env" in line for line in dockerignore):
        errors.append("Docker build context must not re-include environment files")

    _validate_wheel_package_data(root, errors)
    _validate_rag_subject_coverage(root, errors)

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
    if actual != expected or len(actual) != 8 or len(indexes["indexes"]) != 8:
        errors.append(
            "composite index contract mismatch: expected exactly 8 canonical indexes"
        )

    ttl = {
        item["collectionGroup"]
        for item in indexes["fieldOverrides"]
        if item.get("fieldPath") == "expires_at" and item.get("ttl") is True
    }
    ttl_entries = [
        item
        for item in indexes["fieldOverrides"]
        if item.get("fieldPath") == "expires_at" and item.get("ttl") is True
    ]
    if ttl != TTL_COLLECTIONS or len(ttl_entries) != 2:
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

    optional_environment = cloud_run.get("optionalEnvironment", {})
    expected_optional = {
        "common": {"LOG_LEVEL"},
        "worker": {
            "GEMINI_MODEL_ID",
            "RAG_REGION",
            "RAG_CORPUS_ID",
            "RAG_CORPUS_VERSION",
            "PATENT_SEARCH_STRATEGY",
            "PATENT_COMPARE_STRATEGY",
            "KIPRIS_MAX_RPS",
        },
    }
    for role, expected_names in expected_optional.items():
        actual_names = set(optional_environment.get(role, ()))
        if actual_names != expected_names:
            errors.append(f"Cloud Run {role} optional environment mismatch")

    _validate_v2_namespace(deploy, cloud_run, errors)

    _validate_rag_corpus_manifest(root, errors)

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
        f"{IMAGE_NAME}@${{IMAGE_DIGEST}}"
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
    if services.get("worker", {}).get("ingress") != "internal":
        errors.append("Cloud Run Worker must use internal ingress")
    if services.get("api", {}).get("ingress") != "all":
        errors.append("Cloud Run API ingress contract mismatch")
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
            "GOOGLE_DRIVE_SERVICE_ACCOUNT": DRIVE_SERVICE_ACCOUNT,
            "GITHUB_APP_PRIVATE_KEY_SECRET_ID": FIXED_SECRET_IDS[
                "github_private_key"
            ],
            "SOURCE_CREDENTIAL_SECRET_PREFIX": DYNAMIC_CREDENTIAL_SECRET_PREFIX,
        },
        "api": {
            "APP_ROLE": "api",
            "FRONTEND_DIST_DIR": "/app/frontend/dist",
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
            "DRIVE_WATCH_CHANNEL_TOKEN": FIXED_SECRET_IDS["drive_channel"],
        },
        # D1 이후 worker 에는 Drive 비밀이 없다. 접근이 폴더 공유에서 오므로
        # 보관할 자격증명 자체가 없다.
        "worker": {},
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
    expected_build_identity = (
        f"projects/{PROJECT_ID}/serviceAccounts/{DEPLOY_SERVICE_ACCOUNT}"
    )
    if cloudbuild.get("serviceAccount") != expected_build_identity:
        errors.append("Cloud Build must execute as the canonical v2 deploy identity")
    if cloudbuild.get("options", {}).get("logging") != "CLOUD_LOGGING_ONLY":
        errors.append("user-specified Cloud Build identity requires CLOUD_LOGGING_ONLY")
    image_prefix = (
        f"${{_REGION}}-docker.pkg.dev/${{PROJECT_ID}}/"
        f"${{_REPOSITORY}}/${{_IMAGE}}:"
    )
    build_images = cloudbuild.get("images", [])
    if build_images != [image_prefix + "${SHORT_SHA}"]:
        errors.append("Cloud Build must publish only the commit-tagged v2 image")
    steps = {step.get("id"): step for step in cloudbuild.get("steps", ())}
    expected_smoke_imports = {
        "smoke-import-api": "from ip_risk_agent.main import create_app",
        "smoke-import-worker": "from ip_risk_agent.worker import create_app",
    }
    for step_id, import_statement in expected_smoke_imports.items():
        step = steps.get(step_id, {})
        args = step.get("args", [])
        if (
            step.get("name") != "gcr.io/cloud-builders/docker"
            or args[:4] != ["run", "--rm", "--entrypoint", "python"]
            or import_statement not in " ".join(str(arg) for arg in args)
        ):
            errors.append(f"Cloud Build {step_id} must run the locally built image")

    queue = yaml.safe_load((deploy / "cloud-tasks-queue.yaml").read_text("utf-8"))[
        "queue"
    ]
    if queue.get("name") != TASK_QUEUE or queue.get("location") != REGION:
        errors.append("Cloud Tasks queue violates the v2 namespace")

    scheduler = yaml.safe_load((deploy / "scheduler-jobs.yaml").read_text("utf-8"))
    if tuple(job.get("name") for job in scheduler.get("jobs", ())) != SCHEDULER_JOBS:
        errors.append("Cloud Scheduler jobs violate the v2 namespace")
    if tuple(job.get("path") for job in scheduler.get("jobs", ())) != SCHEDULER_ROUTES:
        errors.append("Cloud Scheduler jobs do not match the production routes")
    if any(
        job.get("body")
        != {"cursor": None, "limit": (500 if index == 2 else 100)}
        for index, job in enumerate(scheduler.get("jobs", ()))
    ):
        errors.append("Cloud Scheduler request bodies violate the bounded cursor contract")
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
        # D1 — 이 SA 를 가장할 수 있는 것은 두 실행 신원뿐이다. 사람이 여기 들어오면
        # 공유받은 폴더 전부를 사람이 읽을 수 있게 된다.
        "driveImpersonation": {
            "members": [API_SERVICE_ACCOUNT, WORKER_SERVICE_ACCOUNT]
        },
    }
    expected_roles = {
        "firestore": "roles/datastore.user",
        "taskEnqueue": "roles/cloudtasks.enqueuer",
        "taskCallerActAs": "roles/iam.serviceAccountUser",
        "workerInvoke": "roles/run.invoker",
        "schedulerInvoke": "roles/run.invoker",
        "stagingObjects": "roles/storage.objectUser",
        "artifactRepository": "roles/artifactregistry.writer",
        "driveImpersonation": "roles/iam.serviceAccountTokenCreator",
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
        binding.get("role")
        for group in (bindings, iam.get("buildBindings", {}))
        for binding in group.values()
        if isinstance(binding, dict)
    }
    forbidden = {"roles/owner", "roles/editor", "roles/secretmanager.admin"}
    if runtime_roles & forbidden:
        errors.append("IAM contract grants a forbidden broad runtime role")

    expected_build_bindings = {
        "buildLogs": {
            "role": "roles/logging.logWriter",
            "member": DEPLOY_SERVICE_ACCOUNT,
            "resource": f"projects/{PROJECT_ID}",
        },
        "buildSourceBucketRead": {
            "role": "roles/storage.objectViewer",
            "member": DEPLOY_SERVICE_ACCOUNT,
            "resource": f"projects/_/buckets/{CLOUD_BUILD_SOURCE_BUCKET}",
        },
        "buildServiceAgentToken": {
            "role": "roles/iam.serviceAccountTokenCreator",
            "member": (
                f"service-{PROJECT_NUMBER}@gcp-sa-cloudbuild.iam.gserviceaccount.com"
            ),
            "resource": (
                f"projects/{PROJECT_ID}/serviceAccounts/{DEPLOY_SERVICE_ACCOUNT}"
            ),
        },
    }
    if iam.get("buildBindings") != expected_build_bindings:
        errors.append("Cloud Build execution/logging/source IAM contract mismatch")

    dynamic = iam.get("dynamicCredentialPermissions", {})
    if dynamic.get("creator", {}).get("permissions") != [
        "secretmanager.secrets.create"
    ]:
        errors.append("dynamic credential creator must use the minimal create permission")
    expected_prefix = (
        f"projects/{PROJECT_NUMBER}/secrets/{DYNAMIC_CREDENTIAL_SECRET_PREFIX}-"
    )
    for name, permission in (
        ("versionManager", "secretmanager.versions.add"),
        ("accessor", "secretmanager.versions.access"),
        # workspace 삭제가 자격증명 secret 을 지운다. 이 권한이 없으면 지우기가
        # 권한 거부로 실패하고, eraser 가 그 실패를 올려 workspace 가 DELETING 에
        # 머문 채 영원히 재시도된다. create 와 달리 삭제는 존재하는 secret resource
        # 에 평가되므로 prefix condition 이 실제로 걸린다.
        ("deleter", "secretmanager.secrets.delete"),
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


_CORPUS_VERSION_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")


def _corpus_checksum(text: str) -> str:
    """``intelligence.rag.ingestion.checksum`` 과 같은 규칙.

    수집이 본문을 ``strip()`` 한 뒤 지문을 내므로 여기서도 그렇게 한다. 두 규칙이
    어긋나면 배포 검증은 통과하는데 수집이 거부한다.
    """
    return "sha256:" + hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _validate_rag_corpus_manifest(root: Path, errors: list[str]) -> None:
    """corpus 에 **검토된 자료만** 들어 있는지 확인한다.

    예전에는 "source_id 세 개가 정확히 이것이고 corpus_version 이 이 문자열" 로
    확인했다. 의도는 옳았지만 — 아무도 검토하지 않은 문서가 RAG 로 가면 안 된다 —
    수단이 **문서를 하나도 더할 수 없게** 만들었다. corpus 를 넓히는 것이 계획에
    들어 있으므로 목록을 고정하는 대신 **자료마다 성질을 확인한다.**

    그중 지문 대조가 가장 세다. 예전 검사는 파일 내용을 한 번도 보지 않았으므로
    manifest 에 적힌 세 이름만 맞으면 본문이 무엇으로 바뀌었든 통과했다. 지금은
    manifest 가 가리키는 것과 디스크에 있는 것이 같아야 한다 — 수집이 실제로
    거부하는 조건과 같은 조건을 배포 전에 본다.
    """
    manifest_path = root / "rag-corpus" / "manifest.yaml"
    if not manifest_path.is_file():
        errors.append("rag-corpus/manifest.yaml is missing")
        return

    document = yaml.safe_load(manifest_path.read_text("utf-8")) or {}
    version = document.get("corpus_version")
    if not isinstance(version, str) or not _CORPUS_VERSION_PATTERN.match(version):
        errors.append(
            "RAG corpus_version must look like YYYY-MM-DD.N, got %r" % (version,)
        )

    sources = document.get("sources") or []
    if not sources:
        errors.append("RAG corpus declares no sources")
        return

    corpus_root = (root / "rag-corpus").resolve()
    seen: set[str] = set()
    for source in sources:
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            errors.append("RAG corpus source is missing a source_id")
            continue
        if source_id in seen:
            errors.append(f"RAG corpus source_id is duplicated: {source_id}")
        seen.add(source_id)

        # 검토를 거치지 않은 자료는 들어오지 못한다. 이것이 원래 검사의 핵심이고
        # 그대로 남는다.
        if source.get("approved_for_rag") is not True:
            errors.append(f"RAG corpus source is not approved: {source_id}")

        relative = source.get("path")
        if not isinstance(relative, str) or not relative:
            errors.append(f"RAG corpus source has no path: {source_id}")
            continue
        target = (corpus_root / relative).resolve()
        if not target.is_relative_to(corpus_root):
            errors.append(f"RAG corpus source escapes rag-corpus/: {source_id}")
            continue
        if not target.is_file():
            errors.append(f"RAG corpus source file is missing: {relative}")
            continue

        # 파일 이름과 source_id 가 같아야 한다. 검색 결과의 `sourceDisplayName` 이
        # 둘 중 무엇으로 오는지 정해져 있지 않아서다 (`rag/engine.py`). 같게 두면
        # 어느 쪽이 오든 참조 게이트가 표에서 찾는다. 다르면 전문이 검색되어도
        # 게이트가 "관련 없음" 으로 버리고, 그 실패는 조용하다.
        if target.stem != source_id:
            errors.append(
                f"RAG corpus source_id must match its file name: {source_id} "
                f"vs {target.name}"
            )

        declared = source.get("checksum")
        actual = _corpus_checksum(target.read_text(encoding="utf-8"))
        if declared != actual:
            errors.append(
                f"RAG corpus checksum mismatch for {source_id}: "
                f"manifest says {declared}, file is {actual}"
            )


def _validate_rag_subject_coverage(root: Path, errors: list[str]) -> None:
    """corpus 가 다루는 라이선스와 게이트가 아는 라이선스가 같은지 확인한다.

    어긋나면 게이트가 조용히 잘못 판정한다 — 관련 문서를 버리거나, 더 나쁘게는 관련
    없는 문서를 통과시킨다.

    표가 있는 자리가 옮겨 가는 중이다. 원래는 ``reference_gate`` 안에 손으로 적혀
    있었다 — ``rag-corpus/`` 가 런타임 이미지에 없기 때문이었다. 지금은
    ``scripts/build_rag_corpus.py`` 가 매니페스트의 ``covers`` 에서 뽑아 wheel 에 실리는
    ``corpus_coverage.json`` 으로 낸다. 옮기는 동안 **셋이 모두 같아야 한다.**
    """
    manifest_path = root / "rag-corpus" / "manifest.yaml"
    if not manifest_path.is_file():
        return
    document = yaml.safe_load(manifest_path.read_text("utf-8")) or {}
    declared = {
        str(source["source_id"]): frozenset(source.get("covers") or ())
        for source in document.get("sources", ())
        if source.get("approved_for_rag")
    }

    empty = sorted(name for name, covers in declared.items() if not covers)
    if empty:
        errors.append(
            "approved RAG sources must declare the licenses they cover: "
            + ", ".join(empty)
        )

    index_path = (
        root
        / "backend"
        / "src"
        / "ip_risk_agent"
        / "intelligence"
        / "license"
        / "corpus_coverage.json"
    )
    if not index_path.is_file():
        errors.append(
            "corpus_coverage.json is missing; run scripts/build_rag_corpus.py"
        )
        return
    index = {
        name: frozenset(values)
        for name, values in json.loads(index_path.read_text("utf-8")).items()
    }
    if index != declared:
        errors.append(
            "corpus_coverage.json is stale against rag-corpus/manifest.yaml; "
            "run scripts/build_rag_corpus.py"
        )

    if CORPUS_SUBJECT_COVERAGE != index:
        only_code = sorted(set(CORPUS_SUBJECT_COVERAGE) - set(index))
        only_index = sorted(set(index) - set(CORPUS_SUBJECT_COVERAGE))
        errors.append(
            "RAG subject coverage mismatch: "
            "intelligence.license.reference_gate.CORPUS_SUBJECT_COVERAGE does not match "
            "corpus_coverage.json. The gate would ignore documents the corpus contains. "
            f"only in code: {only_code or '-'}; only in index: {only_index or '-'}"
        )


def _validate_wheel_package_data(root: Path, errors: list[str]) -> None:
    """코드가 아닌 runtime 자료 파일이 wheel 에 실리는지 정적으로 확인한다.

    Dockerfile 이 ``pip install .`` 로 wheel 을 설치하므로, ``.py`` 가 아닌 파일은
    ``[tool.setuptools.package-data]`` 에 선언하지 않으면 이미지에서 사라진다.
    소스로 실행하는 로컬·테스트에서는 파일이 그 자리에 있어 **절대 재현되지 않고**,
    배포에서만 ``FileNotFoundError`` 로 죽는다. Gemini 프롬프트가 실제로 그랬다.
    """
    pyproject = root / "pyproject.toml"
    source_root = root / "backend" / "src"
    package_root = source_root / "ip_risk_agent"
    if not pyproject.is_file() or not package_root.is_dir():
        return

    declared = (
        tomllib.loads(pyproject.read_text("utf-8"))
        .get("tool", {})
        .get("setuptools", {})
        .get("package-data", {})
    )
    patterns_by_package = {
        Path(*package.split(".")): tuple(patterns)
        for package, patterns in declared.items()
    }

    for path in sorted(package_root.rglob("*")):
        if not path.is_file() or path.suffix == ".py" or path.name == ".gitkeep":
            continue
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(source_root)
        patterns = patterns_by_package.get(relative.parent, ())
        if not any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns):
            errors.append(
                "runtime data file is not shipped in the wheel — declare it in "
                f"[tool.setuptools.package-data]: {relative.as_posix()}"
            )


def _docker_stage_environment(dockerfile: str, *, stage: str) -> set[str]:
    """Return ENV keys defined in one Dockerfile stage without executing Docker."""

    logical_lines = (
        dockerfile.replace("\\\r\n", " ").replace("\\\n", " ").splitlines()
    )
    in_stage = False
    environment: set[str] = set()
    for raw_line in logical_lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.upper().startswith("FROM "):
            parts = line.split()
            in_stage = (
                len(parts) >= 4
                and parts[-2].upper() == "AS"
                and parts[-1] == stage
            )
            continue
        if not in_stage or not line.upper().startswith("ENV "):
            continue
        tokens = shlex.split(line[4:].strip(), posix=True)
        if all("=" in token for token in tokens):
            environment.update(token.split("=", 1)[0] for token in tokens)
        elif tokens:
            environment.add(tokens[0])
    return environment


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
