# integration-v2 통합 현황 기록

> 성격: **삭제 가능한 비규범적 작업 로그**
> 시작일: 2026-08-21
> 현재 단계: **통합 Phase 9 진행 중 — 외부 project/권한/credential 입력 대기**
> 기준 문서: `INTEGRATION_V2_DEPENDENCY_BASELINE.md`, `INTEGRATION_V2_EXECUTION_PLAN.md`

이 문서는 통합 진행 중 확인한 사실, 실행 결과와 임시 판단을 시간순으로 남기는 보조 기록이다. 프로젝트의 실행, build, test 또는 배포가 이 문서에 의존해서는 안 되며, 작업 완료 후 삭제해도 프로젝트 완결성에 영향이 없어야 한다. 규범적 결정이 이 로그와 두 기준 문서 사이에서 충돌하면 기준 문서가 우선한다.

## 진행 원칙

- `integration-v2`에서만 변경한다.
- 두 통합 기준 문서를 규범적 기준으로 사용하고, 이 문서에는 실행 상태와 검증 증거만 누적한다.
- phase gate를 통과하기 전 다음 phase의 변경을 섞지 않는다.
- dependency manifest/lock, runtime composition, GCP 구성은 각 소유 phase에서만 변경한다.
- `shared/contracts/**`는 수정하지 않는다.
- 기존 agent별 원본 문서는 Phase 8 전까지 삭제하지 않는다.

## 시작 상태

| Branch | 시작 HEAD | 상태 |
|---|---|---|
| `integration-v2` | `ae566be3ffcc0e48e512b40c398269de7d6fff45` | clean |
| `main` | `7cfbec446ac50fcc36c14031cb4310c30c8a0e5c` | clean |
| `platform-control` | `de1dacce05474d4e3e6c7c2567f6b8a6bbdbeb64` | clean |
| `source-integration-desktop` | `ee861b730d161caf876d2a300b476783d03bbaf6` | clean |
| `risk-intelligence-rag` | `68e07a3fdf543bcb4871cb13aee95fcc64b5749d` | clean |

## Merge 기록

### 1. `platform-control`

- 상태: 완료
- merge commit: `f253312ea52519922edef9e8c8da3bdca0fcc5db`
- conflict: 없음
- 해결/검증:
  - `ort` strategy로 `--no-ff` merge 완료
  - Control canonical domain, application, persistence, API, Product UI와 test가 추가됨
  - merge 직후 worktree에 미해결 파일 없음
  - dependency/toolchain 정리 및 전체 test는 이번 단계 범위 밖이므로 실행하지 않음

### 2. `source-integration-desktop`

- 상태: 완료
- merge commit: `12c5b9f9dd71c981a2b6614099245fbc3e5493b9`
- conflict: 아래 네 frontend 설정 파일
  - `frontend/index.html`
  - `frontend/package.json`
  - `frontend/tsconfig.json`
  - `frontend/vite.config.ts`
- 해결/검증:
  - `index.html`: Control Product entrypoint와 metadata를 유지하고 `lang="ko"` 적용
  - `package.json`: Control의 exact dependency, router, Vitest/Testing Library 및 no-emit build 체계 유지
  - `tsconfig.json`: Control의 Bundler/no-emit/strict 설정을 유지하고 Source test compile을 위한 `node` type 추가
  - `vite.config.ts`: Control의 API proxy, sourcemap, Vitest/jsdom 설정 유지
  - 네 파일의 conflict marker 및 unmerged entry가 없음을 확인
  - Source의 `pnpm-lock.yaml`은 merge 결과를 그대로 수용했으며 최종 재생성은 이후 dependency 통합 단계로 보류
  - Source test의 Vitest 포팅과 dev preview 제거는 semantic integration이므로 이번 단계에서 수행하지 않음
  - staged whitespace 검사에서 incoming `AGENT_2_DELIVERY.md`의 EOF 빈 줄 1건이 보고됐으나, branch 원문을 보존하기 위해 수정하지 않음

### 3. `risk-intelligence-rag`

- 상태: 완료
- merge commit: `13caa161d204c819dbaa90fdf5292b1fd2ea071f`
- conflict: 없음
- 해결/검증:
  - `ort` strategy로 `--no-ff` merge 완료
  - Intelligence, Gemini, Patent, License, RAG, corpus와 test가 추가됨
  - merge 직후 worktree에 미해결 파일 없음
  - dependency/toolchain 정리 및 전체 test는 이번 단계 범위 밖이므로 실행하지 않음

## 현재 단계 종료 조건

- [x] 세 feature branch merge commit이 `integration-v2` history에 존재
- [x] 모든 merge conflict 해결
- [x] conflict marker 없음
- [x] `git diff --check` 통과
- [x] `shared/contracts/**`에 의도하지 않은 변경 없음
- [x] 다른 네 worktree clean 유지
- [x] 전체 통합 개발 및 dependency 재생성은 시작하지 않음

## 단계 종료 요약

- merge 순서: `platform-control` → `source-integration-desktop` → `risk-intelligence-rag`
- merge conflict: frontend 설정 파일 4건, 모두 기준 문서의 확정안대로 해결
- semantic integration: 미실행
- dependency/lockfile 최종화: 미실행
- test/build: 다음 dependency 통합 단계로 보류

## 전체 통합 계획

Merge는 준비 단계인 Phase 0으로 완료됐다. 본 통합은 아래 **9개 phase**로 진행한다.

| Phase | 목표 | 핵심 산출물 | 종료 gate | 상태 |
|---|---|---|---|---|
| 1 | 계획 확정과 agent 문서 통합 | 전체 phase 계획, Agent 1/2/3 단일 문서, 삭제 보류 목록 | source 문서 coverage와 보존 확인 | 완료 (`31e3fc4`) |
| 2 | dependency/toolchain 수렴 | root Python/Node manifest, 최종 lock, env schema | install/frozen install, Plane 전체 baseline test | 완료 (`83c901f`) |
| 3 | P0 경계 보강 | canonical worker input, lease/retry, Source authz/CSRF, pending connection, device auth, analyzer 완결성 | 경계별 integration test | 완료 (`dfa1193`) |
| 4 | Backend/API/Worker 조립 | settings/container, Control+Source app, worker pipeline, provider registry, Open Original backend | local API/worker E2E와 상태 전이 검증 | 완료 (`bbbcd2b`) |
| 5 | Web/Electron 제품 통합 | SourcePanel, OAuth completion/mount UI, Electron renderer/enrollment/local flow | browser/desktop E2E | 완료 (`e89c6e0`) |
| 6 | GCP 내부 구현 | Firestore operational stores, Secret Manager/GCS/Tasks adapters, indexes, Docker/Cloud Run/Scheduler/RAG tooling | emulator 및 staging-ready dry run | 완료 (`41cdc42`) |
| 7 | 전체 검증과 release freeze | 전체 회귀, 보안/실패/복구 test, live-test runbook, blocker 0건 | 통합 완료 승인 | 완료 (`5f9aa58`) |
| 8 | 문서 정리와 배포 후보 고정 | 구 agent 문서 삭제, README/운영 문서 최종화, release candidate commit | 삭제 후 전체 검증 재통과 | 완료 (본 commit) |
| 9 | GCP 외부 구성·배포·실환경 검증 | console/IAM/resource 구성, 배포, live provider/E2E 증거 | production readiness 승인 | 진행 중 (외부 입력 대기) |

### Phase 의존 관계

```text
Phase 0 merge
  -> Phase 1 계획/문서
  -> Phase 2 dependency
  -> Phase 3 P0 경계
  -> Phase 4 backend composition
  -> Phase 5 Web/Electron
  -> Phase 6 GCP 내부 구현
  -> Phase 7 전체 검증
  -> Phase 8 구 문서 삭제 및 RC 고정
  -> Phase 9 GCP 외부 배포
```

Phase 5와 Phase 6의 일부 구현은 Phase 4의 public runtime contract가 확정된 뒤 병행할 수 있지만, gate 판정과 commit은 위 순서를 유지한다. Phase 8은 반드시 Phase 7 통과 후, Phase 9 시작 전에 수행한다.

### Phase 공통 운영 방식

각 phase마다 다음을 이 문서에 남긴다.

1. 시작 HEAD와 목표
2. 변경 파일과 핵심 결정
3. 발견한 blocker/known issue와 처리 상태
4. 실행한 검증 명령과 결과
5. 남은 작업 및 다음 phase 진입 여부

실패한 검증은 삭제하거나 성공으로 덮어쓰지 않고, 실패 원인과 재실행 결과를 함께 기록한다.

## Phase 1 — 계획 확정 및 agent 문서 통합

### 목표

- 9개 phase와 gate를 확정한다.
- agent별 분산 문서를 Agent 1/2/3 단일 참조 문서로 통합한다.
- 어떤 기존 문서를 Phase 8에서 삭제할지 명시한다.
- 기존 원본은 비교·검증을 위해 그대로 보존한다.

### 신규 유지 문서

```text
docs/AGENT_1_PLATFORM_CONTROL.md
docs/AGENT_2_SOURCE_DESKTOP.md
docs/AGENT_3_RISK_INTELLIGENCE_RAG.md
```

각 문서는 구현 범위, 코드 지도, public surface, dependency 검증 이력, 환경 변수, test 증거, integration wiring, 제약과 후속 작업을 한 곳에 모은다. 최종 dependency 결정은 각 문서의 과거 agent 검증값보다 `INTEGRATION_V2_DEPENDENCY_BASELINE.md`가 우선한다.

### Phase 8 삭제 예정 원본

```text
AGENT_1_DELIVERY.md
AGENT_1_PLATFORM_CONTROL_IMPLEMENTATION_PLAN.md
LOCAL_RUN_AND_TEST_GUIDE.md
agent-deliverables/agent-1-dependencies.md
AGENT_2_DELIVERY.md
agent-deliverables/agent-2-dependencies.md
AGENT_3_DELIVERY.md
agent-deliverables/agent-3-dependencies.md
```

삭제 조건:

- Phase 7 전체 검증 완료
- 신규 3개 문서와 최종 README/운영 문서만으로 build/test/운영 정보가 충분함을 확인
- build/test/운영 절차에서 사용하는 원본 파일명 참조를 신규 통합 문서 또는 최종 운영 문서로 교체
- 보호 대상 명세·기준 문서와 provenance/history 구간의 과거 파일명은 실행 경로로 오인되지 않도록 문맥을 확인한 뒤 보존 가능
- 삭제 commit 이후 전체 non-live regression 재통과
- GCP 외부 배포 Phase 9는 아직 시작하지 않은 상태

`CODING_AGENT_MASTER_SPEC.md`, 세 상세 명세, 청사진, 두 통합 기준 문서와 이 진행 로그는 위 삭제 대상이 아니다. Gemini prompt, RAG corpus source/README처럼 runtime 또는 data provenance에 필요한 Markdown도 agent 문서 정리 대상이 아니다.

### 작업 추적

