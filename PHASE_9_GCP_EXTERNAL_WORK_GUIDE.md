# Phase 9 GCP 외부 작업 가이드

> 성격: **삭제 가능한 비규범적 실행 체크리스트**
> 작성일: 2026-08-21
> 대상 Release Candidate: `e05ad90583f0c3c35363fd02dcb64c399c522afc`

이 문서는 GCP Console, Google Cloud Shell, Google OAuth Console, GitHub 설정 화면처럼
저장소 밖에서 수행하는 Phase 9 작업을 단계별로 안내하고 실행 증거를 임시로 기록한다.
프로젝트의 실행, build, test 또는 배포는 이 문서에 의존하지 않는다. Phase 9 종료 후
삭제해도 프로젝트 완결성에 영향이 없다.

규범적 배포 계약과 검증 기준은 다음 유지 문서가 우선한다.

- `INTEGRATION_V2_DEPENDENCY_BASELINE.md`
- `INTEGRATION_V2_EXECUTION_PLAN.md`
- `docs/GCP_INTERNAL_DEPLOYMENT.md`
- `docs/STAGING_VERIFICATION_RUNBOOK.md`
- `deploy/*`

## 0. 반드시 지킬 원칙

1. 첫 배포는 production이 아닌 **전용 staging project**에서 수행한다.
2. 현재 RC SHA에서 image를 만들고 **tag가 아닌 digest**로 API와 Worker를 배포한다.
3. 서비스 계정 JSON key를 만들지 않는다. Cloud Run attached service account와 OIDC를
   사용한다.
4. secret 값, OAuth token, private key, webhook secret, KIPRIS key, 원문과 로컬 절대
   경로를 이 문서·ticket·screenshot·build log에 기록하지 않는다.
5. API, Worker, Cloud Tasks caller, Scheduler caller, Deploy identity를 재사용하지 않는다.
6. 각 단계의 확인란과 비민감 resource ID를 채운 뒤 다음 단계로 이동한다.
7. 권한 없는 호출 성공, raw content/credential 노출, readiness 실패가 발생하면 즉시
   중단하고 §17의 rollback 절차를 따른다.

## 1. 작업 입력표

secret **값은 절대 적지 않고** 이름과 version 번호만 기록한다.

| 항목 | 확정값 |
|---|---|
| 실행 승인자 / 승인 시각 | |
| staging `PROJECT_ID` / project number | |
| billing account 연결 확인 | |
| application region | `asia-northeast3` 또는 확정값: |
| Vertex RAG 지원 region | |
| Firestore database ID | |
| Artifact Registry repository | `ip-risk-agent` 또는 확정값: |
| RC SHA | `e05ad90583f0c3c35363fd02dcb64c399c522afc` |
| image URI@digest | |
| API / Worker service account | |
| Tasks / Scheduler caller service account | |
| Deploy service account | |
| staging bucket | |
| Cloud Tasks queue / location | `analysis-changes` / |
| Worker URL / revision | |
| API URL / revision | |
| custom domain | |
| RAG corpus ID / version | / `2026-08-14.1` |
| Google OAuth client IDs | login: / Drive: |
| GitHub App ID / slug | |
| 직전 안정 API / Worker revision | |

### 외부 작업 시작 전 필수 입력

- [ ] staging project와 billing이 승인됐다.
- [ ] Console 작업자에게 필요한 관리자 권한이 시간 제한 또는 staging 범위로 부여됐다.
- [ ] OAuth test user, GitHub test organization/repository, KIPRIS staging key가 준비됐다.
- [ ] 공개 HTTPS domain 또는 우선 사용할 Cloud Run `run.app` URL 정책을 확정했다.
- [ ] 비용 한도와 budget alert를 설정했다.

위 입력이 없으면 resource를 만들지 말고 여기서 중단한다.

## 2. RC와 repository gate 재확인

Cloud Shell 또는 Docker/gcloud가 설치된 승인된 배포 host에 정확히 RC SHA를 checkout한다.
아래 repository 검증을 먼저 통과시킨다.

```powershell
git rev-parse HEAD
python -m compileall -q backend/src shared/contracts/python scripts
python -m pip check
python -m pytest shared/contracts/tests tests/control tests/connectors tests/intelligence tests/integration tests/e2e -m "not live"
pnpm install --frozen-lockfile
pnpm run generate
git diff --exit-code -- shared/contracts
pnpm run typecheck
pnpm run build
pnpm run verify:resolution
pnpm --filter @iprisk/frontend test
pnpm --filter @iprisk/desktop test
python scripts/validate_gcp_deployment.py
python scripts/prepare_rag_ingestion.py
```

