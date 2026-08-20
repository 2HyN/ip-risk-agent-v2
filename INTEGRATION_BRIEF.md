# IP Risk Agent v2 — 통합 브리프

> **목적**: 3개 병렬 개발 branch를 `integration` branch로 통합하는 데 필요한 전체 정보를 한 문서에 모은 것.
> **작성 기준**: 2026-08-20, 아래 커밋 기준으로 worktree를 구성해 코드·문서를 직접 확인하고 병합 드라이런까지 실행한 결과.
> **저장소**: `github.com/2HyN/ip-risk-agent-v2`

| worktree | branch | HEAD | 비고 |
|---|---|---|---|
| `ip-risk-agent-v2/` | `main` | `7cfbec4` | 원본. 공통 기준점 |
| `wt-integration/` | `wt/integration` → `origin/integration` | `7cfbec4` | main과 내용 동일 (0 ahead / 0 behind) |
| `wt-control/` | `wt/platform-control` | `de1dacc` | Agent 1 |
| `wt-source/` | `wt/source-integration-desktop` | `ee861b7` | Agent 2 |
| `wt-rag/` | `wt/risk-intelligence-rag` | `68e07a3` | Agent 3 |

---

## 1. 프로젝트 구조 요약

### 1.1 제품 정의

Local Directory / GitHub Repository / Google Drive 등 여러 실제 협업 Source Workspace를 하나의 **Risk Workspace(VWS)** 에 연결하고, 변경을 지속 감지해 Patent·License 중심의 IP Risk를 **근거 기반**으로 분석하며, 사용자가 장기적으로 검토·추적·감사할 수 있게 하는 Secure Human-in-the-Loop AI Risk Management System.

### 1.2 3-Plane 병렬 개발 구조

```
                  PLATFORM & CONTROL PLANE  (Agent 1 / platform-control)
               ┌──────────────────────────────────┐
               │ Identity / VWS / Roles           │
               │ Mount Registry                   │
               │ VWS Security Gate                │
               │ Risk Lifecycle / History / Audit │
               │ Firestore / Control API / Web UI │
               └────────────────┬─────────────────┘
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
  SOURCE INTEGRATION PLANE          RISK INTELLIGENCE PLANE
  (Agent 2 / source-integration-    (Agent 3 / risk-intelligence-rag)
   desktop)
  ┌───────────────────────┐         ┌────────────────────────┐
  │ Drive / GitHub / Local│         │ Patent / License       │
  │ Electron Desktop      │         │ Gemini / KIPRIS        │
  │ OAuth / Webhook       │         │ RAG Engine / SPDX      │
  │ Watch / Fetch         │         │ Evidence validation    │
  └───────────────────────┘         └────────────────────────┘
```

**Source Plane과 Intelligence Plane 사이에는 직접 호출 경로가 없다.** 모든 교차 통신은 Frozen Shared Contract(`shared/contracts/**`)와 Control Plane을 경유한다.

### 1.3 고정된 처리 파이프라인 (Master Spec §21)

```
Source event → Connector verify/normalize → SourceChange
  → Control persist + idempotency → Cloud Tasks
  → SourceAdapter.fetch_snapshot() → SourceSnapshot
  → SourceAccessEvent record → Control Security Gate
  → AnalysisArtifact → Analyzer Registry
  → Patent / License Analyzer → AnalysisResult
  → Control validates result → Risk Lifecycle reconcile transaction
  → Risk / RiskEvidence / RiskEvent → Notification / UI
```

### 1.4 파일 ownership 경계

| 영역 | 소유 | branch |
|---|---|---|
| `backend/src/ip_risk_agent/core/**`, `application/**`, `persistence/core_firestore/**`, `api/**` | Agent 1 | platform-control |
| `frontend/src/{app,auth,workspace,risk,history,security,shared}/**` | Agent 1 | platform-control |
| `tests/control/**` | Agent 1 | platform-control |
| `backend/src/ip_risk_agent/connectors/**` | Agent 2 | source-integration-desktop |
| `frontend/src/sources/**`, `apps/desktop/**` | Agent 2 | source-integration-desktop |
| `tests/connectors/**` | Agent 2 | source-integration-desktop |
| `backend/src/ip_risk_agent/intelligence/**`, `rag-corpus/**` | Agent 3 | risk-intelligence-rag |
| `tests/intelligence/**` | Agent 3 | risk-intelligence-rag |
| `composition/**`, `main.py`, `worker.py`, `deploy/**`, root manifest/lock, `tests/{integration,e2e}/**` | **Integration** | integration |
| `shared/contracts/**` | **Frozen** — 병렬 개발 중 누구도 수정 불가 | main |

---

## 2. 각 branch 작업 현황

### 2.1 공통 사실

- 세 branch 모두 `origin/main` 대비 **behind 0** — main이 그대로 merge-base. rebase 불필요.
- 세 Agent 모두 **Frozen Contract 미수정**, **contract-change request 0건**.
- 세 Agent 모두 root `pyproject.toml` / `package.json` **미수정**. (예외: Agent 2가 `pnpm-lock.yaml`에 +625줄)
- `deploy/`는 `.gitkeep`만 있는 **빈 디렉터리**. 배포 설정이 아직 아무것도 없다.

### 2.2 Agent 1 — Platform & Control Plane (`platform-control`)

| 항목 | 값 |
|---|---|
| 커밋 | main 대비 **+15** |
| 변경 파일 | **155개** (+28,501 / −19) |
| Python 소스 | 112 파일 / 약 14,711 LOC |
| Frontend TS/TSX | 33 파일 |
| Python 테스트 | `tests/control/**` 21 파일, `def test_` 137개 |
| 문서 기록 실행 결과 | shared contract + Agent 1 전체 Python **286 passed, 1 skipped** / frontend **15 passed** |
| 상태 | Phase 0~13 구현 완료, Integration 조립 준비 완료 |

**구현 범위**: canonical Control domain, RBAC와 provider authority 경계, Firestore persistence, SourceChange/AnalysisJob orchestration, Security Gate, AnalysisResult/Risk reconciliation, human review/history/audit/notification, Google App Login(OIDC), Control API, Product Web UI, structured observability.

**공개 접점 (Integration이 import할 유일한 경로)**

```python
from ip_risk_agent.application.public_facade import (
    ControlPlaneFacade, ControlPlaneFacadeConfig, CorrelationIds,
    PublicVwsAction, SourceAccessReceiptContext,
    SourceAuthorizationCallback, SourceMetadataRegistrationCallback,
    SourceMetadataRegistrationCommand, SourceScopeInput,
    StructuredEventSink, StructuredLogger,
)
from ip_risk_agent.api import (
    ApplicationHardeningConfig, ApplicationSessionConfig,
    ControlApiDependencies, create_control_api_bundle,
)
from ip_risk_agent.persistence.core_firestore import FirestoreControlUnitOfWorkFactory
```

