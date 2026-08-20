# integration-v2 Dependency Baseline

> 상태: **통합 전 확정안**  
> 기준일: 2026-08-21  
> 적용 대상: `integration-v2`에 `platform-control`, `source-integration-desktop`, `risk-intelligence-rag`를 통합하는 작업  
> 목적: 병합 전에 runtime, package, 외부 service 및 환경 변수의 단일 기준을 확정한다.

## 1. 결론

통합 기준 runtime은 다음으로 고정한다.

| 항목 | 확정 버전 |
|---|---:|
| CPython | `3.14.7` (`>=3.14,<3.15`) |
| Node.js | `24.19.0` |
| pnpm | `11.19.0` |
| TypeScript | `5.9.3` |
| Pydantic | `2.13.4` |
| pytest | `9.1.1` |

Python direct dependency는 §5, frontend/desktop dependency는 §7의 exact version을 사용한다. `pnpm-lock.yaml`은 어느 feature branch의 파일도 그대로 채택하지 않고, 통합된 manifest를 기준으로 `integration-v2`에서 다시 생성한다.

Gemini production model ID는 Master Spec과 현재 공식 stable endpoint가 일치하는 다음 값으로 확정한다.

```text
GEMINI_MODEL_ID=gemini-3.6-flash
```

`gemini-3-flash-preview`는 과거 Agent 3 실호출 검증값일 뿐 최종 production 값으로 사용하지 않는다.

## 2. 분석 대상과 repository 상태

분석 시점의 worktree는 모두 clean 상태였다.

| Worktree / branch | HEAD | 기준과의 관계 |
|---|---|---|
| `main` | `7cfbec446ac50fcc36c14031cb4310c30c8a0e5c` | 기준 |
| `integration-v2` | `7cfbec446ac50fcc36c14031cb4310c30c8a0e5c` | `main`과 동일 |
| `platform-control` | `de1dacce05474d4e3e6c7c2567f6b8a6bbdbeb64` | `main`보다 15 commits ahead |
| `source-integration-desktop` | `ee861b730d161caf876d2a300b476783d03bbaf6` | `main`보다 29 commits ahead |
| `risk-intelligence-rag` | `68e07a3fdf543bcb4871cb13aee95fcc64b5749d` | `main`보다 5 commits ahead |

검토한 공통 문서는 다섯 worktree에서 SHA-256이 동일했다.

- `CODING_AGENT_MASTER_SPEC.md`
- `CODING_AGENT_SPEC_1_PLATFORM_CONTROL.md`
- `CODING_AGENT_SPEC_2_SOURCE_DESKTOP.md`
- `CODING_AGENT_SPEC_3_RISK_INTELLIGENCE_RAG.md`
- `IP_RISK_AGENT_MEETING_BLUEPRINT.md`
- `ENVIRONMENT_SETUP.md`

각 feature branch에서는 다음 인계 문서를 추가로 검토했다.

- `AGENT_1_DELIVERY.md`, `agent-deliverables/agent-1-dependencies.md`
- `AGENT_2_DELIVERY.md`, `agent-deliverables/agent-2-dependencies.md`
- `AGENT_3_DELIVERY.md`, `agent-deliverables/agent-3-dependencies.md`

## 3. 결정 우선순위

dependency 결정에는 다음 순서를 적용한다.

1. Master Spec의 security invariant와 frozen contract
2. 실제 baseline manifest와 runtime
3. feature branch의 실제 import 및 public wiring surface
4. 각 Agent가 기록한 실측 test 결과
5. 공식 package registry의 Python/Node/peer compatibility
6. 최신 버전보다 이미 검증된 exact version 우선

이 원칙에 따라 다음 문서 불일치를 정정한다.

