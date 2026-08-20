# GCP repository-internal deployment contract

이 문서는 Phase 6에서 확정한 **프로젝트 내부 산출물**만 설명한다. 리소스 생성,
IAM binding, OAuth consent, DNS/TLS, GitHub App 설정 같은 실제 외부 변경은 수행하지
않았으며 이후 GCP 외부 작업 단계에서 승인 후 실행한다.

## 1. 배포 단위

하나의 non-root image를 두 Cloud Run service가 공유한다.

| 서비스 | `APP_ROLE` | entrypoint | ingress/auth |
|---|---|---|---|
| `ip-risk-agent-api` | `api` | `ip_risk_agent.main:create_app` | public HTTPS, application session 보호 |
| `ip-risk-agent-worker` | `worker` | `ip_risk_agent.worker:create_app` | internal, Cloud Tasks OIDC만 허용 |

API는 image 안의 `frontend/dist`를 `/app`과 Product route에 same-origin으로 제공한다.
Worker task body는 `change_event_id` 하나만 허용한다. queue task name은 이 ID의
SHA-256으로 결정되어 동일 event의 짧은 시간 중복 enqueue를 흡수한다.

두 production entrypoint는 `build_google_cloud_foundation()`을 먼저 호출한 뒤 role별
runtime composer를 `build_container()`에 전달한다. API는 outbound Cloud Tasks와 모든
Source router를, Worker는 inbound Tasks OIDC와 Source adapters/Intelligence pipeline을
조립한다. local/test entrypoint는 기존 in-memory 기본값을 유지한다.

## 2. service identity와 최소 권한 matrix

| identity | project/resource 권한 |
|---|---|
| API SA | Firestore read/write, Source credential Secret version access/add, staging bucket object create/read/delete, Cloud Tasks enqueue, task caller SA act-as |
| Worker SA | Firestore read/write, Source/provider Secret access, staging bucket object read/delete, Vertex AI/RAG invoke; Cloud Tasks queue 관리 권한 없음 |
| Cloud Tasks caller SA | Worker Cloud Run Invoker만 |
| Scheduler caller SA | API Cloud Run Invoker만 |
| Deploy SA | Artifact Registry write, Cloud Build build, 두 Cloud Run service 갱신, 제한된 service-account act-as, index/queue/scheduler 배포 |

서비스 identity는 서로 재사용하지 않는다. API/Worker에는 credential JSON을 넣지
않고 attached service account의 Application Default Credentials를 사용한다.

## 2.1 role별 environment 계약

- 공통: project/region/database/public base, staging bucket, Drive client ID/secret,
  GitHub App ID/private-key secret ID.
- API 전용: session/frontend, Google login, Drive callback/webhook/channel, Picker,
  GitHub slug/webhook/callback, Tasks location/queue/Worker target/caller, Scheduler caller.
- Worker 전용: Worker target/caller(OIDC audience/email), Vertex location, KIPRIS secret ID,
  package metadata base URL. RAG 세 값은 all-or-none 선택 group이다.

`deploy/cloud-run-services.yaml`과 `Settings.validate()`가 이 구분을 동일하게 검증한다.
GitHub private key와 KIPRIS key는 Secret Manager ID로 전달하고 attached identity로 읽는다.

현재 `SchedulerOperations`의 네 maintenance 구현과 API router wiring은 별도 후속 blocker다.
해당 구현 전에는 `deploy/scheduler-jobs.yaml`의 job을 enabled 상태로 배포하지 않는다.

## 3. durable resource contract

- canonical Control state: `FIRESTORE_DATABASE`의 canonical collection.
- Source operational state: `source_operational_*` namespace만 사용한다.
- OAuth state, pending connection, device challenge: `expires_at` Firestore TTL 적용.
- Source credential: Secret Manager automatic replication secret의 immutable version.
- Local transient content: uniform bucket-level access가 켜진 private bucket의
  `staging/` object. signed/public URL은 만들지 않으며 lifecycle은 하루 뒤 방어적 삭제.
- analysis dispatch: `deploy/cloud-tasks-queue.yaml`의 bounded concurrency/retry,
  OIDC audience는 Worker base URL.
- RAG: `rag-corpus/manifest.yaml`에 승인되고 checksum이 일치한 public reference만 허용.

## 4. repository-owned 검증

```powershell
.\.venv\Scripts\python.exe scripts/validate_gcp_deployment.py
.\.venv\Scripts\python.exe scripts/prepare_rag_ingestion.py
docker build --tag ip-risk-agent:phase6 .
```

첫 명령은 canonical query index와 TTL 선언이 deploy JSON에 빠지지 않았는지,
Cloud Build/Run/Tasks/Scheduler/Storage 파일이 파싱 가능한지를 검사한다. 두 번째
명령은 외부 쓰기 없이 approved manifest 경계와 source checksum을 검증한다.

## 5. 외부 작업으로 넘길 값

- `PROJECT_ID`, Application region, Firestore database ID
- Artifact Registry repository와 image digest
- API/Worker/Tasks/Scheduler/Deploy service account email
- API/Worker URL과 custom domain
- Secret ID 및 Secret-mapped environment 목록
- private staging bucket 이름과 region
- Cloud Tasks queue name/location
- RAG region/corpus ID/version
- OAuth/GitHub callback 및 webhook URL

값은 `deploy/*.yaml` placeholder와 Cloud Run environment에 주입하며 source에
실제 credential, project-specific resource ID 또는 access token을 commit하지 않는다.

## 6. 관측과 readiness

`/health/live`는 process liveness, `/health/ready`는 role별 구성 완전성을 나타낸다.
운영 log/metric label에는 workspace/mount/artifact ID, source/analyzer type, attempt,
safe failure category, duration, outcome만 허용한다. raw content, snapshot segment,
credential/token, authorization header, provider raw response, local absolute path,
signed URL은 log에 남기지 않는다.

최소 alert는 queue age/error, stuck lease, provider failure/latency, analyzer coverage,
job terminal latency, staging cleanup failure에 둔다.