`ControlPlaneFacade` 공개 async 메서드 12개: `authorize_vws_action`, `register_source_metadata`, `register_source_change`, `claim_analysis`, `fail_analysis`, `retry_failed_analysis`, `register_source_access`, `build_analysis_artifact`, `accept_analysis_result`, `get_mount_ref`, `get_source_workspace_context`, `get_original_source_request`.

`tests/control/test_delivery_contract.py`가 이 공개 surface의 드리프트를 자동 탐지한다 (4 tests).

**Control API 라우트** — prefix `/api/v1/{auth,workspaces,invitations,notifications}`

```
GET    /api/v1/auth/google/login,  /google/callback,  /me
POST   /api/v1/auth/logout
GET    /api/v1/workspaces               POST   /api/v1/workspaces
GET    /api/v1/workspaces/{vws_id}      PATCH  /api/v1/workspaces/{vws_id}      DELETE /api/v1/workspaces/{vws_id}
GET    /api/v1/workspaces/{vws_id}/dashboard
GET    /api/v1/workspaces/{vws_id}/members
PATCH  /api/v1/workspaces/{vws_id}/members/{user_id}
DELETE /api/v1/workspaces/{vws_id}/members/{user_id}
GET    /api/v1/workspaces/{vws_id}/membership
GET    /api/v1/workspaces/{vws_id}/mounts,  /mounts/{mount_id}
PATCH  /api/v1/workspaces/{vws_id}/mounts/{mount_id}/alias
POST   /api/v1/workspaces/{vws_id}/mounts/{mount_id}/disable
GET    /api/v1/workspaces/{vws_id}/risks/{risk_id},  /{risk_id}/timeline
PATCH  /api/v1/workspaces/{vws_id}/risks/{risk_id}/review
GET    /api/v1/workspaces/{vws_id}/activity,  /audit,  /audit/export,  /source-access
GET    /api/v1/workspaces/{vws_id}/data-access-summary
PUT    /api/v1/workspaces/{vws_id}/ipriskignore
GET    /api/v1/notifications            POST  /api/v1/notifications/{id}/read
```

**Firestore**: `CANONICAL_COLLECTIONS` 16개, `REQUIRED_COMPOSITE_INDEXES` 8개 (memberships×3, workspace_mounts×2, risks×2, change_events×1). 이 tuple은 **query 요구사항이지 배포 가능한 `firestore.indexes.json` 형식이 아니다** — Integration이 변환해야 한다.

### 2.3 Agent 2 — Source Integration & Desktop (`source-integration-desktop`)

| 항목 | 값 |
|---|---|
| 커밋 | main 대비 **+19** |
| 변경 파일 | **92개** (+7,810 / −10) |
| Python 소스 (connectors) | 45 파일 / 약 3,210 LOC |
| Electron TS | 29 파일 |
| 테스트 | Python `def test_` 211개, desktop TS 65개, frontend TS 8개 |
| 문서 기록 실행 결과 | **297 tests — 295 passed, 2 skipped, 0 failed** (Python 224 / desktop 65 / frontend 8) |
| 상태 | Phase A~F 전부 완료 |

**구현 범위**: Drive/GitHub/Local 3개 provider 전부 `SourceAdapter` 계약 구현. 연결 시작(OAuth/App 설치) → 파일·저장소 선택 → Mount 생성 → 변경 감지·수신까지 라이프사이클 전체 연결. Electron 앱은 폴더 선택 → 서버 등록 → 로컬 저장 → watcher 시작 → 변경 감지 → 서버 전송까지 실제 왕복. 외부 API에 지수 백오프 재시도 적용.

**Source 라우트** (전부 `APIRouter` 반환 — `include_router()`로 붙이면 됨)

```
POST /api/v1/source-connections/google-drive/start
POST /webhooks/google-drive
POST /webhooks/github
POST /desktop/devices/register
POST /desktop/mounts/register
POST /desktop/staging
POST /desktop/events
```

**Integration이 실제 구현으로 교체해야 하는 Protocol 포트 (전부 fake만 존재)**

| 포트 | 위치 | 연결 대상 |
|---|---|---|
| `AuthzDependency` | `connectors/common/authz.py` | **전체 라우터 공용. 기본값이 무검사 — 프로덕션 전 Agent 1 VWS Role 검사로 교체 필수** |
| `SourceChangeSink` | `common/change_sink.py` | Control persist + idempotency + Cloud Tasks enqueue |
| `OAuthStateStore` | `common/oauth_state.py` | 다중 인스턴스면 Firestore 등 공유 저장소 |
| `Drive/GitHubConnectionCreationCallback` | 각 `oauth_routes.py`/`install_routes.py` | canonical `SourceConnection` 생성 |
| `Drive/GitHub/Local MountCreationCallback` | 각 `mounts_routes.py`/`local/routes.py` | canonical `SourceWorkspace` + `Mount` 생성 |
| `DeviceRegistrationCallback` | `local/routes.py` | device_id ↔ app_user 연결 |
| `*ConnectionLookup`, `*MountResolver` | 각 provider | canonical 데이터 조회 |
| `SourceCredentialVault` | `common/credential_vault.py` | 실제 Secret Manager |
| `*RuntimeStore`, `*TrackingScope` | `common/runtime_store.py` | Firestore |
| `LocalStagingStore` | `local/staging_store.py` | 실제 GCS 버킷 |

### 2.4 Agent 3 — Risk Intelligence & RAG (`risk-intelligence-rag`)

| 항목 | 값 |
|---|---|
| 커밋 | main 대비 **+5** |
| 변경 파일 | **44개** (+5,308) |
| Python 소스 (intelligence) | 35 파일 / 약 3,733 LOC |
| 테스트 | `def test_` 68개 |
| 문서 기록 실행 결과 | `-m "not live"` **58 passed**, `-m live` **10 passed** (실제 provider 호출) |
| 상태 | 전 영역 완료 |

**구현 범위**: 승인된 `AnalysisArtifact` → Patent/License 분석 → `AnalysisResult` 반환 경로 전체. License(매니페스트·잠금파일·SPDX·정책·설명), Patent(추출·검색·순위·근거·대조·검증·우선순위), Gemini client(구조화 출력·재시도·프롬프트 버전), RAG(매니페스트·적재·검색·버전), corpus 초기 자료 3건.

**공개 접점**

```python
from ip_risk_agent.intelligence.public import create_facade_from_env
facade = create_facade_from_env(env, retriever=retriever)
results = await facade.analyze(artifact)   # list[AnalysisResult]
facade.supports(artifact)                  # 실행 대상 사전 확인
```