- [ ] 출력 SHA가 입력표의 RC SHA와 정확히 같다.
- [ ] 모든 non-live gate가 통과했다.
- [ ] `git status --short`가 비어 있다.
- [ ] RAG dry-run이 3개 승인 문서와 checksum 일치를 보고했다.

## 3. project와 API 준비

Console에서 project selector로 staging project를 고정하고 **Billing**에서 연결 상태를
확인한다. 이어서 **APIs & Services → Library**에서 아래 API를 검색해 활성화한다.

- Artifact Registry API: `artifactregistry.googleapis.com`
- Cloud Build API: `cloudbuild.googleapis.com`
- Cloud Run Admin API: `run.googleapis.com`
- Firestore API: `firestore.googleapis.com`
- Secret Manager API: `secretmanager.googleapis.com`
- Cloud Tasks API: `cloudtasks.googleapis.com`
- Cloud Scheduler API: `cloudscheduler.googleapis.com`
- IAM 및 IAM Service Account Credentials API
- Vertex AI API: `aiplatform.googleapis.com`
- Google Drive API와 Google Picker API
- Cloud Logging API와 Cloud Monitoring API

API 활성화 작업자는 `roles/serviceusage.serviceUsageAdmin` 또는 동등한
`serviceusage.services.enable` 권한이 필요하다.

- [ ] 활성 project ID를 다시 확인했다.
- [ ] 위 API가 모두 Enabled 상태다.
- [ ] project budget alert가 설정됐다.

## 4. service account와 IAM

**IAM & Admin → Service Accounts → Create service account**에서 다음 5개 계정을 만든다.
`Create key`는 누르지 않는다.

| 권장 ID | 사용 위치 | 부여할 최소 권한 |
|---|---|---|
| `iprisk-api` | API Cloud Run | Firestore User, queue 한정 Cloud Tasks Enqueuer, staging bucket Storage Object User, 필요한 Secret 접근/버전 관리 |
| `iprisk-worker` | Worker Cloud Run | Firestore User, staging bucket Storage Object User, Vertex AI User, 필요한 Secret Accessor |
| `iprisk-tasks` | Cloud Tasks OIDC | Worker service의 Cloud Run Invoker만 |
| `iprisk-scheduler` | Scheduler OIDC | API service의 Cloud Run Invoker만 |
| `iprisk-deploy` | build/deploy | Artifact Registry write, Cloud Build 실행, Cloud Run/queue/scheduler/index 배포와 위 runtime SA에 대한 제한된 act-as |

세부 적용 순서:

1. API/Worker에 project 범위 `roles/datastore.user`를 부여한다.
2. API에 `roles/cloudtasks.enqueuer`를 가능하면 `analysis-changes` queue 범위로 부여한다.
3. API에 `iprisk-tasks` 계정에 대한 `roles/iam.serviceAccountUser`를 부여한다.
4. API/Worker에 staging bucket 범위 `roles/storage.objectUser`를 부여한다.
5. Worker에 `roles/aiplatform.user`를 부여한다.
6. secret별로 API/Worker에 `roles/secretmanager.secretAccessor`를 부여한다.
7. API가 Source credential version을 추가·폐기해야 하는 secret에는
   `roles/secretmanager.secretVersionAdder`와 필요한 version 관리 권한을 secret 범위로
   부여한다. app이 새 secret 자체를 만드는 배포를 선택하면 staging project에만 적용한
   최소 custom role을 우선하고, 불가피할 때만 `roles/secretmanager.admin`을 사용한다.
8. Worker 배포 후 `iprisk-tasks`에 **그 Worker service만** `roles/run.invoker`를 부여한다.
9. API 배포 후 `iprisk-scheduler`에 **그 API service만** `roles/run.invoker`를 부여한다.
10. deploy identity의 `roles/iam.serviceAccountUser`는 API/Worker runtime SA에만 한정한다.

`roles/cloudtasks.serviceAgent` 같은 service-agent role은 사용자 계정이나 위 5개 계정에
직접 부여하지 않는다.

- [ ] 다섯 identity의 email을 입력표에 기록했다.
- [ ] runtime service account key가 0개다.
- [ ] project-wide Owner/Editor가 runtime identity에 없다.
- [ ] API와 Worker의 effective permission을 Policy Analyzer로 검토했다.

