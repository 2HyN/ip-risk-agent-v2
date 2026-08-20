# integration-v2 병합·통합 실행 계획

> 상태: **병합 직전 실행 기준안**  
> 기준일: 2026-08-21  
> 대상 branch: `integration-v2`  
> 병합 대상: `platform-control`, `source-integration-desktop`, `risk-intelligence-rag`  
> 선행 결정: [`INTEGRATION_V2_DEPENDENCY_BASELINE.md`](./INTEGRATION_V2_DEPENDENCY_BASELINE.md)

이 문서는 세 feature branch를 단순히 Git으로 합치는 방법뿐 아니라, 병합 직후 어떤 경계를 보강하고 어떤 순서로 실제 실행 가능한 제품으로 조립할지를 확정한다. 아래 순서와 gate를 따르면 별도 설계 회의 없이 merge와 통합 구현을 시작할 수 있다.

---

## 1. 최종 결론

### 1.1 병합 순서

다음 순서로 `--no-ff` merge한다.

1. `platform-control`
2. `source-integration-desktop`
3. `risk-intelligence-rag`

Control을 먼저 넣어 canonical domain/API/Product UI를 기준면으로 만든다. Source를 두 번째로 넣고 유일한 충돌 영역인 frontend toolchain을 즉시 확정한다. Intelligence는 다른 두 branch와 변경 경로가 겹치지 않으므로 마지막에 독립적으로 합친다.

예상 text conflict는 아래 네 파일뿐이다.

```text
frontend/index.html
frontend/package.json
frontend/tsconfig.json
frontend/vite.config.ts
```

`risk-intelligence-rag`와 다른 branch 사이의 변경 파일 교집합은 없다. Backend plane 소유 경로끼리도 교집합이 없다. `pnpm-lock.yaml`은 Source branch의 변경을 최종본으로 인정하지 않고 통합 manifest에서 재생성한다.

### 1.2 목표 실행 구조

```text
Browser / Electron renderer
        |
        v
Cloud Run API (FastAPI + static web)
  - Control API / session / CSRF / RBAC
  - Drive OAuth + mount + webhook
  - GitHub App + mount + webhook
  - Desktop enrollment + staging + event
        |
        +--> Firestore canonical state
        +--> Firestore source operational state
        +--> Secret Manager
        +--> Cloud Storage transient staging
        +--> Cloud Tasks: { change_event_id }
                         |
                         v
Cloud Run Analysis Worker
  claim -> SourceAdapter.fetch_snapshot
  -> SourceAccessEvent -> Security Gate
  -> IntelligenceFacade -> AnalysisResult
  -> Control reconciliation
```

API와 Worker는 같은 Python package 및 image를 사용할 수 있지만 서로 다른 entrypoint와 service account로 배포한다. Web UI는 API와 same-origin으로 제공해 session cookie, CSRF, OAuth callback 및 CORS 복잡도를 최소화한다.

### 1.3 통합 완료의 의미

다음 조건을 모두 충족해야 “통합 완료”다.

- 세 branch의 전체 기능 및 frozen Contract v1 test가 하나의 dependency set에서 통과한다.
- 실제 FastAPI app에 Control bundle과 모든 활성 Source router가 장착된다.
- Source의 기본 `allow_all_authz`와 in-memory production port가 남지 않는다.
- Cloud Tasks payload는 `change_event_id` 하나만 포함한다.
- Worker가 ID만으로 원래 `SourceChange`를 안전하게 복구하고, crash/retry 후에도 영구 `PROCESSING` 상태를 만들지 않는다.
- Gate 승인 전 Intelligence가 호출되지 않는다.
- 요청된 analyzer마다 정확히 하나의 `AnalysisResult`가 Control로 수렴한다.
- 실패, 부분 결과, 불확정 결과가 기존 Risk를 resolve하지 않는다.
- Web에서 Drive/GitHub 연결과 mount 선택이 끝까지 이어진다.
- Electron에서 로그인/기기 등록/로컬 mount/변경 전송이 인증된 경로로 끝까지 이어진다.
- production profile에서 미설정 dependency가 in-memory로 조용히 하강하지 않는다.
- GCP 내부 코드와 배포 산출물이 준비되고, 외부 console 작업만 별도 체크리스트로 남는다.

---

## 2. 기준점과 변경 금지 범위

### 2.1 분석 기준 commit

| Branch | 분석 기준 HEAD |
|---|---|
| `main` | `7cfbec446ac50fcc36c14031cb4310c30c8a0e5c` |
| `integration-v2` | `1f2d3f3` (`main` + dependency baseline 문서) |
| `platform-control` | `de1dacce05474d4e3e6c7c2567f6b8a6bbdbeb64` |
| `source-integration-desktop` | `ee861b730d161caf876d2a300b476783d03bbaf6` |
| `risk-intelligence-rag` | `68e07a3fdf543bcb4871cb13aee95fcc64b5749d` |

실제 merge 직전에 각 branch HEAD를 다시 기록한다. 위 SHA와 달라졌다면 먼저 차이를 검토하고 이 문서의 충돌 예측과 public surface 표를 갱신한다.

### 2.2 수정 정책

- 모든 merge, conflict resolution, 통합 코드, manifest, lockfile, test, deploy 파일은 `integration-v2`에서만 수정한다.
- `main`, `platform-control`, `source-integration-desktop`, `risk-intelligence-rag` worktree는 읽기 전용으로 취급한다.
- `shared/contracts/**`는 frozen Contract v1이다. 통합 편의를 위해 수정하지 않는다.
- Plane 내부를 우회 import하지 않는다. 필요한 bridge가 없으면 public facade/port를 명시적으로 보강하고 회귀 test를 추가한다.
- raw source, provider token, secret, local absolute path를 Firestore canonical state, task payload, log, fixture에 넣지 않는다.

### 2.3 소유 경계

| 영역 | 최종 책임 |
|---|---|
| canonical domain, RBAC, Risk lifecycle, Control API | Control 코드 유지 |
| provider API, webhook normalization, local watcher | Source 코드 유지 |
| analyzer, Gemini, KIPRIS, RAG retrieval | Intelligence 코드 유지 |
| `composition/**`, `main.py`, `worker.py`, root manifest/lock, deploy, integration/e2e test | Integration 구현 |
| frontend app shell | Control 기준, Source UI는 public slot으로 주입 |
| integration 과정에서 발견된 Plane 간 public gap | 최소 public bridge + 해당 Plane 회귀 test |

---

## 3. Merge 실행 절차

### 3.1 사전 점검

PowerShell에서 `integration-v2` worktree를 기준으로 실행한다.

```powershell
git status --short --branch
git branch --show-current
git rev-parse HEAD
git rev-parse platform-control
git rev-parse source-integration-desktop
git rev-parse risk-intelligence-rag
```