**실호출로 검증된 것**: deps.dev(`requests 2.32.3` → `Apache-2.0`), PyPI 폴백(`PyMuPDF 1.24.0` → `AGPL-3.0-only` → `POLICY_CONFLICT`), npm(`express 4.19.2` → `MIT`), KIPRIS 검색/0건/상세/잘못된 키, Gemini 구조화 출력. **RAG Engine만 실호출 미검증** (GCP 프로젝트와 corpus 필요).

---

## 3. 병합 계획

### 3.1 검증된 충돌 — worktree 드라이런 결과

`origin/integration`에서 시작해 세 branch를 순차 병합한 결과 (2026-08-20, 최신 HEAD 기준 재확인):

| 순서 | branch | 결과 |
|---|---|---|
| 1 | `platform-control` | **충돌 없음** |
| 2 | `risk-intelligence-rag` | **충돌 없음** |
| 3 | `source-integration-desktop` | **충돌 4건** — 전부 `frontend/` 설정 파일 |

충돌 파일: `frontend/index.html`, `frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`

**backend는 파일 단위 충돌 0건.** 디렉터리 ownership이 사전에 갈려 있어 세 branch가 서로 다른 파일만 생성했다.

### 3.2 권장 병합 순서와 이유

**`platform-control` → `risk-intelligence-rag` → `source-integration-desktop`**

- `platform-control`이 가장 크고 프론트엔드 뼈대(라우터·API 클라이언트·vitest 하네스)를 전부 갖고 있어 기준선으로 적합.
- `risk-intelligence-rag`는 충돌 0 · backend 전용이므로 무비용으로 중간 삽입.
- 충돌을 가진 `source-integration-desktop`을 마지막에 두면, 프론트 설정 해결 시 최종 트리 전체를 보고 판단할 수 있다.

### 3.3 충돌 4건 해결 지침

네 파일 모두 **"같은 프론트엔드를 서로 다른 빌드·테스트 철학으로 설정"** 한 충돌이다. 파일별로 고르는 게 아니라 **한쪽 철학으로 통일**해야 한다.

| | `platform-control` (ours) | `source-integration-desktop` (theirs) |
|---|---|---|
| 테스트 러너 | **vitest** + jsdom + Testing Library | `node --test` (컴파일된 `dist/*.test.js` 대상) |
| tsconfig | `moduleResolution: Bundler`, `noEmit: true`, `types: [vite/client, vitest/globals]` | `NodeNext`, `declaration: true`, `rootDir: src`, `outDir: dist` |
| vite.config | `vitest/config`, `/api` → `127.0.0.1:8000` proxy, `sourcemap: true` | `vite`, `build.outDir: dist/web` |
| index.html | `/src/main.tsx`, `lang="en"` | `/src/sources/dev/preview.tsx`, `lang="ko"` |
| 의존성 | 버전 **핀 고정**, `react-router-dom 7.18.2` 포함 | 캐럿 범위(`^`), 라우터 없음 |

**권장 해결: `platform-control` 채택 + Agent 2 자산 흡수**

```bash
git checkout --ours frontend/package.json frontend/tsconfig.json frontend/vite.config.ts frontend/index.html
```

1. `package.json` — ours. 라우터·Testing Library·핀 고정 버전을 모두 갖고 있고, Agent 2가 추가로 요구하는 신규 런타임 의존성은 없다.
2. `tsconfig.json` — ours. NodeNext/emit 설정은 `node --test` 전용이므로 vitest로 통일하면 불필요.
3. `vite.config.ts` — ours. **`/api` proxy는 백엔드 연동에 필수.** `build.outDir: dist/web` 분리는 `dist` emit을 안 하면 의미가 없다.
4. `index.html` — ours 채택 후 `lang="ko"`로 변경. 진입점은 `/src/main.tsx` 하나로 유지.

**충돌 해결과 같은 커밋에 포함해야 하는 후속 작업**

- `frontend/src/sources/platform/PlatformAdapter.test.ts` → `node --test` 문법에서 **vitest 문법으로 포팅**. (`noEmit`이 되면 그대로는 실행 자체가 불가)
- `frontend/src/sources/dev/preview.tsx` → 별도 진입점이 사라지므로 `AddSourceChooser` / `ConnectLocalSource` 라우트로 흡수하거나 삭제. (Agent 2 문서 §10-3에서 "임시 파일"로 명시)
- `apps/desktop/package.json`의 `test` 스크립트(`node --test dist/**`)는 **그대로 유지**한다. Electron 쪽은 vitest 전환 대상이 아니다.

### 3.4 병합 후 frontend 구조 (충돌 해결 완료 시)

```
frontend/src/
├─ app/          app-shell, auth-guard, control-plane-app, integration-context,
│                integration.ts, notifications-page, source-slot-page      [Agent 1]
├─ auth/         login-page, session                                       [Agent 1]
├─ history/      history-page                                              [Agent 1]
├─ risk/         risk-detail-page, risk-list-page, risk-timeline-page      [Agent 1]
├─ security/     security-page                                             [Agent 1]
├─ shared/       api/{client,control-api,types}, format, hooks/*, styles.css, ui/  [Agent 1]
├─ workspace/    capability-route, dashboard-page, members-page,
│                workspace-context, workspace-list-page                    [Agent 1]
├─ sources/      AddSourceChooser, ConnectLocalSource, api/connectionClient,
│                platform/PlatformAdapter, dev/preview.tsx(제거 대상)      [Agent 2]
├─ test/         setup.ts + 4개 vitest 스펙                                [Agent 1]
└─ main.tsx, index.ts
```

**소스 파일 자체는 충돌하지 않는다.**

---

## 4. Dependency 버전 및 호환성

### 4.1 기준 런타임

| 항목 | 버전 | 근거 |
|---|---|---|
| CPython | **3.14.7** (`>=3.14,<3.15`) | `pyproject.toml`, `README.md` |
| Node.js | **24.19.0** | root `package.json` `engines` |
| pnpm | **11.19.0** | root `package.json` `packageManager` |
| TypeScript | **5.9.3** | root `devDependencies` |
| Pydantic | **2.13.4** | `pyproject.toml` dependencies |
| pytest | **9.1.1** | `pyproject.toml` optional-dependencies.dev |

### 4.2 Python dependency 통합표

