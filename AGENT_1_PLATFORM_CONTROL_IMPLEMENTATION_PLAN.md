# Agent 1 — Platform & Control Plane 구현 현황 및 추적

## 0. 현재 상태

| 항목 | 상태 |
|---|---|
| 현재 완료 Phase | Phase 0 — 기준점 보호와 개발 게이트 확정 |
| 다음 개발 Phase | Phase 1 — 공통 Domain 기반과 불변식 |
| 전체 진행률 | 1/14 Phase 완료 |
| 기준 Python | CPython 3.14.7 |
| 기준 Branch | `platform-control` |
| 마지막 업데이트 | 2026-08-16 |

Git commit과 push 권한은 프로젝트 소유자에게만 있다. Agent 1은 커밋과 push를 실행하지 않고, 매 개발 요청 종료 시 제안 커밋 메시지만 제공한다.

## 1. 문서 목적

이 문서는 현재 `platform-control` 브랜치의 초기 skeleton을 기준으로 Agent 1이 Platform & Control Plane을 구현할 순서, 산출물, 검증 게이트와 통합 경계를 정의하고 실제 구현 상태를 계속 기록하는 추적 문서다. 각 개발 요청이 끝날 때 해당 Phase 상태, 완료/미구현 항목, 검증 결과와 추가 검토 사항을 갱신한다.

상위 규약은 `CODING_AGENT_MASTER_SPEC.md`이고, 세부 구현 기준은 `CODING_AGENT_SPEC_1_PLATFORM_CONTROL.md`이다. 두 문서가 충돌하면 Master Spec을 우선한다.

## 2. 확인한 자료와 현재 저장소 상태

### 2.1 검토 완료 문서

- `IP_RISK_AGENT_MEETING_BLUEPRINT.md`
- `CODING_AGENT_MASTER_SPEC.md`
- `CODING_AGENT_SPEC_1_PLATFORM_CONTROL.md`
- `CODING_AGENT_SPEC_2_SOURCE_DESKTOP.md`
- `CODING_AGENT_SPEC_3_RISK_INTELLIGENCE_RAG.md`
- `ENVIRONMENT_SETUP.md`
- `README.md`

### 2.2 현재 구조 요약

- Backend는 `backend/src/ip_risk_agent` 아래에 Control, Source, Intelligence, Integration namespace만 생성된 상태다.
- Agent 1 소유 Backend 영역인 `core`, `application`, `persistence/core_firestore`, Control 전용 `api`는 모두 빈 package skeleton이다.
- Frontend는 `frontend/src` 아래 Agent 1/2 소유 디렉토리만 있고, 현재 코드는 Frozen TypeScript Contract import 검증뿐이다. React/Vite 제품 UI는 아직 없다.
- `tests/control`은 비어 있다.
- `shared/contracts/**`에는 Pydantic Contract v1, JSON Schema, 생성 TypeScript 타입, fixture, frozen test가 존재한다.
- `main.py`, `worker.py`, `composition/**`는 Integration 전용 placeholder다.
- Root Python dependency는 현재 Pydantic과 pytest뿐이고, Frontend dependency는 TypeScript와 `@iprisk/contracts`뿐이다.
- 현재 브랜치는 `platform-control`이며 `origin/platform-control`을 추적한다.

### 2.3 확정된 개발 기준점과 보호 항목

1. 현재 작업 트리에는 다음 Frozen 생성 파일의 선행 변경이 존재한다.
   - `shared/contracts/schemas/*.json` 4개
   - `shared/contracts/typescript/generated/contracts.ts`
2. Agent 1은 이 변경을 수정·복원·재생성·커밋하지 않으며 모든 Agent 1 변경에서 제외한다.
3. 버전 관리는 README를 우선하며 Python은 CPython 3.14.7로 확정했다. `.venv\Scripts\python.exe`가 3.14.7임을 검증했다.
4. 현재 환경에는 Windows `py` launcher가 없으므로 Python 명령은 `.venv\Scripts\python.exe`를 직접 사용한다.
5. Frozen contract test는 생성 파일을 다시 쓰는 테스트를 포함하므로 선행 변경 처리 전에는 schema/TypeScript generation test를 실행하지 않는다.
6. Windows에서 pytest가 pnpm을 subprocess로 실행할 때 `PNPM_EXECUTABLE`은 `pnpm.ps1`이 아닌 `pnpm.cmd`의 절대 경로로 지정한다.

