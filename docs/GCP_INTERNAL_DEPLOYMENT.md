# GCP repository-internal deployment contract

이 문서는 같은 GCP project를 사용하는 v1을 보호하기 위한 v2의 규범적 배포 계약이다.
실제 resource 생성이나 IAM 변경은 이 repository 작업에 포함하지 않는다. canonical 값의
source of truth는 `deploy/v2-resource-contract.yaml`이며 validator가 모든 deploy 입력과
`Settings.validate()`의 동일 계약을 회귀 검증한다.

## 1. shared project와 v2 namespace

| 종류 | v2 canonical 값 |
|---|---|
| Project / number / region | `proj-aj22-211200020328` / `555102774494` / `asia-northeast3` |
| Firestore | `ip-risk-agent-v2`; `(default)` 금지 |
| Cloud Run | `ip-risk-agent-v2-api`, `ip-risk-agent-v2-worker` |
| Cloud Tasks | `ip-risk-agent-v2-analysis-changes` |
| Artifact Registry / image | `ip-risk-agent-v2` / `application` |
| staging bucket | `proj-aj22-211200020328-iprisk-v2-staging` |
| service accounts | `iprisk-v2-{api,worker,tasks,scheduler,deploy}` |
| dynamic credential prefix | `iprisk-v2-cred-` |
| RAG corpus display name | `ip-risk-agent-v2-legal-reference` |

v1의 `(default)` database, `ip-risk-agent` Run service,
`ip-risk-agent-drive-poll` Scheduler job, `ip-risk-agent-runtime` 및
`ip-risk-agent-scheduler` identity, 모든 `ipra-*` secret, 기존 bucket과
`cloud-run-source-deploy` repository에는 v2 binding을 추가하거나 수정·삭제하지 않는다.

## 2. 배포 단위와 role 계약

하나의 non-root immutable `application` image digest를 두 Cloud Run service가 공유한다.

| 서비스 | entrypoint | ingress/auth | 고유 책임 |
|---|---|---|---|
| `ip-risk-agent-v2-api` | `ip_risk_agent.main:create_app` | public HTTPS, application session | OAuth/source routers, Cloud Tasks enqueue |
| `ip-risk-agent-v2-worker` | `ip_risk_agent.worker:create_app` | internal, unauthenticated 금지 | inbound Tasks OIDC, source fetch, Intelligence |

API/Worker 공통 설정은 project/region/named database, 각 role의 base URL, v2 bucket,
Drive/GitHub provider identity와 `SOURCE_CREDENTIAL_SECRET_PREFIX`다. API만 session/frontend,
Google Login, Drive callback/webhook/channel, Picker, GitHub callback/webhook, queue/Worker
target/Tasks caller/Scheduler caller를 받는다. Worker만 Vertex/KIPRIS/package metadata와
선택 RAG group을 받는다.

Worker는 `ANALYSIS_WORKER_URL`, `CLOUD_TASKS_SERVICE_ACCOUNT`, queue, Scheduler 및 API OAuth
설정을 받지 않는다. inbound token audience는 Worker 자신의 `APP_PUBLIC_BASE_URL`, 허용
caller는 canonical `iprisk-v2-tasks@...`에서 얻으므로 Worker를 API와 queue보다 먼저
배포할 수 있다. canonical deterministic base URL은
`https://ip-risk-agent-v2-worker-555102774494.asia-northeast3.run.app`이며 실제 service
status URL과 일치하는지 배포 직후 확인한다. API는 이 URL을 target으로 사용한다.

## 3. named Firestore와 IAM isolation

production startup은 project, region, bucket과 함께
`FIRESTORE_DATABASE=ip-risk-agent-v2`를 exact-match한다. `(default)`, emulator host 또는
다른 database는 즉시 `SettingsError`다. `GoogleCloudClients`도 해당 database ID를
`firestore.AsyncClient(database=...)`에 명시한다.

API/Worker의 `roles/datastore.user`는 project-wide unconditional binding이 아니라 다음
조건으로 제한한다.

