# IP Risk Agent
추가 수정

IP Risk Agent는 Google Drive, GitHub, Local Desktop에서 선택한 소스의 변경을 감지하고 특허·라이선스 위험을 분석한 뒤, 사람이 검토하고 승인하는 흐름을 제공하는 IP 리스크 관리 시스템이다.

세 Plane, API/Worker durable GCP composition, production Scheduler maintenance, v2
namespace/IAM/build 계약과 Web/Electron 제품 흐름이 통합되어 있다. Firestore operational
store, Secret Manager/GCS/Cloud Tasks/OIDC adapter, 네 Scheduler route, 8개 composite
index·2개 TTL, user-specified Cloud Build identity와 immutable shared image 계약은
repository preflight로 검증한다. Phase 9의 GCP 외부 작업은 끝났고 API `00037-6zz` /
Worker `00037-tq6` (`78a6490`) 리비전이 배포되어 동작 중이다.

다음 단계의 기준은 `docs/DEVELOPMENT_SPEC.md`이며, 그 §11 의 **0 단계 — 오답 제거**
(항목 0-A~0-L)가 다른 모든 작업의 선행이다.

## 통합 상태

| 범위 | 상태 |
|---|---|
| 세 feature branch merge와 conflict 해결 | 완료 |
| Agent 인계 문서 통합 | 완료 |
| Python/Node dependency 및 lock 수렴 | 완료 |
| Source frontend test의 Vitest 통합 | 완료 |
| P0 경계 보강 | 완료 |
| API/Worker composition과 local integration E2E | 완료 |
| Web/Electron 제품 wiring | 완료 |
| GCP 내부 adapter와 배포 입력물 | 완료 |
| 전체 release regression과 staging runbook | 완료 |
| 구 Agent 원본 제거와 release candidate 고정 | 완료 |
| GCP 외부 resource/IAM/live 배포 | 완료. API `00037-6zz` / Worker `00037-tq6` (`78a6490`) 배포 상태 |
| 라이선스 오답 제거 (`docs/DEVELOPMENT_SPEC.md` §11 의 0 단계, 0-A~0-L) | 다음 단계 |

Production v2는 기존 v1과 `proj-aj22-211200020328` project를 공유하므로 project 경계가
아니라 `deploy/v2-resource-contract.yaml`의 v2 namespace로 격리한다. `(default)`
Firestore, v1 Run/Scheduler/identity/secret/bucket/repository의 재사용이나 IAM 변경은
금지되며 repository validator와 production startup이 이를 fail-closed한다.

설계와 구현 기준은 `docs/DEVELOPMENT_SPEC.md`가 우선한다. 알려진 결함과 그것이 닫히는
자리는 같은 문서 §8에, 추적 기록은 `docs/V3_DEVELOPMENT_WATCH.md`와
`docs/INTEGRATION_V1_CROSSCHECK.md`에 있다(둘 다 비규범 문서다). dependency 결정 근거는
아래 "Dependency pin 근거"에 있다.

## 시스템 구성

```text
shared/contracts/                 Frozen Contract v1과 generated bindings
backend/src/ip_risk_agent/
  api/                            Control API와 인증 경계
  application/                    canonical application service
  core/                           domain model과 policy
  persistence/                    in-memory/Firestore persistence
  composition/                    설정/container, API/Worker, browser runtime과 Plane 사이 경계
  gcp/                            durable Google Cloud adapter와 foundation factory
  connectors/                     Drive, GitHub, Local source adapters
  intelligence/                   Patent, License, Gemini, RAG
frontend/                         React/Vite Product UI, SourcePanel과 provider completion flow
apps/desktop/                     보안 Electron shell, enrollment, Local watcher와 registry
rag-corpus/                       reference-only RAG corpus와 provenance
tests/                            contracts/control/connectors/intelligence/integration/e2e
scripts/                          contract/deploy 검증과 RAG ingestion dry-run
deploy/                           Cloud Build/Run/Tasks/Scheduler, Firestore TTL/index, GCS lifecycle
docs/                             개발 명세, 배포 계약/runbook, 설계 노트와 추적 기록
```