조건:

- 현재 branch가 `integration-v2`다.
- tracked/untracked 사용자 변경이 없다. 단, 의도적으로 유지할 문서가 있다면 먼저 별도 commit한다.
- 세 feature branch SHA가 §2.1과 같거나, 달라진 commit을 검토했다.
- merge 시작 전 tag 또는 branch pointer를 만든다.

```powershell
git tag integration-v2-premerge-20260821
```

tag 이름이 이미 있으면 덮어쓰지 말고 새 날짜/sequence를 사용한다.

### 3.2 첫 번째 merge: Control

```powershell
git merge --no-ff platform-control -m "merge: platform-control into integration-v2"
git status --short
git diff --check HEAD^
```

예상 결과는 conflict 없음이다. 다음을 확인한다.

- `backend/src/ip_risk_agent/core/**`, `application/**`, `persistence/**`, `api/**`가 들어왔다.
- `frontend/src/app/**`, `auth/**`, `workspace/**`, `risk/**`가 들어왔다.
- `main.py`, `worker.py`, `composition/**`, root manifests는 아직 baseline placeholder/통합 소유 상태다.

### 3.3 두 번째 merge: Source

```powershell
git merge --no-ff source-integration-desktop -m "merge: source-integration-desktop into integration-v2"
git status --short
```

네 frontend conflict는 §4의 최종 내용을 적용한다. Source의 `pnpm-lock.yaml`은 merge 결과에 남더라도 최종 lock으로 간주하지 않는다.

해결 후:

```powershell
git add frontend/index.html frontend/package.json frontend/tsconfig.json frontend/vite.config.ts
git add pnpm-lock.yaml
git diff --check --cached
git commit
```

Git이 자동으로 merge commit을 만들기 위해 대기 중인 경우 마지막 `git commit`만 수행한다. 별도 일반 commit으로 conflict resolution을 분리하지 않는다.

### 3.4 세 번째 merge: Intelligence

```powershell
git merge --no-ff risk-intelligence-rag -m "merge: risk-intelligence-rag into integration-v2"
git status --short
git diff --check HEAD^
```

예상 결과는 conflict 없음이다. `backend/src/ip_risk_agent/intelligence/**`, `rag-corpus/**`, `tests/intelligence/**`가 추가됐는지 확인한다.

### 3.5 merge 직후 구조 검증

아직 dependency manifest를 정리하기 전이므로 전체 test 성공을 기대하지 않는다. 먼저 구조만 확인한다.

```powershell
git status --short --branch
git log --oneline --decorate --graph -12
git diff --name-only main...HEAD
git diff --check main...HEAD
```

필수 확인:

- 세 merge commit이 모두 history에 존재한다.
- conflict marker(`<<<<<<<`, `=======`, `>>>>>>>`)가 없다.
- frozen contract generated source에 의도하지 않은 diff가 없다.
- 다른 worktree에는 변경이 없다.

---

## 4. Frontend conflict 확정안

### 4.1 `frontend/package.json`

Control manifest를 기준으로 한다.

- `react-router-dom`, Vitest, jsdom, Testing Library를 유지한다.
- React/React DOM을 exact `19.2.8`로 유지한다.
- `build`는 `tsc --noEmit` 후 Vite build다.
- `test`는 `vitest run`으로 단일화한다.
- Source UI test는 Node test runner import를 Vitest로 포팅한다.
- 최종 exact version은 dependency baseline §7.2를 그대로 적용한다.

### 4.2 `frontend/tsconfig.json`

Control 설정을 기준으로 한다.

```json
{
  "module": "ESNext",
  "moduleResolution": "Bundler",
  "noEmit": true,
  "strict": true,
  "noUncheckedIndexedAccess": true,
  "exactOptionalPropertyTypes": true,
  "types": ["vite/client", "vitest/globals", "node"]
}
```

Source의 `NodeNext`, declaration emit, `dist` 출력은 frontend에 적용하지 않는다. Electron package는 자체 `NodeNext` 구성을 유지한다.

### 4.3 `frontend/vite.config.ts`

Control 설정을 유지한다.

- React plugin
- `/api` → `http://127.0.0.1:8000` proxy
- source map
- Vitest `jsdom`
- Control test setup file

Source test 중 DOM을 사용하지 않고 `globalThis.window`를 직접 대체하는 파일에는 다음 파일 단위 환경을 적용한다.

```ts
// @vitest-environment node
```

### 4.4 `frontend/index.html`

Control Product entrypoint `/src/main.tsx`를 유지한다. `lang="ko"`를 적용하되 viewport, theme, description metadata는 Control본을 유지한다.

`frontend/src/sources/dev/preview.tsx`는 merge 직후 잠시 존재할 수 있으나, Source panel을 app shell에 연결한 commit에서 삭제한다.

### 4.5 `pnpm-lock.yaml`

두 branch 중 어느 lockfile도 선택하지 않는다.

1. 모든 package manifest를 먼저 확정한다.
2. 기존 lockfile을 수동 편집하지 않는다.
3. 기준 Node/pnpm으로 root에서 lockfile을 재생성한다.
4. `pnpm install --frozen-lockfile`을 다시 실행해 재현성을 확인한다.

---

## 5. 먼저 해결할 P0 통합 공백

Branch별 unit test가 통과해도 아래 공백을 해결하지 않으면 제품은 실제로 동작하지 않거나 보안상 열려 있다. 일반 조립보다 먼저 처리한다.

### P0-1. Worker가 `change_event_id`로 `SourceChange`를 복구할 수 없음

현재 `ControlPlaneFacade.claim_analysis()`의 `AnalysisExecutionClaim`에는 다음만 있다.

```text
change_event_id, analysis_job_id, artifact_id, revision,
requested_analysis_types, attempt
```

그러나 `SourceAdapter.fetch_snapshot()`은 전체 `SourceChange`를 요구한다. Task payload에 `SourceChange`를 넣는 것은 금지되어 있고, worker가 Control 내부 repository를 직접 import하는 것도 금지한다.

확정 해결 방식:

1. Control의 canonical `ChangeEvent`에 frozen `SourceChange`의 **metadata-only 실행 입력**을 보존한다.
2. Firestore mapper가 이를 명시적으로 직렬화/역직렬화한다.
3. `AnalysisExecutionClaim`에 `source_change: SourceChange`를 추가한다.
4. `claim_analysis()`가 같은 transaction에서 읽은 canonical event로 claim을 반환한다.
5. raw content가 없는지 contract validation 및 mapper test로 고정한다.

이 변경은 frozen contract 자체를 바꾸지 않는다. 기존 `SourceChange` 모델을 canonical 실행 metadata로 보존하는 것이다. 신규 integration-v2 deployment는 새 schema로 시작한다. 기존 document 호환이 필요하면 누락된 `source_change`를 성공으로 추정하지 말고 명시적 migration/error로 처리한다.