### 2.4 Phase 현황

| Phase | 내용 | 상태 |
|---|---|---|
| 0 | 기준점 보호와 개발 게이트 확정 | 완료 |
| 1 | 공통 Domain 기반과 불변식 | 미구현 |
| 2 | 인증, Role/Permission, VWS와 Mount 권한 | 미구현 |
| 3 | Repository protocol과 In-memory transaction | 미구현 |
| 4 | Firestore canonical persistence | 미구현 |
| 5 | SourceChange intake와 AnalysisJob orchestration | 미구현 |
| 6 | Security Gate | 미구현 |
| 7 | AnalysisResult intake와 Risk reconciliation | 미구현 |
| 8 | Human review, History, Audit, Notification | 미구현 |
| 9 | Google App Login과 Control API | 미구현 |
| 10 | ControlPlaneFacade와 Integration surface | 미구현 |
| 11 | Product Web UI | 미구현 |
| 12 | 관측성, 보안 hardening과 전체 검증 | 미구현 |
| 13 | 인계 문서와 통합 준비 | 미구현 |

## 3. Agent 1의 구현 범위와 절대 경계

### 3.1 구현 범위

- Google OIDC 기반 App authentication과 안전한 application session
- RiskWorkspace, Membership, Role/Permission과 Mount application metadata
- Artifact, ArtifactState, ChangeEvent, AnalysisJob canonical state
- SourceChange의 idempotent intake와 queue-enqueue port
- VWS `.ipriskignore`, secret redaction, data minimization을 포함한 유일한 Security Gate
- 승인된 `AnalysisArtifact` 생성
- `AnalysisResult` 검증과 Risk/RiskEvidence/RiskEvent transactional reconciliation
- Machine lifecycle과 Human review disposition의 독립 관리
- Firestore canonical repositories
- AuditEvent, SourceAccessEvent, in-app Notification
- Control Plane public facade와 Control 소유 API
- App shell, VWS, Risk, History, Security & Data Access 중심 Web UI
- `tests/control/**`, Agent 1 dependency request, `AGENT_DELIVERY.md`

### 3.2 수정 가능한 영역

```text
backend/src/ip_risk_agent/core/**
backend/src/ip_risk_agent/application/**
backend/src/ip_risk_agent/persistence/core_firestore/**
backend/src/ip_risk_agent/api/{auth,workspaces,risks,history,security,notifications}/**
frontend/src/{app,auth,workspace,risk,history,security,shared}/**
tests/control/**
agent-deliverables/agent-1-dependencies.md
AGENT_DELIVERY.md
contract-change-requests/agent1-*.md  # 정말 필요한 경우에만
```

### 3.3 수정·구현 금지 영역

- `shared/contracts/**`
- `connectors/**`, `frontend/src/sources/**`, `apps/desktop/**`
- `intelligence/**`, `rag-corpus/**`
- `composition/**`, `main.py`, `worker.py`
- `deploy/**`, root manifest/lockfile/CI 설정
- `tests/connectors/**`, `tests/intelligence/**`, `tests/integration/**`, `tests/e2e/**`
- Drive/GitHub/provider credential 처리, Local filesystem 접근
- Gemini/KIPRIS/RAG/SPDX 호출 또는 Analyzer 내부 알고리즘
- Raw source proxy/viewer endpoint

## 4. 목표 내부 구조

구현 시 각 package는 외부 SDK보다 domain/application 방향으로 의존하게 한다.

```text
api / public_facade
        ↓
application use cases
        ↓
core domain + repository/port protocols
        ↑
persistence/core_firestore + external adapters supplied by Integration
```