| 패키지 | Agent 1 | Agent 2 | Agent 3 | 판정 |
|---|---|---|---|---|
| `pydantic` | `2.13.4` (baseline) | — | `2.13.3`으로 기재 | ⚠️ **문서 오기** — 실제 baseline은 2.13.4. Agent 3 문서만 수정하면 됨 |
| `fastapi` | **`0.141.1`** | **`0.121.2`** | — | 🔴 **충돌** — §4.4 참조 |
| `httpx` | `0.28.1` | `>=0.28,<0.29` | `0.28.1` | ✅ 일치. `0.28.1`로 pin |
| `google-auth` | — | `2.56.3` | `2.56.3` | ✅ 일치 |
| `google-cloud-firestore` | `2.28.1` | — | — | ✅ 단독. `grpcio==1.83.0` transitive (CPython 3.14 Windows wheel 확인됨) |
| `authlib` | `1.7.2` | — | — | ✅ 단독 |
| `itsdangerous` | `2.2.0` | — | — | ✅ 단독 |
| `google-api-python-client` | — | `2.198.0` (`>=2.180,<3.0`) | — | ✅ 단독 |
| `PyJWT[crypto]` | — | `2.10.1` | — | ✅ 단독 |
| `defusedxml` | — | — | `0.7.1` | ✅ 단독 |
| `PyYAML` | — | — | `6.0.3` | ✅ 단독 |
| `google-genai` | — | — | `2.17.0` | ✅ 단독 |
| `starlette` | `1.6.0` (fastapi가 선택) | — | — | fastapi 버전 결정에 종속 |
| **dev** `pytest` | `9.1.1` | `9.1.1` | `9.1.1` | ✅ 일치 |
| **dev** `httpx2` | `2.10.0` (Starlette TestClient) | — | — | ✅ 단독. `httpx`와 역할이 다름 (공존 필요) |
| **dev** `pytest-asyncio` | **불필요** (`asyncio.run` 기반) | — | **`1.4.0` 필수** (strict 모드) | 🟡 §4.5 참조 |
| Integration 추가 예정 | `uvicorn` (미선택) | `google-cloud-secret-manager` (미검증) | — | Integration이 결정 |

### 4.3 Node dependency 통합표

| 패키지 | Agent 1 (frontend) | Agent 2 | 판정 |
|---|---|---|---|
| `react`, `react-dom` | `19.2.8` (exact) | `^19.2.8` | 🟡 표기 차이. exact로 통일 |
| `react-router-dom` | `7.18.2` | 없음 | Agent 1 값 채택 |
| `vite` | `8.2.1` (exact) | `^8.2.1` | 🟡 exact로 통일 |
| `@vitejs/plugin-react` | `6.0.5` (exact) | `^6.0.5` | 🟡 exact로 통일 |
| `@types/react` / `@types/react-dom` | `19.2.18` / `19.2.4` | `^19.2.0` / `^19.2.0` | 🟡 exact로 통일 |
| `@types/node` | **`26.2.0`** (frontend) | **`^24.0.0`** (frontend + desktop) | 🔴 **major 충돌** — §4.4 참조 |
| `vitest`, `jsdom` | `4.1.10`, `30.0.1` | 없음 | Agent 1 값 채택 |
| Testing Library | `react 16.3.2`, `dom 10.4.1`, `user-event 14.6.4`, `jest-dom 7.0.1` | 없음 | Agent 1 값 채택 |
| `typescript` | `5.9.3` | `5.9.3` | ✅ 일치 (root에서도 5.9.3) |
| `chokidar` | — | `^5.0.0` (desktop) | ✅ 단독 |
| `electron` | — | `^43.4.0` (desktop) | ✅ 단독 |

### 4.4 반드시 해결해야 하는 버전 충돌 2건

#### 🔴 A. FastAPI — `0.141.1` (Agent 1) vs `0.121.2` (Agent 2)

두 Plane 모두 FastAPI 라우터를 만들고 최종적으로 **한 개의 앱에 함께 등록**되므로 하나만 설치된다.

- **권장: `0.141.1` (Agent 1 값) 채택.** 상위 버전이며 Agent 1이 Pydantic 2.13.4 / CPython 3.14.7에서 `pip check` + Control API 전체 suite를 통과시켰다. Agent 1 쪽 검증 범위가 훨씬 넓다(Control API 137 테스트).
- **검증 절차**: `0.141.1` 설치 후 `pytest tests/connectors/`를 재실행해 Agent 2의 224건이 그대로 통과하는지 확인. Agent 2는 `APIRouter` + `TestClient`라는 안정적 API만 쓰므로 통과 가능성이 높지만, `0.121 → 0.141` 사이 Starlette major 변화(Starlette 1.6.0)가 있어 **반드시 실측이 필요하다.**
- 실패 시 대안: Agent 2 라우터의 실패 지점만 수정. FastAPI를 낮추면 Agent 1의 286건이 위험해지므로 방향은 이 순서로 고정.

#### 🔴 B. `@types/node` — `26.2.0` (Agent 1) vs `^24.0.0` (Agent 2)

pnpm workspace에서 `frontend`와 `apps/desktop`이 각각 선언하므로 **패키지별로 다른 버전을 유지하는 것은 기술적으로 가능**하다. 그러나:

- Node.js 런타임은 **24.19.0**으로 고정되어 있다. `@types/node@26`은 Node 26 API 타입을 포함하므로 **런타임에 없는 API가 타입상 존재하는 것으로 보이는 위험**이 있다.
- **권장: 전 workspace를 `@types/node` 24.x 최신으로 통일.** 런타임 버전과 타입 버전을 맞추는 것이 원칙이다.
- 통일 후 `pnpm --filter @iprisk/frontend typecheck`를 재실행해 Agent 1의 strict 옵션(`noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`)에서 오류가 나지 않는지 확인.

### 4.5 🟡 pytest-asyncio 도입 판단

- Agent 1: async 테스트를 `asyncio.run` 기반으로 작성 — `pytest-asyncio` **불필요**하다고 명시.
- Agent 3: `pytest-asyncio 1.4.0`을 **strict 모드**로 사용하며 marker를 명시.

`pytest-asyncio`를 strict 모드로 설치하면 marker 없는 async 테스트는 **실행되지 않고 skip/warning 처리**된다. Agent 1이 `asyncio.run`으로 감싼 **동기 함수**를 쓴다면 영향이 없지만, `async def test_`가 하나라도 있으면 조용히 건너뛴다.

**조치**: 병합 후 `grep -rE "^\s*async def test_" tests/control/`로 확인하고, 있으면 `asyncio_mode = "strict"` + 해당 테스트에 marker를 붙이거나 `asyncio.run` 래핑으로 통일한다. **통합 후 테스트 총계가 줄어들지 않는지 반드시 대조할 것.**

### 4.6 Python 버전 문서 불일치 🔴

세 곳이 서로 다르다:

| 위치 | 명시 버전 |
|---|---|
| `pyproject.toml` | `requires-python = ">=3.14,<3.15"` |
| `README.md` | CPython **3.14.7** 고정 |
| `ENVIRONMENT_SETUP.md` 20행 | "검증 기준 버전은 Python **3.12.13**" + 25행 `py -3.12 -m venv .venv` |
| Agent 3 dependency 문서 | "**3.13**에서 개발·검증했다" |