Integration-owned relay collection은 차선책으로만 남긴다. relay를 쓰면 Control commit, relay write, task enqueue 사이의 원자성/race를 추가로 해결해야 하므로 기본안으로 채택하지 않는다.

### P0-2. Worker retry와 crash recovery가 완전하지 않음

현재 상태 전이는 정상 실행의 중복 claim은 막지만 다음 경우를 완전히 해결하지 못한다.

- worker가 `PROCESSING/RUNNING`으로 바꾼 뒤 crash
- `fail_analysis()` 후 Cloud Tasks가 같은 task를 재전달
- 실패 재처리 메서드가 별도 task를 다시 enqueue해 중복 task를 만드는 경우

확정 보강:

- claim에 `lease_expires_at` 또는 동등한 bounded lease를 둔다.
- 실행 attempt를 fencing 값으로 사용한다.
- 첫 delivery는 `PENDING/QUEUED`만 claim한다.
- retry delivery는 `FAILED` 또는 만료된 `PROCESSING`을 **재enqueue 없이** 원자적으로 reclaim한다.
- 유효 lease가 남은 중복 delivery는 2xx no-op 처리한다.
- 오래된 attempt가 결과를 제출하면 started-at/attempt fencing으로 거부한다.
- retryable provider/system failure는 canonical FAILED 기록 후 5xx로 Cloud Tasks retry를 허용한다.
- non-retryable validation/configuration failure는 FAILED 기록 후 2xx로 종료해 무한 재시도를 막는다.
- 마지막 queue attempt가 실패해도 Risk는 유지되고 failure notification/audit가 남는다.

필요 public surface는 내부 repository 우회 대신 Control facade에 최소로 추가한다. 예시는 `claim_analysis(change_event_id, allow_retry=False)`와 lease-aware claim DTO이며, 정확한 이름보다 위 상태 의미가 우선이다.

### P0-3. Source router의 기본 authz와 CSRF

Source router의 `AuthzDependency` 기본값은 `allow_all_authz`다. production에서 단 한 곳이라도 기본값을 사용하면 안 된다.

Web 요청:

- Control의 `CurrentPrincipalDependency`로 session version까지 검증한다.
- POST 등 mutation에는 Control의 `CsrfGuard`를 적용한다.
- Source frontend client는 `/api/v1/auth/me`에서 받은 CSRF token을 `X-CSRF-Token`으로 보낸다.
- workspace/mount/connection scope를 구분하고 Control facade의 `authorize_vws_action()`을 호출한다.

Webhook 요청:

- user session을 요구하지 않는다.
- Drive는 channel token + channel/resource binding을 검증한다.
- GitHub는 raw body HMAC + delivery ID + repository/mount binding을 검증한다.

Internal worker/scheduler 요청:

- browser session이 아니라 Cloud Run IAM/OIDC service identity로 제한한다.
- 단순히 `X-CloudTasks-*` header 존재만으로 신뢰하지 않는다.

### P0-4. Electron background 요청에는 인증 수단이 없음

현재 Electron main process의 `fetch()`는 session cookie, CSRF token 또는 device credential 없이 `/desktop/**`를 호출한다. Source router authz를 올바르게 닫는 즉시 현재 desktop 경로는 401이 된다.

확정 설계:

1. Electron renderer에서 사용자가 Control UI로 Google login한다.
2. session+CSRF로 one-time device enrollment challenge를 발급한다.
3. preload의 제한된 IPC를 통해 main process가 challenge를 교환한다.
4. 서버는 user와 device를 연결하고 회전 가능한 opaque device credential을 한 번 반환한다.
5. main process는 Electron `safeStorage`로 credential을 암호화해 userData 아래에 저장한다.
6. watcher background 요청은 `Authorization: Bearer <device credential>`을 사용한다.
7. 서버는 저장된 **hash**만 비교하고 VWS/mount/device binding을 다시 검증한다.
8. logout, device revoke, owner/session invalidation 시 credential을 폐기한다.

renderer에 credential을 노출하거나 localStorage에 보관하지 않는다. preload allow-list에는 enrollment/connection status처럼 필요한 IPC만 추가한다.

### P0-5. Connection과 Mount 사이의 canonical 모델 차이

Source는 OAuth/App install 직후 connection ID를 반환한 뒤 나중에 mount를 만든다. Control의 `register_source_metadata()`는 connection, source workspace, mount를 한 번에 만든다.

확정 해결 방식은 placeholder canonical mount를 만들지 않는 것이다.

- OAuth/App callback 단계: Integration-owned persistent `pending_source_connections`에 provider identity, VWS, owner, credential reference/installation ID를 저장하고 opaque pending connection ID를 반환한다.
- Picker/repository 선택 단계: pending record를 읽고 `SourceMetadataRegistrationCommand`를 **한 번** 호출해 canonical connection/workspace/mount를 생성한다.
- 같은 provider account의 여러 mount는 동일한 stable `connection_key`를 사용해 Control이 canonical connection을 재사용하게 한다.
- pending ID와 canonical connection/mount ID의 binding은 Integration-owned operational collection에 저장한다.
- callback retry는 같은 provider subject/installation 및 owner/VWS 조합으로 멱등화한다.
- pending record에는 TTL과 consumed/active 상태를 둔다.

OAuth callback 시점에 `external_scope_id="pending"`인 가짜 source workspace/mount를 만드는 방식은 채택하지 않는다.

### P0-6. Requested analyzer와 반환 결과의 완결성

Control 기본 설정은 PATENT와 LICENSE를 모두 요청한다. Intelligence registry는 구성되지 않은 analyzer를 조용히 제외할 수 있다. 이 상태에서 결과 일부만 수락하면 job이 영구 RUNNING으로 남을 수 있다.

확정 규칙:

- production 시작 시 활성 analyzer set을 먼저 확정한다.
- `ControlPlaneFacadeConfig.requested_analysis_types`와 활성 analyzer set을 일치시킨다.
- production 목표는 PATENT + LICENSE 모두 활성이다. 필수 provider 설정이 없으면 startup/readiness 실패다.
- Gate 후 `artifact.requested_analyzers`와 반환 `AnalysisResult.analysis_type` 집합이 정확히 같은지 검사한다.
- 누락, 중복, 예상 밖 result type은 canonical FAILED로 종료한다.
- 결과는 모두 Control에 전달하며, 마지막 type 수락 시 기존 aggregate logic이 job을 SUCCEEDED/INCONCLUSIVE/FAILED로 닫는지 test한다.
- `intelligence=None` 또는 `supports=False`를 정상 skip으로 ACK하지 않는다. production에서는 configuration failure다.