핵심 원칙은 다음과 같다.

- Domain은 FastAPI, Firestore, Google SDK 타입을 알지 않는다.
- Application은 Frozen Contract와 Agent 1 내부 protocol에만 의존한다.
- Firestore 구현은 repository protocol을 구현하며 business rule을 소유하지 않는다.
- API는 use case 호출, 인증/인가, safe DTO 변환만 담당한다.
- 다른 Plane은 Agent 1 내부 repository를 import하지 않고 Integration이 `ControlPlaneFacade`를 통해 연결한다.
- 시간, ID, hashing, queueing은 테스트 가능한 port로 주입한다.

## 5. 단계별 구현 계획

### Phase 0 — 기준점 보호와 개발 게이트 확정 `[완료]`

1. [x] 선행 dirty Frozen 파일을 기록하고 Agent 1 diff에서 제외했다.
2. [x] README를 우선해 Python 3.14.7을 확정하고 `.venv` interpreter를 검증했다.
3. [x] 현재 dependency로 가능한 Python import/contract smoke check를 수행했다.
4. [x] FastAPI, Firestore, Google OIDC, React/Vite 및 테스트 dependency를 `agent-deliverables/agent-1-dependencies.md`에 기록했다. Root manifest는 수정하지 않았다.
5. [x] Control 테스트와 안전한 shared contract test 명령을 확정했다.

완료 조건:

- [x] 개발 중 건드리면 안 되는 선행 변경 목록이 명확하다.
- [x] 사용할 Python 버전과 Agent 1 test command가 확정됐다.
- [x] Root 변경 없이 필요한 dependency 목록과 환경 변수가 문서화됐다.

검증 결과:

- Python 3.14.7, Pydantic 2.13.4, pytest 9.1.1 import smoke: 통과
- Frozen Contract tests(생성 결정성 test 제외): 26 passed, 1 deselected
- `pnpm run typecheck`: 통과
- `pnpm run verify:resolution`: 통과
- 첫 pytest 시도에서 `pnpm.ps1` subprocess 실행 문제로 2건 실패했으나 `pnpm.cmd`를 지정한 재실행에서 모두 통과
- 생성 결정성 test 1건은 선행 Frozen 파일 보호를 위해 의도적으로 보류

확정 명령:

```powershell
# Agent 1 전용 테스트
.\.venv\Scripts\python.exe -m pytest tests/control

# Frozen 생성물을 쓰지 않는 shared contract 검증
$env:PNPM_EXECUTABLE = (Get-Command pnpm.cmd).Source
.\.venv\Scripts\python.exe -m pytest shared/contracts/tests/test_contracts.py -k "not schema_and_typescript_generation_is_deterministic"

# TypeScript 읽기 전용 검증
pnpm run typecheck
pnpm run verify:resolution
```

### Phase 1 — 공통 Domain 기반과 불변식

1. Agent 1 내부 공통 ID, UTC timestamp, status, safe error/value type을 정의한다.
2. User, RiskWorkspace, Membership, SourceConnection metadata, SourceWorkspace metadata, WorkspaceMount를 dataclass/Pydantic 내부 model로 정의한다.
3. Artifact, ArtifactState, ChangeEvent, AnalysisJob을 정의한다.
4. Risk, RiskEvidence, RiskEvent, AuditEvent, SourceAccessEvent, Notification을 정의한다.
5. Machine lifecycle(`NEW`, `EXISTING`, `RESOLVED`)과 review disposition(`UNREVIEWED`, `MONITORING`, `ACCEPTED_RISK`, `EXCLUDED`)을 별도 타입과 transition 함수로 분리한다.
6. 정규화·결정론적 ID 함수에 명확한 canonical input encoding과 hash version을 둔다.

핵심 불변식:

- User identity key는 email이 아니라 Google `sub`이다.
- VWS는 collaboration/security/risk boundary다.
- SourceWorkspace 하나는 MVP에서 VWS 하나에만 Mount된다.
- Mount alias는 VWS 안에서 unique지만 Artifact/Risk identity에는 들어가지 않는다.
- Artifact mapping은 `(source_workspace_id, source_artifact_id)`에 대해 안정적이다.
- DELETE는 Artifact availability만 바꾸며 Risk를 resolve하지 않는다.
- 과거 RiskEvent는 update/overwrite할 수 없다.

완료 조건:

- 외부 SDK 없이 pure unit test로 모든 entity와 transition invariant를 검증한다.

### Phase 2 — 인증, Role/Permission, VWS와 Mount 권한

1. `OWNER`, `SOURCE_MANAGER`, `RISK_REVIEWER`, `VIEWER`를 permission set으로 매핑한다.
2. `authorize_vws_action` service를 만들고 인증, membership status, permission, resource ownership을 순서대로 검증한다.
3. Workspace 생성 시 Owner membership을 원자적으로 생성하는 use case를 구현한다.
4. 멤버 초대, role 변경, 제거, ownership transfer와 workspace 삭제 guard를 구현한다.
5. Source Manager의 own-mount 관리 규칙과 Owner의 administrative disable/remove 권한을 분리한다.
6. Provider credential authority를 VWS role로 추론하지 않고, credential 필요 작업에는 Source Plane의 별도 authority 확인이 필요하다는 decision/context를 반환한다.
7. 제거된 Source Manager의 Mount를 `MANAGER_ACTION_REQUIRED` 등 non-active 상태로 전환하고 AuditEvent와 Owner notification을 생성한다.

완료 조건:

- Role matrix, own-mount 제한, Owner의 provider credential impersonation 금지가 unit test로 고정된다.

### Phase 3 — Repository protocol과 In-memory transaction 기반

1. User, Workspace, Membership, Mount, Artifact, ChangeEvent, AnalysisJob, Risk, Audit, SourceAccess, Notification repository protocol을 정의한다.
2. 여러 aggregate를 원자적으로 바꾸기 위한 Unit of Work/transaction protocol을 정의한다.
3. 아래 deterministic uniqueness strategy를 protocol 수준에서 명시한다.
   - Membership: `(vws_id, user_id)`
   - ChangeEvent: `event_fingerprint`
   - Artifact: `(source_workspace_id, source_artifact_id)`
   - Risk: stable `risk_key`
   - VWS Mount alias: `(vws_id, normalized_alias)`
4. In-memory repository와 transaction fake를 구현해 이후 모든 application test의 기본 저장소로 사용한다.
5. append-only event repository는 update/delete API 자체를 노출하지 않는다.

완료 조건:

- Firestore 없이 Agent 1 전체 use case를 실행할 기반이 마련된다.
- duplicate/concurrency 조건을 재현하는 unit test helper가 존재한다.

### Phase 4 — Firestore canonical persistence

1. 명세의 16개 canonical collection만 사용해 Firestore document mapper와 repository를 구현한다.
2. Domain model과 Firestore document dict 사이의 명시적 mapper를 두고 SDK 타입이 core/application으로 새지 않게 한다.
3. deterministic document ID 또는 transaction lookup으로 uniqueness를 보장한다.
4. 다음 원자 연산을 구현한다.
   - Workspace + Owner membership 생성
   - Source Manager 제거 + Mount 상태 + Audit + Notification
   - ChangeEvent idempotent insert + Artifact upsert
   - Risk projection + Evidence + append-only RiskEvent reconciliation
   - optimistic review update + review event
5. Firestore emulator를 사용할 수 있는 test fixture를 만들되 실제 production credential을 요구하지 않는다.
6. 필요한 composite index 목록은 delivery 문서에 wiring/deploy 요청으로 기록한다.

완료 조건:

- In-memory와 Firestore repository가 같은 contract test suite를 통과한다.
- SDK 없이 domain test, emulator로 persistence test를 독립 실행할 수 있다.

### Phase 5 — SourceChange intake와 AnalysisJob orchestration