```text
resource.name ==
projects/proj-aj22-211200020328/databases/ip-risk-agent-v2
```

console의 data viewer 동작과 client/API의 IAM condition enforcement는 구분하여 검증한다.
index/TTL도 반드시 이 named database를 target으로 적용하며 `(default)`에는 적용하지 않는다.

## 4. identity와 최소 IAM

`deploy/iam-policy-contract.yaml`은 실제 IAM 변경 명령이 아니라 검토 가능한 최소 권한
handoff다.

| identity | 허용 범위 |
|---|---|
| API | v2 database, v2 queue enqueue, v2 staging objects, API fixed secrets, dynamic credential create/add/access, Tasks SA act-as |
| Worker | v2 database, v2 staging objects, Worker fixed secrets, dynamic credential add/access, Vertex AI와 v2 RAG corpus |
| Tasks caller | v2 Worker service의 `roles/run.invoker`만 |
| Scheduler caller | v2 API service의 `roles/run.invoker`만 |
| Deploy/build | v2 Artifact repository writer와 project Logs Writer만; runtime secret/data 권한 없음 |
| Cloud Build service agent | `iprisk-v2-deploy`에 대한 Token Creator만 |

runtime identity에는 Owner, Editor, `roles/secretmanager.admin`, unconditional
`roles/datastore.user`를 부여하지 않는다. API queue 권한은 queue-level
`roles/cloudtasks.enqueuer`, Storage는 v2 bucket-level object 권한, Run Invoker는 각 v2
service-level binding을 사용한다. JSON service-account key는 만들지 않는다.

## 5. Secret Manager

fixed ID와 사용 role은 다음과 같다. 환경 값으로 쓰는 네 secret도 Cloud Run Secret Manager
mapping으로 주입하며 평문 deploy value로 저장하지 않는다.

| secret ID | API | Worker | 주입 방식 |
|---|:---:|:---:|---|
| `iprisk-v2-session-secret` | O | - | `SESSION_SECRET` mapping |
| `iprisk-v2-google-login-client-secret` | O | - | `GOOGLE_LOGIN_CLIENT_SECRET` mapping |
| `iprisk-v2-drive-client-secret` | O | O | `GOOGLE_DRIVE_CLIENT_SECRET` mapping |
| `iprisk-v2-drive-channel-token` | O | - | `DRIVE_WATCH_CHANNEL_TOKEN` mapping |
| `iprisk-v2-github-private-key` | O | O | secret ID를 전달하고 ADC로 read |
| `iprisk-v2-github-webhook-secret` | O | - | secret ID를 전달하고 ADC로 read |
| `iprisk-v2-kipris-access-key` | - | O | secret ID를 전달하고 ADC로 read |

Source OAuth credential은
`iprisk-v2-cred-{provider}-{sha256[:40]}`만 생성·수락한다. secret label은
`owner=ip-risk-agent-v2`, `environment=v2`, provider를 사용한다. API는 OAuth 연결에서
secret create/add/access, webhook/mount token refresh에서 add/access를 사용한다. Worker는
source fetch 중 access와 refresh 시 add를 사용한다. 현재 runtime 경로는 disable을 호출하지
않으므로 disable 권한을 부여하지 않는다.

중요한 IAM 한계가 있다. `secretmanager.secrets.create`는 새 secret이 아니라 project parent에
대해 평가되므로 IAM resource-name condition으로 미래의 `iprisk-v2-cred-*` ID만 생성하도록
제한할 수 없다. 유지할 최소 custom role은 API에 project scope의
`secretmanager.secrets.create` 하나뿐이며, prefix 안전성은 application validation이
강제한다. `versions.add`와 `versions.access`는 생성된 secret resource 이름이 있으므로
`projects/555102774494/secrets/iprisk-v2-cred-` prefix condition으로 제한한다. 더 강한 격리가
필요하면 runtime secret create를 제거하고 별도 provisioning broker/identity로 분리해야 한다.

## 6. durable resource와 RAG