- [x] 현재 Markdown inventory 작성
- [x] 전체 통합을 9개 phase로 분해
- [x] 삭제 시점을 Phase 8로 고정
- [x] Agent 1 단일 문서 작성
- [x] Agent 2 단일 문서 작성
- [x] Agent 3 단일 문서 작성
- [x] source 문서별 정보 coverage 확인
- [x] 기존 agent 문서가 삭제되지 않았는지 확인
- [x] Phase 1 변경 commit 및 종료 gate 판정

### Phase 1 검증 기록

- 통합 대상 원본 8개를 Agent 1/2/3 문서의 provenance 표와 일대일로 대조했다.
- 신규 문서 3개의 Markdown code fence 짝과 conflict marker 부재를 확인했다.
- 삭제 예정 원본 8개와 보호 대상 명세·청사진·통합 기준 문서가 모두 남아 있음을 확인했다.
- 변경 범위는 이 진행 로그와 신규 agent 통합 문서 3개뿐이며 runtime code와 dependency file은 변경하지 않았다.
- 이 phase는 문서 정리만 수행하므로 runtime test는 실행하지 않는다. Phase 2부터 각 phase gate에 맞는 검증을 기록한다.
- Phase 1 산출물 commit: `31e3fc4e2490b963208a230a4e40b718ec86ec2c` (`docs: consolidate agent integration references`)
- 종료 gate: **통과**. Phase 2 dependency/toolchain 수렴 작업을 시작할 수 있다.

## Phase 2 — dependency/toolchain 수렴

### 시작 상태와 범위

- 시작 HEAD: `acc4ab7603105444d5657d48b32428c89ae3f886`
- 목표: 두 통합 기준 문서의 exact dependency를 manifest와 lock에 적용하고, 같은 환경에서 세 Plane 및 Web/Desktop baseline을 검증한다.
- 포함: Python/Node manifest와 lock, tool version pin, pytest 설정, Source frontend test 포팅, `.env.example`, `README.md`.
- 제외: P0 경계 변경, API/Worker composition, Web/Electron 제품 wiring, GCP adapter 및 외부 resource 구성.

### 수렴 결과

- runtime을 CPython `3.14.7`, Node.js `24.19.0`, pnpm `11.19.0`, TypeScript `5.9.3`으로 고정하고 `.python-version`, `.node-version`을 추가했다.
- `pyproject.toml`에 baseline §5의 production direct dependency 17개와 dev dependency 3개를 exact pin으로 적용했다.
- pytest discovery에 contracts/control/connectors/intelligence/integration/e2e를 포함하고 strict asyncio 및 `live` marker를 등록했다.
- Python 산출물 이름을 `requirements.lock`으로 확정했다. direct dependency는 `pyproject.toml`, CPython 3.14 transitive resolution은 이 lock이 담당한다.
- baseline §5.3의 검증 snapshot을 유지하기 위해 `protobuf==7.35.1`을 포함한 주요 transitive version을 lock에 고정했다.
- Frontend manifest는 baseline exact set을 유지하고, Desktop의 `chokidar`, `electron`, `@types/node` caret를 제거해 각각 `5.0.0`, `43.4.0`, `24.13.3`으로 고정했다.
- Source frontend의 `node:test`/`node:assert` test 2개를 Vitest assertion과 runner로 포팅했다.
- 기존 feature branch lock을 최종본으로 사용하지 않고 통합 workspace manifest에서 `pnpm-lock.yaml`을 재생성했다.
- `.env.example`에 baseline §10 전체 변수와 `APP_ENV`, `APP_ROLE`, `LOG_LEVEL`을 반영했다. 실제 secret/resource 값은 추가하지 않았다.
- `README.md`를 단일 통합 환경, repository 구조, install/lock 정책, 환경 변수, 검증 명령, 현재 실행 가능 범위와 보안 불변조건 중심으로 전면 재작성했다.
- Frozen Contract generator를 실행했으며 tracked contract content에는 변경이 없다.

### 검증 기록

| 검증 | 결과 |
|---|---|
| `python --version` | `3.14.7` |
| `node --version` | `v24.19.0` |
| `pnpm --version` | `11.19.0` |
| clean `.venv/lock-check`에서 `requirements.lock` 설치 + editable no-deps + `pip check` | 통과 |
| manylinux2014 x86_64 / CPython 3.14 / binary-only `requirements.lock` dry-run | 통과 |
| `pnpm install --frozen-lockfile` | 통과, 4 workspace projects / 159 packages |
| contract generation 후 `git diff --exit-code -- shared/contracts` | 통과, content 변경 없음 |
| Python `compileall` + `pip check` | 통과 |
| contracts/control/connectors/intelligence non-live suite | `568 passed, 1 skipped, 10 deselected` |
| root TypeScript typecheck/build/resolution | 통과 |
| Frontend Vitest | `6 files, 23 passed` |
| Desktop Node test | `65 tests, 63 passed, 2 skipped` |

첫 Python suite 실행은 코드 assertion 실패 없이 `566 passed` 후 sandbox 사용자 Temp 디렉터리 권한으로 `tmp_path` setup error 2건이 발생했다. `--basetemp .venv/pytest-tmp`로 repository 내부 ignored 경로를 지정해 같은 suite를 재실행했고 `568 passed, 1 skipped`로 통과했다. skip은 Firestore emulator 미설정 1건이며, deselected 10건은 명시적으로 제외한 `live` test다. Desktop skip 2건은 Windows Developer Mode/admin 권한이 없어 symlink 생성이 불가능한 환경 제약이다.

### Phase 2 gate

- [x] baseline production/dev exact version 적용
- [x] Python lock clean install 및 `pip check`
- [x] Linux Cloud Run 계열 wheel 가용성 dry-run
- [x] Node lock 재생성과 frozen install
- [x] FastAPI `0.141.1`에서 Source connector suite 통과
- [x] Pydantic `2.13.4`/Python `3.14.7`에서 Intelligence suite 통과
- [x] Source frontend test Vitest 통과
- [x] Frontend/Desktop typecheck, build, resolution 및 test 통과
- [x] Frozen Contract content 무변경
- [x] README 및 environment template 수렴

종료 gate: **통과**. Phase 3 P0 경계 보강을 시작할 수 있다. Phase 2 변경은 이 로그를 포함하는 단일 dependency/toolchain commit으로 기록한다.

## Phase 3 — P0 통합 경계 보강

### 시작 상태와 범위

- 시작 HEAD: `83c901f48c90847500d0598bc2536fcd2d98808b`
- 목표: `INTEGRATION_V2_EXECUTION_PLAN.md` §5의 P0-1부터 P0-6까지를 production composition 전에 코드 계약과 실패 경로로 고정한다.
- 포함: canonical `SourceChange` claim, bounded lease와 attempt fencing, Source session/CSRF authz, pending connection과 canonical mount 수렴, desktop enrollment credential, analyzer/result 완전성.
- 제외: 실제 API/Worker container 조립, Firestore operational store, Electron `safeStorage`/IPC, GCP adapter와 resource 구성. 이 항목들은 각각 Phase 4~6에서 현재 경계를 구현체에 연결한다.

### 수렴 결과

1. **Canonical worker input**
   - `ChangeEvent`가 raw content 없는 frozen Contract v1 `SourceChange`를 canonical 실행 metadata로 보존한다.
   - 중복 identity와 safe metadata 불일치를 domain invariant로 거부한다.
   - Firestore mapper는 `source_change`를 필수 schema로 직렬화·역직렬화하며, 누락된 구 schema를 성공으로 추정하지 않는다.
   - `AnalysisExecutionClaim`이 같은 canonical transaction에서 읽은 `source_change`, `attempt`, `lease_expires_at`을 반환한다.

2. **Lease/retry/crash recovery**
   - claim lease를 기본 300초, 허용 범위 1~3600초로 고정했다.
   - 유효 lease 중복 delivery는 no-op, 만료된 `PROCESSING/RUNNING`과 명시적 retry delivery의 `FAILED/FAILED`는 재enqueue 없이 원자적으로 reclaim한다.
   - reclaim마다 attempt와 job `started_at` fencing을 전진시키고 기존 outcome/failure를 제거한다.
   - `fail_analysis()`에 attempt ownership 검사를 추가해 오래된 worker의 실패 기록을 거부한다.

3. **Source web authz/CSRF**
   - 모든 Drive/GitHub/Local router authz slot의 기본값을 `deny_all_authz`로 교체했다.
   - connection/workspace/mount/device-registration scope를 factory parameter부터 분리해 한 resource ID의 의미를 추정하지 않게 했다.
   - session version을 검증하는 principal resolver, mutation CSRF, pending connection owner 및 canonical mount resolve, Control facade action 판정을 결합하는 `SessionSourceAuthorizer`를 추가했다.
   - OAuth/App callback GET은 one-time state 검증 후 callback service가 현재 principal을 다시 해석하며, webhook/internal identity는 browser authorizer와 섞지 않는다.

4. **Pending connection에서 canonical mount로의 수렴**
   - TTL/status/idempotency key를 가진 `PendingSourceConnection`, canonical binding 및 durable store protocol을 추가했다.
   - OAuth/App callback은 high-entropy opaque pending ID만 만들고 placeholder mount를 생성하지 않는다.
   - Drive file 또는 GitHub repository/branch가 실제 선택될 때 deterministic key로 `register_source_metadata()`를 한 번 호출한다.
   - callback/mount retry, VWS/owner/type mismatch, expiry와 credential/installation lookup을 경계에서 처리한다.
   - 현재 adapter는 local/test용 in-memory이며 Firestore 구현은 Phase 6 소유다.

5. **Desktop device authentication**
   - session+CSRF로 one-time enrollment challenge를 발급하고, 교환 시 opaque device credential을 한 번만 반환하는 service/router를 추가했다.
   - challenge와 credential은 SHA-256 hash만 store에 남기며 challenge replay, expiry, revoke, session-version invalidation을 거부한다.
   - background bearer 요청은 device↔VWS↔mount binding과 Control action을 재검증한다.
   - Electron `safeStorage`, preload IPC와 기존 Local route의 최종 제품 wiring은 Phase 5에서 수행한다.

6. **Analyzer/result 완전성**
   - Control configured analyzer set과 active analyzer set이 startup 구성 시 정확히 같지 않으면 실패하는 wrapper를 추가했다.
   - gated artifact 요청 집합과 반환 result 집합의 누락·중복·예상 밖 type을 거부한다.
   - 모든 result의 job/artifact/revision identity가 gated artifact와 정확히 같은지 검증한다.

### 검증 기록

| 검증 | 결과 |
|---|---|
| Phase 3 경계 focused suite | `28 passed` |
| Python `compileall` + `pip check` | 통과 |
| contracts/control/connectors/intelligence/integration/e2e non-live 전체 suite | `574 passed, 1 skipped, 10 deselected` |
| root TypeScript typecheck/build/resolution | 통과 |
| Frontend Vitest | `6 files, 23 passed` |
| Desktop Node test | `65 tests, 63 passed, 2 skipped` |
| `pnpm install --frozen-lockfile` | 통과, lock 변경 없음 |
| `git diff --check` | 통과 |
| `shared/contracts/**` diff | 없음 |

