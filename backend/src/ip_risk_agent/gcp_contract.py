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
#: D1 — 사용자가 이 신원에 폴더를 공유하면 그 안이 보인다. **프로젝트 역할이 0 이다.**
#: 접근이 공유에서만 오므로 역할이 필요 없고, 역할이 없으므로 이 신원이 새더라도
#: 우리 데이터에 닿지 않는다. api·worker 가 이 SA 하나에 대한 가장 권한만 갖는다.
DRIVE_SERVICE_ACCOUNT_ID = "iprisk-v2-drive"
DEPLOY_SERVICE_ACCOUNT_ID = "iprisk-v2-deploy"

SCHEDULER_JOBS = (
    "ip-risk-agent-v2-drive-watch-renewal",
    "ip-risk-agent-v2-drive-reconciliation",
    "ip-risk-agent-v2-expired-state-cleanup",
    "ip-risk-agent-v2-source-health-refresh",
    # 외부 사실 변화를 촉발하는 유일한 것 (§7.6 · 결함 24).
    "ip-risk-agent-v2-license-revalidation",
)

FIXED_SECRET_IDS = {
    "session": "iprisk-v2-session-secret",
    "google_login_client": "iprisk-v2-google-login-client-secret",
    "drive_channel": "iprisk-v2-drive-channel-token",
    "github_private_key": "iprisk-v2-github-private-key",
    "github_webhook": "iprisk-v2-github-webhook-secret",
    "kipris": "iprisk-v2-kipris-access-key",
}
DYNAMIC_CREDENTIAL_SECRET_PREFIX = "iprisk-v2-cred"

#: 분석을 큐에 넣고 실제로 시작하기까지 미루는 시간(초).
#:
#: 문서를 한 번 고쳐도 Drive 는 판본을 여럿 만들고 알림도 여럿 보낸다. 그때마다
#: 분석이 따로 돌면 마지막 하나만 살아남고 나머지는 KIPRIS 와 모델 호출을 쓴 뒤
#: 버려진다. 실제로 한 번의 편집에서 분석 네 개가 돌아 18 회를 썼다.
#:
#: 미뤄 두면 그 사이에 뒤엣것이 도착하고, 앞엣것은 시작 직전 검사에서 밀린 것을
#: 알아 아무 값도 치르지 않는다. 대가는 감지에서 분석까지의 지연이 그만큼 는다는
#: 것이다. 분석 자체가 1~2 분 걸리므로 이 정도는 체감되지 않는다.
ANALYSIS_COALESCE_DELAY_SECONDS = 45


def service_account_email(account_id: str) -> str:
    return f"{account_id}@{PROJECT_ID}.iam.gserviceaccount.com"


API_SERVICE_ACCOUNT = service_account_email(API_SERVICE_ACCOUNT_ID)
WORKER_SERVICE_ACCOUNT = service_account_email(WORKER_SERVICE_ACCOUNT_ID)
TASKS_SERVICE_ACCOUNT = service_account_email(TASKS_SERVICE_ACCOUNT_ID)
SCHEDULER_SERVICE_ACCOUNT = service_account_email(SCHEDULER_SERVICE_ACCOUNT_ID)
DRIVE_SERVICE_ACCOUNT = service_account_email(DRIVE_SERVICE_ACCOUNT_ID)
DEPLOY_SERVICE_ACCOUNT = service_account_email(DEPLOY_SERVICE_ACCOUNT_ID)


__all__ = [
    "ANALYSIS_COALESCE_DELAY_SECONDS",
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
    "DRIVE_SERVICE_ACCOUNT",
    "SCHEDULER_SERVICE_ACCOUNT",
    "STAGING_BUCKET",
    "TASK_QUEUE",
    "TASKS_SERVICE_ACCOUNT",
    "WORKER_SERVICE",
    "WORKER_BASE_URL",
    "WORKER_SERVICE_ACCOUNT",
]