### P0-7. Source Web UI는 연결 시작 이후가 완성되지 않음

현재 Source UI는 Drive/GitHub 연결 시작 버튼까지만 실제 API를 호출한다. 다음을 구현해야 한다.

- OAuth/App callback 후 Product UI로 안전하게 복귀
- Drive Picker session → 선택 파일 → mount 생성
- GitHub repository 목록 → branch 선택 → mount 생성
- mount 생성 결과/오류 표시
- 현재 VWS ID 사용; `dev-workspace` 하드코딩 제거
- CSRF-aware client
- Local 선택 후 `connectLocalMount` IPC 호출
- 연결된 source/mount 상태 표시 및 reconnect/disable 진입점

callback redirect에는 secret/token을 넣지 않는다. opaque pending connection ID와 짧은 status만 전달한다.

### P0-8. Drive watch 생성/갱신 경로

Drive webhook router는 channel binding이 이미 존재한다고 가정하지만 branch에는 production watch channel을 만들고 갱신하는 전체 경로가 없다.

통합에서 다음을 추가한다.

- Drive mount 활성화 시 start page token 확보
- random channel ID와 검증 token으로 changes watch 생성
- channel ID/resource ID/expiry/mount binding 저장
- 만료 전에 Cloud Scheduler가 갱신
- webhook은 저장된 channel/resource/token 조합을 확인
- webhook 누락 대비 periodic reconcile
- old channel stop 및 cleanup

GitHub는 webhook을 주 경로로 사용하되 periodic health/reconcile에서 no-op 제약을 명시적으로 노출한다.

---

## 6. Dependency와 root 설정 적용

`INTEGRATION_V2_DEPENDENCY_BASELINE.md`를 단일 기준으로 적용한다. 이 문서에는 버전표를 중복하지 않는다.

### 6.1 `pyproject.toml`

- production direct dependencies를 baseline §5.1 exact version으로 적용한다.
- dev dependencies를 §5.2로 적용한다.
- package discovery가 `backend/src`와 frozen Python contract를 올바르게 포함하는지 유지한다.
- pytest 경로에 다음을 포함한다.

```text
shared/contracts/tests
tests/control
tests/connectors
tests/intelligence
tests/integration
tests/e2e
```

- `asyncio_mode = "strict"`와 `live` marker를 등록한다.
- Python lock/constraints 산출물 이름을 하나로 확정해 commit한다.

### 6.2 Node workspace

- root `package.json`에 `packageManager: pnpm@11.19.0`, 필요하면 Node engine을 명시한다.
- frontend는 §4와 dependency baseline §7.2를 적용한다.
- desktop은 dependency baseline §7.3 exact version을 적용한다.
- Source frontend tests를 Vitest로 포팅한다.
- contract generation 이후 resolution verification을 실행한다.

### 6.3 `.env.example`

dependency baseline §10의 이름만 포함하고 값은 비워두거나 안전한 placeholder를 사용한다. 다음 profile 변수를 추가한다.

```text
APP_ENV=local|test|production
APP_ROLE=api|worker|scheduler
LOG_LEVEL
```

Drive Picker 구현에서 project number/API key 같은 추가 public configuration이 실제로 필요하다고 확인되면 이름, 비밀 여부, 사용처를 baseline 문서에 먼저 기록한 뒤 추가한다.

### 6.4 Manifest commit gate

```powershell
python -m pip install -e ".[dev]"
python -m pip check
pnpm install
pnpm install --frozen-lockfile
```

manifest/lock commit에는 application 기능 변경을 섞지 않는다.

---

## 7. Integration-owned backend 구조

권장 파일 배치는 다음과 같다. 구현 중 이름은 조금 달라질 수 있지만 책임은 섞지 않는다.

```text
backend/src/ip_risk_agent/composition/
  __init__.py
  settings.py                 # profile별 strict env validation
  runtime.py                  # UTC clock, opaque ID, safe logging helpers
  container.py                # 전체 dependency graph
  app.py                      # FastAPI/router/static/lifespan 조립
  authz.py                    # session/CSRF/device/internal auth adapters
  source_registration.py      # pending connection -> canonical metadata
  source_bindings.py          # provider/mount/device operational mappings
  source_ports.py             # Source Protocol production adapters
  providers.py                # Drive/GitHub/Local adapter bundles
  sinks.py                    # SourceChange -> Control facade
  pipeline.py                 # worker execution order
  originals.py                # Open Original backend dispatch
  health.py                   # liveness/readiness safe status
  gcp/
    firestore.py              # shared clients, operational stores
    tasks.py                  # Cloud Tasks enqueuer
    secrets.py                # SourceCredentialVault
    storage.py                # LocalStagingStore
    rag.py                    # corpus uploader/ingestion command if adopted
    identity.py               # ADC/OIDC audience helpers

backend/src/ip_risk_agent/main.py
backend/src/ip_risk_agent/worker.py
```

### 7.1 Container 생성 순서

1. `Settings.from_env()`로 profile과 config group을 검증한다.
2. process-wide HTTP/GCP clients를 만든다.
3. Firestore canonical UoW factory를 만든다.
4. operational state, Secret Manager vault, GCS staging, Cloud Tasks adapter를 만든다.
5. Control services/facade를 만든다.
6. session principal, CSRF, workspace/mount/connection/device auth adapters를 만든다.
7. pending connection 및 canonical registration callback을 만든다.
8. provider factory와 SourceAdapter registry를 만든다.
9. Intelligence facade를 만들고 Control requested analyzer set과 대조한다.
10. Control API bundle과 Source routers를 만든다.
11. lifespan에서 owned async clients를 닫는다.

request마다 GCP client나 `httpx.AsyncClient`를 새로 만들지 않는다.

### 7.2 Runtime profile 정책

| Profile | 허용 |
|---|---|
| `test` | 명시적으로 주입된 fake/in-memory |
| `local` | 명시적 in-memory/emulator, health에 표시 |
| `production` | Firestore/Tasks/Secret Manager/GCS/Intelligence 필수; silent fallback 금지 |

일부만 채워진 config group은 항상 startup error다. 예를 들어 Cloud Tasks 네 변수 중 세 개만 설정된 상태를 in-memory로 하강시키지 않는다.

---

## 8. Control ↔ Source 조율

### 8.1 `SourceChangeSink`

production 구현은 단순하다.

```python
class ControlSourceChangeSink:
    async def persist(self, change: SourceChange) -> None:
        await facade.register_source_change(change)
```

P0-1의 canonical execution input 보강 후 별도 relay는 필요 없다. 반환 receipt는 structured log/metric에 safe ID만 남긴다.

### 8.2 Authz scope mapping

