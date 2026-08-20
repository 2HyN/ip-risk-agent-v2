# Integration

세 개발 branch 를 `integration` 으로 합치고, 각 Plane 이 내놓은 조립 부품을 하나의 실행
가능한 애플리케이션으로 잇는 작업의 기록이자 참조 문서다.

**현재 상태** — 병합·조립 완료. 앱이 기동하고 전 계층 검증이 통과한다.
GCP 자원 연동만 남았다.

```
uvicorn ip_risk_agent.main:app       # API
uvicorn ip_risk_agent.worker:app     # 분석 워커
```

---

## 1. 병합 기록

`origin/integration` 기준 세 branch 를 순서대로 병합했다.

| 순서 | branch | 결과 |
|---|---|---|
| 1 | `platform-control` | 충돌 없음 |
| 2 | `risk-intelligence-rag` | 충돌 없음 |
| 3 | `source-integration-desktop` | **충돌 4건 — 전부 `frontend/` 설정** |

**backend 파일 충돌 0건.** 디렉터리 ownership 을 사전에 나눈 설계가 실제로 작동했다.
세 branch 291개 파일 변경에서 충돌은 공유 툴체인 설정에서만 발생했다.

병합 규모: 316 files changed, +45,448 / −29.

### 충돌 해결

| 파일 | 처리 |
|---|---|
| `frontend/package.json` | Control 채택 (vitest·Testing Library·라우터 보유) |
| `frontend/vite.config.ts` | Control 채택. `/api` → `127.0.0.1:8000` proxy 가 필수 |
| `frontend/tsconfig.json` | Control + `types` 에 `"node"` 추가 |
| `frontend/index.html` | Control + `lang="ko"`. 진입점 `/src/main.tsx` 단일화 |

Source 의 `build.outDir: dist/web` 분리는 Control 의 `noEmit` 을 채택하면서 불필요해졌다.

### 테스트 포팅 — `// @vitest-environment node` 가 필수인 이유

Source 의 프론트엔드 테스트 2개 파일 8건은 `node --test` 용이었다. vitest 로 옮길 때
러너 import 교체만으로는 깨진다.

```ts
// PlatformAdapter.test.ts
(globalThis as ...).window = { desktopApi: fakeApi };
try { ... } finally { delete (globalThis as ...).window; }
```

Control 의 vite 설정은 `environment: "jsdom"` 이 전역이라 `window` 가 이미 존재하고
재정의가 막혀 있다. 파일 단위 환경 오버라이드로 `node --test` 와 같은 의미를 유지했다.

```diff
+ // @vitest-environment node
+
- import test from "node:test";
+ import { test } from "vitest";
  import assert from "node:assert/strict";
```

두 파일 모두 DOM 을 쓰지 않는 순수 로직 테스트라 부작용이 없다.
결과: frontend vitest **15 + 8 = 23건**.

### 함께 처리한 정합성 수정

| 대상 | 내용 |
|---|---|
| `pyproject.toml` | 세 Plane dependency 통합, `testpaths` 확장, `asyncio_mode`, `live` marker 등록 |
| `pnpm-lock.yaml` | 재생성. `--frozen-lockfile` 통과 |
| `ENVIRONMENT_SETUP.md` | Python 3.12.13 → 3.14.7 (현재는 [DEVELOPMENT.md](DEVELOPMENT.md) 로 통합) |
| `.env.example` | 코드가 실제로 읽는 변수 4개 추가 (`GEMINI_API_KEY`, `KIPRIS_ACCESS_KEY`, `RAG_CORPUS_VERSION`, `IPRISK_SERVER_BASE_URL`) |
| `.gitattributes` | 신규. 생성물 LF 고정으로 Windows CRLF 잡음 제거 |
| `frontend/src/sources/dev/preview.tsx` | 제거 — app shell 연결로 대체 |

---

## 2. 조립 구조