| 불일치 | 확정 |
|---|---|
| `ENVIRONMENT_SETUP.md`의 Python `3.12.13` | 실제 `pyproject.toml`, Agent 1/2 검증값인 `3.14.7` 사용 |
| Agent 3의 Python `3.13` 개발 기록 | 통합 runtime `3.14.7`에서 재검증 필요 |
| Agent 3 dependency 문서의 Pydantic `2.13.3` | frozen contract baseline인 `2.13.4` 사용 |
| Source의 FastAPI `0.121.2`와 Control의 `0.141.1` | 단일 app이므로 `0.141.1` 사용 |
| Agent 3의 “Gemini 3.6 Flash ID 없음” 기록 | 현재 공식 stable ID `gemini-3.6-flash` 사용 |

## 4. dependency 분류 원칙

- 코드에서 직접 import하는 package는 transitive dependency에 기대지 않고 direct dependency로 선언한다.
- application runtime과 test-only package를 분리한다.
- feature package에는 exact version을 기록하고, 최종 lockfile도 함께 commit한다.
- `google-cloud-aiplatform`은 추가하지 않는다. 현재 RAG 구현은 `google-auth` + `httpx` REST client를 사용한다.
- `requests`를 별도 direct dependency로 추가하지 않는다. `google-auth[requests]` extra로 transport requirement를 명시한다.
- Cloud Run runtime, Secret Manager vault, Cloud Tasks queue, Local staging 구현에 필요한 Integration-owned package도 병합 전에 확정한다.

## 5. Python direct dependencies

### 5.1 Runtime

아래 목록을 root `pyproject.toml`의 production dependency 기준으로 사용한다.

| Package | 확정 requirement | 소유/사용 영역 | 근거 |
|---|---|---|---|
| `pydantic` | `==2.13.4` | Shared | frozen Contract v1 baseline |
| `fastapi` | `==0.141.1` | Control, Source, Integration | 두 Plane의 router가 하나의 app에 설치됨; 상위 Control 검증 버전 선택 |
| `starlette` | `==1.6.0` | Control API | Control 코드가 Starlette를 직접 import하므로 direct pin; FastAPI 0.141.1 조합 |
| `google-cloud-firestore` | `==2.28.1` | Control | async Firestore repository/transaction |
| `authlib` | `==1.7.2` | Control | Google OIDC flow |
| `httpx` | `==0.28.1` | Control, Source, Intelligence | OIDC, GitHub, KIPRIS, package metadata, RAG REST 공용 async client |
| `itsdangerous` | `==2.2.0` | Control | session/cursor signing 및 SessionMiddleware |
| `google-api-python-client` | `==2.198.0` | Source | Google Drive API v3 |
| `google-auth[requests]` | `==2.56.3` | Source, Intelligence, GCP | OAuth credential refresh, ADC, RAG token refresh |
| `PyJWT[crypto]` | `==2.10.1` | Source | GitHub App RS256 JWT |
| `defusedxml` | `==0.7.1` | Intelligence | 외부 KIPRIS XML 안전 파싱 |
| `PyYAML` | `==6.0.3` | Intelligence | RAG corpus manifest의 `safe_load` |
| `google-genai` | `==2.17.0` | Intelligence | Gemini structured output; Agent 3 실호출 검증 버전 |
| `uvicorn[standard]` | `==0.52.4` | Integration | Cloud Run/local ASGI runtime |
| `google-cloud-secret-manager` | `==2.30.0` | Integration | provider credential vault production adapter |
| `google-cloud-tasks` | `==2.24.0` | Integration | content-free analysis task enqueue |
| `google-cloud-storage` | `==3.13.1` | Integration | private Local snapshot staging |

### 5.2 Development/test

| Package | 확정 requirement | 용도 |
|---|---|---|
| `pytest` | `==9.1.1` | 전체 Python test |
| `pytest-asyncio` | `==1.4.0` | Intelligence async provider test; strict mode |
| `httpx2` | `==2.10.0` | Starlette 1.6.0 `TestClient` transport |

`pytest-asyncio` 도입 시 root 설정에 다음을 명시한다.

```toml
[tool.pytest.ini_options]
asyncio_mode = "strict"
markers = [
  "live: tests requiring real external providers or credentials",
]
```