| Source route 성격 | `resource_id` 의미 | Control action |
|---|---|---|
| Drive/GitHub connection start | `risk_workspace_id` | `SOURCE_MOUNT` |
| Drive/GitHub mount create | body의 `risk_workspace_id` | `SOURCE_MOUNT` |
| Picker/repository list | pending `connection_id` | binding으로 VWS/owner 복구 후 `SOURCE_MOUNT` |
| Desktop mount create | `risk_workspace_id` | `SOURCE_MOUNT` |
| Desktop staging/event | `mount_id` | `MOUNT_SOURCE_OPERATION` |
| mount status | `mount_id` | `MOUNT_STATUS_VIEW` |
| reconnect | `mount_id` | `MOUNT_RECONNECT` + provider owner 확인 |
| scope change | `mount_id` | `MOUNT_SCOPE_MANAGE` |

모든 web mutation은 principal 검증 후 CSRF를 함께 검증한다. connection ID를 workspace ID로 오인하는 단일 generic authz 구현은 금지한다.

### 8.3 Pending connection record

안전한 최소 필드:

```text
pending_connection_id
source_type
risk_workspace_id
owner_user_id
provider_subject OR installation_id
provider_account_label
credential_ref                  # opaque ref only
status: PENDING | ACTIVE | EXPIRED | REVOKED
created_at, expires_at
canonical_connection_id optional
```

provider secret/token 본문은 Secret Manager에만 저장한다.

### 8.4 Canonical registration key

- Drive connection key: provider subject + owner boundary를 안정적으로 표현
- Drive workspace key: 선택 file ID set의 정렬된 digest
- GitHub connection key: installation ID
- GitHub workspace key: repository ID/full name + tracked branch
- Local connection/workspace key: owner + device ID
- registration key: VWS + source type + stable source workspace key

긴 file ID 목록을 raw key로 이어 붙이지 말고 stable digest를 사용한다. retry 때 같은 입력은 같은 key를 만들어야 한다.

### 8.5 Source operational stores

Firestore canonical collection과 분리된 namespace를 사용한다.

| Store | 내용 |
|---|---|
| pending connections | OAuth/install과 mount 사이 상태 |
| connection bindings | pending/canonical connection과 provider identity/ref |
| mount bindings | mount → connection/provider repository/channel |
| tracking scopes | Drive selected files, GitHub patterns/branch |
| runtime | cursor, watch expiry, webhook status, heartbeat |
| OAuth state | single-use state + actor/VWS + TTL |
| desktop devices | owner, public metadata, credential hash/status |

Risk, Review, Membership는 여기 저장하지 않는다. TTL 대상 OAuth/pending/temporary record에는 cleanup policy를 둔다.

---

## 9. API와 router 조립

### 9.1 API app

`create_api_app(container)`는 다음 순서로 조립한다.

1. FastAPI app 및 lifespan
2. Control error handlers/hardening/session middleware
3. Control API bundle install
4. Source web routers
5. provider webhook routers
6. desktop enrollment/source routers
7. health/readiness routes
8. production frontend static files와 SPA fallback

SPA fallback은 `/api/**`, `/webhooks/**`, `/internal/**`, health route를 가로채지 않아야 한다.

### 9.2 Source router mount 조건

production에서는 “설정 없으면 route를 숨기고 정상”으로 끝내지 않는다. 제품에서 활성화하기로 한 provider의 필수 설정이 없으면 readiness를 실패시킨다. local profile만 provider별 disabled 상태를 허용한다.

| Router | 필수 binding |
|---|---|
| Drive OAuth | OAuth state, OAuth client, vault, pending callback, workspace authz/CSRF |
| Drive mounts | vault, connection binding, tracking scope, canonical callback, scoped authz/CSRF |
| Drive webhook | adapter, channel resolver, channel validation, change sink |
| GitHub install | OAuth state, pending callback, workspace authz/CSRF |
| GitHub mounts | installation lookup, tracking scope, canonical callback, scoped authz/CSRF |
| GitHub webhook | processor/HMAC, mount resolver, change sink |
| Local desktop | GCS staging, device auth, device/mount callback, change sink |

### 9.3 OAuth/App callback 완료

- state는 single-use, TTL, actor/VWS-bound다.
- callback에서 provider code/installation을 처리한 후 pending record를 만든다.
- 성공 시 JSON 화면에 멈추지 않고 Product UI의 source completion route로 303 redirect한다.
- redirect query/fragment에는 opaque pending ID와 safe status만 넣는다.
- error는 safe code로 redirect하거나 safe HTTP error를 반환한다.

### 9.4 Open Original

backend endpoint 흐름:

1. current principal + CSRF/intent 검증
2. `facade.get_original_source_request()`로 VWS/Risk 권한 재검증
3. `mount.source_type`으로 adapter 선택
4. provider authority 재검증
5. `adapter.resolve_original()` 호출
6. Web Drive/GitHub는 허용된 URL scheme/host를 검증해 반환
7. Local은 opaque mount handle + relative path만 renderer로 반환
8. Electron preload가 canonical local root 아래인지 다시 검사한 후 OS open

Control frontend의 `openOriginal` integration callback이 이 endpoint와 `PlatformAdapter`를 연결한다.

---

## 10. Worker 파이프라인

### 10.1 API contract

Worker는 별도 FastAPI app으로 다음 내부 endpoint만 노출한다.

```text
POST /internal/tasks/analyze-change
body: { "change_event_id": "..." }
```

body에 source content, `SourceSnapshot`, credential, path를 넣지 않는다. Cloud Run IAM과 OIDC audience로 호출자를 제한한다.

### 10.2 고정 실행 순서

```text
1. task identity/body validation
2. lease-aware facade.claim_analysis(change_event_id)
3. claim.source_change.source_type으로 SourceAdapter 선택
4. adapter.fetch_snapshot(claim.source_change)
5. SourceAccessReceipt canonical 기록
6. facade.build_analysis_artifact(snapshot, analysis_job_id, source_scope)
7. snapshot reference 제거; 저장/로그 금지
8. Gate denied이면 Control이 terminal state를 기록했는지 확인 후 ACK
9. requested analyzer set 완결성 검증
10. intelligence.analyze(artifact)
11. result set 완결성/identity 검증
12. 각 result를 facade.accept_analysis_result()
13. 최종 job terminal state 확인
14. Local staging best-effort cleanup + TTL safety net
15. safe metric/log 후 ACK
```

`SourceSnapshot`은 함수 local scope 밖으로 내보내지 않는다. 예외 메시지를 그대로 canonical failure/log에 넣지 않고 safe category로 매핑한다.

### 10.3 실패 분류

