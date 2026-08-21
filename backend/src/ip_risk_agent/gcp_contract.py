"""Canonical v2 resource namespace for the shared production GCP project."""

from __future__ import annotations

PROJECT_ID = "proj-aj22-211200020328"
PROJECT_NUMBER = "555102774494"
REGION = "asia-northeast3"

FIRESTORE_DATABASE = "ip-risk-agent-v2"
API_SERVICE = "ip-risk-agent-v2-api"
WORKER_SERVICE = "ip-risk-agent-v2-worker"
WORKER_BASE_URL = (
    f"https://{WORKER_SERVICE}-{PROJECT_NUMBER}.{REGION}.run.app"
)
TASK_QUEUE = "ip-risk-agent-v2-analysis-changes"
ARTIFACT_REPOSITORY = "ip-risk-agent-v2"
IMAGE_NAME = "application"
CLOUD_BUILD_SOURCE_BUCKET = f"{PROJECT_ID}_cloudbuild"
STAGING_BUCKET = f"{PROJECT_ID}-iprisk-v2-staging"
RAG_CORPUS_DISPLAY_NAME = "ip-risk-agent-v2-legal-reference"

API_SERVICE_ACCOUNT_ID = "iprisk-v2-api"
WORKER_SERVICE_ACCOUNT_ID = "iprisk-v2-worker"
TASKS_SERVICE_ACCOUNT_ID = "iprisk-v2-tasks"
SCHEDULER_SERVICE_ACCOUNT_ID = "iprisk-v2-scheduler"
DEPLOY_SERVICE_ACCOUNT_ID = "iprisk-v2-deploy"

SCHEDULER_JOBS = (
    "ip-risk-agent-v2-drive-watch-renewal",
    "ip-risk-agent-v2-drive-reconciliation",
    "ip-risk-agent-v2-expired-state-cleanup",
    "ip-risk-agent-v2-source-health-refresh",
)

FIXED_SECRET_IDS = {
    "session": "iprisk-v2-session-secret",
    "google_login_client": "iprisk-v2-google-login-client-secret",
    "drive_client": "iprisk-v2-drive-client-secret",
    "drive_channel": "iprisk-v2-drive-channel-token",
    "github_private_key": "iprisk-v2-github-private-key",
    "github_webhook": "iprisk-v2-github-webhook-secret",
    "kipris": "iprisk-v2-kipris-access-key",
}
DYNAMIC_CREDENTIAL_SECRET_PREFIX = "iprisk-v2-cred"


def service_account_email(account_id: str) -> str:
    return f"{account_id}@{PROJECT_ID}.iam.gserviceaccount.com"


API_SERVICE_ACCOUNT = service_account_email(API_SERVICE_ACCOUNT_ID)
WORKER_SERVICE_ACCOUNT = service_account_email(WORKER_SERVICE_ACCOUNT_ID)
TASKS_SERVICE_ACCOUNT = service_account_email(TASKS_SERVICE_ACCOUNT_ID)
SCHEDULER_SERVICE_ACCOUNT = service_account_email(SCHEDULER_SERVICE_ACCOUNT_ID)
DEPLOY_SERVICE_ACCOUNT = service_account_email(DEPLOY_SERVICE_ACCOUNT_ID)


__all__ = [
    "API_SERVICE",
    "API_SERVICE_ACCOUNT",
    "ARTIFACT_REPOSITORY",
    "CLOUD_BUILD_SOURCE_BUCKET",
    "DEPLOY_SERVICE_ACCOUNT",
    "DYNAMIC_CREDENTIAL_SECRET_PREFIX",
    "FIRESTORE_DATABASE",
    "FIXED_SECRET_IDS",
    "IMAGE_NAME",
    "PROJECT_ID",
    "PROJECT_NUMBER",
    "RAG_CORPUS_DISPLAY_NAME",
    "REGION",
    "SCHEDULER_JOBS",
    "SCHEDULER_SERVICE_ACCOUNT",
    "STAGING_BUCKET",
    "TASK_QUEUE",
    "TASKS_SERVICE_ACCOUNT",
    "WORKER_SERVICE",
    "WORKER_BASE_URL",
    "WORKER_SERVICE_ACCOUNT",
]