Python skip 1건은 Phase 2와 동일하게 `FIRESTORE_EMULATOR_HOST` 미설정이며, deselected 10건은 실제 provider credential이 필요한 `live` test다. Desktop skip 2건도 Phase 2와 동일한 Windows symlink 권한 제약이다. Phase 3은 Python backend와 integration test만 변경했고 dependency manifest/lock 및 Web/Desktop TypeScript source는 변경하지 않았다.

### Phase 3 gate

- [x] claim에서 canonical metadata-only `SourceChange` 복구
- [x] bounded lease, duplicate no-op, expired/failed reclaim와 attempt fencing
- [x] Source router fail-closed default와 session/CSRF scope adapter
- [x] pending connection TTL/idempotency 및 실제 선택 시 canonical mount 생성
- [x] one-time desktop enrollment, hash-only credential, revoke/session/mount binding
- [x] analyzer 구성 집합과 result identity/집합 완전성 검사
- [x] 경계별 negative integration test 및 전체 non-live 회귀 통과
- [x] Frozen Contract와 dependency/lock 무변경

종료 gate: **통과**. Phase 4에서는 이 phase의 public boundary만 사용해 settings/container, 통합 API와 analysis worker pipeline을 조립한다. In-memory operational store를 production fallback으로 사용하지 않으며, durable adapter는 Phase 6에서 제공한다.

## Phase 4 — Backend/API/Worker 조립

### 시작 상태와 범위

- 시작 HEAD: `dfa1193882dddfc5d56b6a040fc08f36c465c7f2`
- 목표: Phase 3의 public boundary를 settings/container와 실행 가능한 API/Worker application으로 조립하고, SourceChange에서 canonical terminal state까지의 local integration 경로를 검증한다.
- 포함: runtime profile 설정 검증, container/factory, Control+Source API 조립, provider registry와 canonical source binding, analysis pipeline, internal task 인증, Open Original, health/readiness/lifespan.
- 제외: Web/Electron 제품 wiring, production Firestore operational store, Secret Manager/GCS/Cloud Tasks concrete adapter, 실제 GCP IAM/OIDC/resource 구성. 전자는 Phase 5, durable GCP 구현은 Phase 6, 외부 작업은 Phase 9 소유다.

### 수렴 결과

1. **설정과 container**
   - `test`, `local`, `production` runtime profile과 `api`, `worker`, `scheduler` role을 명시하고 URL, secret 길이와 provider configuration group의 all-or-none 규칙을 시작 시점에 검증한다.
   - test/local은 명시적인 in-memory 구성만 허용하고 production은 durable store/queue, 전체 provider/analyzer와 workload identity가 주입되지 않으면 시작을 거부한다.
   - API/Worker factory, shared container와 close callback 기반 lifespan을 추가했으며 module import만으로 외부 client 또는 resource를 생성하지 않는다.

2. **통합 API surface**
   - Control session/hardening/error boundary와 Control router bundle을 하나의 API application에 설치한다.
   - Source web, webhook, desktop router는 소유 Plane의 router를 수정하지 않고 composition bundle로 주입한다.
   - liveness와 role별 readiness route를 추가하고 누락된 필수 runtime 구성은 안전한 `503`으로 노출한다.

3. **Source provider와 canonical binding**
   - `SourceType`별 adapter registry가 중복 등록과 미등록 dispatch를 fail-closed로 처리한다.
   - Drive/GitHub의 pending credential·installation을 canonical mount에서 조회하는 binding lookup과 SourceChange를 Control facade에 전달하는 sink를 추가했다.
   - production worker는 Drive, GitHub, Local adapter의 정확한 전체 집합을 요구한다.

4. **Analysis worker pipeline**
   - `POST /internal/tasks/analyze-change`는 인증 후 `change_event_id`만 받으며 path, URL, content 또는 provider credential을 task body로 허용하지 않는다.
   - canonical claim → source adapter snapshot → receipt → Security Gate → 완전성 검증된 Intelligence 결과 → Control accept → terminal state 순서를 고정했다.
   - active lease 중복 delivery와 gate deny는 `2xx`, retryable provider failure는 canonical `FAILED` 기록 후 `5xx`, claim 이후의 adapter/config/analyzer contract failure는 안전한 terminal failure 후 `2xx`로 분류했다. Pipeline 자체가 없는 경우는 canonical failure 없이 ACK하지 않고 readiness 실패와 `503`을 반환한다.
   - Local staging object는 snapshot fetch 직후 삭제하지 않고 canonical terminal 기록 뒤 best-effort cleanup하여 crash/retry 복구 가능성을 보존한다.

5. **Open Original**
   - 요청 시 Control facade authorization을 통과한 뒤 mount 단위 authorization을 다시 수행하고 provider adapter로 dispatch한다.
   - Drive는 정확한 `drive.google.com`, GitHub는 정확한 `github.com` HTTPS host만 허용하여 lookalike host를 거부한다.
   - Local 응답은 device/artifact opaque ID만 반환하며 filesystem path를 서버 응답에 포함하지 않는다.

6. **통합 중 발견한 경계 보정**
   - Phase 3 analyzer wrapper가 gate의 source별 analyzer 부분집합까지 전체 active 집합과 같다고 요구하던 오류를 수정했다. Startup 구성은 여전히 전체 집합 일치를 요구하고, 각 artifact 결과는 gate가 요청한 정확한 부분집합과 일치해야 한다.
   - retryable 예외와 예기치 않은 worker 예외가 canonical failure를 남기며 cleanup 자체의 실패가 이미 결정된 terminal 결과를 뒤집지 않도록 고정했다.

### 검증 기록

| 검증 | 결과 |
|---|---|
| Phase 4 focused API/Worker/Open Original/Local suite | `19 passed` |
| Python `compileall` + `pip check` | 통과 |
| contracts/control/connectors/intelligence/integration/e2e non-live 전체 suite | `584 passed, 1 skipped, 10 deselected` |
| API composition/session/source route/lifespan integration | 통과 |
| worker success/duplicate/retry/config/analyzer failure integration | 통과 |
| Open Original authorization/host/local opaque response integration | 통과 |
| root TypeScript typecheck/build/resolution | 통과 |
| Frontend Vitest | `6 files, 23 passed` |
| Desktop Node test | `65 tests, 63 passed, 2 skipped` |
| `pnpm install --frozen-lockfile` | 통과, lock 변경 없음 |

Python skip 1건은 이전 phase와 동일한 `FIRESTORE_EMULATOR_HOST` 미설정이며 deselected 10건은 실제 provider credential이 필요한 `live` test다. Desktop skip 2건도 Windows symlink 권한 제약이다. Phase 4에서 dependency manifest/lock과 Frozen Contract는 변경하지 않았다.

최종 순서 회귀를 추가한 뒤 첫 focused 실행은 project dependency가 없는 시스템 Python을 사용해 FastAPI import와 `asyncio_mode` 설정 단계에서 실패했다. `.venv` Python으로 교정한 실행에서는 cleanup probe가 provider event ID로 canonical job을 조회해 assertion 관찰 자체가 실패했다. Probe를 canonical `change_event_id` 기준으로 수정하고 pipeline 미구성 ACK 방지 회귀를 추가한 뒤 focused `19 passed`, 이어서 전체 Python `584 passed, 1 skipped, 10 deselected`로 재검증했다. 이 과정에서 production code의 추가 실패는 발견되지 않았다.

### 명시적 후속 범위

- SourcePanel, OAuth completion/mount UI, Electron enrollment credential 저장과 Local flow 제품 연결은 Phase 5에서 수행한다.
- Firestore operational store, Secret Manager/GCS/Cloud Tasks concrete adapter와 production OIDC verifier는 Phase 6에서 container override에 연결한다.
- 실제 Google/GitHub/KIPRIS/Gemini credential을 사용하는 live test와 GCP Console/IAM/resource 작업은 아직 수행하지 않았다.
- 위 구현이 없는 상태를 숨기지 않도록 production 구성은 누락된 adapter에서 fail-fast하고 Worker readiness는 실패한다.

### Phase 4 gate

- [x] runtime profile과 provider configuration group fail-fast
- [x] production in-memory fallback 금지
- [x] Control+Source router와 health/lifespan 조립
- [x] ID-only task body와 인증된 worker endpoint
- [x] canonical claim부터 terminal state까지 pipeline 통합
- [x] duplicate/retry/gate/config/analyzer failure 상태 전이 검증
- [x] Open Original 재인가, provider dispatch와 host/local 경계 검증
- [x] local API/worker integration 및 전체 non-live 회귀 통과
- [x] Frozen Contract와 dependency/lock 무변경

종료 gate: **통과**. Phase 5에서는 현재 API/Worker public surface를 기준으로 Web Source flow와 Electron enrollment/local flow를 제품 UI에 연결한다.

## Phase 5 — Web/Electron 제품 통합

### 시작 상태와 범위

- 시작 HEAD: `bbbcd2bfdc8e5e246b8c3e2d35d5ff9894fe51dc`
- 목표: Phase 4의 API surface를 유일한 Product UI entrypoint와 Electron shell에 연결하고, source 선택부터 mount 생성·상태·Open Original까지의 사용자 흐름을 완성한다.
- 포함: SourcePanel composition, CSRF-aware Source client, OAuth/install completion redirect, Drive Picker, GitHub repository/branch, Local enrollment/mount, Electron renderer 보안, credential rotation/revoke, bearer background event와 watcher 복구.
- 제외: production Source operational store/router concrete binding, Firestore/Secret Manager/GCS/Cloud Tasks adapter, built frontend static serving, packaging/signing/update, 실제 provider credential과 GCP Console 작업. 전자는 Phase 6, 외부 작업은 Phase 9 소유다.

### 수렴 결과

1. **Product UI composition과 Source 상태**
   - `frontend/src/main.tsx`만 Control과 Source 구현을 함께 아는 composition point로 두고 `ControlPlaneRoutes.integration`에 SourcePanel과 Open Original handler를 주입했다.
   - SourcePanel은 현재 workspace context와 Control data-access summary를 사용해 connected status, reconnect와 Owner mount disable을 제공한다. 기존 Source 전용 `dev/preview.tsx`와 고정 `dev-workspace` 경로는 제거했다.

2. **인증된 provider completion**
   - Source client는 Control `ApiClient`를 재사용하므로 same-origin cookie와 모든 mutation의 CSRF header를 공유한다.
   - Drive/GitHub callback은 token이나 provider 원문을 query에 싣지 않고 provider, bounded opaque connection ID와 connected status만 Product source route로 303 redirect한다.
   - Drive는 short-lived Picker token과 browser runtime config를 사용해 명시적으로 선택된 고유 file ID만 mount 요청에 넣는다. GitHub는 접근 가능한 repository와 branch를 선택해 현재 workspace mount를 생성한다.
   - browser-safe runtime endpoint에는 Picker browser key와 Cloud project number만 포함하며 OAuth access/refresh token과 client secret은 노출하지 않는다. 두 설정은 all-or-none이고 production에서 필수다.