기존 root의 `--strict-markers`를 유지하므로 `live` marker 등록은 필수다. Control/Source가 사용하는 `asyncio.run` 기반 test에는 동작 변경이 없어야 한다.

### 5.3 중요한 transitive resolution

2026-08-21 CPython 3.14.7에서 위 direct set을 `pip install --dry-run --ignore-installed`로 해석했으며 dependency conflict 없이 성공했다. 주요 해석 결과는 다음과 같다.

| Package | 해석 버전 | 주의점 |
|---|---:|---|
| `pydantic-core` | `2.46.4` | Pydantic 2.13.4 exact dependency |
| `grpcio` | `1.83.0` | CPython 3.14 Windows wheel 존재 |
| `protobuf` | `7.35.1` | Google Cloud clients 공통 범위 충족 |
| `cryptography` | `50.0.0` | Google Auth/PyJWT crypto 공통 범위 충족 |
| `google-api-core` | `2.34.0` | Firestore/Tasks/Secret Manager 공통 범위 충족 |
| `requests` | `2.34.2` | `google-auth[requests]` 및 `google-genai`가 제공 |

이 표의 transitive package를 `pyproject.toml`에 임의 direct dependency로 추가하지 않는다. 재현 가능한 배포를 위해 통합 후 Python lock/constraints 파일을 생성하고 실제 해석 결과를 고정한다.

## 6. Python 충돌 해결

### 6.1 FastAPI

결정: `fastapi==0.141.1`, `starlette==1.6.0`.

- Control은 FastAPI `0.141.1`로 API와 Product backend를 검증했다.
- Source는 `0.121.2`를 요청했지만 사용하는 API는 `APIRouter`, `Request`, `HTTPException`, `TestClient` 중심이다.
- 두 버전을 한 Python environment에 동시에 설치할 수 없고 router도 하나의 FastAPI app에 mount된다.
- 따라서 상위 버전인 Control 기준으로 통일하고 Source connector suite를 병합 후 반드시 다시 실행한다.
- Starlette 1.6.0의 `TestClient`가 요구하는 `httpx2`와 application/provider HTTP client인 `httpx`는 서로 다른 package이므로 함께 유지한다.

### 6.2 Pydantic

결정: `pydantic==2.13.4`.

Frozen Contract가 실제 source of truth이므로 Agent 3의 개발 기록 `2.13.3`보다 baseline `2.13.4`가 우선한다. 세 Plane 모두 strict Pydantic v2 model을 사용하므로 minor drift를 허용하지 않는다.

### 6.3 Google Auth transport

결정: `google-auth[requests]==2.56.3`.

Source의 Drive client와 Intelligence의 RAG client가 모두 `google.auth.transport.requests.Request`를 직접 사용한다. base `google-auth`만 선언하면 `requests` extra가 보장되지 않으므로 extra를 명시한다.

### 6.4 RAG SDK

결정: `google-cloud-aiplatform` 미채택.

현재 코드가 RAG `retrieveContexts`를 `httpx` REST로 호출하며 ADC/token refresh만 `google-auth`에 맡긴다. 대형 SDK를 추가할 구현상 필요가 없다. RAG REST contract가 바뀌거나 ingestion 구현이 SDK 전용 기능을 요구할 때만 재평가한다.

## 7. Node, frontend, desktop dependencies

### 7.1 Root toolchain

| Package/tool | 확정 버전 |
|---|---:|
| Node.js | `24.19.0` |
| pnpm | `11.19.0` |
| `typescript` | `5.9.3` |

Node `24.19.0`은 Vite 8.2.1, Vitest 4.1.10, jsdom 30.0.1, Electron 43.4.0 및 Chokidar 5.0.0의 engine 범위를 모두 충족한다.

### 7.2 `frontend`

Control의 Product UI manifest를 기준으로 하고 Source UI를 그 위에 통합한다.

#### Runtime