## 5. Artifact Registry와 image 고정

1. **Artifact Registry → Repositories → Create repository**로 이동한다.
2. Format은 Docker, mode는 Standard, location은 application region으로 고정한다.
3. repository 이름은 입력표와 `deploy/cloudbuild.yaml`의 `_REPOSITORY`가 일치해야 한다.
4. **Cloud Build → Triggers**를 새로 만들지 않아도 된다. 승인된 Cloud Shell/CI에서
   `deploy/cloudbuild.yaml`을 지정해 RC SHA를 build한다.
5. build의 `smoke-import-api`, `smoke-import-worker`가 모두 성공했는지 확인한다.
6. Artifact Registry image 상세 화면에서 생성된 immutable digest를 복사해 입력표에
   `.../application@sha256:...` 형식으로 기록한다. 이후 두 서비스 모두 이 digest를 쓴다.

- [ ] build source SHA가 RC SHA와 같다.
- [ ] 두 smoke-import step이 성공했다.
- [ ] image digest를 기록했다.
- [ ] 알려진 취약점 scan 결과를 검토했다.

## 6. Firestore database, index와 TTL

1. **Firestore → Databases → Create database**에서 Native mode database를 만든다.
2. location은 확정한 application region과 맞추고, 생성 후 변경 불가 특성을 재확인한다.
3. `deploy/firestore.indexes.json`을 기준으로 아래 composite index 7개를 생성한다.

| collection group | field 순서 |
|---|---|
| `memberships` | `record_kind`, `risk_workspace_id` |
| `memberships` | `record_kind`, `user_id`, `status` |
| `memberships` | `record_kind`, `email` |
| `workspace_mounts` | `record_kind`, `risk_workspace_id` |
| `workspace_mounts` | `record_kind`, `risk_workspace_id`, `mounted_by_user_id` |
| `risks` | `record_kind`, `artifact_id`, `analysis_type`, `lifecycle_state` |
| `risks` | `record_kind`, `risk_workspace_id` |

모든 field direction은 deploy JSON의 `ASCENDING`, query scope는 `COLLECTION`이다.
이어 **Databases → 해당 database → Time-to-live**에서 다음 collection group의
`expires_at`에 TTL policy를 둔다.

- `source_operational_oauth_states`
- `source_operational_pending_connections`
- `source_operational_device_challenges`

TTL 삭제는 즉시성을 보장하지 않으므로 application의 만료 검사는 그대로 유지한다.

- [ ] 7개 index가 Building이 아니라 Enabled/Ready다.
- [ ] 3개 TTL policy가 Active다.
- [ ] 실제 database ID를 `FIRESTORE_DATABASE`로 기록했다.
- [ ] staging 데이터와 production 데이터가 같은 database를 공유하지 않는다.

## 7. private staging bucket

1. **Cloud Storage → Buckets → Create**에서 전역 고유 이름과 application region을 정한다.
2. Public access prevention을 Enforced로, uniform bucket-level access를 Enabled로 둔다.
3. object versioning은 필요성 없이 켜지 않는다.
4. **Lifecycle**에서 `deploy/storage-lifecycle.json`과 동일하게 설정한다.
   - `staging/` prefix object: age 1일에 Delete
   - incomplete multipart upload: age 1일에 Abort
5. API/Worker의 `roles/storage.objectUser`를 이 bucket에만 부여한다.

- [ ] public principal(`allUsers`, `allAuthenticatedUsers`) binding이 없다.
- [ ] uniform access와 public access prevention이 활성화됐다.
- [ ] 두 lifecycle rule이 저장됐다.
- [ ] private upload/read/delete와 권한 없는 read 거부를 확인했다.

## 8. Secret Manager

**Security → Secret Manager → Create secret**에서 다음 logical secret을 만든다. 실제
조직 naming policy에 따라 ID를 바꿔도 되지만 Cloud Run environment mapping과 일치시킨다.

| 용도 | 권장 secret ID | Cloud Run environment |
|---|---|---|
| session signing | `iprisk-session-secret` | `SESSION_SECRET` |
| Google login client secret | `iprisk-google-login-client-secret` | `GOOGLE_LOGIN_CLIENT_SECRET` |
| Drive client secret | `iprisk-drive-client-secret` | `GOOGLE_DRIVE_CLIENT_SECRET` |
| Drive channel token | `iprisk-drive-channel-token` | `DRIVE_WATCH_CHANNEL_TOKEN` |
| GitHub App private key | `iprisk-github-private-key` | `GITHUB_APP_PRIVATE_KEY_SECRET_ID`에는 secret ID만 전달 |
| GitHub webhook secret | `iprisk-github-webhook-secret` | `GITHUB_WEBHOOK_SECRET_ID`에는 secret ID만 전달 |
| KIPRIS key | `iprisk-kipris-access-key` | `KIPRIS_API_KEY_SECRET_ID`에는 secret ID만 전달 |