1. `register_source_change(SourceChange)`를 구현한다.
2. `risk_workspace_id`, `mount_id`, `source_workspace_id`, `source_type` 관계와 Mount 처리 가능 상태를 검증한다.
3. `event_fingerprint`로 idempotent ChangeEvent를 생성하고 중복 DONE 이벤트는 harmless ACK한다.
4. SourceArtifactRef를 stable Artifact에 resolve/upsert한다.
5. CREATE/UPDATE/MOVE/DELETE semantics를 적용하며 MOVE continuity에는 `previous_artifact`를 사용한다.
6. DELETE에서 Artifact availability만 바꾸고 Risk reconciliation은 호출하지 않는다.
7. 분석 가능한 변경에는 AnalysisJob/queue record를 만들고, queue port에는 `change_event_id`만 전달한다.
8. claim/start/finish/fail transition을 retry-safe compare-and-set으로 구현한다.
9. Cloud Tasks SDK는 직접 wiring하지 않고 `TaskEnqueuer` protocol과 fake를 제공한다.

완료 조건:

- 동일 SourceChange의 반복 및 동시 수신이 ChangeEvent, Job, Risk를 중복 생성하지 않는다.
- queue payload에 raw source나 provider credential이 없다.

### Phase 6 — Security Gate

1. `build_analysis_artifact(snapshot, job_id)`의 단일 진입점을 만든다.
2. canonical Mount/SourceWorkspace/Artifact/Job과 Snapshot 식별자·revision을 교차 검증한다.
3. logical path를 mount alias 기준으로 정규화하고 traversal/잘못된 scope metadata를 거부한다.
4. VWS global `.ipriskignore` parser를 구현한다.
   - deny-only
   - `*`, `**`, `?`
   - negation `!` 미지원 또는 명시적 validation error
   - source-level deny가 전달되면 VWS allow보다 항상 우선
5. artifact kind, MIME/type, content scope, byte-size policy를 적용한다.
6. deterministic secret filter를 구현한다.
   - PEM private key block
   - `.env` 형태 credential line
   - common secret/token assignment
   - bearer/token-like value
   - 고정 placeholder와 정확한 `redaction_count`
7. artifact kind별 deterministic minimization을 적용한다.
   - MANIFEST/LOCKFILE: size 한도 내 full 가능
   - SOURCE_CODE: changed/context 우선
   - DOCUMENT_TEXT/TEXT: threshold와 segment cap 적용
8. static analyzer eligibility matrix로 PATENT/LICENSE 요청 목록을 계산한다.
9. redaction/minimization 이후 canonical serialization을 hash하여 `analysis_input_checksum`을 만든다.
10. 모든 gate를 통과한 경우에만 `security_context.approved=true`인 Frozen `AnalysisArtifact`를 생성한다.
11. fetch가 이미 발생했다는 사실은 allow/deny와 무관하게 SourceAccessReceipt에서 idempotent SourceAccessEvent로 기록한다.
12. SourceSnapshot 또는 원문 segment를 repository, event, error, structured log에 보관하지 않는다.

완료 조건:

- deny-wins, redaction, minimization, checksum, approved-only 생성이 pure test로 검증된다.
- ignored/unsupported/oversized 입력에서 Analyzer로 전달 가능한 artifact가 생성되지 않는다.
- Snapshot 전체를 저장하는 persistence API가 존재하지 않는다.

### Phase 7 — AnalysisResult intake와 Risk reconciliation

1. `accept_analysis_result(AnalysisResult)`를 구현한다.
2. Job 존재 여부, artifact ID, revision, requested analysis type을 검증한다.
3. AnalysisResult의 status/coverage/provider failure/version summary를 AnalysisJob에 반영한다. 별도 임의 canonical collection은 추가하지 않는다.
4. Evidence를 minimal retention policy로 정규화하고 excerpt 길이, safe metadata와 reference를 제한한다.
5. Patent와 License candidate의 stable risk key를 결정론적으로 생성한다.
6. `SUCCEEDED + COMPLETE`일 때만 active risk set과 candidate set을 transaction 안에서 reconcile한다.
   - 교집합: `EXISTING`, evidence/last_seen 갱신
   - 신규: `NEW`, DETECTED event
   - 사라짐: `RESOLVED`, RESOLVED event
   - 과거 RESOLVED 재등장: active `EXISTING`, REOPENED event