3. **Open Original 경계**
   - Web은 backend 재인가 결과가 정확한 `drive.google.com` 또는 `github.com` HTTPS URL일 때만 이동한다.
   - Local은 서버가 반환한 device/artifact opaque ID만 Electron main에 전달하고 renderer나 cloud response에 absolute path를 포함하지 않는다.

4. **Local enrollment와 credential 수명주기**
   - 로그인 session에서 발급한 one-time challenge만 unauthenticated enrollment exchange에 사용한다. device credential은 Electron `safeStorage`로 암호화하고 plaintext 저장·renderer getter를 제공하지 않는다.
   - rotation은 같은 device identity에 새 challenge를 교환해 이전 server hash를 교체한다. revoke는 소유 session+CSRF API로 server credential을 폐기한 뒤 watcher를 닫고 local ciphertext를 삭제한다.
   - 폴더 선택은 one-time opaque selection ID와 display name만 renderer에 반환하며 main process의 canonical path는 mount 등록 성공 후 local registry에만 기록한다.

5. **Electron Product runtime과 background event**
   - `data:` smoke page를 제거하고 local loopback Vite 또는 production same-origin `/app`을 로드한다. Production renderer와 API origin이 다르면 시작을 거부한다.
   - `contextIsolation: true`, `nodeIntegration: false`, `sandbox: true`, 고정 CommonJS preload와 최소 IPC allowlist를 적용했다. Electron 공식 제약에 맞춰 sandboxed preload의 ESM import를 제거했다.
   - navigation은 Product/API·Google account·GitHub origin으로 제한하고 external open은 정확한 Drive/GitHub host만 허용한다.
   - background HTTP는 device bearer, network/429/5xx bounded retry를 사용한다. 실행 중 offline queue는 event 순서를 유지해 재전송하고 credential이 있으면 app restart 후 ACTIVE watcher를 복구한다. process restart를 넘는 durable event spool은 Phase 6 운영 adapter 범위로 명시했다.

6. **통합 중 발견한 오류 보정**
   - 기존 Electron event reporter가 server mount ID가 아닌 local handle을 전송하던 오류를 `serverMountId` 사용으로 수정했다.
   - 기존 renderer directory selection 응답이 canonical absolute path를 노출하던 경계를 opaque one-time selection으로 교체했다.
   - sandboxed renderer와 `.mjs` preload 조합이 Electron에서 ESM import를 지원하지 않는 문제를 공용 capability 목록 기반 `.cjs` preload로 수정했다.
   - device enrollment/revoke router가 factory로만 존재하고 API container에 포함되지 않던 404 wiring 공백을 수정했다. test/local은 명시적 in-memory service를 조립하고 production은 durable device auth service가 없으면 시작을 거부한다.

### 검증 기록

| 검증 | 결과 |
|---|---|
| Phase 5 focused backend boundary/composition suite | `19 passed` |
| Python `compileall` + `pip check` | 통과 |
| contracts/control/connectors/intelligence/integration/e2e non-live 전체 suite | `586 passed, 1 skipped, 10 deselected` |
| root TypeScript typecheck/build/resolution | 통과 |
| Frontend Vitest | `9 files, 30 passed` |
| Desktop Node test | `72 tests, 70 passed, 2 skipped` |
| 실제 API+Vite browser smoke | `/`에서 미인증 `/login` 수렴, Product login UI 표시, console error 없음 |
| `pnpm install --frozen-lockfile` | 통과, lock 변경 없음 |
| contract 재생성과 `shared/contracts/**` diff | 변경 없음 |

Python skip 1건은 이전 phase와 동일한 `FIRESTORE_EMULATOR_HOST` 미설정이며 deselected 10건은 실제 provider credential이 필요한 `live` test다. Desktop skip 2건도 Windows symlink 권한 제약이다. 실제 Google/GitHub Picker·OAuth는 credential과 외부 resource가 필요한 Phase 9 live 검증으로 남겼고, 제품 흐름은 DOM integration test의 명시적 file ID, current workspace, CSRF, opaque local selection assertion으로 검증했다.

구현 중 최초 Desktop 실행은 preload capability의 exact 목록을 검사하는 기존 test가 새 enrollment/Open Original 채널을 반영하지 않아 실패했다. allowlist source와 assertion을 함께 갱신하고, 이어서 공식 Electron sandbox 제약에 따라 공용 CommonJS 채널 모듈로 수렴한 뒤 전체 Desktop `70 passed, 2 skipped`를 재확인했다.

### 명시적 후속 범위

- Phase 6에서 production Source router/store와 pending binding, Drive watch, Secret Manager/GCS/Cloud Tasks adapter를 container에 연결한다.
- built frontend를 API의 same-origin `/app`으로 제공하는 image/static hosting과 Electron production packaging은 Phase 6 배포 산출물에 포함한다.
- 실행 중 queue는 offline 재전송을 제공하지만 crash/restart까지 보존하는 durable event spool은 Phase 6에서 local/GCP delivery 정책과 함께 구현한다.
- 실제 Google Picker API key restriction, OAuth consent/App 설치, credential 기반 provider live E2E와 GCP Console/IAM 작업은 Phase 9 전에는 수행하지 않는다.

### Phase 5 gate

- [x] sole Product UI composition point와 current workspace SourcePanel
- [x] same-origin cookie/CSRF-aware Source client
- [x] safe OAuth/install callback과 Drive/GitHub mount completion
- [x] connected status/reconnect/disable와 provider/local Open Original
- [x] Electron Product renderer, sandbox/preload/navigation 경계
- [x] one-time enrollment, encrypted credential, rotation/revoke
- [x] opaque Local selection, mount 등록, watcher와 ordered offline retry
- [x] browser smoke, frontend/desktop test와 전체 non-live 회귀 통과
- [x] Frozen Contract와 dependency manifest/lock 무변경

종료 gate: **통과**. Phase 6에서는 이 제품 surface를 유지하면서 production durable adapter, static hosting과 GCP repository-internal deploy 산출물을 구현한다.

## Phase 6 — GCP 내부 구성과 배포 준비

### 시작 상태와 범위

- 시작 HEAD: `e89c6e033db0d5cef10284965bd16a8f480a48d3`
- 목표: Phase 4/5의 public surface를 유지하면서 production durable foundation,
  same-origin frontend image, GCP deploy 입력물, scheduler/RAG/운영 검증을 저장소
  내부에서 완성한다.
- 포함: Firestore operational store와 index/TTL, Secret Manager/GCS/Cloud Tasks/OIDC
  adapter, durable device store injection, static Product hosting, non-root multi-stage
  image, Cloud Build/Run/Tasks/Scheduler 선언, RAG checksum dry-run, readiness/운영 handoff.
- 제외: GCP project/resource 생성, IAM binding, OAuth/GitHub console 설정, 실제 Secret
  값 등록, RAG upload, domain/TLS와 live provider test. 이는 승인받은 외부 작업 소유다.

### 수렴 결과

1. **Firestore durable foundation**
   - canonical `FirestoreControlUnitOfWorkFactory`와 하나의 Async Firestore client를
     공유하는 Google Cloud foundation factory를 추가했다.
   - OAuth state, pending connection/binding, desktop challenge/device/credential/mount,
     Drive/GitHub/Local runtime과 tracking scope를 `source_operational_*` namespace로
     분리했다.
   - raw lookup/state/credential을 document ID로 쓰지 않고 SHA-256 key를 사용하며,
     OAuth state consume는 transaction과 명시적 expiry/consumed 검사를 함께 사용한다.
   - canonical composite index와 OAuth/pending/challenge `expires_at` TTL을
     `deploy/firestore.indexes.json`에 고정하고 코드 선언과 정적 대조한다.

2. **GCP managed adapter**
   - Secret Manager vault는 project/provider scope의 opaque resource와 immutable version
     추가/조회/disable을 구현하고 project 밖 reference를 거부한다.
   - GCS Local staging은 UTF-8/1MB 상한, random private object, uniform bucket-level
     access 확인, no-store와 metadata denylist, best-effort delete를 적용했다.
   - Cloud Tasks는 exact ID-only JSON, deterministic task name, 240초 deadline과
     caller service account OIDC/audience를 사용하며 `AlreadyExists`를 idempotent
     success로 처리한다.
   - Worker/Scheduler용 Google-signed OIDC verifier는 audience와 exact verified service
     account email을 모두 확인한다.

3. **Product image와 deploy 입력물**
   - Node 24.19.0/pnpm 11.19.0 frontend build stage와 Python 3.14 non-root runtime
     stage를 가진 공용 Dockerfile을 추가했다. API는 build된 Product UI를 `/app`,
     `/w/*`, `/login` 등에서 same-origin으로 제공한다.
   - Cloud Build image build/smoke, API/Worker Cloud Run desired state, Cloud Tasks queue,
     네 Scheduler job, GCS lifecycle을 `deploy/`에 문서화했다.
   - API/Worker/Tasks/Scheduler/Deploy identity를 분리한 최소 권한 matrix와 외부
     작업 handoff 값을 `docs/GCP_INTERNAL_DEPLOYMENT.md`에 정리했다.

4. **Scheduler와 RAG 준비**
   - Drive watch renewal/reconciliation, expired state cleanup, source health refresh를
     OIDC 보호된 POST endpoint와 cursor/limit 기반 최대 500건 batch contract로
     고정했다.
   - RAG dry-run 도구는 approved manifest path만 읽고 corpus version과 모든 checksum을
     검증한다. 세 public reference 문서를 준비했으며 외부 write는 수행하지 않았다.

5. **운영 안전장치와 검증 가능성**
   - production API 설정에 region, built frontend, Scheduler identity를 필수화했고
     durable device store가 없으면 시작을 거부한다. test/local만 in-memory fallback을
     유지한다.
   - deploy validator가 image/config 파일 존재, YAML/JSON parse, canonical index,
     operational TTL, staging lifecycle을 offline gate로 확인한다.
   - operational schema, TTL의 비-즉시성, emulator 원칙, 허용/금지 log field와 최소
     alert set을 문서화했다.

### 검증 기록

| 검증 | 결과 |
|---|---|
| Phase 6 GCP/Scheduler/deploy/static focused suite | `14 passed` |
| Python `compileall` + `pip check` | 통과 |
| contracts/control/connectors/intelligence/integration/e2e non-live 전체 suite | `597 passed, 1 skipped, 10 deselected` |
| root TypeScript typecheck/build/resolution | 통과 |
| Frontend Vitest | `9 files, 30 passed` |
| Desktop Node test | `72 tests, 70 passed, 2 skipped` |
| `pnpm install --frozen-lockfile` | 통과, lock 변경 없음 |
| deploy static validator | `GCP deployment inputs: valid` |
| RAG ingestion dry-run | version `2026-08-14.1`, 3 documents, checksum 일치, external write 없음 |
| contract 재생성과 `shared/contracts/**` diff | 변경 없음 |
| Docker image 실제 build | 현재 host에 Docker CLI가 없어 미실행; Cloud Build 입력과 Dockerfile은 static gate 통과 |

