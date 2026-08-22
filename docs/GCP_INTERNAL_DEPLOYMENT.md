# GCP repository-internal deployment contract

이 문서는 같은 GCP project를 사용하는 v1을 보호하기 위한 v2의 규범적 배포 계약이다.
실제 resource 생성이나 IAM 변경은 이 repository 작업에 포함하지 않는다. canonical 값의
source of truth는 `deploy/v2-resource-contract.yaml`이며 validator가 모든 deploy 입력과
`Settings.validate()`의 동일 계약을 회귀 검증한다.

## 0. project 전제와 API 활성화

resource를 하나라도 만들기 전에 Console project selector를 shared project
`proj-aj22-211200020328`에 고정하고 **Billing** 연결 상태와 budget alert를 확인한다.
이어서 **APIs & Services → Library**에서 다음 API를 모두 Enabled로 만든다. 이 목록은
repository의 어떤 `deploy/` 파일에도 없으므로, 두 번째 환경을 세울 때 여기서부터
시작한다.

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

API 활성화를 수행하는 작업자에게는 `roles/serviceusage.serviceUsageAdmin` 또는 동등한
`serviceusage.services.enable` 권한이 필요하다. 활성화는 project-level 변경이므로 활성
project ID를 다시 확인한 뒤 수행한다. Google Picker API는 §8의 D1 결정으로 폐기 대상이니
새 환경에서는 Drive OAuth/Picker 관련 활성화를 §8에서 먼저 확인한다.

Vertex RAG 지원 region, billing account 연결, OAuth test user, GitHub test
organization/repository, KIPRIS staging key, 공개 HTTPS domain(또는 우선 사용할 Cloud Run
`run.app` URL) 정책이 확정되지 않았다면 resource를 만들지 않는다.

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
따라서 Dockerfile runtime `ENV`에는 API-only 또는 Worker-only 변수를 두지 않는다.
`FRONTEND_DIST_DIR=/app/frontend/dist`는 API revision manifest에만 명시하며 Worker에는
직접 또는 image 기본값으로도 주입하지 않는다.

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
| Deploy/build | v2 Artifact repository writer, project Logs Writer, `proj-aj22-211200020328_cloudbuild` bucket Object Viewer; runtime secret/data 권한 없음 |
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

> **[2026-08-23] `secrets.delete` 가 빠져 있다 — workspace 삭제가 끝나지 못한다.**
> `deploy/iam-policy-contract.yaml` 에 `secretmanager.secrets.delete` 가 **0 건**인데
> `gcp/secret_vault.py` 의 `delete()` 는 `delete_secret` 을 부르고 `NotFound` 만 잡는다.
> `gcp/operational_eraser.py:90-99` 는 그 실패를 일부러 올려 workspace 를 `DELETING` 으로
> 남기므로, 자격증명이 붙은 workspace 는 **영영 지워지지 않고 재시도만 반복한다.**
>
> `secrets.create` 와 달리 삭제는 존재하는 secret resource 에 대해 평가되므로 위 문단이
> 말한 prefix 조건의 한계가 적용되지 않는다 — `iprisk-v2-cred-` prefix condition 을 실제로
> 걸 수 있다. `docs/DEVELOPMENT_SPEC.md` §9.4 · 결함 23.
>
> **[진행] 계약에는 `deleter` 를 넣었다** — `dynamicCredentialPermissions.deleter`, API SA
> 하나에 `secretmanager.secrets.delete` 를 같은 prefix 조건으로. worker 는 넣지 않았다:
> 삭제 경로가 `api/workspaces/router.py:314` 하나뿐이라 worker 는 이 길을 타지 않는다
> (`creator` 와 같은 모양이다). `scripts/validate_gcp_deployment.py` 도 이 항목을 기대하도록
> 함께 고쳤다.
>
> **아직 끝나지 않았다.** 이 검증기는 **계약 파일만** 읽는다. 실제 IAM 정책은 보지 않으므로
> 계약을 고쳤다고 운영이 고쳐지지 않는다. 남은 것 셋 —
> ① 실제 정책에 이 binding 이 있는지 `gcloud projects get-iam-policy` 로 확인,
> ② 없으면 조건부 binding 을 실제로 부여,
> ③ **자격증명이 붙은 workspace 를 실제로 지워** `DELETING` 에서 벗어나는지 확인.

## RAG corpus 판본은 배포 직전에 손으로 맞춘다

**저장소가 이것을 잡아 주지 못한다.** `RAG_CORPUS_VERSION` 은
`deploy/cloud-run-services.yaml` 의 `optionalEnvironment.worker` 에 **이름만** 있고 값은
라이브 Cloud Run service 에만 산다. 그래서 `scripts/validate_gcp_deployment.py` 는 이 변수가
선언돼 있는지만 보고 값은 보지 못한다.