핵심 Plane의 책임은 다음과 같다.

- Control Plane은 VWS, membership, SourceMetadata, canonical state, Risk, Review와 authorization을 소유한다.
- Source Plane은 provider connection, mount, metadata/snapshot lookup과 content-free SourceChange 생산을 담당한다.
- Intelligence Plane은 supplied snapshot을 분석하고 Patent/License/RAG evidence를 반환한다. canonical state를 직접 변경하지 않는다.
- Integration layer는 fail-closed 인증, pending binding, device credential, analyzer 완전성, runtime 설정/container, API와 Worker pipeline 조립을 소유한다.

`shared/contracts/**`는 frozen 영역이다. 변경이 필요하면 `contract-change-requests/` 절차를 사용하며 feature 또는 통합 편의를 위해 직접 수정하지 않는다.

## 고정 개발 환경

| Tool/runtime | Version |
|---|---:|
| CPython | `3.14.7` |
| Node.js | `24.19.0` |
| pnpm | `11.19.0` |
| TypeScript | `5.9.3` |
| Pydantic | `2.13.4` |
| pytest | `9.1.1` |

`.python-version`, `.node-version`, `pyproject.toml`과 root `package.json`이 이 기준을 표현한다. 다른 Python minor 또는 caret/range 기반 Node dependency로 개발 환경을 임의 변경하지 않는다.

## 설치

### 1. 버전 확인

```powershell
python --version
node --version
pnpm --version
```

각 출력은 위 고정 버전과 일치해야 한다.

### 2. Python