Python skip 1건은 이전 phase와 동일하게 `FIRESTORE_EMULATOR_HOST` 미설정이며,
deselected 10건은 실제 provider credential이 필요한 `live` test다. Desktop skip 2건도
Windows symlink 권한 제약이다. 새 GCP adapter는 provider client 대역으로 payload,
privacy, one-time consume, version/ref, identity 경계를 검증했다. 실제 emulator와 image
build는 해당 runtime이 있는 외부/CI 환경에서 같은 commit을 대상으로 재실행한다.

### Phase 6 gate

- [x] canonical/operational Firestore 분리와 durable factory
- [x] operational namespace, schema version, index와 TTL deploy declaration
- [x] Secret Manager/GCS/Cloud Tasks/OIDC concrete adapter
- [x] production durable device store injection과 in-memory fallback 금지
- [x] same-origin built Product hosting과 non-root 공용 image
- [x] Cloud Build/Run/Tasks/Scheduler/GCS repository input
- [x] OIDC 보호·bounded Scheduler endpoint contract
- [x] manifest-bounded RAG ingestion dry-run
- [x] service identity/IAM handoff와 observability/readiness 기준
- [x] 전체 non-live 회귀 및 Frozen Contract/dependency lock 무변경

종료 gate: **repository-internal 범위 통과**. Firestore emulator와 Docker runtime이 없는
현재 host의 두 실환경 검증은 명시적으로 보류되었으며, GCP 외부 resource/IAM/live
provider 작업 전에 CI 또는 배포 host에서 재확인한다. 다른 worktree는 수정하지 않았다.

## Phase 7 — 전체 검증과 release freeze

### 시작 상태와 범위

- 시작 HEAD: `41cdc42e84de5bd27d1185a824a563ea6f071473`
- 목표: merge/dependency/local integration/GCP 내부 gate를 한 번에 재검증하고,
  Phase 9 live 작업을 재현 가능한 runbook으로 고정하며 release blocker를 0건으로 만든다.
- 변경 범위: 검증 증거와 staging/live verification runbook. runtime/dependency/contract는
  freeze하며 기능 변경을 추가하지 않는다.

### 검증과 감사 결과

1. **보안·실패·복구 집중 검증**
   - SourceChange idempotency/concurrency, Security Gate, session/CSRF/connection scope,
     pending connection TTL/idempotency, one-time device enrollment/revoke, worker
     retry/reclaim/analyzer mismatch, Open Original host/device boundary, GCP identity와
     Scheduler batch를 묶어 `55 passed`를 확인했다.
   - 첫 focused command는 존재하지 않는 `tests/control/test_analysis_jobs.py`를
     포함해 collection 전에 실패했다. 실제 소유 파일이
     `test_analysis_result_reconciliation.py` 및 integration pipeline test임을 확인하고
     잘못된 경로를 제거한 동일 범위 재실행에서 `55 passed`로 교정했다.

2. **전체 release regression**
   - Python compile/pip check와 전체 non-live suite `597 passed, 1 skipped,
     10 deselected`를 재확인했다.
   - TypeScript typecheck/build/resolution, Frontend `30 passed`, Desktop
     `70 passed, 2 skipped`, frozen pnpm install을 재확인했다.
   - contract 재생성 후 `shared/contracts/**` diff, Python/Node manifest/lock diff가 없다.

3. **repository/deploy integrity**
   - 세 feature merge commit이 현재 HEAD의 ancestor이며 conflict marker가 없다.
   - deploy static validator와 RAG dry-run이 각각 통과했다.
   - credential-shaped literal scan의 유일한 private-key marker는 redaction unit test의
     의도된 synthetic fixture이며 실제 credential이 아님을 확인했다.
   - main과 세 feature worktree는 per-command safe-directory 설정으로 재확인했으며 clean이다.

4. **staging/live runbook 고정**
   - `docs/STAGING_VERIFICATION_RUNBOOK.md`에 진입 조건, resource 생성 순서,
     explicit live opt-in, provider별 positive/negative case, managed resource 확인,
     evidence 금지값, alert/rollback drill과 Go/No-Go 기록 형식을 확정했다.
   - 실제 project/resource/credential을 요구하는 항목은 Phase 9 전에는 실행하지 않는다.

### 알려진 환경 제약

- `FIRESTORE_EMULATOR_HOST`가 없어 emulator test 1건은 skip이다.
- 실제 provider credential이 필요한 10건은 `-m "not live"`에서 의도적으로 제외했다.
- Windows Developer Mode/admin이 없어 Desktop symlink escape 2건은 skip이다.
- Docker CLI가 없어 image build는 Phase 6과 동일하게 미실행이며 Cloud Build 입력의
  static validation만 완료했다.

위 네 항목은 숨겨진 release blocker가 아니라 runbook에 명시된 Phase 9/배포-host
검증 입력이다. repository 내부에서 해결 가능한 실패 또는 미분류 blocker는 0건이다.

### Phase 7 gate

- [x] merge ancestry/conflict marker/다른 worktree 상태 확인
- [x] security/failure/retry/recovery focused suite 통과
- [x] 전체 Python/Web/Desktop non-live regression 통과
- [x] Frozen Contract와 dependency manifest/lock 무변경
- [x] GCP deploy/RAG dry-run 재통과
- [x] staging/live/negative/rollback runbook 확정
- [x] repository-internal blocker 0건과 외부 제약 명시

종료 gate: **통과**. runtime과 dependency를 release freeze했으며, Phase 8에서 계획된
agent 원본 8개만 삭제하고 참조를 통합 문서/README/운영 문서로 수렴한 뒤 같은 전체
regression을 다시 실행한다.

## Phase 8 — 문서 정리와 Release Candidate 고정

### 시작 상태와 범위

- 시작 HEAD: `5f9aa585676fb6c7f286935436ec5650dd149b04`
- 목표: Phase 1에서 지정한 구 Agent 원본 8개를 제거하고, 유지 문서와 실행 경로의
  참조를 최종 상태로 수렴한 뒤 삭제 후 전체 regression으로 RC를 고정한다.
- 보호: 코딩 에이전트 명세 4개, 청사진, dependency/execution 기준 문서 2개,
  통합 현황 로그, 세 Agent 통합 문서와 runtime provenance 문서는 삭제하지 않는다.

### 삭제와 참조 수렴

계획된 아래 8개만 삭제했다.

```text
AGENT_1_DELIVERY.md
AGENT_1_PLATFORM_CONTROL_IMPLEMENTATION_PLAN.md
LOCAL_RUN_AND_TEST_GUIDE.md
agent-deliverables/agent-1-dependencies.md
AGENT_2_DELIVERY.md
agent-deliverables/agent-2-dependencies.md
AGENT_3_DELIVERY.md
agent-deliverables/agent-3-dependencies.md
```

- Google Drive/Gemini/RAG runtime error와 connector test가 삭제된 dependency 문서를
  가리키던 5개 참조를 root `pyproject.toml` 설치 안내로 교체했다.
- 세 Agent 통합 문서의 상태를 최종 유지 문서로 바꾸고 원본 삭제 결과, Phase 6 완료
  사항과 Phase 9 live 후속을 반영했다.
- README를 Phase 8 RC 상태, release regression/runbook 완료, 원본 제거와 Git history
  provenance 구조로 갱신했다.
- 보호 대상 Master Spec의 `agent-deliverables/` 구조 예시, dependency baseline과
  execution/progress history의 과거 파일명은 실행 경로가 아니므로 그대로 보존했다.

### 삭제 후 검증 기록

| 검증 | 결과 |
|---|---|
| 삭제 대상 8개 존재 여부 | 모두 없음 |
| runtime/build/test/운영 문서의 삭제 파일 참조 | 없음 |
| Python `compileall` + `pip check` | 통과 |
| 전체 non-live Python suite | `597 passed, 1 skipped, 10 deselected` |
| root TypeScript typecheck/build/resolution | 통과 |
| Frontend Vitest | `9 files, 30 passed` |
| Desktop Node test | `72 tests, 70 passed, 2 skipped` |
| `pnpm install --frozen-lockfile` | 통과, lock 변경 없음 |
| deploy validator/RAG dry-run | 통과, 3 documents/checksum 일치/external write 없음 |
| contract 재생성 및 `shared/contracts/**` diff | 변경 없음 |
| dependency manifest/lock diff | 변경 없음 |
| `git diff --check` | 통과 |

skip/deselection 사유는 Phase 7과 동일하다. 문서 삭제와 안내 문자열 교체 외 runtime
동작 변경은 없으며, GCP Console/IAM/resource/provider live 작업은 시작하지 않았다.

### Phase 8 gate

- [x] Phase 7 전체 검증 선행
- [x] 지정된 구 Agent 원본 8개만 삭제
- [x] 세 Agent 통합 문서와 README/운영 문서만으로 build/test/handoff 가능
- [x] 실행 경로의 삭제 파일 참조 0건
- [x] 삭제 후 전체 Python/Web/Desktop regression 재통과
- [x] Frozen Contract/dependency lock 무변경
- [x] Phase 9 staging/live runbook과 rollback 기준 존재
- [x] 다른 worktree 무변경, GCP 외부 작업 미시작

종료 gate: **통과**. 이 Phase 8 commit을 GCP 외부 작업에 전달할 Release Candidate로
고정한다. 다음 단계는 `docs/STAGING_VERIFICATION_RUNBOOK.md`를 따르는 Phase 9이며,
실제 project/resource/IAM/credential 변경은 별도 승인 없이는 수행하지 않는다.

## Phase 9 — GCP 외부 구성·배포·실환경 검증

### 시작 상태와 범위

- 시작 HEAD / Release Candidate: `e05ad90583f0c3c35363fd02dcb64c399c522afc`
- 목표: 승인된 staging GCP project에서 IAM/resource를 구성하고 같은 RC image digest를
  API/Worker에 배포한 뒤 provider/RAG positive·negative E2E와 rollback을 검증한다.
- repository 내부 작업: Phase 9 진입 gate 재확인, 외부 실행 절차와 증거 형식 기록.
- repository 외부 작업: GCP/Google/GitHub Console, Cloud Shell/CI build, OAuth/GitHub
  credential 구성, live test. 실제 credential 값은 저장소나 이 로그에 기록하지 않는다.

### 2026-08-21 착수 결과

1. RC worktree가 clean이고 시작 commit이 Phase 8 RC임을 확인했다.
2. 현재 host에는 `gcloud` CLI가 없고 활성 Google Cloud account/project도 제공되지
   않았다. Phase 6에서 확인한 것처럼 Docker CLI도 없는 상태다.
3. project ID, billing 승인, 외부 작업자 권한, service account, provider credential,
   domain이 확정되지 않아 비용·IAM·credential 변경을 임의로 시작하지 않았다.
4. `PHASE_9_GCP_EXTERNAL_WORK_GUIDE.md`를 별도의 삭제 가능한 비규범 문서로 작성했다.
   유지 문서는 이 파일을 역참조하지 않으므로 Phase 9 종료 후 삭제해도 runtime,
   build/test, 배포 계약 또는 프로젝트 문서 완결성에 영향이 없다.