**조치**: `3.14.7`로 통일하고 `ENVIRONMENT_SETUP.md`를 수정한다. 동시에 **Agent 3 코드를 3.14.7에서 재검증**해야 한다 (3.13에서 개발됨). `pytest tests/intelligence -m "not live"` 58건으로 확인.

### 4.7 root manifest 병합 결과안

```toml
# pyproject.toml
requires-python = ">=3.14,<3.15"
dependencies = [
  "pydantic==2.13.4",
  # Agent 1 — Control Plane
  "fastapi==0.141.1",          # ← Agent 2의 0.121.2 대신 상위 버전 채택 (§4.4-A)
  "google-cloud-firestore==2.28.1",
  "authlib==1.7.2",
  "httpx==0.28.1",
  "itsdangerous==2.2.0",
  # Agent 2 — Source Integration
  "google-api-python-client>=2.180,<3.0",
  "google-auth>=2.40,<3.0",
  "PyJWT[crypto]==2.10.1",
  # Agent 3 — Risk Intelligence
  "defusedxml==0.7.1",
  "PyYAML==6.0.3",
  "google-genai==2.17.0",
  # Integration
  "uvicorn[standard]==<선택 필요>",
  "google-cloud-secret-manager==<선택 필요>",
]

[project.optional-dependencies]
dev = [
  "pytest==9.1.1",
  "httpx2==2.10.0",            # Starlette TestClient 전용
  "pytest-asyncio==1.4.0",     # Agent 3 필수 (§4.5 확인 후)
]

[tool.pytest.ini_options]
# 🔴 현재 main은 testpaths=["shared/contracts/tests"] 뿐이라 세 Plane 테스트가 실행되지 않는다
testpaths = ["shared/contracts/tests", "tests"]
pythonpath = ["shared/contracts/python", "backend/src", "."]
addopts = "--strict-config --strict-markers -ra -p no:cacheprovider"
markers = ["live: 실제 외부 provider 를 호출한다. 자격증명이 없으면 건너뛴다"]
asyncio_mode = "strict"
```

> **주의**: root `addopts`에 `--strict-markers`가 있고 Agent 3의 `live` marker는 `tests/intelligence/conftest.py`에서만 등록된다. `tests/intelligence` 밖에서 `-m live`를 쓰면 실패하므로, root `pyproject.toml`의 `markers`에도 올리는 편이 안전하다.

`pnpm-lock.yaml`은 Agent 2가 +625줄 수정했다. 세 Plane의 `package.json`을 확정한 뒤 **`pnpm install`로 lock을 재생성**하고, `pnpm install --frozen-lockfile`이 통과하는지 확인한다.

---

## 5. 환경 변수 통합

### 5.1 Plane별 요구 변수

| 변수 | 요구 Plane | `.env.example` 존재 | 비고 |
|---|---|:---:|---|
| `GOOGLE_LOGIN_CLIENT_ID` | Agent 1 | ✅ | |
| `GOOGLE_LOGIN_CLIENT_SECRET` | Agent 1 | ✅ | Secret Manager 주입 |
| `GOOGLE_LOGIN_REDIRECT_URI` | Agent 1 | ✅ | 등록된 exact HTTPS. local만 HTTP 허용 |
| `SESSION_SECRET` | Agent 1 | ✅ | 최소 32자. session/cursor signing |
| `APP_PUBLIC_BASE_URL` | Agent 1 | ✅ | exact CORS origin |
| `GCP_PROJECT_ID` | Agent 1·2·3 | ✅ | |
| `FIRESTORE_DATABASE` | Agent 1 | ✅ | |
| `FIRESTORE_EMULATOR_HOST` | Agent 1 (test) | ❌ | **production 설정 금지** |
| `GOOGLE_DRIVE_CLIENT_ID/SECRET/REDIRECT_URI` | Agent 2 | ✅ | |
| `GOOGLE_DRIVE_WEBHOOK_BASE_URL` | Agent 2 | ✅ | |
| `DRIVE_WATCH_CHANNEL_TOKEN` | Agent 2 | ❌ | **추가 필요** |
| `GITHUB_APP_ID` | Agent 2 | ✅ | |
| `GITHUB_APP_SLUG` | Agent 2 | ❌ | **추가 필요** |
| `GITHUB_APP_PRIVATE_KEY_SECRET_ID` | Agent 2 | ✅ | |
| `GITHUB_WEBHOOK_SECRET_ID` | Agent 2 | ✅ | |
| `GITHUB_APP_CALLBACK_URL` | Agent 2 | ✅ | |
| `LOCAL_STAGING_BUCKET` | Agent 2 | ✅ | |
| `IPRISK_SERVER_BASE_URL` | Agent 2 (desktop) | ❌ | **추가 필요** |
| `GEMINI_MODEL_ID` | Agent 3 | ✅ | 🔴 §5.3 |
| `GEMINI_API_KEY` | Agent 3 | ❌ | **추가 필요** (AI Studio 사용 시) |
| `VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG` | Agent 3 | ✅ | Vertex 사용 시 |
| `KIPRIS_ACCESS_KEY` | Agent 3 | ❌ | 🔴 §5.2 |
| `KIPRIS_API_KEY_SECRET_ID` | — | ✅ | 🔴 §5.2 — 코드가 읽지 않음 |
| `RAG_REGION` | Agent 3 | ✅ | |
| `RAG_CORPUS_ID` | Agent 3 | ✅ | |
| `RAG_CORPUS_VERSION` | Agent 3 | ❌ | **추가 필요**. 없으면 `unversioned` |
| `RAG_MANAGED_DB_CONFIG` | — | ✅ | 코드가 읽지 않음 |
| `PACKAGE_METADATA_BASE_URL` | — | ✅ | 코드가 읽지 않음 |

### 5.2 🔴 KIPRIS 변수명 불일치

`IntelligenceConfig.from_env()`는 **`KIPRIS_ACCESS_KEY`** 를 읽는데, `.env.example`에는 **`KIPRIS_API_KEY_SECRET_ID`** 만 있다. 현재 상태로 배포하면 특허 분석 경로가 **조용히 비활성화**된다 (키 없으면 해당 경로만 꺼지는 설계).

**조치**: `.env.example`에 `KIPRIS_ACCESS_KEY` 추가. `_SECRET_ID` 계열 이름은 Secret Manager 참조 ID를 담는 별도 용도라면 둘 다 유지하되, Integration이 Secret Manager에서 읽어 `KIPRIS_ACCESS_KEY`에 주입하는 흐름을 명시한다.

### 5.3 🔴 `GEMINI_MODEL_ID` 값 미확정