7. FAILED, INCONCLUSIVE, SKIPPED, PARTIAL, NONE은 old-only resolution을 절대 실행하지 않는다.
8. duplicate AnalysisResult acceptance가 evidence/event를 중복 추가하지 않도록 result identity/idempotency를 둔다.
9. multi-analyzer Job aggregate 상태를 각 analysis type 결과와 독립적으로 계산한다.
10. high/reopened/failure 조건에 Notification과 필요한 AuditEvent를 생성한다.

완료 조건:

- zero-candidate complete success만 기존 Risk를 resolve할 수 있다.
- provider failure와 incomplete coverage가 기존 Risk를 보존한다.
- alias rename, DELETE, review disposition이 machine Risk identity/lifecycle을 오염시키지 않는다.

### Phase 8 — Human review, History, Audit, Notification

1. review disposition 변경 use case에 optimistic version check를 적용한다.
2. actor, 이전/신규 disposition, optional comment, timestamp를 append-only RiskEvent로 남긴다.
3. Risk timeline query와 Workspace activity projection을 구현한다.
4. VWS 운영/보안 사건은 AuditEvent, source read는 SourceAccessEvent, Risk 변화는 RiskEvent로 분리한다.
5. Notification list/read 상태와 대상 사용자 filtering을 구현한다.
6. audit export는 raw source/token 없이 safe field만 직렬화한다.

완료 조건:

- `EXCLUDED != RESOLVED`와 과거 event 불변성이 API까지 유지된다.
- 세 history stream 어디에도 raw source, local absolute path, token이 없다.

### Phase 9 — Google App Login과 Control API

1. Google OIDC discovery/authorization-code flow를 provider adapter 뒤에 구현한다.
2. state/nonce/redirect 검증 후 `google_subject` 기준 User upsert와 last-login update를 수행한다.
3. Drive OAuth credential과 섞이지 않는 application session을 만든다.
4. secure, HTTP-only, SameSite cookie와 logout/session revocation 정책을 적용한다.
5. 공통 authentication/authorization dependency와 safe API error model을 만든다.
6. 아래 Control API를 feature별 router factory로 구현한다.
   - `/api/v1/auth/**`
   - `/api/v1/workspaces/**` 및 members
   - Workspace별 Mount metadata read/admin
   - Workspace별 risks/review/timeline
   - activity/audit/source-access
   - security/ipriskignore/data-access-summary
   - `/api/v1/notifications/**`
7. request/response Pydantic DTO는 `extra="forbid"`를 사용하고 domain/entity를 그대로 노출하지 않는다.
8. raw source endpoint를 만들지 않으며 Open Original은 Integration이 Source Plane locator action을 연결할 수 있는 opaque action boundary만 제공한다.
9. router를 `main.py`에 직접 등록하지 않고 Integration이 사용할 factory/export를 제공한다.

완료 조건:

- 모든 VWS route가 authenticated user → membership → permission 순서로 검사된다.
- raw provider error, token, internal stack이 API 응답에 노출되지 않는다.

### Phase 10 — ControlPlaneFacade와 Integration surface

1. `application/public_facade`에 최소 다음 기능을 안정된 public surface로 제공한다.
   - `authorize_vws_action`
   - `register_source_change`
   - `register_source_access`
   - `build_analysis_artifact`
   - `accept_analysis_result`
   - `get_mount_ref`
   - `get_source_workspace_context`
2. facade constructor가 repository Unit of Work, queue port, clock/ID factory와 config를 명시적으로 받게 한다.
3. Agent 2 source router가 사용할 authorization callback과 canonical metadata creation callback을 정의하되 Agent 2 내부 타입을 import하지 않는다.
4. Integration용 예제는 fake ports 기반으로 작성하고 production wiring은 `composition/**`에 남긴다.