5. 가이드에는 RC 재검증, API/identity/IAM, Artifact Registry/image digest, Firestore
   index/TTL, private bucket/lifecycle, Secret Manager, Worker→Tasks→API→Scheduler,
   RAG, Google OAuth/Drive/Picker, GitHub App, domain/TLS, live negative test, alert와
   rollback/Go-No-Go 순서를 고정했다.

### Repository 진입 gate 재검증

| 검증 | 결과 |
|---|---|
| Python `compileall` / `pip check` | 통과 / `No broken requirements found` |
| 전체 non-live Python suite | `597 passed, 1 skipped, 10 deselected` |
| frozen pnpm install / contract generate·diff | 통과 / Frozen Contract 변경 없음 |
| root typecheck / build / resolution | 통과 |
| Frontend Vitest | `9 files, 30 passed` |
| Desktop Node test | `72 tests, 70 passed, 2 skipped` |
| deploy static validator | `GCP deployment inputs: valid` |
| RAG ingestion dry-run | 3 documents, checksum 일치, external write 없음 |
| main과 세 feature worktree | 모두 clean, 변경 없음 |

첫 Python suite 실행은 Windows 전역 pytest 임시 디렉터리
`C:\Users\leehy\AppData\Local\Temp\pytest-of-leehy` 접근 거부로 `tmp_path` fixture 3건이
setup error였다. repository 내부 `--basetemp .pytest-tmp-phase9`를 지정해 동일 608개
collection을 다시 실행했고 위 결과로 전부 수렴했다. 코드나 test assertion 실패는
없었다. skip/deselection은 Phase 7/8과 동일하게 Firestore emulator 1건과 explicit live
provider 10건이며, Desktop skip 2건은 Windows symlink 권한 제약이다.

### 현재 차단 입력

- staging GCP `PROJECT_ID`, project number, billing 및 비용 한도 승인
- application/RAG region, Firestore database ID, bucket/queue 이름
- Console/Cloud Shell 실행 권한 또는 구성 완료 결과
- OAuth test user/client, GitHub test App/repository, KIPRIS provider key
- API custom domain 또는 staging `run.app` URL 정책

이는 repository 결함이 아니라 승인된 외부 환경이 필요한 Phase 9 입력이다. 입력이
준비되기 전에는 cloud resource 생성, IAM binding, credential 등록과 live provider
호출을 실행하지 않는다.

### Phase 9 gate

- [x] Phase 8 RC와 외부 작업 진입 조건 재확인
- [x] 삭제 가능한 GCP 외부 작업 문서와 단계별 체크리스트 작성
- [ ] staging project/API/service account/IAM 최소 권한 구성
- [ ] RC image build와 immutable digest 고정
- [ ] Firestore/index/TTL, bucket/lifecycle, secrets 구성
- [ ] private Worker→Cloud Tasks→public API→Scheduler 순서 배포
- [ ] RAG corpus와 Google OAuth/Drive/Picker/GitHub App 구성
- [ ] provider/RAG positive·negative live E2E 통과
- [ ] monitoring alert와 rollback drill 통과
- [ ] production readiness Go 승인

현재 gate: **진행 중 — 외부 입력 대기**. repository 안에서 수행 가능한 Phase 9 착수
문서화까지 완료했으며, 외부 환경이 준비되면 체크리스트 §2부터 증거를 누적한다.

## 번외 정리 — 초기 환경 문서 제거

- 대상: `ENVIRONMENT_SETUP.md`
- 판단: 삭제. 환경 설정의 유지 기준은 root `README.md`, `.env.example`,
  `INTEGRATION_V2_DEPENDENCY_BASELINE.md`와 실제 manifest/lock이다.
- 근거: 해당 문서는 통합 초기 skeleton을 설명하여 Python 3.12.13, 미구현
  API/Worker/Plane, 병렬 Agent ownership, 누락·폐기된 환경 변수 등 현재 상태와 충돌했다.
- coverage: 최신 CPython 3.14.7/Node/pnpm 설치, lock 기반 설치, 전체 검증 명령,
  environment group, API/Worker와 Web/Electron 로컬 실행, 보안 불변조건은 이미
  `README.md`에 유지된다. exact dependency 결정은 dependency baseline과 manifests가
  소유한다.
- 참조 확인: runtime, build/test script, README와 운영 안내에는 활성 참조가 없어 삭제 후
  실행·안내 경로의 dangling link가 없다. dependency baseline의 두 언급은 최초 분석
  대상과 Python 3.12 오류를 남긴 역사적 근거이므로 그대로 보존했다.
- 부수 정리: `README.md`의 통합 상태를 Phase 8 RC 기반 Phase 9 착수·외부 입력 대기로
  갱신했다. runtime, dependency, Frozen Contract와 배포 파일은 변경하지 않았다.
- 검증: `git diff --check`와 runtime/build/test/README/운영 경로의 활성 참조 scan이
  통과했다. 문서 삭제와 상태 문구만 변경했으므로 runtime regression은 재실행하지 않았다.

## Phase 9 repository blocker 해결 — production composition root

### 시작 상태와 원인

- 시작 HEAD: `a125f429f9150d44a4966d25c7f55d860d3f042d`
- `main.py`와 `worker.py`가 production에서도 `build_container(settings)`를 직접 호출해
  `build_google_cloud_foundation()`의 Firestore/Cloud Tasks/Secret Manager/GCS adapter가
  container에 전달되지 않았다.
- `build_container()`는 모든 production role에 Firestore와 outbound Cloud Tasks를 함께
  요구했으므로 Worker도 사용하지 않는 queue client/location/name을 필요로 했다.
- `Settings.validate()`는 Worker에 Google Login/Picker/API callback/Scheduler까지 요구한
  반면 `deploy/cloud-run-services.yaml`은 API가 실제로 요구하는 Source/OAuth 변수를
  다수 누락하여 runtime과 deploy 계약이 서로 달랐다.
- foundation만 단순 주입해도 production guard가 요구하는 전체 Source adapter/router와
  Worker Intelligence/OIDC가 없으므로 실제 entrypoint startup은 계속 실패하는 상태였다.

### 변경과 수렴

1. production entrypoint가 Google Cloud foundation을 만들고 role-aware runtime composer를
   `build_container()`에 전달하도록 연결했다. local/test 경로는 기존 in-memory 기본값을
   그대로 사용한다.
2. API composition은 Firestore canonical/operational store, Cloud Tasks publisher,
   Secret Manager credential vault/static secret reader, GCS staging, durable device auth,
   Drive/GitHub/Local adapters와 web/webhook/desktop routers를 조립한다.
3. Worker composition은 같은 durable store/vault/staging과 전체 Source adapters,
   Vertex Gemini/KIPRIS/package metadata 및 선택 RAG Intelligence facade, exact Worker URL과
   Tasks caller email을 검사하는 Google OIDC authenticator를 조립한다.
4. Worker outbound enqueue를 제거했다. Worker 내부 facade에는 호출 시 fail-closed하는
   role-local enqueuer를 두고 readiness에는 `task_queue=not_applicable`을 기록한다. 실제
   queue 생성/enqueue 권한과 client는 API만 소유한다.
5. GitHub private key, webhook secret과 KIPRIS key는 secret ID만 settings에 두고 attached
   service identity를 사용하는 Secret Manager client로 startup에 읽는다. 서비스 계정
   key file 경로는 추가하지 않았다.
6. operational Firestore에 bounded nested-field lookup을 추가하고 GitHub tracking
   `record.owner + record.repo` composite index를 deploy JSON에 추가했다.
7. Settings와 Cloud Run manifest를 API/Worker 공통, API 전용, Worker 전용, Worker 선택
   RAG group으로 일치시켰으며 deploy validator가 exact environment set과 새 index를
   회귀 검증한다.

### role별 production 필수 환경

- 공통: `APP_ENV`, `APP_ROLE`, `APP_PUBLIC_BASE_URL`, `GCP_PROJECT_ID`, `GCP_REGION`,
  `FIRESTORE_DATABASE`, `LOCAL_STAGING_BUCKET`, Drive client ID/secret, GitHub App ID와
  private-key secret ID.
- API: session/frontend, Google Login, Drive callback/webhook/channel, Picker, GitHub
  slug/webhook/callback, Tasks location/queue/Worker URL/caller SA, Scheduler caller SA.
- Worker: Worker URL/caller SA, Vertex location, KIPRIS secret ID, package metadata base URL.
  RAG region/corpus ID/version은 all-or-none 선택 group이다.

### 검증

| 검증 | 결과 |
|---|---|
| production composition/settings/deploy focused | 통과 |
| production composition/settings/GCP adapter focused | `16 passed` |
| 전체 non-live Python suite | `577 passed, 1 skipped, 10 deselected` |
| Python compile / pip check | 통과 |
| TypeScript typecheck/build/resolution | 통과 |
| Frontend Vitest | `9 files, 30 passed` |
| Desktop Node test | `72 tests, 70 passed, 2 skipped` |
| deploy validator / RAG dry-run | 통과 / 3 documents, external write 없음 |
| Frozen Contract / dependency manifest | 변경 없음 |

전체 marker를 포함한 실행도 수행했으며, 저장소 내부 검증은 `577 passed`였다. 외부 네트워크가
차단된 현재 실행 환경에서 deps.dev/PyPI/NPM에 직접 연결하는 live provider test 4개가
`ConnectError`로 실패했고 credential이 필요한 live test 6개와 Firestore emulator test
1개는 skip됐다. 이는 production composition 회귀 실패가 아니며 staging에서는 외부 연결과
credential을 준비한 뒤 live marker를 별도 재실행한다.

### 남은 blocker

- **repository (당시 상태)**: `SchedulerOperations`의 Drive watch renewal/reconciliation,
  expired-state cleanup, source health refresh 구현과 API router wiring이 없었다. 아래
  predeployment readiness 후속 작업에서 해결했다.
- **external**: 실제 GCP project/IAM/Secret version/index/bucket/queue/image와 provider
  credential이 없어 ADC 권한 및 live E2E는 아직 실행하지 않았다.
- Firestore emulator와 Docker/Cloud Build image 검증은 해당 runtime이 있는 배포 환경에서
  같은 blocker-fix commit을 대상으로 수행한다.

현재 Phase 9 gate는 계속 **진행 중**이다. API/Worker production startup composition
blocker는 해결됐지만 Scheduler repository blocker와 기존 외부 입력 gate가 남아 있다.

## Phase 9 shared-project v2 namespace isolation

### 범위와 시작 상태

- 시작 HEAD: `4ec2b9e`
- shared GCP project: `proj-aj22-211200020328` / project number `555102774494`
- 목표: 기존 v1 resource를 수정·삭제·재사용하거나 IAM binding 대상으로 삼지 못하도록
  production startup, deploy contract, validator와 외부 작업 문서를 v2 namespace로 수렴한다.
- 이 작업에서는 `gcloud`, Console, 실제 resource/IAM/secret 변경을 실행하지 않았다.

### 구현 결과

1. `gcp_contract.py`와 `deploy/v2-resource-contract.yaml`에 project/region, named Firestore,
   Run services, Tasks queue, repository/image, five service accounts, Scheduler jobs, bucket,
   fixed/dynamic secrets와 RAG corpus의 canonical 이름을 고정했다.