OAuth Source credential secret은 app이 opaque ID로 관리하므로 여기서 실제 값이나 ID
규칙을 수기로 만들지 않는다. 각 secret에 initial version을 추가하고 runtime에는 필요한
최소 secret만 노출한다. Secret value를 일반 environment value로 직접 붙여 넣지 않는다.

- [ ] 모든 secret에 enabled initial version이 있다.
- [ ] 이 문서에는 secret ID와 version 번호만 있고 값은 없다.
- [ ] API/Worker 각각의 accessor 범위를 검토했다.
- [ ] rollback용 직전 version을 disable/destroy하지 않고 보존했다.

## 9. Worker를 먼저 배포

1. **Cloud Run → Create service**에서 service 이름을 `ip-risk-agent-worker`로 둔다.
2. §5의 image digest를 지정하고 `iprisk-worker` service account를 attach한다.
3. Authentication은 Require authentication, ingress는 Internal로 둔다.
4. `deploy/cloud-run-services.yaml`의 Worker CPU/memory/concurrency/min/max와 command를
   그대로 반영한다.
5. `APP_ENV=production`, `APP_ROLE=worker`와 `deploy/cloud-run-services.yaml`의 common,
   worker required environment를 설정한다. `.env.example`의 production group은
   all-or-none이므로 누락 없이 주입하되 실제 secret은 Secret Manager mapping을 쓴다.
6. `ANALYSIS_WORKER_URL`은 task endpoint가 아니라 Worker **base URL**로 둔다. app이
   `/internal/tasks/analyze-change`를 붙인다.
7. 첫 revision은 traffic 100%를 주기 전 readiness와 로그 redaction을 확인한다.

- [ ] unauthenticated 호출이 401/403이다.
- [ ] `/health/live`가 성공한다.
- [ ] `/health/ready`가 production durable composition을 확인한다.
- [ ] log에 token, raw content, private path가 없다.
- [ ] Worker URL/revision을 입력표에 기록했다.

## 10. Cloud Tasks queue와 Worker OIDC

1. **Cloud Tasks → Create queue**에서 `deploy/cloud-tasks-queue.yaml`과 동일한 이름,
   location, rate, concurrency, retry/backoff를 설정한다.
2. `iprisk-tasks` caller에 Worker service의 Cloud Run Invoker만 부여한다.
3. API SA에는 queue의 Cloud Tasks Enqueuer와 `iprisk-tasks` act-as만 부여한다.
4. OIDC audience는 Worker base URL, service account email은 `iprisk-tasks`로 설정한다.
5. 직접 test task를 보낼 때 body는 `{"change_event_id":"<staging-id>"}`만 사용하고
   원문이나 credential을 넣지 않는다.

- [ ] queue 설정이 deploy YAML과 일치한다.
- [ ] Tasks caller delivery가 성공한다.
- [ ] 사용자 session, static bearer, 다른 service account 호출은 거부된다.
- [ ] duplicate delivery가 중복 Risk를 만들지 않는다.

## 11. API 배포와 Scheduler

1. `ip-risk-agent-api`를 같은 image digest, `iprisk-api` service account로 배포한다.
2. ingress는 All, authentication은 Allow unauthenticated로 두되 제품 route는 application
   session/CSRF 정책으로 보호한다.
3. `APP_ENV=production`, `APP_ROLE=api`, `FRONTEND_DIST_DIR=/app/frontend/dist`와 required
   environment를 설정한다. `APP_PUBLIC_BASE_URL`은 최종 HTTPS API origin이다.
4. `/health/live`, `/health/ready`, `/app` static asset 제공을 확인한다.
5. `iprisk-scheduler`에 API service의 Cloud Run Invoker만 부여한다.
6. **Cloud Scheduler → Create job**에서 `deploy/scheduler-jobs.yaml`의 네 job을 만든다.
   URL은 API base URL + path, method는 POST, body는 해당 JSON, time zone은
   `Asia/Seoul`, attempt deadline은 300초다.