완료 조건:

- Integration이 Agent 1 내부 service/repository를 직접 import하지 않고 전체 pipeline을 연결할 수 있다.

### Phase 11 — Product Web UI

1. Root dependency 변경 없이 필요한 React/Vite dependency를 먼저 dependency request에 확정한다.
2. `frontend/src/shared`에 접근성 있는 최소 design primitive, API client, session/workspace context, loading/error/empty state를 만든다.
3. `frontend/src/app`에 Web/Electron 공용 app shell, routing, auth guard, VWS navigation과 Agent 2 Source UI 삽입 slot을 만든다.
4. 다음 화면을 구현한다.
   - Login
   - Workspace list/create
   - VWS dashboard
   - Members/roles
   - Risk list/filter
   - Risk detail/review
   - Risk timeline
   - Workspace activity/audit
   - Security & Data Access
   - Notifications
5. Dashboard 수치는 canonical Risk/AnalysisJob state 기반 API만 사용한다.
6. Security & Data Access 화면에서 연결 범위, 실제 SourceAccessEvent, retention, `.ipriskignore`, source health를 구분해 보여준다.
7. Raw source preview를 만들지 않고 provider/desktop별 Open Original action만 렌더링한다.
8. role에 따라 action을 숨기거나 비활성화하되 Backend authorization을 최종 방어선으로 유지한다.

완료 조건:

- Agent 2의 `frontend/src/sources/**`를 수정하지 않고 public component/route slot으로 통합 가능하다.
- Web과 Electron renderer에서 공유 가능한 browser-safe UI다.

### Phase 12 — 관측성, 보안 hardening과 전체 검증

1. request/event/job/workspace/mount/artifact correlation ID를 가진 structured logging helper를 적용한다.
2. source content, Evidence 전체, token, local absolute path, full prompt/model output을 logging deny-list test로 검증한다.
3. safe error category와 internal diagnostic context를 분리한다.
4. concurrent SourceChange, job claim, review update, result acceptance를 stress test한다.
5. API permission matrix와 frontend route/action state를 교차 검증한다.
6. In-memory end-to-end control scenario를 실행한다.

```text
Fake SourceChange
 -> ChangeEvent / AnalysisJob
 -> Fake SourceSnapshot
 -> Security Gate
 -> approved AnalysisArtifact
 -> Fake AnalysisResult
 -> Risk / Evidence / RiskEvent
 -> API/UI query and review
```

7. 확정된 환경에서 shared contract tests, `tests/control/**`, Python compile, frontend typecheck/build를 실행한다.
8. 실패한 외부 service는 empty success로 변환되지 않는지 최종 검토한다.

완료 조건:

- Agent 1 acceptance criteria와 아래 추적 표가 모두 충족된다.
- 다른 Plane 구현 없이 fake ports로 Control flow가 완결된다.

### Phase 13 — 인계 문서와 통합 준비

1. `AGENT_DELIVERY.md`를 작성한다.
2. `agent-deliverables/agent-1-dependencies.md`를 최종 갱신한다.
3. 아래 wiring point를 실제 import path와 signature로 문서화한다.
   - `ControlPlaneFacade`
   - repository/Unit of Work constructor
   - SecurityGate constructor/config
   - queue port
   - authz/source metadata callbacks
   - Control router factory
   - frontend exports/source UI slot
   - Open Original callback
   - 환경 변수와 Firestore index
4. Frozen Contract가 부족한 경우에만 `contract-change-requests/agent1-XXX.md`를 작성하며 shared 파일은 수정하지 않는다.
5. 알려진 제약, 미지원 기능, emulator/production 차이와 실제 test 결과를 기록한다.

완료 조건:

- Integration Agent가 내부 재작성 없이 public surface를 조립할 수 있다.

## 6. 필수 테스트 추적표

