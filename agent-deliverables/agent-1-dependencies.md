# Agent 1 Dependency and Environment Request

## Status

- Owner: Agent 1 — Platform & Control Plane
- State: requested; root manifest merge pending Integration Owner
- Python compatibility target: CPython 3.14.7
- Existing fixed packages: Pydantic 2.13.4, pytest 9.1.1

Agent 1은 root manifest와 lockfile을 수정하지 않는다. 아래 항목의 실제 버전 선택, lockfile 갱신과 runtime wiring은 Integration Owner가 담당한다. 선택 버전은 Python 3.14.7 또는 Node.js 24.19.0과 호환되어야 한다.

## Python runtime dependencies

| Package/capability | Purpose | Requirement |
|---|---|---|
| FastAPI | Control-owned HTTP API와 dependency injection | Pydantic 2.13.4 및 Python 3.14.7 호환 |
| Uvicorn | 개발 및 Cloud Run ASGI runtime | 선택한 FastAPI/Starlette와 호환 |
| Google Cloud Firestore client | Canonical Firestore repositories와 transaction | Python 3.14.7 호환 |
| Authlib 또는 동등 OIDC client | Google OIDC authorization-code flow, discovery, state/nonce 검증 | Google OIDC 및 async Web flow 지원 |
| HTTPX 또는 동등 async HTTP client | OIDC discovery/token/userinfo 통신과 API test client | 선택한 FastAPI/Auth library와 호환 |
| itsdangerous 또는 동등 signing capability | Secure application session/state signing | Starlette session 사용 시 필요 |

## Python development dependencies

| Package/capability | Purpose | Requirement |
|---|---|---|
| pytest-asyncio | Async application/repository/API test | pytest 9.1.1 및 Python 3.14.7 호환 |
| Firestore emulator support | Transaction, deterministic ID, concurrency persistence test | production credential 불필요 |

## Frontend runtime dependencies

| Package/capability | Purpose | Requirement |
|---|---|---|
| React | Product Web UI | Node.js 24.19.0 호환 |
| React DOM | Browser/Electron renderer | React과 동일 major |
| React Router | Auth/VWS/Risk/History/Security routing | 선택한 React version 호환 |

## Frontend development dependencies

| Package/capability | Purpose | Requirement |
|---|---|---|
| Vite | Web build/dev server | Node.js 24.19.0 호환 |
| Vite React plugin | React transform/build | 선택한 Vite/React와 호환 |
| Vitest | Frontend unit/component test | 선택한 Vite와 호환 |
| Testing Library | 접근성 중심 component test | 선택한 React와 호환 |
| jsdom | Browser DOM test environment | Node.js 24.19.0 호환 |

## Environment variables

```text
GOOGLE_LOGIN_CLIENT_ID
GOOGLE_LOGIN_CLIENT_SECRET
GOOGLE_LOGIN_REDIRECT_URI
SESSION_SECRET
APP_PUBLIC_BASE_URL
GCP_PROJECT_ID
FIRESTORE_DATABASE
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

## Deferred version decisions

정확한 신규 package 버전 pin은 Integration Owner가 Python 3.14.7 호환성과 전체 Plane dependency를 함께 확인한 뒤 결정한다. Agent 1은 호환성 확인 전 임의 pin이나 root lockfile 변경을 수행하지 않는다.