7. Auth header는 Add OIDC token, service account는 `iprisk-scheduler`, audience는 query나
   path를 붙이지 않은 API base URL로 고정한다.

- [ ] API와 Worker가 같은 image digest를 쓴다.
- [ ] 네 Scheduler job의 schedule/body/limit가 YAML과 일치한다.
- [ ] Scheduler identity 호출만 성공하고 직접 무인증 호출은 거부된다.
- [ ] batch limit이 500을 넘지 않는다.

## 12. RAG corpus

1. local/배포 host에서 `python scripts/prepare_rag_ingestion.py`를 다시 실행한다.
2. **Vertex AI → RAG Engine**에서 확정한 RAG region에 staging corpus를 만든다.
3. `rag-corpus/manifest.yaml`의 `approved_for_rag: true`이고 checksum이 일치하는 아래
   세 파일만 import한다.
   - `agpl-3.0-obligations.md`
   - `lgpl-2.1-obligations.md`
   - `permissive-notice.md`
4. private workspace, SourceSnapshot, 사용자 repository 파일은 업로드하지 않는다.
5. corpus resource ID와 manifest `corpus_version=2026-08-14.1`을 Cloud Run의
   `RAG_CORPUS_ID`, `RAG_CORPUS_VERSION`에 반영하고 새 revision을 검증한다.

- [ ] import 문서가 정확히 3개다.
- [ ] corpus ID/version과 region을 입력표에 기록했다.
- [ ] retrieval evidence에 exact corpus version이 포함된다.
- [ ] private source 원문 ingestion이 없음을 확인했다.

## 13. Google OAuth, Drive와 Picker

최종 API HTTPS origin이 확정된 뒤 **Google Auth Platform / APIs & Services**에서
consent screen과 web client를 구성한다. staging에서는 test user만 허용한다.

정확히 등록할 URI:

```text
Google login redirect:  https://<API_HOST>/api/v1/auth/google/callback
Drive OAuth redirect:   https://<API_HOST>/api/v1/source-connections/google-drive/callback
Drive webhook endpoint: https://<API_HOST>/webhooks/google-drive
Authorized JS origin:   https://<API_HOST>
```

scheme, host, port, 대소문자, path와 trailing slash까지 runtime environment와 정확히
일치해야 한다. Google login과 Drive client를 분리하고, Picker API key는 HTTPS origin,
필요 API와 가능한 application restriction으로 제한한다. Drive watch 생성 후 전달되는
`X-Goog-*` header와 channel token 검증, 만료 전 renewal을 확인한다.

- [ ] consent screen branding/scope/test user가 staging용으로 제한됐다.
- [ ] login/Drive redirect URI가 runtime 값과 exact match다.
- [ ] Picker key restriction이 적용됐다.
- [ ] Drive webhook HTTPS, channel token, renewal/reconciliation이 통과했다.
- [ ] 잘못된 OAuth state/replay와 선택하지 않은 file 접근이 거부된다.

## 14. GitHub App

GitHub organization 또는 test owner의 **Settings → Developer settings → GitHub Apps →
New GitHub App**에서 staging App을 만든다.

```text
Callback URL: https://<API_HOST>/api/v1/source-connections/github/install/callback
Webhook URL:  https://<API_HOST>/webhooks/github
```

Contents permission은 Read-only로 두고 Push event만 구독한다. Metadata 외 불필요한
permission/event는 추가하지 않는다. webhook secret을 설정하고 private key는 Secret
Manager에 보관한다. test organization의 선택된 repository에만 설치한다.

- [ ] App ID/slug와 callback URL이 runtime 값과 일치한다.
- [ ] permission은 Contents read-only, event는 Push 최소 범위다.
- [ ] private key/webhook secret은 Secret Manager에만 있다.
- [ ] valid signed push는 처리되고 잘못된 HMAC/repo/path는 거부된다.

## 15. domain, TLS와 environment 최종 수렴

1. custom domain을 쓴다면 Cloud Run domain mapping 또는 승인된 load balancer에 연결한다.
2. DNS와 managed certificate가 Active가 될 때까지 기다린다.
3. `APP_PUBLIC_BASE_URL`, OAuth redirect, Drive webhook, GitHub callback/webhook, Picker
   origin을 최종 HTTPS origin으로 한 번에 갱신한다.
4. API/Worker revision 설정을 export해 비민감 environment 이름과 resource ID만 대조한다.
5. secret version, image digest, service account, OIDC audience가 의도한 값인지 확인한다.