일반 개발 설치:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pip check
```

Windows가 아닌 환경에서는 가상환경을 `source .venv/bin/activate`로 활성화한다.
Windows Git Bash에서는 다음 경로를 사용한다.

```bash
source .venv/Scripts/activate
```

아래 gate는 반드시 이 project venv가 활성화된 shell에서 실행한다. system Python에서
`ModuleNotFoundError: fastapi`, `yaml`, `google` 또는 `Unknown config option: asyncio_mode`가
나오면 application 결함으로 판단하기 전에 venv 활성화와 `.[dev]`/lock 설치를 확인한다.

CI 또는 재현 가능한 설치에서는 transitive version까지 고정한 lock을 먼저 적용한다.

```powershell
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m pip check
```

`pyproject.toml`은 direct production/dev dependency의 source of truth이고, `requirements.lock`은 CPython 3.14에서 해석한 transitive set이다. manifest를 변경하면 두 파일을 같은 commit에서 갱신하고 Windows 및 Linux target을 다시 검증한다.

### 3. Node workspace

```powershell
pnpm install --frozen-lockfile
```

workspace는 `@iprisk/contracts`, `@iprisk/frontend`, `@iprisk/desktop`으로 구성된다. 모든 dependency는 exact version 또는 `workspace:*`로 고정되어 있다. `pnpm-lock.yaml`을 직접 편집하지 않는다.

## Dependency pin 근거

`pyproject.toml`과 `requirements.lock`은 어떤 버전인지만 말하고 왜 그 버전인지는 말하지
않는다. 아래 네 결정은 manifest만 보면 중복이나 누락으로 오해하기 쉬우므로 근거를 여기에
남긴다. 이 판단을 뒤집으려면 아래 근거를 먼저 무효화해야 한다.

### `httpx`와 `httpx2`는 중복이 아니다

`httpx==0.28.1`(production)과 `httpx2==2.10.0`(dev)은 **이름이 비슷할 뿐 서로 다른
package다. 둘 다 남겨야 한다.**

- `httpx==0.28.1`은 application/provider용 async client다. Control의 OIDC, Source의
  GitHub, Intelligence의 KIPRIS·package metadata·RAG REST가 모두 이것을 공용으로 쓴다.
- `httpx2==2.10.0`은 Starlette `1.6.0` `TestClient`의 transport다. `starlette/testclient.py`는
  `import httpx2 as httpx`를 먼저 시도하고, `httpx2`가 없을 때만 `httpx`로 내려가며
  `StarletteDeprecationWarning`("Using `httpx` with `starlette.testclient` is deprecated;
  install `httpx2` instead.")을 낸다. 둘 다 없으면 `RuntimeError`로 죽는다.
- 따라서 `httpx2`를 "중복"으로 보고 지우면 `TestClient`를 쓰는 모든 test —
  `tests/connectors`의 7개 파일과 `tests/control`의 3개 파일 — 가 upstream이 이미
  deprecated로 표시한 경로로 내려가고, 그 fallback이 제거되는 순간 전부 실패한다.

`pyproject.toml`도 `requirements.lock`도 이 사실을 설명하지 못한다. lock에는 `httpx==0.28.1`
(40행)과 `httpx2==2.10.0`(41행)이 나란히 있을 뿐이다.

### `fastapi==0.141.1` — Source의 `0.121.2`가 아니라 Control 검증 버전

Control은 `0.141.1`로 API와 Product backend를 검증했고 Source는 `0.121.2`를 요청했지만
Source가 쓰는 API는 `APIRouter`, `Request`, `HTTPException`, `TestClient` 중심이다. 두
버전을 한 Python environment에 동시에 설치할 수 없고 두 Plane의 router가 **하나의 FastAPI
app에 설치되므로**, 이미 검증된 상위 버전인 Control 기준으로 통일했다. 대신 Source
connector suite 전체를 `0.141.1`에서 다시 통과시키는 것이 조건이다. `starlette==1.6.0`을
transitive에 맡기지 않고 direct pin하는 이유는 Control 코드가 Starlette를 직접 import하기
때문이다.

### `google-auth[requests]`의 `[requests]` extra는 의도된 것이다

`requests`를 별도 direct dependency로 올리지 않는 대신 extra로 transport requirement를
명시한다. Drive client(`backend/src/ip_risk_agent/connectors/google_drive/client.py:13`),
RAG engine(`backend/src/ip_risk_agent/intelligence/rag/engine.py:154`), GCP identity
adapter(`backend/src/ip_risk_agent/gcp/identity.py:9`)가 모두
`google.auth.transport.requests.Request`를 직접 import한다. base `google-auth`만 선언하면
`requests` extra가 보장되지 않는다. `requirements.lock`은 extra를 평탄화해
`google-auth==2.56.3`(21행)과 `requests==2.34.2`(62행)로만 남기므로, lock만 보면 `requests`가
지워도 되는 transitive처럼 보인다.

### `google-cloud-aiplatform`은 의도적으로 채택하지 않았다

RAG `retrieveContexts`는 SDK가 아니라 `httpx` REST 호출이다
(`intelligence/rag/engine.py`의 endpoint
`https://{region}-aiplatform.googleapis.com/v1/projects/{project}/locations/{region}:retrieveContexts`).
ADC/token refresh만 `google-auth`에 맡긴다. 코드 주석대로 그 SDK는 100MB를 넘고 이 Plane이
쓰는 기능은 `retrieveContexts` 하나뿐이라, 대형 SDK를 추가할 구현상 필요가 없다.
**재평가 조건: RAG REST contract가 바뀌거나 ingestion 구현이 SDK 전용 기능을 요구할 때만
재평가한다.**

## 환경 변수

`.env.example`을 로컬 전용 `.env`로 복사하고 필요한 값만 설정한다. `.env`, secret, OAuth token, PEM, service-account JSON과 실제 resource ID를 commit하지 않는다.

```powershell
Copy-Item .env.example .env
```

Production Cloud Run 변수 계약은 role별로 나뉜다.