| 실패 | canonical 처리 | HTTP |
|---|---|---|
| 이미 완료/유효 lease 중복 | no-op | 2xx |
| provider rate limit/timeout/unavailable | FAILED safe code, retry 가능 | 5xx |
| transient Gemini/KIPRIS/RAG failure | FAILED result 또는 safe failure, retry 가능 | 5xx 또는 정책상 result 수렴 |
| Gate policy deny | Gate가 INCONCLUSIVE/FAILED terminal 처리 | 2xx |
| malformed task/body | 분석 상태 변경 없음 | 4xx |
| adapter 없음/필수 config 없음 | CONFIGURATION_ERROR | 2xx + readiness 실패 |
| contract/result mismatch | FAILED, alert | 2xx 또는 제한된 재시도 후 2xx |

Cloud Tasks retry 횟수와 application/provider 내부 retry를 중첩해 폭증시키지 않는다. provider client의 짧은 retry budget 이후 queue-level retry로 넘긴다.

### 10.4 Pipeline 회귀 조건

- 같은 event fingerprint는 하나의 ChangeEvent/AnalysisJob/Risk set으로 수렴한다.
- 중복 task는 같은 결과를 두 번 만들지 않는다.
- worker crash 후 lease expiry/retry로 복구된다.
- 요청 analyzer 2개 중 하나가 누락되면 DONE이 되지 않고 명시적 FAILED다.
- 마지막 result가 들어온 뒤 job/event가 terminal이다.
- FAILED/INCONCLUSIVE/PARTIAL/NONE은 기존 active Risk를 유지한다.
- COMPLETE+SUCCEEDED+0 candidate만 기존 risk resolution을 허용한다.

---

## 11. Intelligence 조립

### 11.1 Production 생성

Agent 3의 `create_facade_from_env()`는 API key path에는 편리하지만 현재 Vertex configuration을 환경 변수에서 구성하지 않는다. production에서는 Integration이 명시적으로 다음을 만든다.

1. validated settings
2. ADC/Vertex용 `GoogleGenAIClient`
3. `HttpPackageMetadataProvider`
4. KIPRIS key를 주입한 `KiprisClient`
5. 선택적으로 `RagEngineRetriever`
6. `create_analyzer_registry(...)`
7. `IntelligenceFacade`

`GEMINI_API_KEY`는 local/live test용으로만 허용하고 GCP production은 attached service identity/Vertex 설정을 우선한다.

### 11.2 Analyzer 정책

- production 기본: PATENT + LICENSE
- KIPRIS가 없으면 PATENT를 조용히 제거하지 않고 startup failure
- package metadata provider가 없으면 LICENSE startup failure
- RAG가 필수 정책이면 RAG 미설정/실패를 LICENSE의 complete success로 취급하지 않음
- `patent_candidate_cap=6`은 현 baseline 유지
- model/prompt/policy/corpus version을 모든 result에 기록

### 11.3 RAG

현재 retrieval 구현은 있으나 production `CorpusUploader`는 in-memory 구현만 있다. 다음 중 하나를 phase 4에서 완료한다.

- Integration-owned ADC 기반 uploader와 `scripts/ingest_rag_corpus.py` 구현, 또는
- 공식 관리 도구로 ingestion하고 repository script는 manifest/checksum/버전 검증 및 명령 생성을 담당

어느 방식이든 다음은 고정한다.

- `rag-corpus/manifest.yaml` 승인 source만 적재
- checksum mismatch 시 전체 중단
- private Source Workspace 원문 적재 금지
- corpus version과 deployed resource ID 기록
- staging에서 실제 `retrieveContexts` live test

초기 corpus 3건은 기능 검증용이다. 지원 라이선스 범위가 충분하다는 의미로 표시하지 않는다.

---

## 12. Frontend와 Electron 통합

### 12.1 Web app shell

`frontend/src/main.tsx`만 세 Plane UI를 아는 composition point로 둔다.

```tsx
<ControlPlaneApp
  apiBaseUrl=""
  router={isElectron ? "hash" : "browser"}
  integration={{
    sourcePanel: <SourcePanel />,
    sourceNavigation,
    openOriginal,
  }}
/>
```

`SourcePanel`은 현재 workspace context를 받아 `riskWorkspaceId`를 만든다. Control-owned component가 `frontend/src/sources/**`를 직접 import하지 않는다.

### 12.2 Source API client

Source client를 Control의 인증된 client와 결합한다.

- same-origin cookies 사용
- mutation에 CSRF header
- API error의 safe code 처리
- OAuth 시작, picker/repository, mount 생성, status endpoint 구현
- absolute backend URL 하드코딩 금지

### 12.3 Electron renderer

현재 `data:text/html` smoke page는 제거한다. 개발/배포 모드를 분리한다.

- dev: 허용된 Vite dev URL
- production: same-origin hosted Product UI 또는 검증된 local bundle
- preload는 고정 경로에서만 로드
- `contextIsolation: true`, `nodeIntegration: false`
- navigation/new-window를 allow-list
- renderer는 임의 filesystem API를 얻지 않음
- local root absolute path는 main process registry에만 존재

### 12.4 Local 연결 UI

`ConnectLocalSource`의 폴더 선택 이후 실제 `connectLocalMount` IPC를 호출한다.

필요 입력:

```text
riskWorkspaceId
includePatterns
excludePatterns
```

서버가 반환한 canonical mount/source workspace ID를 Electron registry에 저장하고 watcher를 시작한다. renderer에는 필요한 상태만 반환한다.

### 12.5 Desktop 운영 보강

- background request에 device bearer 적용
- exponential backoff와 offline queue/재전송 정책
- mount status endpoint 구현
- credential revoke/rotation
- app restart 후 ACTIVE watcher 복구
- production packaging/signing/update 정책은 별도 deploy task로 추적
- Windows symlink test는 권한 가능한 CI runner에서 실행

---

## 13. GCP 환경 구성: repository 내부 작업

이 절은 console 조작 전에 코드와 프로젝트 안에서 끝내야 하는 작업이다.

### 13.1 Firestore

- `FirestoreControlUnitOfWorkFactory.from_client()` 조립
- Source operational store의 AsyncClient 기반 구현
- canonical collection과 operational collection namespace 분리
- OAuth/pending/lease/device record TTL field
- Control `REQUIRED_COMPOSITE_INDEXES`를 실제 deploy 형식으로 변환하는 script
- source binding query에 필요한 index 추가
- emulator integration test
- schema/version 문서와 migration policy

### 13.2 Secret Manager

`SourceCredentialVault` production adapter를 구현한다.

- `put`: connection-scoped secret 생성/새 version
- `get`: exact opaque ref로 access
- `update`: 새 version 추가 후 ref/binding 갱신
- `delete`: 즉시 접근 차단 후 retention 정책에 따라 destroy
- secret payload/log/exception 비노출
- Drive token, GitHub private key/webhook secret, KIPRIS key의 접근 주체 분리

### 13.3 Cloud Storage

`LocalStagingStore` production adapter:

- random opaque object name
- private bucket only
- public URL 반환 금지
- metadata에 raw path 금지
- server-side encryption 기본/정책 적용
- worker read 후 best-effort delete
- lifecycle JSON으로 짧은 TTL
- content-size/type 제한

### 13.4 Cloud Tasks

`TaskEnqueuer` production adapter:

- queue resource와 worker URL을 validated group으로 받음
- JSON body는 `change_event_id`만
- OIDC service account와 audience 설정
- safe deterministic correlation ID
- duplicate enqueue와 Cloud Tasks task-name retention 정책을 test
- dispatch deadline < application claim lease
- retry/backoff/max-attempt policy를 deploy config에 기록
- dead-letter 또는 최종 실패 관측 경로

### 13.5 Cloud Run entrypoints

```text
API:    uvicorn ip_risk_agent.main:app --host 0.0.0.0 --port $PORT
Worker: uvicorn ip_risk_agent.worker:app --host 0.0.0.0 --port $PORT
```

- multi-stage Docker build에서 frontend를 build하고 runtime image에 복사
- non-root user
- `.dockerignore`
- API/Worker service account 분리
- startup/readiness/liveness
- graceful shutdown으로 HTTP clients close
- immutable image digest를 배포 문서에 기록

### 13.6 Scheduler 내부 endpoint

Cloud Scheduler가 호출할 내부 작업:

- Drive watch renewal
- Drive periodic reconciliation
- stale pending/OAuth/device enrollment cleanup
- staging cleanup 보조 확인
- 필요 시 source health refresh

각 endpoint는 scheduler service identity만 허용하고, 작업을 chunk/paginate해 Cloud Run timeout을 넘지 않는다.

### 13.7 Observability

structured log allow-list:

```text
event_id, change_event_id, analysis_job_id,
risk_workspace_id, mount_id, artifact_id,
source_type, analyzer_type, attempt,
safe failure category, duration, outcome
```

금지:

```text
raw content, SourceSnapshot segments, token, secret,
authorization header, provider raw response,
local absolute path, signed URL
```

metric/alert 최소 세트:

- source webhook accepted/rejected
- queue enqueue/error/age
- claim duplicate/stale reclaim
- provider fetch latency/failure
- Gate approve/deny reason
- analyzer status/coverage/latency
- job terminal latency 및 stuck lease
- staging cleanup failure

---

## 14. GCP 외부 작업으로 넘길 입력

이 문서 단계에서는 console을 조작하지 않는다. 대신 repository 내부 작업이 끝날 때 다음 값/산출물을 외부 작업 체크리스트에 넘긴다.

- project ID, primary region, RAG region
- Firestore database ID와 index deploy 파일
- API/Worker/Scheduler/Deploy service account 이름과 최소 IAM matrix
- Cloud Tasks queue name/location/policy
- API/Worker image와 command
- Secret Manager secret ID 목록
- staging bucket name/location/lifecycle file
- Google Login OAuth redirect URI
- Drive OAuth/Picker/webhook callback URI
- GitHub App callback/webhook URI 및 permission/event 목록
- Vertex/Gemini model/location 설정
- RAG corpus ID/version 및 ingestion report
- KIPRIS credential secret ID
- domain, TLS, cookie/allowed origin/trusted host 값

외부 작업 후에는 실제 resource ID만 settings/deploy environment에 넣고 code에 하드코딩하지 않는다.

---

## 15. 구현 phase와 commit 단위

### Phase M — Git merge

- M1 Control merge
- M2 Source merge + frontend conflict resolution
- M3 Intelligence merge
- Gate: history/marker/frozen diff 확인

### Phase D — Dependency/toolchain

- D1 root Python manifest
- D2 frontend/desktop manifests 및 Source test 포팅
- D3 lockfile 재생성
- D4 `.env.example`, runtime docs
- Gate: install, pip check, frozen install, plane unit suites

### Phase B — Blocking bridge

- B1 canonical SourceChange claim input
- B2 lease/retry/crash recovery
- B3 pending connection/canonical mount mapping
- B4 session+CSRF/source authz
- B5 desktop enrollment/device auth
- B6 analyzer result-set completeness
- Gate: focused integration tests

### Phase C — Composition

- C1 settings/runtime/container
- C2 Control API bundle
- C3 Source routers/provider registry/stores
- C4 Intelligence/Vertex/RAG registry
- C5 worker pipeline
- C6 Open Original
- Gate: API + pipeline integration suite

### Phase U — UI/Desktop

- U1 SourcePanel app slot
- U2 OAuth callback/picker/repository/mount UI
- U3 CSRF-aware Source client
- U4 Electron Product renderer
- U5 Local connect/device credential/background events
- Gate: frontend/desktop tests and E2E

### Phase G — GCP internal

- G1 Firestore stores/indexes
- G2 Secret Manager/GCS/Cloud Tasks adapters
- G3 Docker/Cloud Build/Cloud Run definitions
- G4 Scheduler endpoints/config
- G5 RAG ingestion tooling
- G6 observability/readiness
- Gate: emulator + staging-ready dry run

각 phase는 독립 commit으로 나눈다. merge commit, dependency commit, bridge fix, feature composition, deploy config를 한 commit에 섞지 않는다.

---

## 16. 검증 계획

### 16.1 정적/전체 회귀

```powershell
pnpm run generate
git diff --exit-code -- shared/contracts

python -m compileall -q backend/src shared/contracts/python scripts
python -m pip check
python -m pytest shared/contracts/tests tests/control tests/connectors tests/intelligence tests/integration -m "not live"

pnpm run typecheck
pnpm run build
pnpm run verify:resolution
pnpm --filter @iprisk/frontend test
pnpm --filter @iprisk/desktop test
pnpm install --frozen-lockfile
```

`verify:resolution`이 generated TypeScript dist를 요구하면 `generate/build` 뒤에 실행한다.

### 16.2 필수 integration test 파일

```text
tests/integration/test_app_composition.py
tests/integration/test_source_authorization.py
tests/integration/test_source_registration.py
tests/integration/test_analysis_pipeline.py
tests/integration/test_worker_retry.py
tests/integration/test_original_source.py
tests/integration/test_gcp_adapters.py
tests/e2e/test_web_source_to_risk.py
tests/e2e/test_desktop_source_to_risk.py
```

### 16.3 보안 시나리오

- unauthenticated Source route 전부 401
- VWS 비회원 및 권한 부족 403
- mutation CSRF 누락/불일치 거부
- connection ID로 다른 VWS mount 생성 거부
- 다른 사용자의 device credential 사용 거부
- invalid/expired OAuth state 거부 및 single-use
- invalid GitHub HMAC 거부
- invalid Drive channel token/resource binding 거부
- 선택하지 않은 Drive file/repository/path fetch 거부
- Local root escape/symlink escape 거부
- task endpoint의 일반 인터넷/사용자 session 호출 거부
- log/Firestore/task에 secret/raw/path 없음

