# IP Risk Agent

IP Risk Agent는 Google Drive, GitHub, Local Desktop에서 선택한 소스의 변경을 감지하고 특허·라이선스 위험을 분석한 뒤, 사람이 검토하고 승인하는 흐름을 제공하는 IP 리스크 관리 시스템이다.

현재 `integration-v2`는 Phase 8 release candidate를 기준으로 Phase 9에 진입했다. 세 Plane, 고정 dependency/toolchain, P0 경계, API/Worker composition, Web/Electron 제품 흐름과 GCP 내부 배포 기반이 통합되어 전체 non-live regression을 통과했다. Firestore operational store, Secret Manager/GCS/Cloud Tasks/OIDC adapter, same-origin 정적 hosting, non-root image와 Cloud Build/Run/Tasks/Scheduler/TTL 입력물은 저장소 안에서 검증된다. 실제 GCP resource/IAM/credential 생성과 provider live 검증은 외부 project·권한·credential 입력을 기다리고 있다.

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
| GCP 외부 resource/IAM/live 배포 | Phase 9 착수, 외부 입력 대기 |

세부 상태와 검증 증거는 `INTEGRATION_V2_PROGRESS_LOG.md`에 기록한다. 이 로그는 통합 작업용 비규범 문서이며, 설계와 의존성 결정은 `INTEGRATION_V2_DEPENDENCY_BASELINE.md`와 `INTEGRATION_V2_EXECUTION_PLAN.md`가 우선한다.

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
docs/                             Agent별 통합 참조 문서
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

## 환경 변수

`.env.example`을 로컬 전용 `.env`로 복사하고 필요한 값만 설정한다. `.env`, secret, OAuth token, PEM, service-account JSON과 실제 resource ID를 commit하지 않는다.

```powershell
Copy-Item .env.example .env
```

Production Cloud Run 변수 계약은 role별로 나뉜다.

| Role | 필수 변수 |
|---|---|
| API/Worker 공통 | `APP_ENV`, `APP_ROLE`, `APP_PUBLIC_BASE_URL`, `GCP_PROJECT_ID`, `GCP_REGION`, `FIRESTORE_DATABASE`, `LOCAL_STAGING_BUCKET`, `GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET`, `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_SECRET_ID` |
| API | `SESSION_SECRET`, `FRONTEND_DIST_DIR`, Google login 3개, Drive redirect/webhook/channel 3개, Picker 2개, GitHub slug/webhook/callback 3개, `CLOUD_TASKS_LOCATION`, `CLOUD_TASKS_QUEUE`, `ANALYSIS_WORKER_URL`, `CLOUD_TASKS_SERVICE_ACCOUNT`, `SCHEDULER_SERVICE_ACCOUNT` |
| Worker | `ANALYSIS_WORKER_URL`, `CLOUD_TASKS_SERVICE_ACCOUNT`, `VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG`, `KIPRIS_API_KEY_SECRET_ID`, `PACKAGE_METADATA_BASE_URL` |
| Worker 선택 RAG group | `RAG_REGION`, `RAG_CORPUS_ID`, `RAG_CORPUS_VERSION` 전체 또는 모두 생략 |
| local/Desktop | `IPRISK_SERVER_BASE_URL`, `IPRISK_DESKTOP_RENDERER_URL`; 필요 시 provider group |
| test only | `FIRESTORE_EMULATOR_HOST` |

`GEMINI_MODEL_ID`의 production 기준값은 `gemini-3.6-flash`다. `FIRESTORE_EMULATOR_HOST`는 test 전용이며 production에서 설정하지 않는다. API는 Cloud Tasks queue publisher 설정을 사용하고 Worker는 `ANALYSIS_WORKER_URL`과 caller service account로 inbound OIDC만 검증한다. Worker는 queue location/name 또는 Scheduler/Google Login/Picker 설정을 요구하지 않는다. Google Picker는 browser API key와 Cloud project number를 함께 설정해야 하며 API production 시작 시 두 값이 모두 필요하다.

Production secret은 Secret Manager reference 또는 Cloud Run Secret Manager mapping으로 해석해야 한다. GitHub App private key와 KIPRIS key는 secret ID만 환경에 두고 composition root가 attached service identity로 latest enabled version을 읽는다. 서비스 계정 key file은 사용하지 않는다. `.env.example`에 비밀 값이나 예시 private key를 추가하지 않는다. Google Picker browser key는 secret이 아니지만 허용 origin과 Picker API로 제한해야 하며, project number와 함께 설정하거나 둘 다 비워야 한다.

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

Vite는 `/api`를 `http://127.0.0.1:8000`으로 proxy한다. 로그인 후 Source 화면은 현재 workspace ID를 사용해 OAuth/install을 시작하고, callback 뒤 Drive Picker 또는 GitHub repository/branch 선택을 mount 생성까지 이어간다. Google Picker가 필요하면 `GOOGLE_PICKER_API_KEY`와 `GOOGLE_CLOUD_PROJECT_NUMBER`를 API 환경에 함께 설정한다. Built frontend는 production image의 `FRONTEND_DIST_DIR`에서 API와 same-origin으로 제공된다.

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
- 외부 provider failure, partial 또는 inconclusive 결과를 empty success로 취급하지 않는다.
- RAG corpus에는 private Source Workspace 원문을 적재하지 않는다.
- production 설정 누락을 in-memory adapter로 조용히 대체하지 않는다.

## 문서 기준

설계 및 구현 시 다음 우선순위를 사용한다.

1. `CODING_AGENT_MASTER_SPEC.md`와 세 상세 명세
2. `IP_RISK_AGENT_MEETING_BLUEPRINT.md`
3. `INTEGRATION_V2_DEPENDENCY_BASELINE.md`
4. `INTEGRATION_V2_EXECUTION_PLAN.md`
5. `docs/AGENT_1_PLATFORM_CONTROL.md`
6. `docs/AGENT_2_SOURCE_DESKTOP.md`
7. `docs/AGENT_3_RISK_INTELLIGENCE_RAG.md`

`INTEGRATION_V2_PROGRESS_LOG.md`는 진행 추적용 부가 기록이다. 기존 Agent delivery/dependency 원본 8개는 Phase 7 전체 검증 뒤 제거했으며, provenance는 세 통합 문서의 표와 Git history에 남는다. 외부 배포 순서와 증거 형식은 `docs/STAGING_VERIFICATION_RUNBOOK.md`를 따른다.

## 통합 작업 규칙

- 모든 통합 변경은 `integration-v2`에서만 수행한다.
- 가능하면 하나의 Phase를 하나의 commit으로 유지한다.
- phase gate가 통과하기 전에 다음 phase의 기능 변경을 섞지 않는다.
- manifest를 변경하면 lock, install, 전체 영향 Plane test 결과를 함께 갱신한다.
- GCP Console/IAM/resource 생성은 코드·배포 산출물과 전체 검증이 완료된 뒤 수행한다.