| Role | 필수 변수 |
|---|---|
| API/Worker 공통 | `APP_ENV`, `APP_ROLE`, `APP_PUBLIC_BASE_URL`, `GCP_PROJECT_ID`, `GCP_REGION`, `FIRESTORE_DATABASE`, `LOCAL_STAGING_BUCKET`, `GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET`, `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_SECRET_ID`, `SOURCE_CREDENTIAL_SECRET_PREFIX` |
| API | `SESSION_SECRET`, `FRONTEND_DIST_DIR`, Google login 3개, Drive redirect/webhook/channel 3개, Picker 2개, GitHub slug/webhook/callback 3개, `CLOUD_TASKS_LOCATION`, `CLOUD_TASKS_QUEUE`, `ANALYSIS_WORKER_URL`, `CLOUD_TASKS_SERVICE_ACCOUNT`, `SCHEDULER_SERVICE_ACCOUNT` |
| Worker | `VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG`, `KIPRIS_API_KEY_SECRET_ID`, `PACKAGE_METADATA_BASE_URL` |
| Worker 선택 RAG group | `RAG_REGION`, `RAG_CORPUS_ID`, `RAG_CORPUS_VERSION` 전체 또는 모두 생략 |
| local/Desktop | `IPRISK_SERVER_BASE_URL`, `IPRISK_DESKTOP_RENDERER_URL`; 필요 시 provider group |
| test only | `FIRESTORE_EMULATOR_HOST` |

`GEMINI_MODEL_ID`의 production 기준값은 `gemini-3.6-flash`다. production은
`FIRESTORE_DATABASE=ip-risk-agent-v2`와 canonical project/region/bucket/secret prefix만
허용하고 `(default)` 및 `FIRESTORE_EMULATOR_HOST`를 거부한다. API만 Cloud Tasks publisher와
Tasks caller act-as 설정을 사용한다. Worker는 자신의 `APP_PUBLIC_BASE_URL`을 inbound OIDC
audience로 사용하고 canonical v2 Tasks caller email을 코드 계약에서 얻으므로
`ANALYSIS_WORKER_URL`이나 Tasks publisher/caller 설정을 받지 않는다. Google Picker는 browser
API key와 project number `555102774494`를 함께 설정해야 한다.

Production fixed secret은 `iprisk-v2-*` ID와 Cloud Run Secret Manager mapping만 사용한다.
GitHub App private key와 KIPRIS key는 canonical secret ID만 환경에 두고 composition root가
attached service identity로 latest enabled version을 읽는다. Source credential은
`iprisk-v2-cred-{provider}-{digest}`만 생성·수락하고 v1/non-v2 reference를 거부한다.
서비스 계정 key file은 사용하지 않는다. 전체 naming/IAM matrix는
`docs/GCP_INTERNAL_DEPLOYMENT.md`와 `deploy/v2-resource-contract.yaml`을 따른다.

## Contract 생성과 검증

Contract schema에서 generated binding을 재생성한다.

```powershell
pnpm run generate
git diff --exit-code -- shared/contracts
```

두 번째 명령에서 diff가 발생하면 원인을 확인한다. Frozen Contract 변경을 일반 생성 결과로 commit해서는 안 된다.

전체 non-live baseline 및 integration 검증:

```powershell
python -m compileall -q backend/src shared/contracts/python scripts
python -m pip check
python -m pytest shared/contracts/tests tests/control tests/connectors tests/intelligence tests/integration tests/e2e -m "not live"

pnpm run typecheck
pnpm run build
pnpm run verify:resolution
pnpm --filter @iprisk/frontend test
pnpm --filter @iprisk/desktop test
pnpm install --frozen-lockfile

python scripts/validate_gcp_deployment.py
python scripts/prepare_rag_ingestion.py
```

Windows sandbox나 제한된 계정에서 pytest의 기본 temp 경로 권한이 거부되면 repository 내부의 ignored 경로를 명시할 수 있다.

```powershell
python -m pytest shared/contracts/tests tests/control tests/connectors tests/intelligence tests/integration tests/e2e -m "not live" --basetemp .venv/pytest-tmp
```

`live` marker는 실제 provider credential과 명시적 opt-in 없이 실행하지 않는다. Firestore emulator test는 `FIRESTORE_EMULATOR_HOST`가 없으면 skip되는 것이 정상이다.

## 로컬 실행 범위

API entrypoint는 factory로 조립한다. `SESSION_SECRET`에는 32자 이상의 로컬 전용 임의 값을 사용한다.

```powershell
$env:APP_ENV = "local"
$env:APP_ROLE = "api"
$env:SESSION_SECRET = "<32자 이상의 로컬 전용 임의 값>"
uvicorn ip_risk_agent.main:create_app --factory --host 127.0.0.1 --port 8000
```