2. production `Settings.validate()`는 project/region/database/bucket/secret prefix와 role별
   fixed secret/task identity를 exact-match하며 `(default)`, emulator, legacy/non-v2 값과
   role 반대편 설정을 거부한다.
3. Worker는 API-only `ANALYSIS_WORKER_URL`, Tasks caller/publisher, OAuth/session/Scheduler
   설정을 받지 않는다. deterministic v2 Run URL을 `APP_PUBLIC_BASE_URL`과 inbound OIDC
   audience로 사용하고 canonical Tasks caller identity를 코드 계약에서 얻어 Worker-first
   deployment가 가능하다.
4. Source credential vault는 `iprisk-v2-cred-{provider}-{digest}`만 생성·수락하고 secret에
   `owner=ip-risk-agent-v2`, `environment=v2` label을 둔다. `ipra-*`, 기존
   `iprisk-google_drive-*` 및 다른 prefix ref는 fail-closed한다.
5. Run/Build/Tasks/Scheduler manifest를 모두 canonical v2 이름으로 바꾸고 API/Worker가 같은
   `ip-risk-agent-v2/application` artifact를 사용하며 Worker unauthenticated가 false임을
   validator가 검사한다.
6. `deploy/iam-policy-contract.yaml`에 v2 database condition, queue/bucket/repository/service
   단위 binding, fixed secret role matrix와 dynamic credential 최소 permission을 기록했다.
   runtime Owner/Editor/Secret Manager Admin/unconditional Datastore User는 금지한다.
7. Secret 생성은 `secretmanager.secrets.create`가 project parent에서 평가되어 미래 secret
   ID prefix로 IAM 제한할 수 없음을 명시했다. API custom role은 이 permission 하나만
   유지하고 versions.add/access는 v2 prefix condition으로 제한하며 disable은 현재 미부여다.
8. Google Auth Platform project-level Branding/Audience/Data Access/authorized domain은 v1과
   shared configuration으로 표시했다. v2 Login/Drive client와 v2 RAG corpus는 별도 생성하되
   v1 client/consent/corpus를 수정·삭제·재사용하지 않는다.

### 회귀 검증

| 검증 | 결과 |
|---|---|
| namespace/settings/composition/GCP adapter/deploy focused | `32 passed` |
| 전체 integration non-live | `46 passed` |
| 전체 Python non-live | `591 passed, 1 skipped, 10 deselected` |
| Python compile / pip check | 통과 / broken requirement 없음 |
| deploy v2 namespace/IAM validator | `GCP deployment inputs: valid` |
| RAG dry-run | 3 documents, checksum 일치, external write 없음 |
| pnpm frozen offline install | lock 변경 없이 통과 |
| TypeScript typecheck/build/resolution | 통과 |
| Frontend / Desktop | `30 passed` / `70 passed, 2 skipped` |
| Frozen Contract regenerate/diff | 변경 없음 |
| `git diff --check` | 통과 |

Python skip/deselection과 Desktop skip 사유는 이전 gate와 동일하게 Firestore emulator,
explicit live provider, Windows symlink 권한이다. v1/default/non-v2 이름, public Worker,
서로 다른 image와 Worker API-setting 유입을 주입한 10개 negative deployment case는 모두
validator failure로 확인했다.

### 남은 blocker

- repository (당시 상태): `SchedulerOperations` 네 maintenance 구현과 API router wiring이
  없었으며, 아래 predeployment readiness 후속 작업에서 해결했다.
- external: named Firestore DB, v2 IAM/resource/secret/OAuth client/RAG corpus/image를 실제로
  만들고 ADC/IAM condition/live E2E를 검증해야 한다.
- dynamic credential secret create permission은 GCP IAM 특성상 project parent scope다.
  현재 코드 prefix guard와 create-only custom role이 v1 수정을 막지만, compromised runtime의
  임의 새 secret 생성을 IAM 자체로 prefix 제한해야 한다면 별도 provisioning broker로
  secret creation을 분리하는 후속 hardening이 필요하다.

현재 Phase 9 gate는 계속 **진행 중**이다. repository 내부 v2 namespace contract는
수렴했으며 실제 shared project에는 아직 어떤 변경도 적용하지 않았다.

## Phase 9 repository predeployment readiness 완결

### 범위

- 시작 HEAD: `3d307fe`
- 실제 GCP resource/IAM/build/deploy 작업은 수행하지 않았다.
- production Scheduler, Cloud Build 실행 identity, index/TTL 및 전체 v2 preflight를
  repository 내부에서 완결하는 작업이다.

### 구현 결과

1. Drive changes watch를 실제 Google provider의 `changes.watch`에 연결하고 channel/resource/
   expiry와 change cursor를 기존 durable Drive runtime에 보존한다. renewal은 만료 24시간
   전 새 channel로 교체하며 중복 delivery는 기존 fingerprint intake로 무해화한다.
2. production Scheduler는 Drive tracking, GitHub tracking, Local runtime, operational
   pending/OAuth/device store와 Control facade를 재사용한다. 네 route가 API composition에
   mount되고 `iprisk-v2-scheduler` OIDC identity만 허용한다.
3. Drive reconciliation은 mount별 provider page를 끝까지 처리해 content-free SourceChange를
   기존 sink에 전달한다. source health는 adapter 결과를 canonical connection/workspace/mount
   status로 idempotent하게 수렴한다.
4. expired cleanup은 bounded cursor/limit으로 동작하며 OAuth state, device challenge와
   만료된 `PENDING` connection만 삭제한다. ACTIVE pending record가 durable credential lookup에
   필요하므로 해당 collection의 TTL을 제거했다.
5. Firestore composite index는 GitHub owner/repo query를 포함한 정확히 8개, TTL은 정확히
   2개로 manifest/validator/배포 문서를 동기화했다.
6. Cloud Build는 `iprisk-v2-deploy` user-specified service account와
   `CLOUD_LOGGING_ONLY`를 명시한다. 이 identity는 v2 repository Writer, Logs Writer와
   source bucket Object Viewer를, Cloud Build service agent는 해당 identity Token Creator만
   요구한다.
7. Cloud Run API/Worker는 동일 `application@${IMAGE_DIGEST}`를 사용한다. validator는
   namespace, role env, IAM/secret, Scheduler job-route, build identity, 8-index/2-TTL,
   Docker context와 승인 RAG 3개 문서를 pure offline gate로 검사한다.

### 검증 상태

- Python compile / pip check: 통과 / broken requirement 없음.
- 전체 Python non-live: `626 passed, 1 skipped, 10 deselected`.
- frozen pnpm install, contract generate/diff, typecheck/build/resolution: 통과.
- Frontend / Desktop: `30 passed` / `70 passed, 2 skipped`.
- deployment validator: `GCP deployment inputs: valid`.
- RAG dry-run: 승인 3 documents, checksum/version 일치, external write 없음.
- API/Worker module import smoke와 `git diff --check`: 통과.
- Docker CLI가 host에 없어 실제 local image build는 미실행했다. Dockerfile/build context와
  Cloud Build의 API/Worker smoke step은 repository validator로 정적 검증했다.
- 실제 shared GCP project에는 어떤 변경도 적용하지 않았다.

### gate 판정

- repository-side predeployment blocker: 없음.
- external: named database/resource/IAM/secret/OAuth/GitHub App/RAG corpus 생성, Cloud Build,
  Docker image runtime smoke와 live ADC/provider E2E가 남아 있다.
- 최종 RC commit SHA와 clean status는 commit 완료 후 이 작업의 완료 보고에 기록한다.

## Phase 9 외부 첫 배포 피드백 반영: Worker image ENV와 build source IAM

### 확인된 blocker

- 시작 RC: `d51320632d` (이 수정 이후 최종 RC가 아님).
- shared runtime image가 `FRONTEND_DIST_DIR=/app/frontend/dist`를 기본 `ENV`로 포함해
  Worker에도 API-only 설정이 암묵적으로 전달됐다. production role contract가 이를
  fail-closed해 Worker startup이 `SettingsError`로 종료됐다.
- user-specified Cloud Build identity `iprisk-v2-deploy@proj-aj22-211200020328.iam.gserviceaccount.com`에
  source staging bucket `gs://proj-aj22-211200020328_cloudbuild` 읽기 권한이 없어 첫
  `gcloud builds submit`이 `storage.objects.get` 403으로 build step 전에 실패했다.

### repository 수렴

1. Dockerfile의 shared runtime ENV에서 `FRONTEND_DIST_DIR`를 제거하고 API manifest에만
   `/app/frontend/dist`를 canonical 값으로 명시했다. Worker manifest에는 해당 key가 없다.
2. validator가 Dockerfile runtime stage의 ENV key를 정적으로 파싱해 모든 API/Worker 전용
   변수의 image-level 유출을 거부하도록 확장했다.
3. production entrypoint 회귀 테스트가 API의 `/app` dist 제공, 유효 Worker startup,
   `FRONTEND_DIST_DIR`가 상속된 Worker의 startup 거부를 함께 검증한다.
4. IAM contract에 deploy identity의 정확한 Cloud Build source bucket 범위
   `roles/storage.objectViewer`를 추가했다. runtime identity 권한이나 v1 resource는 변경하지
   않았으며 실제 GCP/IAM 작업은 이 repository 수정에서 수행하지 않았다.

### 검증 상태

- focused deployment/settings/production composition: `29 passed`.
- Python compile / pip check: 통과 / broken requirement 없음.
- 전체 Python non-live: `629 passed, 1 skipped, 10 deselected`.
- frozen offline pnpm install, contract generate/diff, typecheck/build/resolution: 통과.
- Frontend / Desktop: `30 passed` / `70 passed, 2 skipped`.
- deployment validator: `GCP deployment inputs: valid`.
- RAG dry-run: 승인 3 documents, checksum/version 일치, external write 없음.
- `git diff --check`: 통과.
- Docker CLI가 host에 없어 실제 local image build는 미실행했다. shared runtime image ENV와
  API/Worker production startup은 repository static/composition gate로 검증했다.
- 실제 GCP resource/IAM 변경 명령은 실행하지 않았다.

### gate 판정

- 이번에 확인된 repository-side Worker startup 및 build source IAM blocker는 해결됐다.
- 새 RC SHA와 clean status는 commit 후 완료 보고에 기록한다.
- 외부에는 새 image build/deploy와 Worker/API runtime smoke, 기존 Phase 9 live ADC/provider
  E2E가 남아 있다.

## Phase 9 staging Drive Picker → mount frontend blocker

### live evidence와 원인

- Google Login, Drive OAuth, `pending-*` picker-session 및 실제 Picker 표시/선택은 성공했다.
- 기존 frontend UX는 Picker의 Select에서 `files` state만 설정하고 별도
  `Track selected files` 버튼을 눌러야 mount POST를 실행했다. 따라서 Picker Select만으로는
  `/drive/mounts` 요청이나 source refresh가 발생하지 않는 two-step 경계가 live 기대와
  불일치했다.