`backend/src/ip_risk_agent/composition/` — Integration 소유. 세 Plane 의 public surface
만 import 하고 어떤 Plane 의 내부 모듈도 직접 건드리지 않는다.

| 모듈 | 역할 |
|---|---|
| `settings.py` | 환경변수 바인딩. GCP 설정이 없으면 in-memory 로 하강 |
| `runtime.py` | UTC clock, opaque `id_factory` |
| `container.py` | 전체 의존성 그래프. OIDC·UoW·queue 를 주입 가능하게 개방 |
| `app.py` | FastAPI 조립 + `/health`. provider 라우터는 설정된 것만 붙인다 |
| `authz.py` | Source 라우터 authz 를 Control RBAC 로 잇는 어댑터 |
| `source_callbacks.py` | provider 선택 결과 → canonical 등록 명령 |
| `sinks.py` | `SourceChangeSink` → `facade.register_source_change` |
| `pipeline.py` | Master Spec 21 의 고정 순서 실행체 |

`main.py` 와 `worker.py` 는 조립 결과를 ASGI 런타임이 찾을 이름으로 노출하기만 한다.

### 처리 파이프라인

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

`AnalysisPipeline.run(change)` 가 이 순서를 그대로 수행한다. Source Plane 과
Intelligence Plane 사이에 직접 호출 경로는 없다.

---

## 3. authz 어댑터 — 통합에서 가장 손이 많이 간 부분

두 Plane 의 모양이 다르다.

```python
# Source 가 기대하는 모양
async def __call__(self, request: Request, resource_id: str) -> None: ...

# Control 이 제공하는 모양
async def __call__(self, *, actor_user_id, risk_workspace_id,
                   action: PublicVwsAction, mount_id=None,
                   provider_credential_owner_user_id=None) -> FacadeAuthorizationDecision: ...
```

그대로 꽂히지 않는다. 어댑터가 ① 세션에서 `actor_user_id` 추출 ② `resource_id` 해석
③ 12개 `PublicVwsAction` 중 선택을 수행한다.

**`resource_id` 는 라우트마다 의미가 다르다.** 하나로 뭉뚱그리면 mount 등록이 VWS 멤버십
검사 없이 통과한다. 그래서 스코프별 팩토리를 만들고 경로로 분기한다.

| 팩토리 | `resource_id` | 적용 라우트 |
|---|---|---|
| `workspace_scoped` | `risk_workspace_id` | Drive/GitHub 연결 시작, `/desktop/mounts/register` |
| `mount_scoped` | `mount_id` → `facade.get_mount_ref` 로 workspace 역추적 | `/desktop/staging`, `/desktop/events` |
| `connection_scoped` | `connection_id` → `ConnectionRegistry` 로 역추적 | Picker 세션, repo 목록 |
| `session_only` | 없음 | `/desktop/devices/register` (사용자 단위 자원) |
| `path_scoped` | 위를 경로별로 분기 | 라우터 하나에 여러 스코프가 섞인 경우 |

### 해소한 상태

Source 의 기본값은 아무것도 검사하지 않았다.

```python
async def allow_all_authz(request, resource_id) -> None:
    """개발/테스트 전용 기본값 — 아무 것도 검사하지 않는다."""
    return None
```

이제 모든 Source 라우트가 401/403 으로 닫힌다.
`tests/integration/test_source_authorization.py` 가 회귀 테스트로 잠갔다.

**인증 우회 경로는 만들지 않았다.** Google 자격증명이 없으면 `UnavailableOidcClient` 가
502 로 fail closed 한다. 개발용 로그인 백도어를 두지 않았다.

---

## 4. 라우터 조립 정책

provider 자격증명이 없으면 **라우트를 만들지 않는다.** 있는 척 열어두고 런타임에 실패하면
원인을 찾기 어렵다. 무엇이 붙었고 무엇이 왜 빠졌는지는 `/health` 가 그대로 보여준다.