| 영역 | 반드시 고정할 동작 |
|---|---|
| Auth | Google `sub` 기반 upsert, state/nonce/session 보안 |
| RBAC | 4개 Role permission matrix, membership status |
| Mount | own-mount 제한, alias unique, alias 변경 시 identity 유지 |
| Authority | Owner도 타인의 provider credential을 사용할 수 없음 |
| Membership | Source Manager 제거 시 Mount 보존 및 action-required 전환 |
| Intake | duplicate SourceChange idempotency, stable Artifact mapping |
| Change | MOVE continuity, DELETE가 Risk를 resolve하지 않음 |
| Jobs | retry-safe claim/state transition, raw-free queue payload |
| Security | `.ipriskignore` deny wins, type/size deny, secret redaction |
| Retention | SourceSnapshot 비영속, minimal Evidence excerpt |
| Artifact | 승인된 AnalysisArtifact만 생성, deterministic checksum |
| Reconcile | FAILED/INCONCLUSIVE/PARTIAL/NONE에서 Risk 보존 |
| Reconcile | SUCCEEDED+COMPLETE zero candidate에서만 old Risk resolve |
| Reconcile | stable key, reappearance/reopen, duplicate result safety |
| Review | Human EXCLUDED와 machine RESOLVED 분리 |
| History | RiskEvent append-only와 transaction atomicity |
| Access | SourceAccessReceipt → content-free SourceAccessEvent |
| Persistence | deterministic IDs, concurrent update, emulator parity |
| API | authn/authz/error sanitization, raw source route 부재 |
| UI | Dashboard/Risk/History/Security/Notification 및 role gating |

## 7. 예상 dependency 및 환경 요청

정확한 버전은 Integration Owner가 root manifest에 병합한다. Agent 1은 root 파일을 직접 수정하지 않는다.

### Python runtime 후보

- FastAPI/Starlette: Control API와 cookie/session middleware
- Uvicorn: local/API runtime
- Google Cloud Firestore client: production repository
- Google OIDC/OAuth client(Authlib 또는 동등한 검증 가능한 library)
- HTTP client(httpx 등): OIDC discovery/token/userinfo

### Python test 후보

- `pytest-asyncio`
- FastAPI/httpx test support
- Firestore emulator support 또는 emulator fixture

### Frontend runtime/dev 후보

- React, React DOM
- React Router
- Vite와 React plugin
- UI test framework(Vitest, Testing Library, jsdom)

### Agent 1 환경 변수

```text
GOOGLE_LOGIN_CLIENT_ID
GOOGLE_LOGIN_CLIENT_SECRET
GOOGLE_LOGIN_REDIRECT_URI
SESSION_SECRET
APP_PUBLIC_BASE_URL
GCP_PROJECT_ID
FIRESTORE_DATABASE
```

추가 config는 secret이 아닌 Security Gate threshold, evidence excerpt limit, session TTL 등의 typed application config로 두고 전역 상수로 hardcode하지 않는다.

## 8. 완료 정의

Agent 1 개발은 다음 조건을 모두 만족할 때 완료한다.

1. Control Plane의 domain, persistence, orchestration, security, lifecycle, API와 Web UI가 Agent 1 소유 범위 안에서 구현되어 있다.
2. Security Gate만 `SourceSnapshot -> AnalysisArtifact`를 수행하며 승인되지 않은 데이터가 Intelligence boundary를 넘지 않는다.
3. Source/Analyzer 실패가 빈 성공이나 Risk 해소로 오해되지 않는다.
4. Raw source와 credential을 proxy, 장기 저장 또는 logging하지 않는다.
5. Frozen Contract와 타 Agent/Integration 전용 파일을 수정하지 않는다.
6. fake ports로 독립 Control scenario가 완결되고 `tests/control/**`의 모든 invariant test가 통과한다.
7. Firestore production repository와 emulator 검증 경로가 존재한다.
8. Integration Agent가 사용할 facade/router/frontend wiring point와 dependency가 인계 문서에 명확히 기록되어 있다.