- Picker adapter test double은 공식 `google.picker.Response`와
  `google.picker.Document` namespace 없이 literal `action/docs/id` payload만 전달했다. 현재
  field 문자열과 우연히 일치하는 mock이라 공식 enum 기반 callback 경계와 malformed/error
  처리를 검증하지 못했다.

### frontend 수렴

1. Google Picker callback은 `Response.ACTION`, `Response.DOCUMENTS`, `Action.PICKED/CANCEL/ERROR`,
   `Document.ID/NAME/MIME_TYPE`으로 해석한다.
2. `PICKED`에 documents가 없거나 ID가 invalid/duplicate인 경우 더 이상 빈 선택으로
   성공하지 않고 safe error로 거부한다. console diagnostic은 고정 reason code만 포함하며
   OAuth token과 raw Drive metadata를 기록하지 않는다. CANCEL은 정상적인 빈 선택이다.
3. UX를 Picker Select 즉시 `pending-*` connection ID로 mount POST를 실행하는 one-step 흐름으로
   변경했다. 성공하면 source state를 reload하고, mount 실패 시 선택 파일을 유지한 채 오류와
   retry action을 표시한다.
4. `pending-*`는 OAuth 이후 mount registration에 사용하는 의도된 backend handle이다. mount
   성공 시 backend가 canonical connection을 생성하고 pending record를 ACTIVE로 전환하므로
   frontend에서 임의 치환하지 않는다.

### 검증 상태

- Google Picker 공식 shape, 복수 ID, CANCEL, ERROR/malformed, PICKED-without-documents,
  safe diagnostic: 통과.
- selected IDs → pending connection mount POST, 성공 후 source refresh, 실패 UI/retry: 통과.
- frontend 전체 test: `39 passed`; typecheck/build: 통과.
- 관련 backend Drive mount/pending boundary: `9 passed`.
- backend/API, Drive scope, GCP resource/IAM/OAuth client 계약은 변경하지 않았다.
- 실제 GCP 명령은 실행하지 않았다.

## Phase 9 staging Drive Picker callback sequence diagnostic

### 추가 live evidence

- runtime enum은 `picker.Response.ACTION === "action"`,
  `picker.Action.PICKED === "picked"`였지만 Picker Select 전에 adapter가
  `invalid_action`으로 Promise를 reject했다.
- Google 공식 Action enum은 `PICKED`, `CANCEL`, `ERROR` 세 terminal action만 문서화하며
  intermediate action은 명시하지 않는다. 그러나 live runtime에서 non-terminal callback이
  먼저 관찰됐으므로 unknown callback을 terminal failure로 간주하지 않는다.

### 변경 계약

1. 모든 callback은 `typeof payload`, `Object.keys`, action 값, Response action key,
   PICKED enum 값만 temporary diagnostic으로 기록한다. token, callback/docs 본문, file
   metadata와 raw Drive response는 기록하지 않는다.
2. `CANCEL`만 `[]`로 resolve하고, `ERROR`만 reject하며, `PICKED`만 documents 검증 후
   resolve한다.
3. unknown action 또는 non-object/malformed 선행 payload는 diagnostic 후 무시하고 다음
   terminal callback을 기다린다. `PICKED`에 documents가 없거나 invalid한 경우는 terminal
   payload 오류이므로 reject한다.

### 검증 상태

- PICKED, CANCEL, ERROR, unknown → PICKED, malformed → PICKED, PICKED-without-documents:
  통과.
- diagnostic allowlist 및 token/raw metadata 비노출: 통과.
- frontend 전체 test: `40 passed`; typecheck/build: 통과.
- 실제 GCP 명령은 실행하지 않았다.

## Phase 9 Sources / Virtual Workspace / Risk lifecycle closure

### Confirmed root gaps

- A completed Drive mount persisted canonical source metadata and Picker tracking scope, but it did
  not emit an initial `SourceChange`. Drive reconciliation starts from a new changes cursor, so a
  file selected before that cursor could remain unanalyzed until the user edited it later.
- The Sources UI consumed only the security data-access summary. Canonical Artifact,
  ChangeEvent, AnalysisJob, and Risk records therefore had no provider-neutral Sources read model,
  even when the Worker pipeline had completed successfully.
- Add Source and the active completion/manage flow shared one conditional card. A completion or
  Add-files action therefore replaced the Add Source entry point instead of coexisting with it.

### Implemented convergence

1. Drive mount completion now saves the Picker scope first, fetches metadata only for the
   explicitly selected IDs, emits idempotent CREATE changes with provider revisions, and publishes
   them through the existing canonical intake/Cloud Tasks boundary.
   GitHub mount completion similarly reads the tracked branch tree, applies include/exclude and
   source `.ipriskignore` rules, and publishes tracked blobs by SHA. A truncated provider tree fails
   safely instead of silently presenting incomplete coverage. Desktop continues to publish its
   initial watcher events through the existing device event boundary.
2. Data-access summary now includes workspace-isolated tracked-artifact projections with provider,
   availability, latest change/analysis state, risk counts, and a safe Risk-detail reference.
3. Sources renders that provider-neutral Virtual Workspace list and links artifacts with findings to
   the existing Risk detail/evidence UI. Zero-risk, waiting, running, failed, and succeeded states are
   represented without inferring a finding that does not exist.
4. Add Source is permanently visible. ACTIVE Drive file expansion stays on the connected Drive card
   and reuses the mount-bound ACTIVE credential; it does not restart OAuth.
5. Picker display names are sent as safe metadata. Tokens, callback payloads, raw Drive responses,
   and source content remain excluded from UI diagnostics and logs.

### 422 evidence conclusion

- This repository cannot produce `422 {"detail":"Method Not Allowed"}` for the active Drive POST.
  Starlette produces that exact body only for a method mismatch and returns 405; application 422
  handlers use a different safe error envelope. The mount callback did not call Google Drive at all,
  so the previously observed response was not an external Drive 405 translated by this code.
- The POST route remains covered explicitly, while the wrong-method regression is fixed at 405.
  After this change, the only new provider call in mount completion is the Picker-scoped initial
  metadata fetch; failures are not translated to the contradictory 422 body.
- A provider HTTP failure during that initial metadata operation is mapped to the source connector
  error boundary and returned as a safe 502/503 `DRIVE_INITIAL_SYNC_FAILED` envelope containing only
  operation, category, and retryability. Provider URL, file ID, response body, and credentials are
  excluded.

### Verification

- Drive initial selection/scope and active route tests cover initial change publication, duplicate
  behavior, authorization, and the 405/422 distinction.
- Sources tests cover persistent Add Source, ACTIVE Add files without OAuth, multiple selections,
  retry, provider-neutral mixed artifacts, analysis states, risk/no-risk states, refresh, and Risk
  navigation.
- Existing pipeline tests continue to cover SourceChange intake -> queue -> Worker -> analysis result
  -> risk persistence. No GCP command or resource/IAM/OAuth mutation was executed.
- Final gates: Python non-live `641 passed, 1 skipped, 10 deselected`; frontend `45 passed`;
  workspace typecheck/build, dependency check, deployment validator, and diff check passed.

## Phase 9 staging Drive ACTIVE connection 추가 파일 lifecycle

### live gap 및 원인

- 첫 OAuth와 mount 뒤 operational pending connection은 `ACTIVE`로 유지되고 credential도
  Secret Manager reference로 남았지만, Sources 화면은 canonical workspace mount만 조회했다.
  따라서 frontend에는 ACTIVE credential로 Picker를 다시 여는 안전한 경로가 없었고 Add Source
  OAuth flow만 노출됐다.
- backend의 기존 connection-scoped Picker/mount API는 ACTIVE 상태의 operational
  `pending-*` handle도 허용했다. 다만 그 handle을 화면에 다시 노출하면 동일 계정의 여러
  workspace 경계를 모호하게 만들 수 있어, 기존 mount authorization을 기준으로 credential을
  찾는 mount-scoped API를 추가했다.
- 서로 다른 Drive 선택 집합은 별도 SourceWorkspace/WorkspaceMount로 등록되는 기존 설계였지만
  모든 mount alias가 `Google Drive`로 같았다. 두 번째 선택은 workspace alias unique invariant와
  충돌하는 실제 backend 결함이었다. 선택 집합 digest 기반의 결정적이고 고유한 alias로 수정했다.

### 구현 결과

1. ACTIVE Drive 카드에 tracked file ID 목록/개수와 `Add files` 액션을 표시한다. Add files는
   OAuth start를 호출하지 않고 기존 mount로 Picker session을 발급한 뒤 선택된 새 file ID만
   추가 mount로 등록하고 data-access summary를 reload한다.
2. `POST /api/v1/source-mounts/{mount_id}/drive/picker-session`과
   `POST /api/v1/source-mounts/{mount_id}/drive/mounts`를 추가했다. 두 route는 mount와 workspace를
   각각 authorize한 뒤 operational binding의 기존 ACTIVE credential을 재사용한다.
3. backend는 기존 connection의 모든 Drive tracking scope를 읽어 이미 추적 중인 ID를 제거한다.
   exact retry는 같은 mount를 반환하며, 모두 중복인 새 조합은 `409 selected files are already
   tracked`로 명확히 처리한다. 부분 중복은 새 ID만 저장하므로 duplicate workspace mount를 만들지 않는다.
4. ACTIVE connection은 pending TTL 뒤에도 durable하게 유지한다. 명시적 OAuth reconnect가 발생한
   경우 같은 operational handle의 credential reference만 갱신하고 평행 connection을 만들지 않는다.
5. mount 실패 시 기존 connection/mount와 선택 상태를 유지하고 retry를 제공한다. token, Picker
   callback 원문, Drive metadata는 UI/console/log에 추가하지 않았다.

### 422 `Method Not Allowed` 판정

- 현재 repository에는 `422`와 `detail="Method Not Allowed"`를 함께 생성하는 코드가 없다.
  FastAPI/Starlette의 method mismatch는 정확히 `405 {"detail":"Method Not Allowed"}`이며 이를
  route regression test로 고정했다. request validation 422와 domain 422도 서로 다른 safe body를 쓴다.
- 따라서 live에서 기록된 `422` status와 해당 body의 조합은 현재 배포 코드 한 응답으로는 재현할
  수 없다. 두 번째 서로 다른 선택에서 repository가 실제로 재현한 제품 오류는 동일 mount alias의
  unique collision이었고, 설치된 error handler 계약상 409 conflict 경로다. 이 alias collision과
  OAuth 재시작 우회는 이번 변경으로 제거했다. 새 revision 배포 후에도 동일 조합이 관찰되면 같은
  Network request의 status/body/response headers를 한 번에 다시 수집해야 한다.

### 검증 상태

- frontend 전체 test: `44 passed`; frontend typecheck/build: 통과.
- focused backend integration/Drive route: `12 passed`.
- 전체 Python non-live: `632 passed, 1 skipped, 10 deselected`.
- repository 전체 TypeScript typecheck/build, Python compile, pip check: 통과.
- GCP deployment validator: `GCP deployment inputs: valid`.
- 실제 GCP resource/IAM/OAuth 설정 또는 배포 명령은 실행하지 않았다.
