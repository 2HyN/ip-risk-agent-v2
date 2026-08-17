# Agent 1 Dependency and Environment Request

## Status

- Owner: Agent 1 — Platform & Control Plane
- State: Agent 1 feature 단계별 자체 선택/설치 허용; 최종 root pin은 Integration 단계 검토
- Python compatibility target: CPython 3.14.7
- Existing fixed packages: Pydantic 2.13.4, pytest 9.1.1

Agent 1은 각 feature 구현에 필요한 package를 독자적으로 선택하고 현재 `.venv`/workspace에서 호환성을 검사해 설치할 수 있다. 선택 버전과 검사 결과는 이 문서에 누적한다. Root manifest와 최종 lockfile pin은 Integration 단계에서 다른 Plane과의 충돌 여부를 확인해 최대한 반영한다. 모든 선택은 Python 3.14.7 또는 Node.js 24.19.0과 호환되어야 한다.

Phase 0~3과 Phase 10에서는 신규 package가 필요하지 않아 추가 설치를 수행하지 않았다. Phase 11에서는 아래 React/Vite dependency를 root lockfile 변경 없이 `frontend/package.json`에 pin하고 Node.js 24.19.0에서 설치·typecheck·test·production build를 검증했다.

## 검증 완료 dependency 선택

| Phase | Package | 검증 버전 | 검증 결과 |
|---|---|---:|---|
| 4 | `google-cloud-firestore` | `2.28.1` | CPython 3.14.7 설치/import, async client/transaction API inspection, `pip check`, fake backend 전체 persistence test 통과 |
| 9 | `fastapi` | `0.141.1` | Pydantic 2.13.4/CPython 3.14.7 import, router factory/OpenAPI 생성, Control API test 통과 |
| 9 | `authlib` | `1.7.2` | Google discovery 기반 OIDC state/nonce/ID token 처리와 PKCE 설정 API inspection, fake provider login test 통과 |
| 9 | `httpx` | `0.28.1` | Authlib async OAuth/OIDC runtime 호환 및 `pip check` 통과 |
| 9 | `itsdangerous` | `2.2.0` | signed cursor와 Starlette signed session dependency 호환 검증 |
| 9 | `httpx2` | `2.10.0` | Starlette 1.6.0 TestClient 권장 development dependency, API suite 경고 없이 통과 |
| 11 | `react`, `react-dom` | `19.2.8` | Node.js 24.19.0, strict TypeScript, Testing Library component test와 Vite production build 통과 |
| 11 | `react-router-dom` | `7.18.2` | React 19 peer 및 Node >=20 조건 확인, BrowserRouter/HashRouter Web·Electron 공용 route test 통과 |
| 11 | `vite`, `@vitejs/plugin-react` | `8.2.1`, `6.0.5` | Node `^20.19 || >=22.12` 조건 확인, 45 modules production build 통과 |
| 11 | `vitest`, `jsdom` | `4.1.10`, `30.0.1` | Node.js 24.19.0에서 jsdom 조건(`^24.15` branch) 충족, 9 frontend test 통과 |
| 11 | Testing Library | `@testing-library/react 16.3.2`, `dom 10.4.1`, `user-event 14.6.4`, `jest-dom 7.0.1` | React 19 peer, 접근성 role 기반 component test 통과 |
| 11 | React/Node type packages | `@types/react 19.2.18`, `@types/react-dom 19.2.4`, `@types/node 26.2.0` | TypeScript 5.9.3 strict/noUnchecked/exactOptional 전체 통과 |

Phase 4 검증 환경에서 `google-cloud-firestore==2.28.1`을 설치했다. 직접 dependency인 `grpcio==1.83.0`은 CPython 3.14 Windows wheel로 설치됐고 전체 dependency graph는 `pip check`를 통과했다. Root `pyproject.toml`과 lockfile은 Agent 1 소유 범위가 아니므로 수정하지 않았으며, Integration 단계의 최종 pin 후보는 `google-cloud-firestore==2.28.1`이다.

Phase 9 검증 환경에서는 `fastapi==0.141.1`, `authlib==1.7.2`, `httpx==0.28.1`, `itsdangerous==2.2.0`과 API test 전용 `httpx2==2.10.0`을 설치했다. FastAPI가 선택한 `starlette==1.6.0` 및 전체 dependency graph가 CPython 3.14.7에서 `pip check`와 Control API suite를 통과했다. Authlib OIDC runtime은 `httpx`, Starlette TestClient는 현행 권장인 `httpx2`를 사용하므로 두 package는 역할이 다르다. Root manifest와 lockfile은 수정하지 않았고 Integration 단계 pin 후보로만 기록한다.