`/health/live`는 프로세스 생존, `/health/ready`는 현재 role의 필수 구성 상태를 나타낸다. API는 Control route, 등록된 Source route와 `POST /api/v1/workspaces/{vws_id}/artifacts/{artifact_id}/open-original`을 한 application에 조립한다.

Worker entrypoint는 `ip_risk_agent.worker:create_app`이며 외부 제품 API를 노출하지 않고 `POST /internal/tasks/analyze-change`와 health route만 제공한다. Task body는 `change_event_id` 하나만 허용한다. 실제 로컬 분석에는 source adapter, intelligence facade와 task authenticator를 composition override로 명시적으로 주입해야 하며, 기본 구성 누락은 readiness 실패로 드러난다. Production entrypoint는 Google Cloud foundation과 role별 runtime composer를 자동 연결한다. API만 outbound Cloud Tasks enqueuer를 소유하고 Worker는 OIDC-authenticated task를 수신하며, 둘 다 Firestore/Secret Manager/GCS와 전체 source adapter가 없으면 시작 단계에서 실패하고 in-memory 구현으로 자동 대체하지 않는다.

Frontend 개발 서버는 다음과 같이 실행할 수 있다.

```powershell
pnpm --filter @iprisk/frontend dev
```

Vite는 `/api`를 `http://127.0.0.1:8000`으로 proxy한다. 로그인 후 Source 화면은 현재 workspace ID를 사용해 OAuth/install을 시작하고, callback 뒤 Drive Picker 또는 GitHub repository/branch 선택을 mount 생성까지 이어간다. Google Picker가 필요하면 `GOOGLE_PICKER_API_KEY`와 `GOOGLE_CLOUD_PROJECT_NUMBER`를 API 환경에 함께 설정한다. Built frontend는 API revision에 명시한 `FRONTEND_DIST_DIR=/app/frontend/dist`에서 same-origin으로 제공된다. 이 변수는 shared image 기본 ENV나 Worker 환경에 두지 않는다.

Desktop 개발 실행과 검증:

```powershell
$env:APP_ENV = "local"
$env:IPRISK_SERVER_BASE_URL = "http://127.0.0.1:8000"
$env:IPRISK_DESKTOP_RENDERER_URL = "http://127.0.0.1:5173"
pnpm --filter @iprisk/desktop build
pnpm --filter @iprisk/desktop start
pnpm --filter @iprisk/desktop test
```

개발 renderer는 loopback HTTP만 허용한다. Production Electron은 `IPRISK_SERVER_BASE_URL/app`의 same-origin HTTPS Product UI만 로드하며, `contextIsolation: true`, `nodeIntegration: false`, sandboxed CommonJS preload와 navigation allowlist를 사용한다. Local 절대 경로와 OS 암호화 device credential은 main process 밖으로 노출하지 않는다. Desktop event는 bearer 인증, transient retry와 실행 중 ordered offline queue를 사용하고 앱 재시작 시 ACTIVE watcher를 복구한다.

## 보안 불변조건

- SourceChange와 Cloud Tasks payload에는 content, filename, path, URL, secret을 넣지 않는다.
- Source Plane은 canonical Risk와 VWS state를 직접 변경하지 않는다.
- Intelligence Plane은 canonical database에 직접 쓰지 않는다.
- Drive/GitHub/Local adapter는 사용자가 명시적으로 선택한 scope 밖의 원문을 가져오지 않는다.
- RAG corpus에는 private Source Workspace 원문을 적재하지 않는다.
- production 설정 누락을 in-memory adapter로 조용히 대체하지 않는다.