두 가지가 겹쳐 조용해진다 — **worker 전용**이라 API 를 봐서는 알 수 없고,
**`optional`** 이라 값이 없거나 낡아도 배포가 실패하지 않는다.

어긋나면 원장이 거짓말을 한다. 판정에 실리는 `rag_corpus_version` 이 실제로 검색된 corpus
와 다른 판본을 가리키고, 그러면 `DEVELOPMENT_SPEC.md` §7.4 의 원인 귀속이 "판단 기준이
좋아졌다" 를 엉뚱한 시점에 적는다. §5.6 이 이 필드를 "감사의 전부" 라고 부른 이유가 그것이다.

**순서를 지킨다. 값만 맞추면 라벨만 바뀌고 실제 corpus 는 그대로다.**

1. 적재 — 전문을 Vertex RAG 에 올린다 (Fork A 소유, `0-G` 뒤에만)
2. 매니페스트 첫 줄의 `corpus_version` 을 읽는다
3. 그 값으로 **worker** 의 `RAG_CORPUS_VERSION` 을 갱신한다
4. 배포

**배포 직전 확인 명령**

```
grep '^corpus_version:' rag-corpus/manifest.yaml
gcloud run services describe ip-risk-agent-v2-worker --region=asia-northeast3   --format='value(spec.template.spec.containers[0].env)' | tr ',' '
' | grep RAG_CORPUS_VERSION
```

두 값이 같아야 배포한다. 다르면 **적재를 먼저 했는지부터** 확인한다.

**나중에 코드로 막을 수 있다.** 값을 `optionalEnvironment` 에서 `canonicalEnvironment.worker`
로 옮기면 저장소가 값을 갖게 되고, 검증기가 매니페스트의 `corpus_version` 과 같은지 검사할
수 있다. 지금 하지 않는 이유는 corpus 가 아직 움직이고 있어서다 — 매니페스트가 오를 때마다
이 파일이 깨져 다른 세션의 시험까지 멈춘다. **적재가 끝나 판본이 멎으면 그때 옮긴다.**

중요한 IAM 한계가 있다. `secretmanager.secrets.create`는 새 secret이 아니라 project parent에
대해 평가되므로 IAM resource-name condition으로 미래의 `iprisk-v2-cred-*` ID만 생성하도록
제한할 수 없다. 유지할 최소 custom role은 API에 project scope의
`secretmanager.secrets.create` 하나뿐이며, prefix 안전성은 application validation이
강제한다. `versions.add`와 `versions.access`는 생성된 secret resource 이름이 있으므로
`projects/555102774494/secrets/iprisk-v2-cred-` prefix condition으로 제한한다. 더 강한 격리가
필요하면 runtime secret create를 제거하고 별도 provisioning broker/identity로 분리해야 한다.

## 6. durable resource와 RAG

- canonical/operational collection 모두 v2 named database에만 둔다.
- Local staging은 v2 bucket의 `staging/` prefix와 하루 lifecycle만 사용한다. bucket 자체는
  public access prevention을 **Enforced**, uniform bucket-level access를 **Enabled**로 두고
  object versioning은 필요가 없으므로 켜지 않는다. 이 세 가지는 절차가 아니라 결정이며
  `deploy/storage-lifecycle.json`에는 담기지 않는다 — 그 파일이 가진 것은 `staging/` prefix
  object의 age 1일 Delete와 incomplete multipart upload의 age 1일 Abort 두 lifecycle rule
  뿐이다. `allUsers`/`allAuthenticatedUsers` binding은 두지 않고 API/Worker에는 이 bucket
  범위의 object 권한만 부여한다. 기존 bucket에는 lifecycle도 IAM도 추가하지 않는다.
- analysis task는 v2 queue에서 v2 Tasks caller OIDC로 v2 Worker에 전달한다.
- RAG는 별도 `ip-risk-agent-v2-legal-reference` corpus를 사용하고 기존 corpus를 재사용하지
  않는다. 승인 manifest와 corpus version 계약은 유지한다.

배포된 corpus identity는 repository에 없고 Worker 환경에만 있다.

```text
RAG_CORPUS_ID=6917529027641081856
RAG_REGION=asia-northeast3
RAG_CORPUS_VERSION=2026-08-21.1
```

`.env.example`은 60~62행에 `RAG_REGION=`, `RAG_CORPUS_ID=`, `RAG_CORPUS_VERSION=`를 빈
값으로만 두므로 위 세 값은 이 문서가 유일한 기록이다. 여기에 **미결 하나**가 붙어 있다 —
`rag-corpus/manifest.yaml`의 `corpus_version`은 `2026-08-14.1`인데 배포 환경변수는
`2026-08-21.1`이다. 그리고 `scripts/validate_gcp_deployment.py:289`가 manifest 쪽 값
`2026-08-14.1`을 하드코딩해 강제하므로, repository gate가 통과시키는 버전과 Worker에
주입된 버전이 서로 다르다. 어느 쪽이 실제로 올라간 corpus인지 확인하기 전에는 주기적
갱신을 시작하지 않는다. 확인한 뒤에는 manifest, validator 상수, 배포 환경변수를 함께
움직인다.