### 16.4 Pipeline 시나리오

- Drive SourceChange → snapshot → Gate → Patent/License → Risk
- GitHub private repo webhook → 같은 파이프라인
- Local staging → event → worker → cleanup
- DELETE가 Risk를 자동 resolve하지 않음
- MOVE identity semantics 유지
- duplicate webhook/task가 duplicate Risk를 만들지 않음
- provider failure/partial/inconclusive가 existing Risk를 보존
- complete success 0 candidate만 resolution 허용
- 2 analyzer 중 하나 실패/누락 시 job terminal semantics 정확
- worker crash 후 lease reclaim

### 16.5 Live/staging gate

- Google OIDC roundtrip
- Drive OAuth, Picker, selected file fetch, webhook/reconcile
- GitHub App install, private repo list/fetch, signed webhook
- Firestore transaction/index query
- Secret Manager token refresh update
- GCS staging upload/read/delete/TTL
- Cloud Tasks OIDC delivery/retry/concurrency
- Gemini Vertex structured output
- KIPRIS live search와 0건/실패 구분
- RAG retrieval 및 corpus version evidence
- Electron packaged smoke test

live test는 marker와 명시적 opt-in 없이는 실행하지 않는다.

---

## 17. Go/No-Go gate

### Gate A — merge 완료

- [ ] 세 merge commit 존재
- [ ] 예상 외 conflict 없음
- [ ] conflict marker 없음
- [ ] 다른 worktree 변경 없음

### Gate B — dependency 완료

- [ ] baseline exact versions 적용
- [ ] Python/Node lock 재현 가능
- [ ] FastAPI 0.141.1에서 Source suite 통과
- [ ] Pydantic 2.13.4/Python 3.14.7에서 Intelligence suite 통과
- [ ] frontend Source tests Vitest 통과

### Gate C — local integration 완료

- [ ] API/Worker 기동
- [ ] Source authz/CSRF fail closed
- [ ] pending connection → canonical mount
- [ ] worker ID-only payload
- [ ] claim retry/crash recovery
- [ ] analyzer completeness
- [ ] Web/Electron local E2E

### Gate D — GCP 코드 완료

- [ ] production profile에 in-memory 없음
- [ ] Firestore/Secret Manager/GCS/Tasks adapters
- [ ] index/lifecycle/queue/deploy 산출물
- [ ] service identity 경계
- [ ] RAG ingestion/retrieval 준비

### Gate E — Console 작업 시작 가능

- [ ] 외부 작업 입력값 목록 확정
- [ ] IAM matrix 확정
- [ ] callback/webhook URL 확정
- [ ] deploy image 및 environment schema 확정
- [ ] staging verification runbook 확정

Gate C 이전에는 GCP console 구성을 시작하지 않는다. 코드의 env/resource contract가 흔들리면 console 작업을 반복하게 된다.

---

## 18. Rollback과 문제 처리

### merge 도중

잘못된 conflict resolution을 아직 commit하지 않았다면:

```powershell
git merge --abort
```

### merge commit 이후

공유/push된 history는 reset하지 않는다. 해당 merge commit을 mainline parent 기준으로 revert한다.

```powershell
git revert -m 1 <merge-commit-sha>
```

정확한 대상 SHA를 `git show --summary`로 먼저 확인한다.

### 통합 기능 rollback

- provider/router는 production에서 임의 silent disable하지 않는다. 이전 검증 image로 Cloud Run revision traffic을 되돌린다.
- schema change는 backward-compatible read를 먼저 배포한 뒤 write를 전환한다.
- secret rotation은 이전 version을 즉시 파괴하기 전에 rollback window를 둔다.
- queue consumer rollback 시 새 enqueue를 멈추고 queue를 purge하지 않은 채 안정 revision으로 복귀한다.
- Risk data를 삭제하거나 기존 Risk를 대량 resolve하는 rollback은 금지한다.

---

## 19. 알려진 제약과 후속 우선순위

| 항목 | 분류 | 처리 |
|---|---|---|
| GitHub reconcile가 no-op | P1 reliability | webhook 주 경로 유지, health/periodic 보강 설계 |
| GitHub repository list 100개 단일 page | P1 usability | pagination 추가 |
| Drive id_token 서명 미검증 | P0 hardening | 검증된 OIDC/JWK 방식으로 교체하거나 identity를 표시용으로만 제한하고 server-side account 조회 |
| Local text-only staging | P1 scope | binary 요구 전까지 명시적 거부 |
| `.ipriskignore`가 full gitignore 문법 아님 | P1 correctness | UI/문서 표시, 필요 시 parser 교체 |
| Local MOVE hash 추정 | P1 correctness | 동일 content 충돌 test/표시 |
| Desktop mount status endpoint 없음 | P0 UX/ops | UI 연결 전에 구현 |
| Electron production packaging/signing | P1 release | 기능 통합 후 별도 release gate |
| RAG corpus 초기 3건 | P1 product coverage | corpus governance/확장 없이는 제한 표시 |
| KIPRIS abstract 중심 | P1 evidence quality | claims 확보 전 HIGH 제한 유지 |

P0는 Gate C 전에 모두 닫는다. P1은 미완성 상태와 사용자 영향을 UI/운영 문서에 명확히 표시하면 제한된 staging 진입은 가능하지만 production 출시 판단에서 별도 승인한다.

---

## 20. 바로 시작할 작업 순서

다음 작업자는 아래 체크리스트의 첫 미완료 항목부터 시작한다.

1. `integration-v2`와 세 branch HEAD/clean 상태 재확인
2. pre-merge tag 생성
3. Control → Source → Intelligence 순서로 merge
4. frontend 4개 conflict를 §4대로 해결
5. dependency baseline을 manifests와 lock에 적용
6. plane 전체 unit test로 순수 merge 회귀 제거
7. P0-1 canonical SourceChange claim bridge 구현
8. P0-2 lease/retry/crash recovery 구현
9. pending connection/binding persistent store 구현
10. Source session+CSRF authz와 desktop enrollment 구현
11. analyzer completeness와 production Intelligence 조립
12. API/Worker/container composition
13. Source Web UI와 Electron Product UI 완성
14. integration/e2e gate 통과
15. GCP adapters/deploy/index/lifecycle/scheduler/RAG tooling 구현
16. Gate E 통과 후 별도 GCP console 작업 문서로 이동

이 순서를 바꾸려면 최소한 P0 의존 관계를 유지해야 한다. 특히 production port부터 만들기 전에 canonical execution input과 auth/retry 의미를 먼저 고정해야 store와 queue schema를 두 번 만들지 않는다.