Master Spec §16/35와 Blueprint §35의 **"Gemini 3.6 Flash"는 실재하지 않는 모델 식별자**다. Agent 3은 검증에 `gemini-3-flash-preview`를 사용했다. 환경변수로 받으므로 코드 변경 없이 지정 가능하지만 **배포 전에 값을 확정해야 한다.** 결과의 `versions.model_id`에 기록되므로 재현성에도 영향이 있다.

### 5.4 Secret 취급 원칙

실제 값은 `.env.example`, 소스, fixture, task payload, 로그 어디에도 기록하지 않는다. Agent 2/3 모두 **생성자 인자 주입 구조**이므로 Integration이 Secret Manager에서 읽어 넘기면 된다.

---

## 6. 병합 이후의 실제 통합 작업

git merge가 끝나도 앱은 뜨지 않는다. 병합 후 트리에서도 다음이 자리표시자다:

```python
# backend/src/ip_risk_agent/main.py
"""Integration-only API composition placeholder; business wiring is intentionally absent."""
SKELETON_ONLY = True

# backend/src/ip_risk_agent/worker.py — 동일
# backend/src/ip_risk_agent/composition/__init__.py
"""Reserved for the Integration Agent."""
```

### 6.1 조립 순서 (Agent 1 인계 문서 §14 기준)

1. **root manifest/lock 확정** — §4.7의 병합안을 적용하고 `pip check` / `pnpm install --frozen-lockfile` 통과 확인
2. **인프라 어댑터 생성** — Firestore `AsyncClient` → `FirestoreControlUnitOfWorkFactory.from_client(client, max_attempts=5)`, safe log sink, Cloud Tasks enqueuer(`enqueue_change(change_event_id) -> None`, 동일 ID de-dup 필수), UTC clock, id_factory
3. **`ControlPlaneFacade` 조립** 후 Agent 2 callback 연결
   ```python
   authorization: SourceAuthorizationCallback = facade.authorize_vws_action
   register_metadata: SourceMetadataRegistrationCallback = facade.register_source_metadata
   ```
4. **Control API 조립** — `ControlApiDependencies(auth, workspaces, risks, history, security, notifications, session, hardening, observer)` 생성 후 `create_control_api_bundle(deps).install(app)`
5. **Agent 2 라우터 등록** — Drive/GitHub/Local 7개 라우터를 `include_router()`. 이때 `AuthzDependency`를 Agent 1 VWS Role 검사로 교체 (기본값 무검사)
6. **Agent 3 analyzer 연결** — Gate가 승인한 `AnalysisArtifact` **뒤에만** 붙인다. Worker에서 `facade.analyze(artifact)` → `list[AnalysisResult]` → Control의 `accept_analysis_result`
7. **frontend 조립** — `ControlPlaneApp`에 `sourceNavigation` / `sourcePanel` / `openOriginal` 주입
   ```tsx
   <ControlPlaneApp apiBaseUrl="" router="browser" integration={{ sourceNavigation, sourcePanel, openOriginal }} />
   ```
   `router="browser"`는 Web, `"hash"`는 Electron renderer. callback이 없으면 Open Original 버튼은 **fail closed**로 disabled 된다.
8. **`riskWorkspaceId` placeholder 제거** — `AddSourceChooser`가 현재 `"dev-workspace"`로 고정되어 있다. Agent 1 app shell의 VWS 선택 값을 넘기도록 연결
9. **Firestore index 배포** — `REQUIRED_COMPOSITE_INDEXES` 8개를 실제 `firestore.indexes.json`으로 변환
10. **Cloud Tasks 정책** — retry / dead-letter / rate limit 설정
11. **`tests/integration`, `tests/e2e` 작성** — 현재 사실상 비어 있고, 세 Plane이 실제로 맞물리는지 검증할 유일한 지점
12. **`deploy/` 작성** — 현재 `.gitkeep`뿐. Cloud Run(API/Worker), Cloud Tasks, Cloud Scheduler, Secret Manager, Firestore index

### 6.2 처리 파이프라인 조립 참조 코드 (Agent 1 인계 문서 §5)

```python
registration = await facade.register_source_change(source_change)
claim = await facade.claim_analysis(registration.change_event_id)
if claim is None:
    return

try:
    snapshot = await source_adapter.fetch_snapshot(source_change)
except Exception:
    await facade.fail_analysis(registration.change_event_id, failure_safe="PROVIDER_UNAVAILABLE")
    raise

gate = await facade.build_analysis_artifact(
    snapshot, claim.analysis_job_id, source_scope=SourceScopeInput(in_scope=True)
)
if not gate.approved:
    return

for analyzer in analyzer_registry.supporting(gate.analysis_artifact):
    result = await analyzer.analyze(gate.analysis_artifact)
    await facade.accept_analysis_result(result)
```

**실패를 empty success나 "Risk 없음"으로 바꾸면 안 된다.**

---

## 7. 통합 시 반드시 유지해야 할 불변조건

| 불변조건 | 의미 |
|---|---|
| **Raw source 비영속** | `SourceSnapshot`은 transient. persistence에는 승인된 최소 `AnalysisArtifact`, content-free access event, bounded Evidence만 남는다. Control Plane은 raw source를 HTTP로 proxy하지 않는다 |
| **Provider authority 이중 검증** | `provider_authority_required=True`는 Control RBAC 통과만 의미. Source Plane/provider가 실제 credential과 원본 접근 권한을 **다시** 검증해야 한다 |
| **Gate-only boundary** | Intelligence Plane은 Gate가 승인한 `AnalysisArtifact` 뒤에서만 동작. `security_context.approved` 미승인이면 provider 호출 전에 거부 |
| **Failure preserves risk** | provider/system failure를 성공이나 "Risk 없음"으로 변환 금지. Agent 3은 provider가 하나라도 실패하면 `COMPLETE`를 반환하지 않는다 |
| **Backend-authoritative RBAC** | 권한 판단은 항상 backend. UI는 표시만 |
| **Credential/raw 로그 금지** | raw source·credential을 로그나 Shared Contract에 넣지 않는다 |
| **Risk 해소 판단은 Control** | Intelligence는 `status`/`coverage`를 보수적으로 설정할 뿐 |

---

## 8. 알려진 제약과 미구현 (통합 담당이 인지해야 할 것)

### 8.1 Agent 1

- 실제 Google credential/callback domain의 **OIDC roundtrip 미검증**
- 실제 Firestore emulator/production transaction과 **index 배포 미검증** (emulator 테스트 1건 skip)
- Cloud Tasks de-dup/retry/dead-letter, distributed ingress quota, proxy trust — Integration 소유
- 내장 rate limiter는 **단일 process 안전망**일 뿐 전역 quota가 아니다
- pagination은 scope-bound signed offset cursor. live write 중 offset 특성이 있다
- `RiskEvent`는 append-only/transactional이지만 **cryptographic hash chain은 아니다**
- Source metadata callback은 create/idempotent 등록만. credential rotation/reconnect/provider status transition은 미포함

