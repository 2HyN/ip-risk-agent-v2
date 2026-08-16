# Agent 1 Dependency and Environment Request

## Status

- Owner: Agent 1 — Platform & Control Plane
- State: Agent 1 feature 단계별 자체 선택/설치 허용; 최종 root pin은 Integration 단계 검토
- Python compatibility target: CPython 3.14.7
- Existing fixed packages: Pydantic 2.13.4, pytest 9.1.1

Agent 1은 각 feature 구현에 필요한 package를 독자적으로 선택하고 현재 `.venv`/workspace에서 호환성을 검사해 설치할 수 있다. 선택 버전과 검사 결과는 이 문서에 누적한다. Root manifest와 최종 lockfile pin은 Integration 단계에서 다른 Plane과의 충돌 여부를 확인해 최대한 반영한다. 모든 선택은 Python 3.14.7 또는 Node.js 24.19.0과 호환되어야 한다.

Phase 0~2에서는 신규 package가 필요하지 않아 추가 설치를 수행하지 않았다.

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

## Version selection policy

Agent 1은 package가 처음 필요한 Phase에서 최신 안정 release를 우선 검토하고 Python/Node 기준 버전, 기존 Pydantic/pytest/TypeScript, 직접 및 전체 회귀 test로 호환성을 확인한다. 검증된 개발 버전은 이 문서에 기록한다. 최종 pin은 Integration Owner가 전체 Plane dependency를 비교해 충돌이 없는 한 해당 검증 버전을 반영한다.