```json
{
  "status": "ok",
  "control_backend": "in-memory",
  "google_login": "unconfigured",
  "intelligence": "disabled",
  "sources": {
    "mounted": ["local"],
    "skipped": {
      "google_drive": "GOOGLE_DRIVE_CLIENT_ID/SECRET/REDIRECT_URI 미설정",
      "github": "GITHUB_APP_ID/GITHUB_APP_SLUG 미설정"
    }
  }
}
```

`/health` 는 비밀값을 담지 않는다. 어떤 저장소를 쓰는지, 어떤 provider 라우터가 붙었는지,
분석 경로가 살아 있는지만 알린다.

---

## 5. 프론트엔드 통합

Control UI 는 `frontend/src/sources/**` 를 직접 import 하지 않고, Source UI 는 Control 의
라우팅을 모른다. 연결은 `frontend/src/main.tsx` 에서만 일어난다.

```tsx
<ControlPlaneApp
  router="browser"
  integration={{ sourcePanel: <SourcePanel /> }}
/>
```

`SourcePanel` 이 `useWorkspace()` 로 현재 VWS 를 읽으므로 Source 가 쓰던
`riskWorkspaceId="dev-workspace"` 하드코딩이 사라졌다.

- `router="browser"` 는 Web, `"hash"` 는 Electron renderer 용이다.
- `openOriginal` 콜백은 아직 백엔드 resolver 가 없어 주입하지 않는다. 콜백이 없으면
  버튼이 이유와 함께 disabled 로 **fail closed** 되므로, 임의로 열어주지 않고 그대로 둔다.

번들 규모가 47 → **52 modules** 로 늘어 Source UI 가 실제로 포함됐음을 확인했다.

---

## 6. 확장 지점 — GCP 연동 시 교체할 것

`container.py` 의 `SourcePorts` 한 곳에 모아뒀다. 이 필드만 실물로 바꾸면 된다.

| 포트 | 현재 | 교체 대상 |
|---|---|---|
| `unit_of_work_factory` | `InMemoryControlStore` | Firestore — **코드 분기는 이미 있다.** `GCP_PROJECT_ID` + `FIRESTORE_DATABASE` 설정 시 자동 전환 |
| `task_enqueuer` | `InMemoryTaskEnqueuer` | Cloud Tasks |
| `credential_vault` | `InMemoryCredentialVault` | Secret Manager |
| `oauth_state_store` | `InMemoryOAuthStateStore` | Firestore (다중 인스턴스면 필수) |
| `staging_store` | `InMemoryLocalStagingStore` | GCS 버킷 |
| `change_sink` | ✅ `ControlSourceChangeSink` | 이미 실물 |
| `connections` / `devices` | ✅ Integration 레지스트리 | Firestore 이관 검토 |

그 외 남은 것:

- Drive/GitHub provider factory·webhook·mounts 라우터 (실제 API client 필요)
- `deploy/` — Cloud Run × 2, Cloud Tasks, Cloud Scheduler, Secret Manager
- Firestore composite index 8개 → `firestore.indexes.json` 변환
- `tests/e2e`
- Open Original resolver — `facade.get_original_source_request` 를 호출하는 구현

### 서비스 계정 분리 (Master Spec 48)

| 계정 | 역할 |
|---|---|
| `app-api-sa` | Cloud Run API |
| `analysis-worker-sa` | Cloud Run Analysis Worker |
| `scheduler-sa` | Cloud Scheduler (Drive watch renewal, reconciliation) |
| `deploy-sa` | 배포 |

---

## 7. 🔴 알려진 계약 공백

**Cloud Tasks 경로가 아직 성립하지 않는다.**

`TaskEnqueuer.enqueue_change(change_event_id: str)` 는 content-free ID 하나만 넘긴다.
그런데 다음 단계인 `SourceAdapter.fetch_snapshot(change)` 는 `SourceChange` 전체를
요구하고, `ControlPlaneFacade` 의 공개 메서드 중 `change_event_id` 로 `SourceChange` 를
되짚는 것이 없다.