| Package | 확정 버전 |
|---|---:|
| `@iprisk/contracts` | `workspace:*` |
| `react` | `19.2.8` |
| `react-dom` | `19.2.8` |
| `react-router-dom` | `7.18.2` |

#### Development/test

| Package | 확정 버전 |
|---|---:|
| `typescript` | `5.9.3` |
| `vite` | `8.2.1` |
| `@vitejs/plugin-react` | `6.0.5` |
| `vitest` | `4.1.10` |
| `jsdom` | `30.0.1` |
| `@testing-library/react` | `16.3.2` |
| `@testing-library/dom` | `10.4.1` |
| `@testing-library/user-event` | `14.6.4` |
| `@testing-library/jest-dom` | `7.0.1` |
| `@types/react` | `19.2.18` |
| `@types/react-dom` | `19.2.4` |
| `@types/node` | `26.2.0` |

Frontend의 `@types/node`는 Vite config/test compile scope에만 사용되며 browser production bundle의 runtime API를 결정하지 않는다. Control이 strict TypeScript 환경에서 검증한 `26.2.0`을 유지한다.

### 7.3 `apps/desktop`

| 구분 | Package | 확정 버전 |
|---|---|---:|
| Runtime | `@iprisk/contracts` | `workspace:*` |
| Runtime | `chokidar` | `5.0.0` |
| Development/runtime shell | `electron` | `43.4.0` |
| Development | `@types/node` | `24.13.3` |
| Development | `typescript` | `5.9.3` |

Desktop은 Node 24 runtime API를 직접 많이 사용하므로 `@types/node`도 source branch lock에서 실제 해석된 `24.13.3`으로 exact pin한다.

## 8. frontend merge 시 확정할 설정

두 branch가 동시에 변경한 파일은 다음 네 개뿐이다.

```text
frontend/index.html
frontend/package.json
frontend/tsconfig.json
frontend/vite.config.ts
```

통합 원칙은 다음과 같다.

1. `frontend/package.json`: Control manifest를 기준으로 §7.2 exact version을 적용한다. Source UI는 추가 runtime package가 필요하지 않다.
2. `frontend/tsconfig.json`: Control의 `moduleResolution: "Bundler"`, `noEmit: true`, strict 옵션을 유지한다.
3. `frontend/vite.config.ts`: Control의 `/api -> http://127.0.0.1:8000` proxy, Vitest/jsdom 설정, sourcemap을 유지한다.
4. Source의 Node test 3개는 Vitest로 포팅하고 필요하면 파일별 `// @vitest-environment node`를 사용한다.
5. `frontend/index.html`: Control의 실제 Product entrypoint를 유지한다. `frontend/src/sources/dev/preview.tsx`는 integration slot 연결 후 production entrypoint로 사용하지 않는다.
6. `apps/desktop`은 Source의 `NodeNext` compile과 `node --test` 체계를 유지한다.

Source branch의 `pnpm-lock.yaml`은 Integration-only 경계를 벗어나 변경된 파일이며 Control dependency를 포함하지 않는다. 따라서 그대로 선택하거나 단순 conflict resolution하지 않고 최종 manifest에서 새로 생성한다.

## 9. 외부 service와 non-package dependencies

| Service | 확정 방향 | 상태/주의점 |
|---|---|---|
| Google OIDC | App login | exact redirect URI 필요 |
| Google Drive API + Picker | `drive.file`, selected files | App login credential과 분리 |
| GitHub App | selected repository, read-only | PAT 미채택, webhook HMAC 필수 |
| Firestore Native | canonical application state | Seoul Application Plane |
| Cloud Tasks | content-free async queue | payload는 `change_event_id`만 |
| Cloud Storage | Local transient staging | Seoul private bucket, short TTL, public URL 금지 |
| Secret Manager | provider secrets | service-account JSON key 배포 금지 |
| Gemini | `gemini-3.6-flash` | stable model ID, structured output 사용 |
| KIPRIS Plus | patent search/evidence | 0건과 provider failure 구분 |
| Vertex AI RAG Engine | reference knowledge only | exact external GA region은 GCP 구성 단계에서 확정 |
| RagManagedDb | Basic tier initial target | private Source Workspace 원문 ingestion 금지 |
| deps.dev/PyPI/npm metadata | license fact lookup | provider failure는 empty success로 변환 금지 |