- canonical/operational collection 모두 v2 named database에만 둔다.
- Local staging은 v2 bucket의 `staging/` prefix와 하루 lifecycle만 사용한다.
- analysis task는 v2 queue에서 v2 Tasks caller OIDC로 v2 Worker에 전달한다.
- RAG는 별도 `ip-risk-agent-v2-legal-reference` corpus를 사용하고 기존 corpus를 재사용하지
  않는다. 승인 manifest와 corpus version 계약은 유지한다.

Scheduler의 Drive watch renewal/reconciliation, expired state cleanup, source health refresh는
durable operational store와 기존 adapter/Control facade를 재사용하는 production 구현으로 API
composition에 mount된다. Scheduler OIDC audience는 API base URL이며 허용 caller는
`iprisk-v2-scheduler@...` 하나다. Drive/GitHub/Local health는 canonical source 상태로
수렴하고 cleanup은 OAuth/device challenge와 만료된 `PENDING` connection만 제거한다.

Firestore composite index는 `deploy/firestore.indexes.json`의 정확히 8개다. 기존 canonical
7개에 `source_operational_github_tracking(record.owner, record.repo)`가 포함된다. TTL은 OAuth
state와 device challenge 두 collection에만 둔다. ACTIVE pending connection은 mount의 durable
credential lookup에 필요하므로 TTL 대상으로 두지 않고 scheduler가 stale `PENDING`만
status-aware하게 정리한다.

## 7. Cloud Build 실행 identity와 immutable deploy

`deploy/cloudbuild.yaml`은 다음 user-specified service account를 명시한다.

```text
projects/proj-aj22-211200020328/serviceAccounts/
iprisk-v2-deploy@proj-aj22-211200020328.iam.gserviceaccount.com
```

이 identity는 v2 Artifact Registry repository의 Writer와 Cloud Logging의 Logs Writer만
요구한다. Cloud Build service agent에는 이 build identity에 대한 Token Creator만 둔다.
build log는 `CLOUD_LOGGING_ONLY`이며 default Cloud Build/Compute identity와
`cloud-run-source-deploy` repository에 의존하지 않는다. build는 commit SHA tag 하나를
push하고, API/Worker manifest는 같은 `application@${IMAGE_DIGEST}`를 요구한다.

## 8. Google Auth Platform shared configuration

OAuth Login/Drive client는 각각 `ip-risk-agent-v2-login`, `ip-risk-agent-v2-drive`로 새로
만든다. 다만 Branding, Audience, Data Access, authorized domain은 project-level이라 v1과
완전히 분리되지 않는다. 기존 v1 OAuth client와 consent configuration을 자동 수정·삭제하지
않으며 project-level 변경은 반드시 “v1에도 영향을 줄 수 있는 shared configuration”으로
검토·승인한다.

## 9. repository gate

```powershell
python scripts/validate_gcp_deployment.py
python -m pytest tests/integration -m "not live"
python scripts/prepare_rag_ingestion.py
```

validator는 v1/default namespace, 역할별 환경 불일치, public Worker, 서로 다른 API/Worker
artifact, broad IAM, non-v2 secret prefix, 8-index/2-TTL, 네 Scheduler route/job, Cloud Build
identity/logging과 immutable digest 계약을 실패시킨다. 외부 resource를 조회하거나 만들지
않는 pure repository preflight다.

공식 근거:

- [Firestore named database와 database별 IAM Condition](https://cloud.google.com/firestore/docs/manage-databases)
- [Cloud Tasks queue-level access](https://cloud.google.com/tasks/docs/secure-queue-configuration)
- [Secret 생성/버전 권한의 평가 resource](https://cloud.google.com/secret-manager/docs/reference/rest/v1/projects.secrets/create)
- [Cloud Run deterministic URL](https://cloud.google.com/run/docs/triggering/https-request)
- [Cloud Run service-to-service OIDC audience](https://cloud.google.com/run/docs/authenticating/service-to-service)
- [Cloud Build user-specified service account](https://cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts)