따라서 ID 만으로 워커를 기동하려면 Control 이 조회 메서드를 하나 더 공개해야 한다.
그때까지 워커는 `SourceChange` 본문을 직접 받는 경로(`POST /internal/analysis/run`)만
제공한다.

**Control 내부를 우회 조회해 임시로 메우지 않았다.** Master Spec 62 에 따라
contract-change request 대상으로 올려야 하는 항목이다.

---

## 8. 통합 검증

README 6절의 정식 순서를 따른다.

| 단계 | 명령 | 결과 |
|---|---|---|
| 1 | `pnpm install --frozen-lockfile` | OK |
| 2 | `pnpm run generate` | tracked diff 0건 |
| 3 | `pnpm run typecheck` | contracts + frontend + desktop |
| 4 | `pnpm run build` | frontend 52 modules |
| 5 | `pnpm run verify:resolution` | OK |
| 6 | `pytest` | 593 passed / 7 skipped |
| 7 | `compileall`, `pip check` | OK |
| 8 | `pnpm --filter @iprisk/frontend test` | 23 passed |
| 9 | `pnpm --filter @iprisk/desktop test` | 65 (63 passed / 2 skipped) |

> `verify:resolution` 은 **`build` 이후**에 실행해야 한다. contracts `dist` 가 없으면
> `Cannot find module '@iprisk/contracts/dist/index.js'` 로 실패한다.

### 통합 테스트 21건

한 Plane 안에서는 확인할 수 없는 경계만 다룬다.

| 파일 | 검증 내용 |
|---|---|
| `test_app_composition.py` | `/health` 정확성·비밀 미노출, Control/Source 라우트 동시 마운트, 설정 시 provider 라우터 등장, 로그인 왕복, 미설정 시 fail closed |
| `test_source_authorization.py` | 무인증 Source 접근 거부(회귀 잠금), VWS 멤버십 없는 Mount 등록 거부, provider 라우터 동일 규칙 |
| `test_analysis_pipeline.py` | 어댑터 부재를 성공으로 위장하지 않음, provider 실패 전파, 같은 변경이 하나의 `ChangeEvent` 로 수렴, 진행 중 재점유 차단, Electron 이벤트가 `staging → events → sink → Control` 도달 |

### 통합 중 수정한 잘못된 가정

"같은 변경은 한 번만 점유된다"고 단언한 테스트가 실패했다. 원인은
`ControlPlaneFacadeConfig.retry_failed_events` 기본값이 `True` 라 **실패 기록 후 재점유가
정상 동작**이기 때문이다. 실제 보장은 "같은 사건이 하나의 content-free ID 로 수렴"이므로
그렇게 고쳤고, 진행 중 재점유 차단은 별도 테스트로 분리했다.

---

## 9. 병렬 개발 구조에 대한 회고

**작동한 것**

- 디렉터리 ownership 사전 분할 + Frozen Contract → backend 파일 충돌 **0건**
- 실호출 검증 의무화(mock-only 완료 주장 금지) → Intelligence 에서 결함 5건 발견
- Plane 별 인계 문서·dependency 문서 필수화 → 통합 시 정보 손실 없음

**문제였던 것**

- root manifest 를 아무도 수정하지 않아 dependency 충돌이 **통합 시점에 한꺼번에** 드러났다
  (FastAPI, `@types/node`, lockfile)
- 문서 간 Python 버전이 3.12/3.13/3.14 로 제각각이었다
- 프론트엔드 빌드 철학(vitest vs node:test)이 사전 합의되지 않아 유일한 충돌 지점이 됐다
- **코드는 ownership 으로 나눌 수 있어도 툴체인 설정은 나눌 수 없다**

**다음에 할 것**

- dependency 는 병합 전 **주기적 dry-run 병합**으로 조기 감지
- 프론트엔드 툴체인도 Frozen Contract 처럼 사전 고정
- 통합을 마지막이 아니라 주 1회 리허설로 상시 수행