RAG의 exact region, corpus ID 및 managed DB resource는 package dependency가 아니라 배포 resource이므로 이 문서에서 임의 값으로 고정하지 않는다.

## 10. 통합 환경 변수 기준

실제 값과 secret은 source, `.env.example`, fixture, log 또는 task payload에 기록하지 않는다. 아래 이름만 root `.env.example` 및 Integration settings schema에 합친다.

### 10.1 Shared/application

| 변수 | 필요 조건 | 용도 |
|---|---|---|
| `GCP_PROJECT_ID` | GCP runtime 필수 | 공통 project ID |
| `FIRESTORE_DATABASE` | production 필수 | Firestore database ID |
| `APP_PUBLIC_BASE_URL` | production 필수 | redirect/CORS/cookie 기준 |
| `SESSION_SECRET` | production 필수 | 최소 32자 session/cursor signing secret |
| `FIRESTORE_EMULATOR_HOST` | test only | production 설정 금지 |

### 10.2 App login

```text
GOOGLE_LOGIN_CLIENT_ID
GOOGLE_LOGIN_CLIENT_SECRET
GOOGLE_LOGIN_REDIRECT_URI
```

### 10.3 Google Drive

```text
GOOGLE_DRIVE_CLIENT_ID
GOOGLE_DRIVE_CLIENT_SECRET
GOOGLE_DRIVE_REDIRECT_URI
GOOGLE_DRIVE_WEBHOOK_BASE_URL
DRIVE_WATCH_CHANNEL_TOKEN
```

### 10.4 GitHub App

```text
GITHUB_APP_ID
GITHUB_APP_SLUG
GITHUB_APP_CALLBACK_URL
GITHUB_APP_PRIVATE_KEY_SECRET_ID
GITHUB_WEBHOOK_SECRET_ID
```

Production은 Secret Manager reference ID를 사용한다. local test에서 direct secret injection이 필요하면 Integration settings의 별도 입력으로 처리하되 `.env.example`에 PEM/secret 값을 예시로 넣지 않는다.

### 10.5 Local Desktop/staging

```text
LOCAL_STAGING_BUCKET
IPRISK_SERVER_BASE_URL
```

### 10.6 Cloud Tasks

```text
CLOUD_TASKS_LOCATION
CLOUD_TASKS_QUEUE
ANALYSIS_WORKER_URL
CLOUD_TASKS_SERVICE_ACCOUNT
```

네 값을 하나의 validated configuration group으로 다룬다. 일부만 설정된 상태에서 silent in-memory fallback을 허용하지 않는다.

### 10.7 Intelligence

```text
GEMINI_MODEL_ID
GEMINI_API_KEY                      # local/live test 또는 AI Studio 사용 시만
VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG
KIPRIS_API_KEY_SECRET_ID
KIPRIS_ACCESS_KEY                   # Integration이 secret을 해석해 주입하는 runtime 값
RAG_REGION
RAG_CORPUS_ID
RAG_CORPUS_VERSION
PACKAGE_METADATA_BASE_URL
```

Production GCP에서는 Gemini에 API key보다 attached service identity/Vertex 설정을 우선한다. 현재 Agent 3의 `IntelligenceConfig.from_env()`는 `VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG`를 직접 변환하지 않으므로, Integration은 명시적 `IntelligenceConfig(vertex_config=...)` 조립 또는 settings adapter를 구현한 뒤 production 경로를 활성화해야 한다.

`GEMINI_MODEL_ID`의 확정값:

```text
gemini-3.6-flash
```

## 11. root manifest 적용 계획

실제 merge 후 다음 순서로 적용한다.