Scheduler의 Drive watch renewal/reconciliation, expired state cleanup, source health refresh는
durable operational store와 기존 adapter/Control facade를 재사용하는 production 구현으로 API
composition에 mount된다. Scheduler OIDC audience는 API base URL이며 허용 caller는
`iprisk-v2-scheduler@...` 하나다. Drive/GitHub/Local health는 canonical source 상태로
수렴하고 cleanup은 OAuth/device challenge와 만료된 `PENDING` connection만 제거한다.

operational collection은 canonical aggregate를 대체하지 않는다. 모든 document ID는 raw
state, token, credential, device credential, provider lookup key가 아니라 그 값의
SHA-256이며 document에는 `schema_version: 1`을 둔다. 열두 collection의 목적과 TTL은 다음과
같고, 이름은 `backend/src/ip_risk_agent/gcp/operational_firestore.py`의 상수(34~49행,
runtime 다섯 개는 `RUNTIME_COLLECTIONS`)와 일치한다. 같은 파일 50~56행의
`MAINTENANCE_COLLECTIONS`는 OAuth state, pending connection, device challenge와 runtime
다섯 개를 정리 대상으로 묶는다.

| collection | 목적 | TTL |
|---|---|---|
| `source_operational_oauth_states` | one-time OAuth/App state와 safe callback context | `expires_at` |
| `source_operational_pending_connections` | canonical mount 생성 전 pending connection | `expires_at`* |
| `source_operational_mount_bindings` | deterministic registration key↔mount binding | 없음 |
| `source_operational_device_challenges` | one-time desktop enrollment challenge hash | `expires_at` |
| `source_operational_devices` | owner/session/status와 credential hash | 없음 |
| `source_operational_device_credentials` | credential hash→device ID lookup | 없음 |
| `source_operational_device_mounts` | device↔workspace↔mount binding | 없음 |
| `source_operational_drive_runtime` | Drive cursor/watch runtime | 없음 |
| `source_operational_drive_tracking` | Drive selected file scope | 없음 |
| `source_operational_github_runtime` | GitHub delivery/runtime state | 없음 |
| `source_operational_github_tracking` | repository/branch/path scope | 없음 |
| `source_operational_local_runtime` | Local staging runtime reference | 없음 |

*pending connection의 `expires_at`은 만료 판정 field이지 선언된 Firestore TTL policy가
아니다. `deploy/firestore.indexes.json`의 `fieldOverrides`는 `source_operational_oauth_states`와
`source_operational_device_challenges` 둘만 `ttl: true`로 두며, 만료된 `PENDING` connection은
아래 index/TTL 문단대로 scheduler가 status-aware하게 정리한다.

schema 변경 규칙은 하나다. collection을 **제자리에서 추정하지 않는다** — `schema_version`
decoder를 먼저 추가하고 별도 migration dry-run을 통과시킨 뒤에 바꾼다. emulator 검증은
`FIRESTORE_EMULATOR_HOST`를 명시한 경우에만 실행하며 production에는 이 환경변수를 절대
설정하지 않는다.

OAuth state consume은 Firestore transaction으로 `consumed_at`을 원자적으로 기록한다. TTL
삭제는 즉시성을 보장하는 authorization mechanism이 아니므로, one-time credential을
consume할 때는 `expires_at`과 `consumed_at`을 **둘 다** 검사한다.

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

이 identity는 v2 Artifact Registry repository의 Writer, Cloud Logging의 Logs Writer와
Cloud Build source bucket `gs://proj-aj22-211200020328_cloudbuild`의 bucket-level
`roles/storage.objectViewer`를 요구한다. 마지막 binding은 제출자가 staging한 source
archive를 build identity가 읽을 때 필요한 `storage.objects.get`을 제공하며 object
create/update/delete는 허용하지 않는다. 실제 첫 외부 제출에서는 이 binding이 없어 403이
발생했고 추가 후 source fetch가 진행됐다. Cloud Build service agent에는 이 build
identity에 대한 Token Creator만 둔다. build log는 `CLOUD_LOGGING_ONLY`이며 default Cloud Build/Compute identity와
`cloud-run-source-deploy` repository에 의존하지 않는다. build는 commit SHA tag 하나를
push하고, API/Worker manifest는 같은 `application@${IMAGE_DIGEST}`를 요구한다.

## 8. provider console 등록과 shared configuration