Phase 11 dependency metadata는 2026-08-17 npm registry의 current stable release와 engine/peer 조건을 직접 확인했다. `pnpm install --filter @iprisk/frontend --lockfile=false`로 검증 환경만 구성했으며 root `package.json`과 `pnpm-lock.yaml`은 수정하지 않았다. Vite dev server는 `/api`를 `127.0.0.1:8000`으로 proxy하고 production bundle은 same-origin `/api/v1`을 사용한다.

## Python runtime dependencies

| Package/capability | Purpose | Requirement |
|---|---|---|
| FastAPI | Control-owned HTTP API와 dependency injection | `fastapi==0.141.1` 검증 완료 |
| Uvicorn | 개발 및 Cloud Run ASGI runtime | 선택한 FastAPI/Starlette와 호환 |
| Google Cloud Firestore client | Canonical Firestore repositories와 transaction | `google-cloud-firestore==2.28.1` 검증 완료 |
| Authlib 또는 동등 OIDC client | Google OIDC authorization-code flow, discovery, state/nonce/ID token 검증과 PKCE | `authlib==1.7.2` 검증 완료 |
| HTTPX 또는 동등 async HTTP client | OIDC discovery/token/userinfo 통신 | `httpx==0.28.1` 검증 완료 |
| itsdangerous 또는 동등 signing capability | Secure application session/state와 cursor signing | `itsdangerous==2.2.0` 검증 완료 |

## Python development dependencies

| Package/capability | Purpose | Requirement |
|---|---|---|
| pytest-asyncio | Async application/repository/API test | pytest 9.1.1 및 Python 3.14.7 호환 |
| HTTPX2 | Starlette TestClient transport | `httpx2==2.10.0` 검증 완료 |
| Firestore emulator support | Transaction, deterministic ID, concurrency persistence test | production credential 불필요 |

## Frontend runtime dependencies

| Package/capability | Purpose | Requirement |
|---|---|---|
| React | Product Web UI | `react==19.2.8` 검증 완료 |
| React DOM | Browser/Electron renderer | `react-dom==19.2.8` 검증 완료 |
| React Router | Auth/VWS/Risk/History/Security routing | `react-router-dom==7.18.2` 검증 완료 |

## Frontend development dependencies

| Package/capability | Purpose | Requirement |
|---|---|---|
| Vite | Web build/dev server | `vite==8.2.1` 검증 완료 |
| Vite React plugin | React transform/build | `@vitejs/plugin-react==6.0.5` 검증 완료 |
| Vitest | Frontend unit/component test | `vitest==4.1.10` 검증 완료 |
| Testing Library | 접근성 중심 component test | 위 검증 완료 exact versions 반영 |
| jsdom | Browser DOM test environment | `jsdom==30.0.1`, Node 24.19.0 검증 완료 |

## Environment variables

```text
GOOGLE_LOGIN_CLIENT_ID
GOOGLE_LOGIN_CLIENT_SECRET
GOOGLE_LOGIN_REDIRECT_URI
SESSION_SECRET
APP_PUBLIC_BASE_URL
GCP_PROJECT_ID
FIRESTORE_DATABASE
FIRESTORE_EMULATOR_HOST  # emulator test에서만 사용
```

실제 secret은 `.env.example`, source, fixture 또는 log에 기록하지 않는다.

## External services and local test facilities

- Google OIDC application registration and redirect URI
- Firestore Native database for production
- Firestore emulator for persistence tests
- Integration-provided Cloud Tasks enqueue adapter; Agent 1은 protocol만 소유

## Root/config wiring requests

1. 위 dependency를 root Python/Frontend manifest와 lockfile에 병합한다.
2. `tests/control/**`를 기본 pytest 실행 범위에 포함한다.
3. Firestore emulator test command와 필요한 environment binding을 제공한다.
4. Windows contract test 실행 시 `PNPM_EXECUTABLE`에 `pnpm.cmd`를 지정한다.
5. Agent 1 router/facade의 실제 등록은 Integration 전용 `composition/**`, `main.py`, `worker.py`에서 수행한다.

## Version selection policy

Agent 1은 package가 처음 필요한 Phase에서 최신 안정 release를 우선 검토하고 Python/Node 기준 버전, 기존 Pydantic/pytest/TypeScript, 직접 및 전체 회귀 test로 호환성을 확인한다. 검증된 개발 버전은 이 문서에 기록한다. 최종 pin은 Integration Owner가 전체 Plane dependency를 비교해 충돌이 없는 한 해당 검증 버전을 반영한다.