### 8.2 Agent 2

- **`GET /desktop/mounts/{id}/status` 미구현** (조회용)
- **GitHub `reconcile()` 은 안전한 no-op**
- **Local MOVE 감지는 내용 해시 기반 추정** — 내용이 완전히 같은 다른 파일이면 오판 가능
- **`.ipriskignore`는 fnmatch 기반** — gitignore 전체 문법 미구현
- **Drive id_token 서명 검증 생략** (표시용. 실제 보안은 state CSRF + code exchange에서 완료)
- **GitHub `list_installation_repositories()`는 단일 페이지(최대 100개)만**
- **Drive 실제 파일 API(2HyN 이식 sync 코드)는 재시도 미적용**
- **LocalStagingStore는 텍스트만 처리** — 바이너리 확장 필요
- **symlink escape 테스트 2건 SKIP** — Windows 관리자 권한 없으면 자동 skip. 로직은 존재
- **스타일링 없음, React 컴포넌트 자동 테스트 없음**
- 보안 체크리스트 20개 중 ✅17 / 🟡3 (Drive file ID 안정성, symlink escape, staging TTL)

### 8.3 Agent 3

- **RAG corpus가 초기 3건** (AGPL-3.0 / LGPL-2.1 / 고지형 의무사항, 총 2,120 bytes). 84종 전체는 자료 확보 후 `manifest.yaml`에 추가하고 `corpus_version`을 올리면 된다
- **특허 청구항을 쓰지 못한다** — KIPRIS Plus 제공 범위가 초록. 그래서 `HIGH`가 나오지 않으며, 초록 근거 2개 이상이면 `MEDIUM`으로 올리도록 조정
- **후보 상위 6건만 판정** (비용). 미판정 후보가 있으면 coverage가 `PARTIAL`이 되어 Control이 자동 해소하지 않는다
- **`GEMINI_MODEL_ID` 값 미확정** (§5.3)
- **RAG Engine만 실호출 미검증** — GCP 프로젝트와 corpus 필요
- **VWS별 라이선스 정책 불가** — `AnalysisArtifact`에 자리가 없어 전역 정책 `global-license-policy-2026-08-14.1` 하나만 사용. 조직별 정책이 필요해지면 Contract v2 필요

#### 🔴 8.3.1 인계 문서에 기재되지 않은 RAG 결함 4건 (코드 확인 결과)

Agent 3 인계 문서는 RAG를 "실호출 미검증"으로만 적었으나, 코드를 읽어 확인한 결과 아래 4건은 **미검증이 아니라 미구현·오동작**이다. 통합 담당이 인지해야 한다.

| # | 문제 | 확인 위치 | 영향 |
|---|---|---|---|
| A | **RAG Engine 업로더 미구현.** `CorpusUploader` Protocol의 구현체가 `InMemoryCorpusUploader` 하나뿐이고 `engine.py`에 `importFiles`/`ragFiles` 호출이 없다. 코드로는 corpus를 RAG Engine에 올릴 수 없다 | `rag/ingestion.py:32,125`, `rag/engine.py` | Agent 3 Spec §36의 `upload/import RAG Engine` 미충족. 콘솔/`gcloud` 수동 업로드 없이는 검색 대상이 존재하지 않는다 |
| B | **`filters`가 운영 경로에서 무시된다.** `RagEngineRetriever.retrieve()`가 `filters`를 받지만 payload에 넣지 않는다. `license/analyzer.py`도 `filters`를 넘기지 않는다 | `rag/engine.py:100-118`, `license/analyzer.py:195` | 매니페스트의 `jurisdiction`/`tags` 메타데이터가 무용지물. `test_retrieval_honours_filters`는 `InMemoryReferenceRetriever`만 검증하므로 이 불일치를 잡지 못한다 |
| C | **관련성 임계값 부재.** `threshold`/`vector_distance`/`similarity` 설정이 intelligence 전체에 없다. 관련도와 무관하게 항상 `top_k=3` 반환 | `intelligence/**` 전체 grep | D와 결합해 오근거 발생 |
| D | **corpus 커버리지 18%.** RAG를 타는 식별자는 `POLICY_CONFLICT` 9종 + `REVIEW_REQUIRED` 13종 + `UNKNOWN`인데, 대응 문서가 있는 것은 AGPL-3.0·LGPL-2.1 계열 4개뿐 | `license/policy.py` vs `rag-corpus/sources/` | `GPL-3.0-only` 분석 시 GPL 문서가 없어 **AGPL 문서**("이 점이 GPL-3.0 과 다르다"라고 적힌)가 근거로 붙는다. 근거 ID 검증과 프롬프트 제약을 **모두 통과한 채로** 틀린 근거가 나간다 |

부수 사항: `permissive-notice.md`가 다루는 MIT/BSD/Apache-2.0/ISC는 전부 `NOTICE_REQUIRED`라 `needs_review`가 `False`다. corpus 3건 중 1건은 자기 용도로 검색되지 않고 `UNKNOWN` 케이스에서 잘못 끌려 나올 수만 있다.

**최소 조치 (배포 전 필수)**: C(임계값)를 먼저 넣어 관련 없는 근거가 붙지 않게 하고, 임계 미달이면 근거 없이 `policy.describe()` 고정 문구로 대체한다. 이것만으로 D의 오근거 위험이 사라진다. A·B·D는 그 다음이다.

### 8.4 프로젝트 전체

- **`deploy/` 비어 있음** — 배포 설정 전무
- **`tests/integration`, `tests/e2e` 비어 있음**
- **배포 URL 없음** — 아직 어디에도 배포되지 않았다
- root `pyproject.toml`의 `testpaths`가 `shared/contracts/tests`뿐이라 **`pytest`만 실행하면 세 Plane 테스트가 하나도 돌지 않는다**

---

## 9. 실행 절차

### 9.1 worktree 구성 (완료 상태)

```bash
cd "c:/Users/3780y/바탕 화면/AI부캠/ip-risk-agent-v2"
git fetch --all --prune
git worktree add ../wt-integration -b wt/integration origin/integration
git worktree add ../wt-control     -b wt/platform-control            origin/platform-control
git worktree add ../wt-source      -b wt/source-integration-desktop  origin/source-integration-desktop
git worktree add ../wt-rag         -b wt/risk-intelligence-rag       origin/risk-intelligence-rag
```

worktree마다 `.venv`와 `node_modules`가 독립이므로, 충돌 해결 중에 원본 branch의 테스트를 옆 창에서 그대로 재현할 수 있다.

### 9.2 병합