OAuth Login/Drive client는 각각 `ip-risk-agent-v2-login`, `ip-risk-agent-v2-drive`로 새로
만든다. 다만 Branding, Audience, Data Access, authorized domain은 project-level이라 v1과
완전히 분리되지 않는다. 기존 v1 OAuth client와 consent configuration을 자동 수정·삭제하지
않으며 project-level 변경은 반드시 “v1에도 영향을 줄 수 있는 shared configuration”으로
검토·승인한다.

provider console에 등록하는 endpoint는 최종 API HTTPS origin이 확정된 뒤 한 번에 맞춘다.
scheme, host, port, 대소문자, path와 trailing slash까지 runtime environment 값과 exact
match여야 하며, 임시 `run.app` callback/origin을 console에 남기지 않는다.

Google 쪽 등록은 `docs/DEVELOPMENT_SPEC.md` §2 결정 D1(Drive는 **서비스 계정 + 폴더 공유**,
`drive.file` 폐기·`drive.readonly` 미채택)으로 절반이 정리된다. 보관할 Drive 사용자 토큰이
없어지므로 Drive OAuth client와 browser Picker에 딸린 등록도 함께 사라진다(§2.1).

| 등록 항목 | 값 | D1 이후 |
|---|---|---|
| Google login redirect | `https://<API_HOST>/api/v1/auth/google/callback` | **유지.** `ip-risk-agent-v2-login` client의 server-side redirect flow이며 `composition/container.py`의 `_oidc()`가 `APP_PUBLIC_BASE_URL` + 이 path를 기본 redirect로 만든다 |
| Drive webhook endpoint | `https://<API_HOST>/webhooks/google-drive` | **유지.** push channel 수신 endpoint이지 OAuth redirect가 아니므로 서비스 계정이 만든 watch에도 그대로 필요하다. `X-Goog-*` header와 channel token 검증, 만료 전 renewal을 확인한다 |
| Drive OAuth redirect | `https://<API_HOST>/api/v1/source-connections/google-drive/callback` | **폐기.** `ip-risk-agent-v2-drive` client 자체가 D1으로 없어진다 |
| Authorized JS origin | `https://<API_HOST>` | **폐기.** browser Picker를 위한 등록이었다. login은 server-side flow라 JS origin이 필요 없다. Picker API key의 HTTPS origin·API·application restriction도 같이 폐기된다 |

폐기 두 항목의 코드 경로는 아직 남아 있다(`connectors/google_drive/oauth_routes.py:75`의
Drive callback, `connectors/google_drive/mounts_routes.py`의 picker-session). D1 구현 전에
이미 배포된 등록은 그대로 두되, 새 환경에서는 만들지 않고 D1 이후 재등록하지 않는다.

GitHub App은 organization 또는 test owner의 **Settings → Developer settings → GitHub Apps
→ New GitHub App**에서 만들고 다음 두 URL을 등록한다.

```text
Callback URL: https://<API_HOST>/api/v1/source-connections/github/install/callback
Webhook URL:  https://<API_HOST>/webhooks/github
```

권한 범위 결정은 **Contents는 Read-only, event는 Push만**이다. Metadata 외 불필요한
permission/event는 추가하지 않는다. webhook secret을 설정하고 private key는 Secret
Manager(`iprisk-v2-github-private-key`, `iprisk-v2-github-webhook-secret`)에만 둔다. test
organization에서는 선택한 repository에만 설치하며, App ID/slug와 callback URL은 runtime
값과 일치해야 한다.

## 9. repository gate

```powershell
python scripts/validate_gcp_deployment.py
python -m pytest tests/integration -m "not live"
python scripts/prepare_rag_ingestion.py
```

validator는 v1/default namespace, 역할별 환경 불일치, shared image runtime ENV를 통한
role-only 변수 유입, public Worker, 서로 다른 API/Worker artifact, broad IAM, non-v2 secret
prefix, 8-index/2-TTL, 네 Scheduler route/job, Cloud Build identity/logging/source bucket read와
immutable digest 계약을 실패시킨다. 외부 resource를 조회하거나 만들지 않는 pure repository
preflight다.

공식 근거:

- [Firestore named database와 database별 IAM Condition](https://cloud.google.com/firestore/docs/manage-databases)
- [Cloud Tasks queue-level access](https://cloud.google.com/tasks/docs/secure-queue-configuration)
- [Secret 생성/버전 권한의 평가 resource](https://cloud.google.com/secret-manager/docs/reference/rest/v1/projects.secrets/create)
- [Cloud Run deterministic URL](https://cloud.google.com/run/docs/triggering/https-request)
- [Cloud Run service-to-service OIDC audience](https://cloud.google.com/run/docs/authenticating/service-to-service)
- [Cloud Build user-specified service account](https://cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts)
- [Cloud Storage Object Viewer와 bucket IAM](https://cloud.google.com/storage/docs/access-control/iam)