- [ ] HTTP에서 HTTPS로 강제된다.
- [ ] certificate가 유효하다.
- [ ] callback/webhook/runtime base URL이 서로 일치한다.
- [ ] 이전 임시 `run.app` callback/origin이 provider console에 남지 않았다.

## 16. live 검증과 증거

`docs/STAGING_VERIFICATION_RUNBOOK.md`의 순서로 전용 test account와 staging 데이터만
사용한다. 실제 provider test는 명시적으로 opt-in한다.

```powershell
python -m pytest tests/intelligence/test_live_providers.py -m live -vv
```

| 흐름 | positive | 반드시 실행할 negative | 결과/증거 ID |
|---|---|---|---|
| Google login | login→session→`/api/v1/auth/me` | 잘못된 state/replay | |
| Drive | OAuth→Picker→mount→fetch→watch | unselected file/channel token | |
| GitHub | install→private repo mount→signed push | bad HMAC/repo/path | |
| Local | enroll→mount→staging→event→cleanup | challenge replay/device/path escape | |
| Worker | ID-only OIDC task→terminal job | user token/duplicate delivery | |
| Intelligence | Gemini/KIPRIS/license 결과 | malformed/partial 결과 | |
| RAG | exact corpus version retrieval | private source ingestion | |

증거에는 timestamp, RC SHA/image digest, resource ID, HTTP status, safe failure code,
duration, queue age와 terminal state만 기록한다.

## 17. monitoring, rollback drill과 Go/No-Go

Cloud Monitoring에서 최소한 다음 alert를 구성하고 staging test signal로 한 번씩
발생·회복을 확인한다.

- Cloud Tasks queue age/error
- stuck lease
- provider failure/latency
- analyzer coverage 저하
- job terminal latency
- staging cleanup failure

중단 조건이 발생하면:

1. 새 API traffic 또는 새 enqueue를 중단한다. queue는 purge하지 않는다.
2. API/Worker traffic을 입력표의 직전 안정 revision으로 되돌린다.
3. Secret Manager는 직전 정상 version을 re-enable/고정하고 문제 version을 즉시
   destroy하지 않는다.
4. Firestore canonical Risk를 삭제하거나 대량 resolve하지 않는다.
5. incident evidence에는 안전한 ID와 failure code만 남긴다.
6. 원인을 수정한 새 immutable image/revision으로 §2부터 다시 검증한다.

최종 승인표:

| Gate | 결과 |
|---|---|
| repository gate / image digest | |
| IAM least-privilege 검토 | |
| Firestore index/TTL | |
| bucket/lifecycle/secret | |
| Worker/Tasks/API/Scheduler | |
| provider/RAG positive·negative | |
| alert와 rollback drill | |
| 알려진 제한 | |
| Go/No-Go 승인자 / 시각 | |

모든 칸이 채워지고 `No-Go` 조건이 0건일 때만 production readiness를 승인한다.

## 18. 공식 참고 문서

- [API 활성화](https://docs.cloud.google.com/service-usage/docs/enable-disable)
- [Service account 생성](https://docs.cloud.google.com/iam/docs/service-accounts-create)
- [Artifact Registry Docker repository](https://docs.cloud.google.com/artifact-registry/docs/docker/store-docker-container-images)
- [Cloud Run image 배포와 revision](https://docs.cloud.google.com/run/docs/deploying)
- [Cloud Run service-to-service OIDC](https://docs.cloud.google.com/run/docs/authenticating/service-to-service)
- [Cloud Tasks IAM](https://docs.cloud.google.com/tasks/docs/access-control)
- [Cloud Scheduler HTTP target 인증](https://docs.cloud.google.com/scheduler/docs/http-target-auth)
- [Firestore index](https://firebase.google.com/docs/firestore/query-data/index-overview)
- [Firestore TTL](https://firebase.google.com/docs/firestore/ttl)
- [Secret Manager secret/version](https://docs.cloud.google.com/secret-manager/docs/creating-and-accessing-secrets)
- [Cloud Storage uniform bucket-level access](https://docs.cloud.google.com/storage/docs/uniform-bucket-level-access)
- [Cloud Storage lifecycle](https://docs.cloud.google.com/storage/docs/managing-lifecycles)
- [Vertex AI RAG quickstart](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/rag-quickstart)
- [Google OAuth web server flow](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Google Drive push notification](https://developers.google.com/workspace/drive/api/guides/push)
- [GitHub App 등록](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app)
- [GitHub App 최소 권한 선택](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app)