```bash
cd ../wt-integration

git merge --no-ff origin/platform-control          # 충돌 없음
pytest tests/control -q                            # 기준선 확보

git merge --no-ff origin/risk-intelligence-rag     # 충돌 없음
pytest tests/intelligence -m "not live" -q

git merge --no-ff origin/source-integration-desktop
# → CONFLICT: frontend/{index.html,package.json,tsconfig.json,vite.config.ts}
git checkout --ours frontend/package.json frontend/tsconfig.json frontend/vite.config.ts frontend/index.html
# index.html의 lang="ko" 수정 + PlatformAdapter.test.ts vitest 포팅 + preview.tsx 처리
git add frontend/ && git commit
```

### 9.3 통합 검증

```bash
# root manifest 확정 후
pip install -e ".[dev]"
pip check

pnpm install
pnpm run generate                       # generated contract에 tracked diff가 없어야 함
pnpm run typecheck
pnpm run verify:resolution
pnpm run build

pytest shared/contracts/tests tests -q   # 목표: 3 Plane 전체 통과
pytest tests/intelligence -m live        # 자격증명 있을 때만
python -m compileall -q backend/src shared/contracts/python scripts

pnpm --filter @iprisk/frontend test
pnpm --filter @iprisk/desktop build && pnpm --filter @iprisk/desktop test
```

Windows에서 contract test 실행 시 `PNPM_EXECUTABLE`에 `pnpm.cmd`를 지정한다.

### 9.4 푸시

```bash
git push origin wt/integration:integration
```

이후 GitHub에서 `integration` → `main` PR을 연다. 병합 커밋 3개 + 충돌 해결 커밋 1개 구조라 어느 Agent 작업이 어디서 들어왔는지 히스토리에 그대로 남는다.

### 9.5 worktree 정리 (Windows 주의)

```bash
git worktree remove ../wt-control
git worktree remove ../wt-rag
git worktree remove ../wt-source
# wt-integration은 배선 작업 완료까지 유지
```

VS Code나 파일 감시자가 디렉터리를 잡고 있으면 `Permission denied`로 실패한다. 이때는 해당 폴더를 연 에디터/터미널을 모두 닫고 `git worktree remove --force` → `rm -rf` → `git worktree prune` 순으로 처리한다. `.git/worktrees/<name>` 메타데이터가 남으면 PowerShell `Remove-Item -Recurse -Force`로 직접 삭제한 뒤 `git worktree prune`을 다시 실행한다.

---

## 10. 통합 담당 우선순위 체크리스트

| 우선 | 항목 | 참조 |
|:---:|---|---|
| 🔴 1 | FastAPI 버전 결정 (`0.141.1` 채택 후 Agent 2 테스트 224건 재검증) | §4.4-A |
| 🔴 2 | `@types/node` 24.x로 통일 후 typecheck 재실행 | §4.4-B |
| 🔴 3 | Python 3.14.7로 통일 + `ENVIRONMENT_SETUP.md` 수정 + Agent 3 재검증 | §4.6 |
| 🔴 4 | `KIPRIS_ACCESS_KEY` 변수명 정합화 | §5.2 |
| 🔴 5 | `GEMINI_MODEL_ID` 실제 값 확정 | §5.3 |
| 🔴 6 | root `pyproject.toml` `testpaths`에 `tests` 추가 | §4.7 |
| 🟠 7 | frontend 충돌 4건 해결 + PlatformAdapter.test.ts vitest 포팅 | §3.3 |
| 🟠 8 | `AuthzDependency`를 실제 VWS Role 검사로 교체 (현재 무검사) | §2.3 |
| 🟠 9 | `main.py` / `worker.py` / `composition/` 배선 | §6.1 |
| 🟠 10 | `riskWorkspaceId` placeholder `"dev-workspace"` 제거 | §6.1-8 |
| 🟠 10.5 | RAG 관련성 임계값 도입 (오근거 차단) — 배포 전 필수 | §8.3.1-C |
| 🟡 11 | pytest-asyncio strict 모드 영향 확인 | §4.5 |
| 🟡 11.5 | RAG Engine 업로더 구현 + `filters` payload 반영 + corpus 커버리지 확대 | §8.3.1-A/B/D |
| 🟡 12 | `.env.example`에 누락 변수 6개 추가 | §5.1 |
| 🟡 13 | Firestore composite index 8개 → `firestore.indexes.json` 변환 | §2.2 |
| 🟡 14 | `deploy/` 작성 (Cloud Run × 2, Tasks, Scheduler, Secret Manager) | §6.1-12 |
| 🟡 15 | `tests/integration`, `tests/e2e` 작성 | §6.1-11 |

---

## 부록. 근거 문서 위치

| 문서 | 위치 | 크기 | 역할 |
|---|---|---|---|
| `IP_RISK_AGENT_MEETING_BLUEPRINT.md` | 전 branch 공통 | 49KB | 제품/아키텍처/보안/개발축 청사진 |
| `CODING_AGENT_MASTER_SPEC.md` | 전 branch 공통 | 55KB | 최상위 개발 규약. **충돌 시 최우선** |
| `CODING_AGENT_SPEC_1_PLATFORM_CONTROL.md` | 전 branch 공통 | 31KB | Agent 1 상세 명세 |
| `CODING_AGENT_SPEC_2_SOURCE_DESKTOP.md` | 전 branch 공통 | 27KB | Agent 2 상세 명세 |
| `CODING_AGENT_SPEC_3_RISK_INTELLIGENCE_RAG.md` | 전 branch 공통 | 27KB | Agent 3 상세 명세 |
| `ENVIRONMENT_SETUP.md` | 전 branch 공통 | 7KB | 공통 환경 구조·검증 (🔴 Python 버전 오기) |
| `README.md` | 전 branch 공통 | 9KB | branch 구조·ownership·워크플로 |
| `AGENT_1_DELIVERY.md` | wt-control | 21KB | Agent 1 인계 (조립 코드 포함) |
| `AGENT_1_PLATFORM_CONTROL_IMPLEMENTATION_PLAN.md` | wt-control | 183KB | Agent 1 전체 구현 현황·판단 기록 |
| `LOCAL_RUN_AND_TEST_GUIDE.md` | wt-control | 8KB | 로컬 실행/시나리오 (삭제 가능) |
| `agent-1-dependencies.md` | wt-control | 9KB | Agent 1 검증 dependency |
| `AGENT_2_DELIVERY.md` | wt-source | 13KB | Agent 2 인계 (wiring point 포함) |
| `agent-2-dependencies.md` | wt-source | 4KB | Agent 2 검증 dependency |
| `AGENT_3_DELIVERY.md` | wt-rag | 7KB | Agent 3 인계 |
| `agent-3-dependencies.md` | wt-rag | 7KB | Agent 3 검증 dependency + 실호출 결과 |