1. 세 feature branch를 `integration-v2`에 병합한다.
2. root `pyproject.toml`에 §5 direct dependencies와 dev group을 반영한다.
3. pytest `testpaths`를 shared contracts와 `tests/control`, `tests/connectors`, `tests/intelligence`, 이후 integration/e2e까지 포함하도록 확장한다.
4. `live` marker와 `asyncio_mode = "strict"`를 등록한다.
5. frontend/desktop manifest를 §7 exact version으로 정리한다.
6. Source branch의 lockfile을 폐기하고 root에서 `pnpm install`로 `pnpm-lock.yaml`을 재생성한다.
7. Python dependency lock/constraints를 CPython 3.14.7 기준으로 생성한다.
8. generated files와 lockfile만 dependency 변경 결과로 commit한다.

## 12. 검증 gate

dependency 확정은 문서 작성만으로 완료되지 않는다. merge와 manifest 반영 후 아래 gate를 모두 통과해야 한다.

```powershell
python --version
node --version
pnpm --version

python -m pip install -e ".[dev]"
python -m pip check

python scripts/generate_contracts.py
python -m pytest shared/contracts/tests tests/control tests/connectors tests/intelligence -m "not live"
python -m compileall -q backend/src shared/contracts/python scripts

pnpm install --frozen-lockfile
pnpm run typecheck
pnpm run verify:resolution
pnpm --filter @iprisk/frontend test
pnpm --filter @iprisk/frontend build
pnpm --filter @iprisk/desktop build
pnpm --filter @iprisk/desktop test
```

추가 필수 회귀:

- FastAPI 0.141.1에서 Source connector Python suite 전체 통과
- Pydantic 2.13.4에서 Intelligence suite 전체 통과
- Source frontend test의 Vitest 포팅 후 전체 frontend test 통과
- `pnpm install --frozen-lockfile` 재실행 성공
- Windows 및 Cloud Run target에서 CPython 3.14 wheel/install 확인
- 실제 GCP staging에서 Firestore, Secret Manager, Cloud Tasks, Cloud Storage, Gemini, RAG 연결 확인
- provider failure가 기존 Risk를 resolve하지 않는 integration test 통과

## 13. 현재 남은 결정과 blocker

dependency 버전 자체는 확정했다. 다음 항목은 이후 단계에서 별도 확정 또는 구현이 필요하다.

1. Vertex AI RAG Engine의 external GA region과 corpus resource ID
2. Cloud Tasks retry/rate/dead-letter 정책
3. Local staging TTL 및 bucket lifecycle rule
4. Firestore composite index deployment file
5. Intelligence production Vertex config adapter
6. Source `AuthzDependency`, canonical callback, vault/runtime store의 production binding
7. Agent 3 RAG Engine 실환경 test

위 항목은 dependency version을 바꾸는 근거가 아니다. 구현 중 package 변경이 필요하면 이 문서의 변경 사유, 영향 Plane, 재검증 결과와 lockfile diff를 함께 갱신한다.

## 14. 공식 검증 자료

- [FastAPI 0.141.1 metadata](https://pypi.org/project/fastapi/0.141.1/)
- [Starlette 1.6.0 metadata](https://pypi.org/pypi/starlette/1.6.0/json)
- [Google Cloud Firestore 2.28.1 metadata](https://pypi.org/project/google-cloud-firestore/2.28.1/)
- [Google Gen AI SDK 2.17.0 metadata](https://pypi.org/project/google-genai/2.17.0/)
- [Google API Python Client 2.198.0 metadata](https://pypi.org/project/google-api-python-client/2.198.0/)
- [Google Cloud Storage 3.13.1 metadata](https://pypi.org/project/google-cloud-storage/3.13.1/)
- [Gemini model catalog](https://ai.google.dev/gemini-api/docs/models)
- [Gemini deprecation schedule](https://ai.google.dev/gemini-api/docs/deprecations)
- [React package metadata](https://www.npmjs.com/package/react)
- [Vitest package metadata](https://www.npmjs.com/package/vitest)