**아직 달성되지 않은 목표 — 외부 provider failure, partial 또는 inconclusive 결과를 empty
success로 취급하지 않는다.** 이것을 이미 성립한 성질로 적으면 안 된다.
`docs/DEVELOPMENT_SPEC.md` §8.1이 기록하듯 지금 살아 있는 경로가 넷이고, 서로 독립적으로
같은 결말에 이른다 — 조각화(결함 1) · redaction(14) · 파싱 실패 삼킴(15) · 게이트
절단(16)이 각각 **의존성 0 건 → `succeeded([])` → coverage `COMPLETE` → 권위 있는 결과 →
기존 라이선스 Risk 전부 `RESOLVED`, 알림 0 건**으로 끝난다. 네 경로가 전부 `COMPLETE`로
끝나므로 `PARTIAL`을 손보는 것만으로는 막히지 않는다. 이 목표는 §11의 0 단계 항목
0-A~0-L이 닫는다(분류 층 0-C·0-D, 처분 층 0-E, 경로와 무관한 방벽 0-L). 그중 0-L의
1 걸음 — 의존성 아티팩트에서 후보가 N>0에서 0으로 떨어지는 전이는 예외 없이 권위를 갖지
못한다 — 이 선행이 없고 즉시 듣는다.

## 문서 기준

설계 및 구현 시 다음 우선순위를 사용한다.

1. `docs/DEVELOPMENT_SPEC.md` — **다음 단계 개발의 단일 기준.** 제품 방향, 알려진 결함과
   그것이 닫히는 자리(§8), 구현 순서(§11의 0~4 단계), 하지 않기로 한 것(§12).
2. `CODING_AGENT_MASTER_SPEC.md` — 도메인 용어, 시스템 경계, 공통 Contract, 보안 invariant,
   파일 ownership.
3. Plane별 상세 명세: `CODING_AGENT_SPEC_1_PLATFORM_CONTROL.md`,
   `CODING_AGENT_SPEC_2_SOURCE_DESKTOP.md`, `CODING_AGENT_SPEC_3_RISK_INTELLIGENCE_RAG.md`.
4. `README.md` — 설치, 고정 toolchain, 환경 변수 계약, dependency pin 근거, 검증 명령.
5. `docs/GCP_INTERNAL_DEPLOYMENT.md` — v1을 보호하는 v2 namespace/IAM/build 배포 계약.
   canonical 값의 source of truth는 `deploy/v2-resource-contract.yaml`이다.
6. `docs/STAGING_VERIFICATION_RUNBOOK.md` — 외부 배포 순서와 증거 형식.
7. `docs/RISK_DISPOSITION_POLICY.md` — `ReviewDisposition`의 뜻(2026-08-22 결정).
8. 설계 노트와 계획: `docs/PATENT_PRIORITY_DESIGN_NOTE.md`(특허 우선도 임계값 검토),
   `docs/GITHUB_LOCAL_DESKTOP_PLAN.md`(GitHub·Local·Desktop 마무리 계획).
9. 비규범 추적 기록: `docs/V3_DEVELOPMENT_WATCH.md`(개발 추적),
   `docs/INTEGRATION_V1_CROSSCHECK.md`(integration v1 대조).

`docs/DEVELOPMENT_SPEC.md`가 다음 단계의 기준이지만 저장소의 모든 문서를 대체하지는
않는다. 도메인 용어, frozen Contract와 보안 invariant는 여전히
`CODING_AGENT_MASTER_SPEC.md`와 `shared/contracts/**`가 소유한다. "대체된다"를 "지워도
된다"로 읽지 않는다.

기존 Agent delivery/dependency 원본 8개는 Phase 7 전체 검증 뒤 제거했고, Agent별 통합 참조
문서와 integration-v2 작업 문서(dependency baseline, execution plan, progress log)도
`docs/DEVELOPMENT_SPEC.md`로 수렴한 뒤 제거했다. 옮기지 않은 provenance는 Git history에만
남는다. 외부 배포 순서와 증거 형식은 `docs/STAGING_VERIFICATION_RUNBOOK.md`를 따른다.

## 통합 작업 규칙

- 모든 통합 변경은 `integration-v3`에서만 수행한다. `integration-v2`는 그 백업이며 v3 와 같은 커밋을 가리킨다.
- 가능하면 하나의 Phase를 하나의 commit으로 유지한다.
- phase gate가 통과하기 전에 다음 phase의 기능 변경을 섞지 않는다.
- manifest를 변경하면 lock, install, 전체 영향 Plane test 결과를 함께 갱신한다.
- GCP Console/IAM/resource 생성은 코드·배포 산출물과 전체 검증이 완료된 뒤 수행한다.
