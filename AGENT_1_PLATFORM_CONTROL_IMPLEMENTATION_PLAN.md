# Agent 1 — Platform & Control Plane 구현 현황 및 추적

## 0. 현재 상태

| 항목 | 상태 |
|---|---|
| 현재 완료 Phase | Phase 8 — Human review, History, Audit, Notification |
| 다음 개발 Phase | Phase 9 — Google App Login과 Control API |
| 전체 진행률 | 9/14 Phase 완료 |
| 기준 Python | CPython 3.14.7 |
| 기준 Branch | `platform-control` |
| 마지막 업데이트 | 2026-08-16 |

Git commit과 push 권한은 프로젝트 소유자에게만 있다. Agent 1은 커밋과 push를 실행하지 않고, 매 개발 요청 종료 시 제안 커밋 메시지만 제공한다.

중대한 문제 사항이 아닌 추가 검토 항목은 Agent 1이 자체 검사와 독자적 판단으로 처리하고 구현·테스트·현황 문서에 기록한다. 개발자가 이후 Phase 지시와 함께 수정 방향을 전달하면 해당 결정을 재검토한다.

이전 Phase에서 후속 Phase 범위라는 이유로 보류한 항목은 별도 지시를 기다리지 않고 해당 Phase 개발 시 자동으로 작업 범위에 포함해 보완·완료한다. 해결 여부와 남은 경계는 최신 작업 현황 로그에 명시한다.

한 번 독자 판단해 추가 검토 목록에 기록한 결정도 후속 Phase의 새 정보와 구현 경계에 비추어 가볍게 재검토한다. 기존보다 합리적이고 범위 내에서 안전한 방안을 발견하면 해당 Phase에서 함께 개선하고 변경 근거를 기록한다.

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

- Backend는 `backend/src/ip_risk_agent` 아래에 Control, Source, Intelligence, Integration namespace가 분리되어 있다.
- Agent 1의 `core`에는 Phase 1~2 Domain 모델, identity, lifecycle과 authorization/mutation plan이 구현됐다.
- `application/repositories`에는 async repository/UoW contract와 transactional in-memory 구현이 있고, `application/workspace_admin`에는 Phase 2 plan의 원자적 적용 service가 구현됐다.
- `application/process_change`와 `application/analysis_jobs`에는 SourceChange 관계 검증, idempotent Artifact/ChangeEvent/AnalysisJob 저장, raw-free queue port와 retry-safe job orchestration이 구현됐다.
- `application/security_gate`에는 canonical context 검증, deny-only `.ipriskignore`, file/size policy, secret redaction, deterministic minimization/routing/checksum과 SourceAccess 기록이 구현됐다.
- `application/risk_reconcile`에는 AnalysisResult canonical context 검증, per-analysis-type outcome 수용, minimal evidence retention, authoritative Risk set reconciliation과 결과 기반 Audit/Notification 기록이 구현됐다.
- `application/risk_review`, `application/history`, `application/notifications`에는 versioned human review, 세 canonical history stream의 권한 기반 safe projection/export, 사용자별 in-app inbox와 idempotent read 처리가 구현됐다.
- `persistence/core_firestore`에는 canonical schema, strict document mapper, deterministic unique sentinel, production Google async backend와 Firestore UoW/repository가 구현됐다. API 영역은 아직 skeleton이다.
- Frontend는 `frontend/src` 아래 Agent 1/2 소유 디렉토리만 있고, 현재 코드는 Frozen TypeScript Contract import 검증뿐이다. React/Vite 제품 UI는 아직 없다.
- `tests/control`에는 Phase 1~8 Domain, policy, repository transaction, Firestore persistence와 Control application orchestration test 159개가 구현됐으며 현재 환경에서는 158개 통과, emulator test 1개가 환경 미설정으로 skip된다.
- `shared/contracts/**`에는 Pydantic Contract v1, JSON Schema, 생성 TypeScript 타입, fixture, frozen test가 존재한다.
- `main.py`, `worker.py`, `composition/**`는 Integration 전용 placeholder다.
- Root Python dependency는 현재 Pydantic과 pytest뿐이고, Frontend dependency는 TypeScript와 `@iprisk/contracts`뿐이다.
- 현재 브랜치는 `platform-control`이며 `origin/platform-control`을 추적한다.

### 2.3 확정된 개발 기준점과 보호 항목

1. `shared/contracts/schemas/*.json`과 `shared/contracts/typescript/generated/contracts.ts`는 `scripts/generate_contracts.py` 또는 `pnpm run generate`로 재생성할 수 있다.
2. Pydantic Contract source 변경이 없는 검증에서는 공식 생성 후 tracked diff가 없어야 한다. 생성 파일의 수동 편집은 금지한다.
3. 버전 관리는 README를 우선하며 Python은 CPython 3.14.7로 확정했다. `.venv\Scripts\python.exe`가 3.14.7임을 검증했다.
4. 현재 환경에는 Windows `py` launcher가 없으므로 Python 명령은 `.venv\Scripts\python.exe`를 직접 사용한다.
5. Frozen contract 결정성 test를 포함한 전체 suite를 실행하며, 실행 후 생성 파일 diff가 0인지 확인한다.
6. Windows에서 pytest가 pnpm을 subprocess로 실행할 때 `PNPM_EXECUTABLE`은 `pnpm.ps1`이 아닌 `pnpm.cmd`의 절대 경로로 지정한다.

### 2.4 Phase 현황

| Phase | 내용 | 상태 |
|---|---|---|
| 0 | 기준점 보호와 개발 게이트 확정 | 완료 |
| 1 | 공통 Domain 기반과 불변식 | 완료 |
| 2 | 인증, Role/Permission, VWS와 Mount 권한 | 완료 |
| 3 | Repository protocol과 In-memory transaction | 완료 |
| 4 | Firestore canonical persistence | 완료 |
| 5 | SourceChange intake와 AnalysisJob orchestration | 완료 |
| 6 | Security Gate | 완료 |
| 7 | AnalysisResult intake와 Risk reconciliation | 완료 |
| 8 | Human review, History, Audit, Notification | 완료 |
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

- `shared/contracts/**`의 Pydantic source/fixture/test 수동 변경 및 생성 파일 수동 편집. 공식 생성 스크립트에 의한 generated schema/TypeScript 쓰기는 허용한다.
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

1. [x] Frozen 생성 파일을 공식 script로 재생성하고 source-of-truth와 일치시켰다.
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
- Frozen Contract tests(생성 결정성 test 포함): 27 passed
- `pnpm run typecheck`: 통과
- `pnpm run verify:resolution`: 통과
- 첫 pytest 시도에서 `pnpm.ps1` subprocess 실행 문제로 2건 실패했으나 `pnpm.cmd`를 지정한 재실행에서 모두 통과
- 공식 생성 직후 및 결정성 test 이후 generated tracked diff: 0

확정 명령:

```powershell
# Agent 1 전용 테스트
.\.venv\Scripts\python.exe -m pytest tests/control

# Frozen 생성 및 전체 shared contract 검증
pnpm run generate
$env:PNPM_EXECUTABLE = (Get-Command pnpm.cmd).Source
.\.venv\Scripts\python.exe -m pytest shared/contracts/tests/test_contracts.py

# TypeScript 읽기 전용 검증
pnpm run typecheck
pnpm run verify:resolution
```

### Phase 1 — 공통 Domain 기반과 불변식 `[완료]`

1. [x] Agent 1 내부 공통 ID, UTC timestamp, status, domain error와 JSON-safe immutable value 처리를 정의했다.
2. [x] User, RiskWorkspace, Membership, SourceConnection metadata, SourceWorkspace metadata, WorkspaceMount를 frozen dataclass로 정의했다.
3. [x] Artifact, ArtifactState, ChangeEvent, AnalysisJob을 정의했다.
4. [x] Risk, RiskEvidence, RiskEvent, AuditEvent, SourceAccessEvent, Notification을 정의했다.
5. [x] Machine lifecycle(`NEW`, `EXISTING`, `RESOLVED`)과 review disposition(`UNREVIEWED`, `MONITORING`, `ACCEPTED_RISK`, `EXCLUDED`)을 별도 타입과 순수 transition 함수로 분리했다.
6. [x] JSON canonical component encoding + SHA-256 + `v1` namespace 기반 결정론적 ID 함수를 구현했다.

핵심 불변식:

- [x] User identity key model은 email과 Google `sub`를 분리한다. 실제 upsert use case는 Phase 2에서 구현한다.
- [x] VWS가 security/retention version과 Owner identity를 소유한다.
- [x] SourceWorkspace와 WorkspaceMount 관계를 분리했다. VWS 단일 Mount 정책의 repository 강제는 Phase 3에서 구현한다.
- [x] Mount alias는 presentation value이며 Artifact/Risk identity 함수의 입력에 포함되지 않는다.
- [x] Artifact ID는 `(source_workspace_id, source_artifact_id)`에 대해 안정적이다.
- [x] AnalysisResult가 `SUCCEEDED + COMPLETE`가 아니면 Risk 생성·변경·해소가 모두 차단된다.
- [x] RiskEvent와 nested safe state를 immutable value로 구성했다. Repository append-only API는 Phase 3에서 강제한다.

완료 조건:

- [x] 외부 SDK 없이 pure unit test로 Phase 1 entity와 transition invariant를 검증했다.

구현 파일군:

- `core/common.py`: UTC/시간 순서, domain error, stable key, JSON-safe recursive freeze
- `core/{auth,workspaces,memberships,mounts,artifacts,risk,audit,notifications}`: canonical domain models와 public exports
- `application/{process_change,analysis_jobs}/models.py`: ChangeEvent와 AnalysisJob state
- `tests/control/test_domain_models.py`: entity/value invariant
- `tests/control/test_identity.py`: deterministic/collision-safe identity
- `tests/control/test_risk_transitions.py`: authoritative analysis와 lifecycle/review 분리

검증 결과:

- Phase 1 Control tests: 32 passed
- Frozen Contract + Control tests: 59 passed
- Python compileall: 통과
- `pnpm run typecheck`: 통과
- `pnpm run verify:resolution`: 통과
- 전체 test 후 generated tracked diff: 0

### Phase 2 — 인증, Role/Permission, VWS와 Mount 권한 `[완료]`

1. [x] `OWNER`, `SOURCE_MANAGER`, `RISK_REVIEWER`, `VIEWER`를 permission set으로 매핑했다.
2. [x] `authorize_vws_action` service에서 membership, status, permission, VWS/Mount ownership을 순서대로 검증한다.
3. [x] Workspace + deterministic Owner membership + AuditEvent를 하나의 mutation plan으로 생성하고 Phase 3 Unit of Work가 원자적으로 적용한다.
4. [x] pending email invitation 생성/수락/취소, role 변경, 제거, ownership transfer와 workspace deletion guard를 구현했다.
5. [x] Source Manager own-mount rename/operation 권한과 Owner administrative disable/remove를 분리했다.
6. [x] Provider credential 필요 작업은 Control 허용 여부와 별도로 `provider_authority_required=true`를 반환하고 명시적 owner mismatch를 거부한다.
7. [x] Source Manager 제거 또는 하위 role 강등 시 Mount를 보존한 채 `MANAGER_ACTION_REQUIRED`로 전환하고 Owner notification/AuditEvent를 생성한다.

완료 조건:

- [x] Role matrix, own-mount 제한, Owner의 provider credential impersonation 금지가 unit test로 고정됐다.

구현 파일군:

- `core/memberships/authorization.py`: VWS action policy와 provider-authority separation
- `core/memberships/identity.py`: deterministic membership/invitation identity와 email normalization
- `core/memberships/models.py`: pending invitation lifecycle
- `core/workspaces/services.py`: workspace/member/invitation mutation plans
- `core/mounts/services.py`: rename/disable/remove mutation plans
- `tests/control/test_authorization.py`: Role/action/authority matrix
- `tests/control/test_workspace_policies.py`: workspace/member/invitation lifecycle
- `tests/control/test_mount_policies.py`: own-mount와 Owner administration

검증 결과:

- Phase 1~2 Control tests: 62 passed
- Frozen Contract + Control tests: 89 passed
- Python compileall: 통과
- `pnpm run typecheck`: 통과
- `pnpm run verify:resolution`: 통과
- 전체 test 후 generated tracked diff: 0

### Phase 3 — Repository protocol과 In-memory transaction 기반 `[완료]`

1. [x] User, Workspace, Membership, Source metadata, Mount, Artifact, ChangeEvent, AnalysisJob, Risk, Audit, SourceAccess, Notification async repository protocol을 정의했다.
2. [x] 여러 aggregate를 원자적으로 바꾸기 위한 `ControlUnitOfWork`와 factory protocol을 정의했다.
3. [x] 아래 deterministic uniqueness strategy를 in-memory transaction에서 강제했다.
   - Membership: `(vws_id, user_id)`
   - ChangeEvent: `event_fingerprint`
   - Artifact: `(source_workspace_id, source_artifact_id)`
   - Risk: stable `risk_key`
   - VWS Mount alias: `(vws_id, normalized_alias)`
4. [x] 격리 snapshot, 명시적 commit/rollback, store revision 기반 optimistic conflict를 제공하는 in-memory repository를 구현했다.
5. [x] AuditEvent, SourceAccessEvent, RiskEvent repository는 append/list만 제공하고 event update/delete API를 노출하지 않는다.
6. [x] Phase 2의 workspace/member/mount mutation plan을 transaction 안에서 적용하는 `WorkspaceAdministrationService`를 구현했다.
7. [x] Source Manager 강등/제거 시 대상 사용자의 Mount 전체를 transaction 내부에서 조회해 plan에 전달하도록 public application path를 고정했다.

완료 조건:

- [x] Firestore 없이 Agent 1 application use case를 실행할 persistence-neutral 기반이 마련됐다.
- [x] duplicate, rollback과 concurrent lost-update 조건을 재현하는 in-memory test 기반이 존재한다.

구현 파일군:

- `application/repositories/protocols.py`: persistence-neutral async repository/UoW protocol
- `application/repositories/errors.py`: not-found, unique, concurrency, closed-transaction 오류
- `application/repositories/in_memory.py`: indexed snapshot store와 optimistic Unit of Work
- `application/workspace_admin/service.py`: Phase 2 mutation plan의 원자적 적용 계층
- `tests/control/test_in_memory_repositories.py`: transaction/uniqueness/append-only repository 검증
- `tests/control/test_workspace_admin_service.py`: cross-aggregate atomicity와 rollback 검증

검증 결과:

- Phase 1~3 Control tests: 73 passed
- Frozen Contract + Control tests: 100 passed
- Python compileall: 통과
- `pnpm run typecheck`: 통과
- `pnpm run verify:resolution`: 통과
- 공식 생성 및 전체 test 후 generated tracked diff: 0

### Phase 4 — Firestore canonical persistence `[완료]`

1. [x] 명세의 16개 canonical collection만 사용해 Firestore document mapper와 repository를 구현했다.
2. [x] Domain model과 Firestore document dict 사이의 strict mapper를 두고 SDK 타입을 `persistence/core_firestore/backend.py` 아래에 격리했다.
3. [x] canonical collection 내부 deterministic unique-key sentinel과 transaction `create` 충돌로 uniqueness를 보장했다.
4. [x] 다음 원자 연산을 repository/UoW와 기존 application service로 실행·검증했다.
   - Workspace + Owner membership 생성
   - Source Manager 제거 + Mount 상태 + Audit + Notification
   - ChangeEvent idempotent insert + Artifact upsert
   - Risk projection + Evidence + append-only RiskEvent reconciliation
   - optimistic review update + review event
5. [x] `FIRESTORE_EMULATOR_HOST`가 설정되면 anonymous credential로 production async transaction을 검증하는 emulator test를 추가했다.
6. [x] 필요한 composite index 후보를 코드로 선언하고 dependency/현황 문서에 wiring 요청을 기록했다.

완료 조건:

- [x] In-memory와 Firestore repository가 공용 commit/rollback/lookup/uniqueness contract scenario를 통과한다.
- [x] SDK 없이 domain test가 독립 실행되고, emulator 설정 시 production Firestore persistence test를 별도로 실행할 경로가 존재한다.

구현 파일군:

- `persistence/core_firestore/schema.py`: 16개 collection과 composite index declaration
- `persistence/core_firestore/mappers.py`: 17개 domain record의 strict 양방향 mapper
- `persistence/core_firestore/unique_keys.py`: canonical collection 내부 hashed unique sentinel
- `persistence/core_firestore/backend.py`: Google AsyncClient transaction과 SDK error translation
- `persistence/core_firestore/session.py`: read/query expectation, read-your-writes와 buffered atomic commit
- `persistence/core_firestore/repositories.py`: Phase 3 repository protocol의 Firestore 구현
- `tests/control/test_firestore_mappers.py`: 전체 record round-trip/strictness/discriminator 검증
- `tests/control/test_firestore_repositories.py`: fake atomic backend 기반 transaction/uniqueness/parity 검증
- `tests/control/test_firestore_emulator.py`: 실제 Emulator가 설정된 환경용 production adapter test

검증 결과:

- Phase 1~4 Control tests: 103 passed, 1 skipped(emulator 미설정)
- Frozen Contract + Control tests: 130 passed, 1 skipped(emulator 미설정)
- Google Cloud Firestore 2.28.1 import 및 `pip check`: 통과
- Python compileall: 통과
- `pnpm run typecheck`: 통과
- `pnpm run verify:resolution`: 통과
- 공식 생성 및 전체 test 후 generated tracked diff: 0

### Phase 5 — SourceChange intake와 AnalysisJob orchestration `[완료]`

1. [x] `register_source_change(SourceChange)`를 persistence-neutral application service로 구현했다.
2. [x] `risk_workspace_id`, `mount_id`, `source_workspace_id`, `source_type`, SourceConnection 관계와 각 ACTIVE 상태를 transaction 안에서 검증한다.
3. [x] `event_fingerprint`로 idempotent ChangeEvent를 생성하고 PENDING/PROCESSING/DONE/FAILED 중복 상태를 일관된 ACK/재큐잉 정책으로 처리한다.
4. [x] SourceArtifactRef를 stable Artifact에 resolve/upsert하고 ArtifactState의 revision/availability를 함께 갱신한다.
5. [x] CREATE/UPDATE/MOVE/DELETE semantics를 적용하며 MOVE continuity에는 `previous_artifact`를 사용한다.
6. [x] DELETE에서는 Artifact availability와 ChangeEvent만 기록하고 AnalysisJob/Risk reconciliation/queue를 호출하지 않는다.
7. [x] 분석 대상 변경에는 deterministic AnalysisJob을 같은 transaction에 만들고 commit 후 queue port에 `change_event_id`만 전달한다.
8. [x] claim/start/finish/fail/retry transition과 ChangeEvent/AnalysisJob 상태 쌍을 retry-safe compare-and-set 경로로 구현했다.
9. [x] Cloud Tasks SDK는 직접 wiring하지 않고 idempotent 구현을 요구하는 `TaskEnqueuer` protocol과 deterministic fake를 제공한다.
10. [x] Phase 3~4에서 보류했던 SourceChange referential integrity, AnalysisJob CAS/queue, Artifact MOVE identity-index 이전을 in-memory와 Firestore repository에 보완했다.

완료 조건:

- [x] 동일 SourceChange의 반복 및 동시 수신이 ChangeEvent, Job, Artifact/Risk identity를 중복 생성하지 않는다.
- [x] queue payload에는 raw source나 provider credential 없이 canonical `change_event_id`만 존재한다.

구현 파일군:

- `application/process_change/service.py`: SourceChange 관계/status 검증, Artifact/ChangeEvent/Job 원자 저장, duplicate/retry와 enqueue-after-commit
- `application/process_change/{models,transitions,queue}.py`: canonical 상태 불변식, 순수 transition, raw-free queue port/fake
- `application/analysis_jobs/{models,transitions,service}.py`: deterministic Job identity와 claim/finish/fail/retry orchestration
- `application/repositories/in_memory.py`: MOVE 시 같은 SourceWorkspace 내 source identity index의 원자 이전
- `persistence/core_firestore/repositories.py`: MOVE unique sentinel claim/release를 포함한 Firestore 원자 이전
- `tests/control/test_source_change_intake.py`: intake, duplicate/concurrency, queue recovery, MOVE/DELETE, 상태 관계와 job lifecycle 검증
- `tests/control/test_firestore_repositories.py`: MOVE sentinel 및 Firestore UoW 기반 intake idempotency 검증

검증 결과:

- Phase 1~5 Control tests: 122 passed, 1 skipped(emulator 미설정)
- Frozen Contract + Control tests: 149 passed, 1 skipped(emulator 미설정)
- Python compileall, `pip check`, `pnpm run typecheck`, `pnpm run verify:resolution`: 통과
- 공식 생성 및 전체 test 후 generated tracked diff: 0

### Phase 6 — Security Gate `[완료]`

1. [x] `build_analysis_artifact(snapshot, job_id)`의 단일 transient 진입점을 만들었다.
2. [x] canonical Workspace/Mount/SourceConnection/SourceWorkspace/Artifact/ArtifactState/ChangeEvent/Job과 Snapshot 식별자·revision·처리 상태를 교차 검증한다.
3. [x] logical path를 mount alias 기준 절대 논리 경로로 정규화하고 traversal, local absolute path와 scope metadata 불일치를 거부한다.
4. [x] VWS global `.ipriskignore` parser를 구현했다.
   - deny-only
   - `*`, `**`, `?`
   - negation `!` 미지원 또는 명시적 validation error
   - source-level deny가 전달되면 VWS allow보다 항상 우선
5. [x] artifact kind, MIME/type allow/deny, content scope와 실제 segment/receipt를 포함한 보수적 byte-size policy를 적용한다.
6. [x] deterministic secret filter를 구현했다.
   - PEM private key block
   - `.env` 형태 credential line
   - common secret/token assignment
   - bearer/token-like value
   - 고정 placeholder와 정확한 `redaction_count`
7. [x] artifact kind별 deterministic minimization을 적용했다.
   - MANIFEST/LOCKFILE: size 한도 내 full 가능
   - SOURCE_CODE: changed/context 우선
   - DOCUMENT_TEXT/TEXT: threshold와 segment cap 적용
8. [x] static analyzer eligibility matrix로 PATENT/LICENSE 요청 목록을 계산하고 AnalysisJob 요청 목록도 결과 교집합으로 축소한다.
9. [x] redaction/minimization 이후 identity와 routing을 포함한 canonical serialization을 SHA-256 hash하여 `analysis_input_checksum`을 만든다.
10. [x] 모든 gate를 통과한 경우에만 `security_context.approved=true`인 Frozen `AnalysisArtifact`를 생성한다.
11. [x] fetch가 이미 발생했다는 사실은 allow/deny와 무관하게 SourceAccessReceipt에서 idempotent SourceAccessEvent로 기록한다.
12. [x] SourceSnapshot 또는 원문 segment를 repository, event, error, denial result와 structured log에 보관하지 않는다.
13. [x] policy/scope/type/size deny는 INCONCLUSIVE/DONE, 운영·무결성 오류는 FAILED/FAILED로 Job/Event를 원자 종료하고 동일 receipt 재처리를 idempotent하게 만든다.

완료 조건:

- [x] deny-wins, redaction, minimization, checksum, approved-only 생성이 pure test로 검증된다.
- [x] ignored/unsupported/oversized 입력에서 Analyzer로 전달 가능한 artifact가 생성되지 않는다.
- [x] Snapshot 전체를 저장하는 persistence API가 존재하지 않는다.

구현 파일군:

- `application/security_gate/policy.py`: versioned Gate policy, source-scope deny input과 resolver port/fake
- `application/security_gate/ignore.py`: deny-only mount-absolute `.ipriskignore` parser와 `*`/`**`/`?` matcher
- `application/security_gate/redaction.py`: PEM/env/assignment/Bearer/token pattern의 deterministic redaction
- `application/security_gate/minimization.py`: kind/segment 우선순위와 UTF-8 byte/segment cap
- `application/security_gate/service.py`: canonical validation, deny/approval, analyzer routing, checksum, Job 종료와 SourceAccess 원자 기록
- `application/repositories/**`, `persistence/core_firestore/repositories.py`: SourceAccess direct lookup과 AnalysisJob requested type narrowing invariant
- `tests/control/test_security_gate.py`: deny-wins, redaction, minimization, routing, checksum, mismatch, 상태 종료와 비영속 경계 검증
- `tests/control/test_firestore_repositories.py`: SourceAccess lookup 및 requested type narrowing Firestore parity

검증 결과:

- Phase 1~6 Control tests: 142 passed, 1 skipped(emulator 미설정)
- Frozen Contract + Control tests: 169 passed, 1 skipped(emulator 미설정)
- Python compileall, `pip check`, `pnpm run typecheck`, `pnpm run verify:resolution`: 통과
- 공식 생성 및 전체 test 후 generated tracked diff: 0

### Phase 7 — AnalysisResult intake와 Risk reconciliation `[완료]`

1. [x] `accept_analysis_result(AnalysisResult)`를 구현했다.
2. [x] Job 존재 여부, artifact ID, revision, requested analysis type과 canonical ChangeEvent/Artifact/ArtifactState 관계를 검증한다.
3. [x] AnalysisResult의 status/coverage/provider failure/version summary를 AnalysisJob의 analysis type별 outcome에 반영했다. 별도 임의 canonical collection은 추가하지 않았다.
4. [x] Evidence를 minimal retention policy로 정규화하고 excerpt 길이, safe metadata와 reference를 제한했다.
5. [x] Patent와 License candidate의 stable risk key 및 Risk/Evidence/Event ID를 결정론적으로 생성했다.
6. [x] `SUCCEEDED + COMPLETE`일 때만 active risk set과 candidate set을 transaction 안에서 reconcile한다.
   - 교집합: `EXISTING`, evidence/last_seen 갱신
   - 신규: `NEW`, DETECTED event
   - 사라짐: `RESOLVED`, RESOLVED event
   - 과거 RESOLVED 재등장: active `EXISTING`, REOPENED event
7. [x] FAILED, INCONCLUSIVE, SKIPPED, PARTIAL, NONE은 old-only resolution을 절대 실행하지 않는다.
8. [x] duplicate AnalysisResult acceptance가 evidence/event를 중복 추가하지 않도록 result fingerprint와 analysis type별 append-only outcome을 둔다.
9. [x] multi-analyzer Job aggregate 상태를 각 analysis type 결과와 독립적으로 계산한다.
10. [x] high/reopened/failure 조건에 Notification과 필요한 AuditEvent를 생성한다.

완료 조건:

- zero-candidate complete success만 기존 Risk를 resolve할 수 있다.
- provider failure와 incomplete coverage가 기존 Risk를 보존한다.
- alias rename, DELETE, review disposition이 machine Risk identity/lifecycle을 오염시키지 않는다.

구현 결과:

- `application/risk_reconcile/service.py`: 결과 검증, idempotent intake, authoritative set reconciliation, aggregate completion, Audit/Notification
- `application/risk_reconcile/retention.py`: evidence/reference/metadata/summary/provider failure의 bounded redaction policy
- `application/analysis_jobs/**`: analysis type별 immutable outcome summary와 retry 시 attempt outcome 초기화
- `core/risk/identity.py`: stable Risk/RiskEvidence/RiskEvent ID
- `application/repositories/**`, `persistence/core_firestore/**`: outcome append-only 및 Risk identity 불변식, strict Firestore mapper
- `tests/control/test_analysis_result_reconciliation.py`: authoritative/non-authoritative, lifecycle, duplicate, stale, multi-analyzer, retention 검증
- `tests/control/test_firestore_mappers.py`: nested AnalysisOutcome strict round-trip

검증 결과:

- Phase 1~7 Control tests: 154 passed, 1 skipped(emulator 미설정)
- Frozen Contract + Control tests: 181 passed, 1 skipped(emulator 미설정)
- Python compileall, `pip check`, `pnpm run typecheck`, `pnpm run verify:resolution`: 통과
- 공식 생성 후 generated tracked diff: 0

### Phase 8 — Human review, History, Audit, Notification `[완료]`

1. [x] review disposition 변경 use case에 명시적 `review_version` optimistic check와 transaction을 적용했다.
2. [x] actor, 이전/신규 disposition/version, redacted optional comment와 timestamp를 append-only RiskEvent로 남긴다.
3. [x] 권한이 적용된 Risk timeline query와 Workspace activity projection을 구현했다.
4. [x] VWS 운영/보안 사건은 AuditEvent, source read는 SourceAccessEvent, Risk 변화는 RiskEvent로 분리해 projection에서도 stream discriminator를 유지한다.
5. [x] Notification list/read 상태, unread count와 대상 사용자 filtering을 구현했다.
6. [x] history export는 raw source/token/local absolute path 없이 JSON-compatible safe field만 직렬화한다.

완료 조건:

- `EXCLUDED != RESOLVED`와 과거 event 불변성이 API까지 유지된다.
- 세 history stream 어디에도 raw source, local absolute path, token이 없다.

구현 결과:

- `application/risk_review/**`: reviewer 권한, review version CAS, no-op idempotency와 transactional Risk/RiskEvent 변경
- `application/history/**`: Risk timeline, Workspace activity, safe history export와 bounded redaction
- `application/notifications/**`: user-scoped inbox, unread filtering/count와 idempotent READ 전환
- `core/risk/**`: canonical `review_version`과 deterministic review event identity
- `application/repositories/**`, `persistence/core_firestore/**`: Workspace Risk query, review version 및 Notification 단방향 상태 불변식
- `tests/control/test_review_history_notifications.py`: 권한/CAS/stream 분리/export safety/notification isolation 검증

검증 결과:

- Phase 1~8 Control tests: 158 passed, 1 skipped(emulator 미설정)
- Frozen Contract + Control tests: 185 passed, 1 skipped(emulator 미설정)
- Phase 8 focused service/persistence tests: 50 passed
- Python compileall, `pip check`, `pnpm run typecheck`, `pnpm run verify:resolution`: 통과
- 공식 생성 후 generated tracked diff: 0

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

Agent 1은 package가 필요한 Phase에서 호환 버전을 독자적으로 선택·설치·검증하고 dependency 문서에 기록한다. Integration Owner는 전체 Plane 충돌을 확인한 뒤 root manifest와 lockfile에 최종 pin을 병합한다.

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

## 9. 작업 현황 로그

### 2026-08-16 — 직전 Phase 보완 및 Phase 8 완료

#### 구현 완료 항목

1. 직전 Phase에서 Phase 8 범위로 남겨 둔 Human review, history query, Notification read/filtering과 safe export를 우선 보완했다.
   - Phase 7의 machine Risk reconciliation은 review disposition과 review version을 변경하지 않는다.
   - Phase 8 review use case만 human disposition을 변경하며 Risk와 RiskEvent를 한 transaction으로 저장한다.
2. canonical Risk에 독립적인 `review_version`을 추가했다.
   - 새 Risk는 version 0에서 시작하고 실제 disposition 변경마다 정확히 1 증가한다.
   - 요청은 `expected_review_version`을 반드시 전달하며 stale version이면 현재 version을 포함한 `RiskReviewConflictError`를 반환한다.
   - repository도 disposition 변경 없는 version 조작, version 누락/도약/감소를 거부해 application service 우회를 방어한다.
3. `RiskReviewService.change_disposition()`을 구현했다.
   - ACTIVE Membership의 `RISK_REVIEW` 권한을 확인하고 Risk가 요청 VWS에 속하는지 교차 검증한다.
   - lifecycle, priority, evidence identity는 건드리지 않고 review disposition/version과 updated timestamp만 변경한다.
   - 동일 disposition 재요청은 version과 history를 증가시키지 않는 `UNCHANGED` 결과로 처리한다.
4. Human review history를 append-only RiskEvent로 기록한다.
   - deterministic `(risk_id, review_version)` event ID를 사용한다.
   - USER actor와 actor user ID, 이전/신규 disposition/version, timestamp와 optional comment를 기록한다.
   - comment에는 Phase 6 secret redaction을 재사용하고 Windows/common Unix local absolute path를 별도로 제거하며 길이를 제한한다.
5. `HistoryQueryService.get_risk_timeline()`을 구현했다.
   - VWS `RISK_VIEW` 권한과 Risk scope를 검증한다.
   - 현재 lifecycle/review disposition/version과 최신순 RiskEvent projection을 반환하되 evidence 본문은 포함하지 않는다.
6. `list_workspace_activity()`와 세 history stream projection을 구현했다.
   - RiskEvent는 `RISK`, 운영·보안 AuditEvent는 `AUDIT`, source read receipt는 `SOURCE_ACCESS` discriminator를 유지한다.
   - `AUDIT_VIEW` 권한을 가진 사용자만 조회할 수 있고 세 stream을 timestamp/type/ID로 결정적으로 최신순 병합한다.
   - SourceAccess projection은 ID, revision, access type, byte count와 provider request ID만 포함하고 source content/path를 포함하지 않는다.
7. `export_workspace_history()`와 JSON-compatible safe serialization을 구현했다.
   - `AUDIT_EXPORT` 권한을 별도로 검사한다.
   - metadata의 secret 성격 key는 값 전체를 redaction placeholder로 바꾸고 모든 string에 secret/path redaction과 길이 제한을 적용한다.
   - 중첩 깊이, item 수와 최종 JSON byte 상한을 적용해 `to_safe_dict()` 결과를 바로 JSON 직렬화할 수 있다.
8. `NotificationService`를 구현했다.
   - `list_for_user()`는 요청 actor ID로만 repository query하고 최신순 결과, unread-only filter와 limit 적용 전 전체 unread count를 제공한다.
   - 타 사용자 Notification ID를 read 요청하면 존재하지 않는 것과 같은 오류로 처리해 대상 정보 노출을 막는다.
   - `mark_read()`는 UNREAD → READ만 허용하며 동일 요청 재전달은 기존 read timestamp를 유지한 `changed=false` 결과로 처리한다.
9. Notification repository 불변식을 보완했다.
   - user/workspace/type/created_at/metadata identity는 수정할 수 없다.
   - READ → UNREAD와 이미 기록된 read timestamp의 변경을 In-memory/Firestore 모두 거부한다.
10. History용 Workspace Risk repository query와 Firestore index declaration을 추가했다.
    - Firestore mapper는 `review_version`을 strict required field로 왕복한다.
    - fake Firestore backend에서 workspace scope query, review optimistic transaction과 Notification read 단방향 규칙을 검증했다.
11. Phase 7 회귀 테스트의 직접 review setup도 review version을 증가시키도록 갱신해 새 불변식 아래에서 machine lifecycle의 review 보존을 재검증했다.
12. Phase 8 메인 구현 완료 후 이전 검토 사항을 제한적으로 재검토했다.
    - optional RiskEvent hash chain은 현재 append-only/deterministic identity보다 우선하지 않았고 구현하지 않았다.
    - Security policy persistence는 Phase 9 Control API와 함께 transaction/audit surface를 정하는 기존 결정을 유지했다.

#### 구현 미완료 항목 및 사유

1. Human review, timeline, activity, export와 Notification의 HTTP endpoint/DTO/ETag 매핑은 아직 구현하지 않았다.
   - application use case와 safe projection은 완성했다. 인증 session, 공통 authorization dependency와 API error model이 필요한 Phase 9에서 router와 함께 연결한다.
2. Workspace activity와 Notification의 cursor pagination은 아직 구현하지 않았다.
   - Phase 8은 1~500의 bounded limit와 deterministic ordering을 제공한다. 외부 cursor 형식은 Phase 9 API DTO, 실제 Firestore index/scale 검증은 Phase 12와 함께 확정한다.
3. Firestore 문서에 새로 추가한 `Risk.review_version`의 production migration은 작성하지 않았다.
   - 현재 프로젝트에는 production data가 없고 schema version 1 개발 단계다. 통합 전에 기존 환경 데이터가 생겼다면 version 0 backfill 또는 mapper schema version 증가를 검토해야 한다.
4. 실제 Firestore Emulator에서 Phase 8 service 전체를 실행하지 못했다.
   - `FIRESTORE_EMULATOR_HOST`가 없어 공용 emulator test 1건이 계속 skip된다. strict mapper와 fake transactional backend parity는 통과했다.
5. VWS security policy content 저장/편집과 `SECURITY_POLICY_CHANGED` 생성 use case는 아직 구현하지 않았다.
   - Phase 8은 이미 존재하는 AuditEvent의 query/export를 구현했다. policy request DTO, version precondition과 권한 오류가 함께 필요한 Phase 9 Security API에서 완료한다.
6. RiskEvent hash chain은 구현하지 않았다.
   - 명세상 MVP 권장 사항이지 필수 완료 조건은 아니다. append-only repository, deterministic review event identity와 transactional write가 현재 무결성 기반이며, export 서명/검증 요구가 생기면 Phase 12에서 체인 도입 비용과 migration을 검토한다.
7. Email/Slack/FCM 등 외부 Notification delivery는 구현하지 않았다.
   - MVP 필수 범위는 Firestore/in-app notification이며 외부 channel은 명세상 후속 항목이다.
8. Analyzer 호출/result delivery adapter와 대규모 evidence storage는 이전 Phase와 동일하게 Agent 3/Integration 경계 또는 의도적 비보존 항목이다.
   - Phase 8 본 작업에 포함하지 않았으며 Control history에도 raw result/evidence/source를 새로 노출하지 않는다.

#### 추가 검토가 필요한 사항

1. optimistic precondition은 Risk 전체 `updated_at`이 아니라 독립 `review_version`으로 결정했다.
   - analyzer가 lifecycle/priority를 갱신해도 reviewer의 version이 불필요하게 충돌하지 않고, 동시에 제출된 서로 다른 human disposition만 명확히 충돌시킨다.
2. 같은 disposition 재요청에서 comment만 추가하는 동작은 지원하지 않는다.
   - disposition 변화 이력과 자유 형식 메모를 혼합하지 않기 위해 no-op으로 처리한다. 별도 reviewer note 기능이 필요하면 새로운 event intent/API로 명시해야 한다.
3. Risk timeline은 `RISK_VIEW`, 세 stream이 합쳐진 Workspace activity는 `AUDIT_VIEW`, export는 `AUDIT_EXPORT`로 분리했다.
   - 일반 viewer가 Risk history는 볼 수 있지만 source access와 운영/security audit 전체는 볼 수 없도록 Phase 2 permission 모델을 그대로 적용한다.
4. history 조회 시에도 저장 필드의 `_safe` 이름을 절대 신뢰하지 않고 출력 직전에 다시 redaction한다.
   - 과거/외부 adapter가 잘못된 metadata를 저장했더라도 token과 local path가 export에 그대로 나오지 않도록 하는 defense-in-depth다. 한 event가 bounds를 위반하면 조용히 잘라내기보다 query/export를 fail-closed 처리한다.
5. Notification은 현재 VWS membership이 아니라 canonical target user 소유권으로 조회한다.
   - membership 제거 후에도 본인에게 이미 발생한 보안/운영 알림을 확인할 수 있고 다른 사용자는 ID를 알아도 조회·read할 수 없다. Phase 9 session identity가 이 actor ID를 보증해야 한다.
6. read transition의 clock이 notification 생성보다 과거면 created time으로 올린다.
   - clock skew로 domain chronology가 깨지는 것을 막되 이미 READ인 notification의 timestamp는 재전달 시 수정하지 않는다.
7. 이전 검토 목록의 Firestore emulator, pagination/scale, policy persistence와 RiskEvent hash chain을 메인 작업 후 다시 확인했다.
   - 현재 Phase 범위 안에서 더 합리적인 즉시 개선안은 history query index declaration과 bounded limit뿐이어서 이를 반영했고, 나머지는 위 미완료 사유에 따라 후속 Phase에 유지한다.

#### 검증 결과

```text
Phase 8 focused service/persistence tests               50 passed
tests/control                                           158 passed, 1 skipped
shared/contracts/tests + tests/control                  185 passed, 1 skipped
pnpm run generate                                       PASS
generated files tracked diff after generation/tests    NONE
Python compileall                                       PASS
pip check                                               PASS
pnpm run typecheck                                      PASS
pnpm run verify:resolution                              PASS
git diff --check                                        PASS
```

#### 제안 커밋 메시지

`feat: add versioned review and safe history services`

### 2026-08-16 — 이전 Phase 보완 및 Phase 7 완료

#### 구현 완료 항목

1. `AnalysisResultIntakeService.accept_analysis_result()`를 canonical 결과 수용 경계로 구현했다.
   - AnalysisJob, ChangeEvent, Artifact, ArtifactState와 RiskWorkspace를 같은 Unit of Work에서 읽고 Job/Event/Artifact ID 및 revision 관계를 교차 검증한다.
   - 새 결과는 RUNNING Job과 PROCESSING ChangeEvent에만 허용하며, requested analysis type과 ArtifactState latest revision이 일치하지 않으면 transaction 전체를 거부한다.
   - result 시작 시각이 현재 Job attempt보다 빠르면 이전 attempt의 늦은 결과로 판단해 거부한다.
2. 별도 canonical collection 없이 AnalysisJob 안에 analysis type별 `AnalysisOutcome`을 추가했다.
   - result fingerprint, status, coverage, analyzer/model/prompt/policy/RAG version summary, 시작/완료 시각과 bounded provider failure summary만 보존한다.
   - outcome key는 requested analysis type이어야 하고 terminal result-bearing Job은 모든 요청 type outcome을 가져야 한다.
   - repository는 동일 attempt의 outcome을 append-only로 강제하며, FAILED retry는 기존 attempt outcome을 명시적으로 비운다.
3. AnalysisResult idempotency와 충돌 정책을 구현했다.
   - 전체 Frozen result를 canonical JSON으로 직렬화해 SHA-256 fingerprint를 만든다.
   - 같은 analysis type과 같은 fingerprint의 redelivery는 `DUPLICATE`로 안전하게 ACK하고 Risk/Evidence/Event/Audit/Notification을 다시 만들지 않는다.
   - 같은 analysis type에 다른 fingerprint가 이미 수용된 경우 ambiguous overwrite 대신 오류로 거부한다.
4. bounded evidence retention policy를 구현했다.
   - candidate가 실제 참조한 Evidence만 RiskEvidence로 남기며 사용되지 않은 evidence payload는 저장하지 않는다.
   - excerpt와 summary는 secret redaction 뒤 길이를 제한한다.
   - HTTP(S) reference의 credential/userinfo와 local absolute path를 거부하고 URL query를 제거한다.
   - metadata key/value, 중첩 깊이, item 수와 최종 JSON byte를 제한하며 credential 성격의 key는 값 전체를 `[REDACTED_SECRET]`로 대체한다.
5. Patent와 License stable Risk identity를 확정했다.
   - Patent application number는 Unicode NFKC/casefold 후 공백·하이픈·underscore를 제거한다.
   - License는 ecosystem/package의 NFKC/casefold, version trim, license expression의 whitespace 정규화와 uppercase를 적용한다.
   - canonical risk key로 Risk ID를, Risk+Job+result evidence ID로 RiskEvidence ID를, Risk+result fingerprint+event type으로 RiskEvent ID를 결정론적으로 생성한다.
6. authoritative Risk set reconciliation을 구현했다.
   - 오직 `SUCCEEDED + COMPLETE` 결과만 candidate set을 authoritative truth로 사용한다.
   - 신규 candidate는 NEW/DETECTED, 계속 존재하는 candidate는 EXISTING/CONFIRMED, 사라진 active candidate는 RESOLVED/RESOLVED, 과거 RESOLVED의 재등장은 EXISTING/REOPENED로 기록한다.
   - zero-candidate complete success도 유효한 authoritative 결과이므로 해당 analysis type의 기존 active Risk를 해소한다.
   - machine lifecycle 갱신 시 기존 human review disposition을 그대로 보존한다.
7. non-authoritative 결과가 Risk truth를 변경하지 못하도록 고정했다.
   - FAILED, INCONCLUSIVE, SKIPPED 또는 PARTIAL/NONE coverage는 Risk 생성·갱신·해소 및 successful revision 갱신을 수행하지 않는다.
   - provider failure가 있거나 FAILED인 경우 safe category 중심 `ANALYSIS_FAILED` AuditEvent와 owner in-app Notification을 남긴다.
8. suggested priority와 Risk event/notification을 연결했다.
   - Patent priority는 Frozen candidate 값을 사용한다.
   - License policy outcome은 conflict/review-required=HIGH, notice/unknown=MEDIUM, no-action=LOW로 결정적으로 투영한다.
   - priority 변경은 `PRIORITY_CHANGED` RiskEvent로 분리하며 신규/상향 HIGH와 REOPENED는 deterministic owner Notification을 생성한다.
9. multi-analyzer Job aggregate를 구현했다.
   - 일부 requested type만 도착한 동안 Job/Event는 RUNNING/PROCESSING을 유지하되 해당 analysis type의 authoritative reconciliation은 즉시 완료한다.
   - 모든 type이 도착한 뒤 하나라도 FAILED이면 Job/Event를 FAILED로, 모두 complete success이면 SUCCEEDED/DONE으로, 나머지는 INCONCLUSIVE/DONE으로 종료한다.
10. repository와 Firestore 불변식을 보완했다.
    - In-memory와 Firestore 모두 AnalysisJob source identity, requested-type narrowing, per-attempt outcome append-only를 동일하게 강제한다.
    - Risk의 key뿐 아니라 workspace/artifact/analysis type/first-seen identity도 immutable로 강제한다.
    - nested AnalysisOutcome/provider failure/version summary strict mapper와 round-trip test를 추가했다.
11. Phase 6에서 보류했던 Analyzer 결과 수용, result identity/status/coverage, Risk reconciliation을 이번 Phase에서 완료했다.
12. authoritative/non-authoritative matrix, duplicate/conflict, lifecycle 재등장, review 보존, license normalization, multi-analyzer aggregate, stale rollback, evidence redaction과 canonical context corruption을 회귀 테스트로 고정했다.

#### 구현 미완료 항목 및 사유

1. Human review 변경 use case와 timeline/history query는 아직 구현하지 않았다.
   - Phase 7은 analyzer가 갱신하는 machine lifecycle에서 기존 review disposition을 보존하는 데 집중했다. actor/precondition/comment를 받는 review 변경과 append-only history projection은 Phase 8 범위에서 구현한다.
2. Notification list/read와 사용자별 조회 projection은 아직 구현하지 않았다.
   - Phase 7은 발생 조건과 canonical in-app Notification 생성까지만 완료했다. 수신자 filtering, unread/read 전환과 조회 surface는 Phase 8에서 구현한다.
3. Audit/Risk/SourceAccess 세 history stream의 통합 activity query와 safe export는 아직 구현하지 않았다.
   - event 저장 경계는 준비됐지만 사용자용 정렬·pagination·직렬화는 Phase 8~9 범위다.
4. AnalysisResult 원본 전체와 사용되지 않은 evidence는 의도적으로 저장하지 않는다.
   - 명세의 16개 canonical collection과 data minimization 원칙을 지키기 위해 Job에는 결과 fingerprint/outcome summary만, RiskEvidence에는 candidate가 참조한 bounded evidence만 남긴다. 원본 보존이 통합 요구사항으로 생기면 별도 collection을 임의 추가하지 않고 contract/schema 변경 절차를 따른다.
5. 실제 Analyzer 호출과 result delivery/retry adapter는 구현하지 않았다.
   - Agent 3과 Integration 소유 경계다. Agent 1은 `accept_analysis_result()`의 in-process application surface와 retry-safe semantics를 제공한다.
6. 실제 Firestore Emulator에서 Phase 7 service 전체를 실행하지 못했다.
   - 현재 환경에 `FIRESTORE_EMULATOR_HOST`가 없다. strict mapper, fake transactional backend, Risk atomic persistence와 repository invariant test는 통과했고 emulator test entry는 유지한다.
7. 대규모 Risk/Evidence query의 cursor pagination과 batch 성능 검증은 아직 하지 않았다.
   - 현재 repository contract는 artifact/type 범위의 deterministic tuple query다. API pagination은 Phase 9, index/scale/관측성은 Phase 12에서 실제 조회 shape과 함께 검증한다.
8. 실제 email/push 등의 외부 알림 전송은 구현하지 않았다.
   - 현재 canonical 요구사항은 in-app Notification이며 외부 delivery provider는 Agent 1 명세에 없다. Integration 요구가 확정되기 전에는 side effect를 추가하지 않는다.

#### 추가 검토가 필요한 사항

1. 이전 Phase에서 기록한 “multi-analyzer result 상태와 Risk reconciliation” 항목은 analysis-type truth와 aggregate execution 상태를 분리하는 방식으로 해결했다.
   - 한 type의 complete success는 해당 type Risk에 즉시 authoritative하지만 Job은 모든 requested type outcome이 모일 때까지 RUNNING이다. 다른 type의 실패가 이미 성공한 type의 truth를 되돌리지는 않는다.
2. result idempotency는 별도 Result document가 아니라 AnalysisJob nested outcome으로 구현했다.
   - canonical collection 추가를 피하면서 `(job, analysis_type)`당 한 결과를 강제한다. 동일 fingerprint는 ACK하고 상이한 fingerprint는 overwrite하지 않아 ambiguous analyzer redelivery를 fail-closed 처리한다.
3. FAILED Job retry에서 기존 outcome을 비우는 결정을 재검토해 유지·보완했다.
   - 새 attempt가 이전 attempt 결과와 섞이지 않게 하고, 새 `started_at`보다 오래된 늦은 결과를 거부한다. 향후 type별 독립 retry가 필요해지면 현재 Job 단위 retry와 다른 explicit contract가 필요하다.
4. authoritative 판단은 기존 pure domain rule인 `SUCCEEDED + COMPLETE`를 단일 source로 재사용한다.
   - provider failure가 포함된 complete success는 모순으로 거부한다. partial/inconclusive result에 candidate가 포함돼도 관찰 정보로만 취급하고 canonical Risk에는 반영하지 않는다.
5. evidence reference는 query를 제거하고 fragment는 유지한다.
   - query에는 signed URL/token이 섞일 위험이 높고 fragment는 문서 내 claim/section locator로 유용하기 때문이다. opaque provider locator가 필요한 경우에도 credential-free reference만 허용한다.
6. provider failure의 provider/category/message도 Frozen 필드명이 `safe`라고 해서 그대로 신뢰하지 않는다.
   - Phase 6 secret redactor와 retention cap을 다시 적용하고 Audit/Notification에는 provider 이름이나 원문 메시지 대신 category 집합만 넣는다.
7. License priority mapping은 보수적으로 REVIEW_REQUIRED까지 HIGH로 두었다.
   - 정책 결정이 없는 REVIEW_REQUIRED를 낮추면 사용자 검토가 누락될 수 있다. 실제 policy UX에서 과도한 알림이 확인되면 Phase 11~12에서 사용자 설정과 함께 재평가한다.
8. 새 Risk가 HIGH이면 HIGH notification을 생성하지만 기존 HIGH가 다시 확인된 경우에는 반복 알림을 만들지 않는다.
   - priority가 비-HIGH에서 HIGH로 올라가거나 Risk가 REOPENED일 때만 새 알림을 생성해 analyzer 반복 실행에 따른 소음을 제한한다.
9. RiskEvent hash chain은 이번 Phase에 추가하지 않았다.
   - append-only repository와 deterministic event identity는 확보했다. History의 조회·내보내기 위변조 요구를 Phase 8에서 확인한 뒤 기존 schema 안에서 가능한 integrity metadata를 검토한다.
10. 이전 Phase의 Firestore emulator, policy persistence, structured logging 검토 항목을 다시 살폈다.
    - Phase 7 범위에서 더 안전하게 해결할 새 방안은 발견되지 않았다. 각각 Phase 8~9의 policy/history API와 Phase 12 hardening/CI 환경에서 계속 다룬다.

#### 검증 결과

```text
Phase 7 focused reconciliation/mapper tests             32 passed
tests/control                                           154 passed, 1 skipped
shared/contracts/tests + tests/control                  181 passed, 1 skipped
pnpm run generate                                       PASS
generated files tracked diff after generation/tests    NONE
Python compileall                                       PASS
pip check                                               PASS
pnpm run typecheck                                      PASS
pnpm run verify:resolution                              PASS
git diff --check                                        PASS
```

#### 제안 커밋 메시지

`feat: reconcile AnalysisResults into canonical Risks`

### 2026-08-16 — 이전 Phase 보완 및 Phase 6 완료

#### 구현 완료 항목

1. `SecurityGateService.build_analysis_artifact()`를 `SourceSnapshot -> AnalysisArtifact | denial`의 유일한 application 경계로 구현했다.
   - Frozen SourceSnapshot을 입력으로만 사용하고 repository 또는 canonical event에 Snapshot/segment를 저장하지 않는다.
   - 승인 결과만 `security_context.approved=true`인 Frozen AnalysisArtifact를 반환한다.
   - denial result에는 enum reason과 content-free SourceAccessEvent ID만 포함한다.
2. canonical context와 Snapshot을 교차 검증한다.
   - AnalysisJob, ChangeEvent, Artifact/ArtifactState, Workspace, Mount, SourceWorkspace와 SourceConnection을 한 Unit of Work에서 조회한다.
   - Job/Event RUNNING/PROCESSING 상태, 모든 aggregate ID 관계, SourceType, ACTIVE/AVAILABLE 상태를 검증한다.
   - Snapshot의 workspace/mount/source/artifact/display name과 provider-relative path가 canonical Artifact와 일치해야 한다.
   - Snapshot revision, Job/Event revision과 ArtifactState latest revision이 모두 일치하지 않으면 stale input으로 거부한다.
   - 빈 checksum과 빈/중복 segment ID도 invalid snapshot으로 거부한다.
3. deny-only `.ipriskignore` parser와 matcher를 구현했다.
   - `/mount-alias/path` 형태의 mount-absolute pattern만 허용한다.
   - `*`, `**`, `?`, comment/blank line을 지원한다.
   - negation `!`, backslash, NUL, traversal과 잘못된 relative pattern은 거부한다.
   - deny policy는 case 차이를 이용한 우회를 줄이기 위해 logical path/pattern을 casefold하여 보수적으로 적용한다.
   - VWS global deny와 ephemeral source-level deny 중 하나라도 일치하면 AnalysisArtifact를 만들지 않는다.
4. source scope 경계를 typed ephemeral input으로 구현했다.
   - `SourceScopeDecision.in_scope=false`는 모든 VWS 설정보다 우선해 deny된다.
   - source-level `.ipriskignore` text는 Gate 처리 중에만 사용하고 Firestore/ChangeEvent/Job에 저장하지 않는다.
   - 임의 raw metadata dict 대신 boolean scope와 safe denial code만 허용한다.
5. file/content/size fail-closed policy를 구현했다.
   - METADATA_ONLY, UNSUPPORTED, 빈 segment와 UNKNOWN/no-route kind는 Analyzer로 보내지 않는다.
   - image/audio/video/font/archive/binary MIME은 거부하고 text 및 제한된 textual application MIME만 허용한다.
   - DOCUMENT_TEXT에 한해서 추출된 PDF/RTF/Word MIME을 허용한다.
   - max size 판단은 신고된 snapshot byte size, SourceAccessReceipt content bytes와 실제 UTF-8 segment bytes 중 최댓값을 사용해 축소 신고 우회를 방지한다.
6. deterministic secret/credential redaction을 구현했다.
   - PEM private key block
   - `.env`/export credential line
   - quoted/unquoted common secret assignment
   - Bearer token, GitHub token과 JWT-like token
   - 모든 치환은 `[REDACTED_SECRET]` placeholder를 사용하고 `redaction_count`를 기록한다.
   - raw secret은 AnalysisArtifact, denial, SourceAccessEvent 또는 error에 포함되지 않는다.
7. deterministic data minimization을 구현했다.
   - SOURCE_CODE는 CHANGED를 우선한 뒤 CONTEXT를 포함하고 불필요한 FULL segment를 제외한다.
   - MANIFEST/LOCKFILE은 허용 input/output 한도 내 full segment를 유지할 수 있다.
   - DOCUMENT_TEXT/TEXT는 threshold 초과 시 changed/context 우선 축소를 적용한다.
   - segment 수, segment별 UTF-8 byte와 전체 output byte cap을 적용하며 multi-byte 문자를 중간에서 손상시키지 않는다.
8. static analyzer eligibility를 구현하고 Phase 5 임시 결정을 개선했다.
   - MANIFEST/LOCKFILE -> LICENSE
   - SOURCE_CODE/DOCUMENT_TEXT -> PATENT
   - TEXT -> policy가 허용할 때 PATENT
   - UNKNOWN -> none
   - Phase 5에서 보수적으로 LICENSE/PATENT를 모두 넣은 Job은 Gate 승인 transaction에서 실제 eligibility 교집합으로 축소된다.
   - repository save는 Job identity/revision 불변과 requested type의 narrowing-only를 강제해 Phase 7이 비대상 analysis type을 수용하지 않도록 한다.
9. canonical analysis input checksum을 구현했다.
   - redaction/minimization 이후 Artifact ID, revision, kind, MIME, analyzer route, content scope와 segment JSON을 canonical serialization한다.
   - SHA-256 결과를 `sha256:<hex>` 형식으로 SecurityContext에 기록한다.
   - 같은 input/policy/routing은 같은 checksum을 생성한다.
10. SourceAccessReceipt 기록을 완료했다.
    - 승인/ignore/unsupported/oversized/mismatch 여부와 무관하게 fetch가 발생한 사실을 append-only SourceAccessEvent로 기록한다.
    - event ID는 Job, 실제 Snapshot revision, access type, provider request ID, occurred_at과 byte count에서 결정적으로 생성한다.
    - repository에 direct lookup을 추가해 같은 receipt 재처리는 중복 event를 만들지 않고 다른 실제 fetch는 별도 event가 된다.
    - stale Snapshot도 Job revision이 아니라 실제 accessed revision으로 기록한다.
11. Gate denial과 Phase 5 Job 수명주기를 연결했다.
    - ignore/source scope/unsupported/type/size/no-analyzer와 stale revision은 INCONCLUSIVE/DONE으로 안전하게 종료한다.
    - policy unavailable/invalid, canonical context unavailable/mismatch와 invalid Snapshot은 FAILED/FAILED 및 safe reason으로 기록한다.
    - persisted `SECURITY_GATE:<reason>`을 인식해 동일 receipt redelivery를 idempotent하게 ACK한다.
    - 승인된 Job은 RUNNING을 유지하여 Integration Worker가 실제 Analyzer 실행 후 Phase 7 result 처리를 계속할 수 있다.
12. 신규 dependency 없이 Security Gate 및 Firestore parity test를 추가하고 전체 회귀 검증을 통과했다.

#### 구현 미완료 항목 및 사유

1. VWS `.ipriskignore` 편집 내용의 production persistence와 version 갱신 use case는 아직 구현하지 않았다.
   - Phase 6은 `(workspace_id, security_policy_version)` 기반 `SecurityPolicyResolver` port와 in-memory fake로 Gate를 독립 검증한다. 실제 PUT API, Workspace version 증가, AuditEvent와 Firestore 저장 형태는 Phase 8~9의 Security API/History 범위에서 완료한다.
2. 실제 Source Plane tracking 결과를 `SourceScopeDecision`으로 변환하는 adapter wiring은 구현하지 않았다.
   - provider branch/folder/local root scope 판정은 Agent 2 책임이다. Integration Worker는 Agent 2의 content-free 판정만 Gate의 ephemeral input으로 전달해야 한다.
3. 승인 AnalysisArtifact의 Analyzer 전달과 AnalysisResult 수용은 구현하지 않았다.
   - 실제 Intelligence 호출은 Integration/Agent 3 경계이며, result identity/status/coverage와 Risk reconciliation은 Phase 7에서 구현한다.
4. Security Gate denial의 사용자용 history/query/API projection은 구현하지 않았다.
   - canonical Job/Event safe status는 기록된다. Workspace activity, SourceAccess 조회와 사용자 문구는 Phase 8~9 범위다.
5. Security policy 변경 AuditEvent는 아직 생성하지 않는다.
   - Gate는 현재 policy를 소비하는 경계다. 정책 편집 권한, version increment와 `SECURITY_POLICY_CHANGED` event는 Phase 8~9의 원자적 update use case에서 함께 구현한다.
6. structured logging deny-list와 런타임 telemetry는 아직 구현하지 않았다.
   - Phase 6 코드에는 raw content logging 자체가 없다. logger integration과 content/token/path 회귀 검사는 Phase 12 hardening에서 완료한다.
7. 실제 Firestore Emulator production-adapter test는 계속 미실행 상태다.
   - 현재 환경에 Emulator host가 없어 1건이 skip된다. SourceAccess direct lookup과 Job narrowing은 fake Firestore transaction test를 통과했다.
8. secret filter는 deterministic accidental-forwarding 방어이며 완전한 DLP가 아니다.
   - entropy 기반 임의 secret 탐지는 false positive/negative와 비결정성이 커 MVP에 포함하지 않았다. pattern 확장은 실제 유출 사례와 test fixture를 근거로 Phase 12에서 검토한다.

#### 추가 검토가 필요한 사항

1. 이전 Phase의 “Job이 LICENSE/PATENT를 모두 요청” 결정은 Phase 6 정보로 개선했다.
   - SourceChange만으로 kind를 알 수 없다는 판단은 유지하되, Snapshot kind가 검증되는 Gate에서 Job 요청 목록을 narrowing-only로 영속한다. 이로써 AnalysisArtifact와 Phase 7 canonical Job 허용 범위가 일치한다.
2. Gate denial이 RUNNING Job을 방치하지 않도록 상태 종료 정책을 추가했다.
   - 보안/제품상 정상 skip은 INCONCLUSIVE, 재처리 가치가 있는 운영·무결성 문제는 FAILED로 분리했다. stale revision은 obsolete 작업이므로 재시도 loop 대신 INCONCLUSIVE로 종료한다.
3. `.ipriskignore`는 deny-only이므로 case-insensitive matching을 사용한다.
   - case-sensitive provider에서 의도보다 넓게 차단할 수 있지만 허용 우회보다 안전한 fail-closed 선택이다. 향후 provider별 case semantics를 도입하더라도 VWS deny가 약화되지 않는 방향만 허용한다.
4. MIME이 명시된 경우 allowlist 성격으로 처리하지만 `mime_type=None`은 artifact kind와 text segment 검증을 전제로 허용한다.
   - Frozen Contract에서 MIME은 optional이고 일부 provider가 제공하지 않을 수 있기 때문이다. Phase 12에서 실제 Connector 출력 품질을 확인해 provider/kind별 MIME 필수화를 강화할 수 있다.
5. input size는 세 독립 값 중 최댓값을 사용한다.
   - Connector가 byte_size를 잘못 축소해도 receipt 또는 실제 segment bytes가 한도를 넘으면 deny된다. 반대로 receipt가 원문 전체 access byte를 나타내고 전달 segment가 작아도 보수적으로 원문 규모 기준 deny가 적용된다.
6. redaction은 minimization보다 먼저 실행한다.
   - 최소화로 버려질 segment도 먼저 필터링하므로 향후 selection 규칙 변경이 secret을 되살리지 않는다. redaction_count는 최종 전달 segment뿐 아니라 검사한 전체 Snapshot에서 발견한 수를 뜻한다.
7. SourceAccessEvent는 실제 Snapshot revision을 기록한다.
   - stale/mismatch deny에서도 실제 읽은 revision을 숨기지 않는다. canonical Job revision과의 차이는 denial reason 및 Job state로 분리해 추적한다.
8. VWS policy content는 현재 resolver port 뒤에 있다.
   - 정확히 16개 canonical collection 제약 때문에 임의 security policy collection을 추가하지 않았다. Phase 9에서 RiskWorkspace document 내 안전한 policy value 또는 versioned external config 중 API 원자성과 audit를 만족하는 저장 형태를 재검토한다.
9. AnalysisArtifact는 의도적으로 canonical DB에 저장하지 않는다.
   - redacted/minimized content도 장기 저장 필요성이 명세에 없고 checksum으로 재현 identity를 추적할 수 있다. Analyzer 전달은 transient object로 유지한다.

#### 검증 결과

```text
pnpm run generate                                      PASS
tests/control                                          142 passed, 1 skipped
shared/contracts/tests + tests/control                 169 passed, 1 skipped
Security Gate focused tests                            18 passed
Firestore repository/security parity tests             14 passed
Python compileall                                      PASS
pip check                                              PASS
pnpm run typecheck                                     PASS
pnpm run verify:resolution                             PASS
generated files tracked diff after generation/tests   NONE
```

#### 제안 커밋 메시지

```text
feat: implement transient Security Gate
```

### 2026-08-16 — 이전 Phase 보완 및 Phase 5 완료

아래 미구현/검토 항목은 Phase 5 종료 당시의 상태다. analyzer eligibility/Job narrowing, SourceAccessEvent와 Gate denial 상태 종료 등 Phase 6에서 해결된 내용은 위 최신 로그를 우선한다.

#### 구현 완료 항목

1. Phase 3~4에서 후속 범위로 보류했던 SourceChange referential integrity를 완료했다.
   - RiskWorkspace, WorkspaceMount, SourceWorkspace, SourceConnection 존재 여부를 확인한다.
   - VWS/Mount/SourceWorkspace/Connection의 상호 ID 관계와 SourceType 일치를 검증한다.
   - Workspace, Mount, SourceWorkspace, SourceConnection이 모두 ACTIVE인 경우에만 새 변경을 처리한다.
   - 검증 실패나 revision/path 오류가 발생하면 staged Artifact/Event/Job 전체가 rollback되고 queue 호출도 발생하지 않는다.
2. content-free `SourceChangeIntakeService.register_source_change()`를 구현했다.
   - `event_fingerprint`에서 deterministic ChangeEvent ID를 만들고 unique lookup을 먼저 수행한다.
   - 신규 분석 변경은 Artifact/ArtifactState, ChangeEvent와 AnalysisJob을 같은 Unit of Work에서 commit한다.
   - AnalysisJob ID는 ChangeEvent ID에서 결정적으로 생성한다.
   - `provider_event_id`, revision, source identity 등 의미 필드가 다른 fingerprint 재사용은 collision으로 거부한다.
   - persistence commit이 성공한 뒤에만 queue를 호출한다.
3. duplicate 및 동시 전달 정책을 상태별로 고정했다.
   - PENDING/QUEUED 중복은 동일 ChangeEvent ID를 다시 enqueue하여 이전 enqueue 실패를 회복한다.
   - PROCESSING/RUNNING은 이미 worker가 소유한 것으로 보고 enqueue하지 않는다.
   - DONE/SUCCEEDED 또는 DONE/INCONCLUSIVE는 무해하게 ACK한다.
   - FAILED/FAILED는 정책이 허용하면 두 record를 원자적으로 PENDING/QUEUED로 되돌린 뒤 enqueue한다.
   - 불가능한 ChangeEvent/AnalysisJob 상태 조합은 손상된 canonical state로 보고 명시적으로 거부한다.
4. Phase 3에서 보류했던 AnalysisJob claim/finish/fail CAS와 retry 경로를 완료했다.
   - claim은 ChangeEvent와 AnalysisJob을 각각 PROCESSING/RUNNING으로 한 transaction에서 전환하고 attempt를 증가시킨다.
   - finish는 SUCCEEDED/INCONCLUSIVE와 DONE을, fail은 FAILED/FAILED 및 safe failure를 함께 기록한다.
   - 같은 terminal 요청은 idempotent하고 잘못된 상태에서의 transition은 거부한다.
   - 수동 retry도 상태 commit 후 injected TaskEnqueuer로 재큐잉하며, 이미 PENDING/QUEUED인 retry 호출은 복구 목적으로 다시 enqueue한다.
5. raw-free queue boundary를 구현했다.
   - `TaskEnqueuer.enqueue_change(change_event_id)` 외 payload surface를 노출하지 않는다.
   - 구현체는 ChangeEvent ID를 task identity로 사용해 idempotent해야 함을 protocol contract에 명시했다.
   - in-memory fake는 pending ID를 중복 제거하면서 enqueue 시도 이력과 주입 가능한 실패를 제공한다.
6. CREATE/UPDATE semantics를 구현했다.
   - 동일 `(source_workspace_id, source_artifact_id)`는 기존 canonical Artifact를 upsert한다.
   - mount alias와 provider-relative path로 logical path를 구성하고 absolute Windows/POSIX path 및 traversal을 거부한다.
   - 분석 대상 변경은 non-empty revision을 필수로 하며 ArtifactState를 AVAILABLE로 갱신한다.
7. MOVE continuity와 Phase 3~4 repository identity 규칙을 보완했다.
   - `previous_artifact`가 없거나 이전 source identity가 존재하지 않으면 MOVE를 거부한다.
   - 같은 SourceWorkspace 안에서 내부 Artifact ID와 연결된 Risk ID를 보존한 채 현재 source identity/path만 이전한다.
   - in-memory secondary index와 Firestore unique sentinel은 새 identity claim 및 이전 identity release를 같은 transaction에 수행한다.
   - 다른 SourceWorkspace로 Artifact를 이동하는 repository save는 계속 거부한다.
   - 이동 전 source identity가 새 Artifact에 재사용될 때 기존 Artifact의 보존 ID와 충돌하지 않도록 event fingerprint 기반 deterministic instance ID fallback을 적용했다.
8. DELETE semantics를 구현했다.
   - ArtifactState availability를 DELETED로 기록하고 ChangeEvent를 즉시 DONE으로 저장한다.
   - AnalysisJob과 queue 요청을 생성하지 않으며 기존 Risk lifecycle/review state를 변경하지 않는다.
   - 기존 Artifact가 없는 DELETE도 canonical tombstone Artifact를 남겨 관찰 사실과 unavailable 상태를 보존한다.
9. Phase 1 모델의 상태 불변식을 보강했다.
   - ChangeEvent의 PROCESSING/FAILED attempt 및 safe error 조건을 강제한다.
   - AnalysisJob의 QUEUED/RUNNING/terminal timestamp와 FAILED/SUCCEEDED failure 조건을 강제한다.
   - pure transition 함수가 timestamp 정규화와 허용된 상태 이동만 수행한다.
10. persistence parity와 회귀 테스트를 추가했다.
    - in-memory에서 duplicate/concurrent delivery, queue failure recovery, failed retry, MOVE/DELETE, path/revision rollback과 job lifecycle을 검증한다.
    - Firestore fake backend에서 Artifact identity sentinel 이전과 실제 SourceChangeIntakeService의 반복 수신 idempotency를 검증한다.
    - Phase 1~4 기존 suite를 포함한 전체 Control 및 Frozen Contract test를 통과했다.

#### 구현 미완료 항목 및 사유

1. Static analyzer eligibility와 artifact kind별 requested analysis type 축소는 아직 구현하지 않았다.
   - SourceChange에는 canonical ArtifactKind/content 판별 정보가 없으므로 Phase 5에서는 configured default인 LICENSE/PATENT를 결정적으로 요청한다. Phase 6 Security Gate가 SourceSnapshot의 kind/MIME/policy를 검증한 뒤 실제 analyzer eligibility를 제한한다.
2. SourceSnapshot fetch와 provider 원문 접근은 구현하지 않았다.
   - 명세대로 Agent 2 SourceAdapter와 Integration Worker의 책임이다. Agent 1은 content-free ChangeEvent ID만 queue boundary로 전달한다.
3. Cloud Tasks production adapter, queue 이름/region, retry/backoff/dead-letter 설정은 구현하지 않았다.
   - Agent 1은 SDK 독립 `TaskEnqueuer` port와 fake까지만 소유한다. 실제 adapter와 service account/config wiring은 Integration 범위다.
4. AnalysisResult별 multi-analyzer aggregate와 최종 AnalysisJob 판정은 구현하지 않았다.
   - Phase 5의 Job은 요청 목록과 실행 수명주기만 관리한다. analysis type별 result 수용, partial/provider failure 및 aggregate completion은 Phase 7에서 Risk reconciliation과 함께 완료한다.
5. SourceAccessEvent는 아직 생성하지 않는다.
   - Phase 5 intake는 원문을 읽지 않으므로 source access가 발생하지 않는다. Phase 6에서 Worker가 전달한 SourceAccessReceipt를 fetch 발생 사실 기준으로 기록한다.
6. 실제 Firestore Emulator production-adapter test는 계속 미실행 상태다.
   - 현재 환경에 `FIRESTORE_EMULATOR_HOST`가 없어 1건이 skip된다. fake backend의 Phase 5 transaction/idempotency는 통과했으며 Integration/CI가 host를 제공하면 기존 emulator gate가 실행된다.
7. transactional outbox용 별도 canonical record는 추가하지 않았다.
   - 명세가 정확히 16개 canonical collection을 고정하고 별도 queue/outbox collection을 정의하지 않는다. commit 후 enqueue 실패는 persisted PENDING/QUEUED와 동일 SourceChange redelivery 또는 명시적 retry 호출로 회복한다.

#### 추가 검토가 필요한 사항

1. queue delivery는 at-least-once이고 `change_event_id`가 유일한 task identity다.
   - commit과 외부 Cloud Tasks 호출을 하나의 transaction으로 묶지 않는다. production TaskEnqueuer는 같은 ChangeEvent ID의 반복 enqueue를 중복 작업으로 만들지 않아야 하며, worker claim CAS가 최종 중복 실행 방어선이다.
2. FAILED 자동 재처리는 현재 기본 활성화이며 횟수 제한은 application intake가 아니라 queue 운영 정책에 둔다.
   - ChangeEvent attempts는 실제 claim 횟수를 누적한다. 최대 retry/backoff/dead-letter와 운영 알림은 Integration queue config 및 Phase 12 관측성에서 확정한다.
3. MOVE는 SourceWorkspace 내부 identity continuity만 허용한다.
   - Artifact의 VWS/SourceWorkspace 경계를 넘는 이동은 새로운 canonical Artifact로 취급해야 한다. provider가 잘못된 previous identity를 전달하면 기존 Risk를 임의 연결하지 않고 거부한다.
4. 기본 Artifact ID는 기존 `(source_workspace_id, source_artifact_id)` 결정식을 유지한다.
   - 단, MOVE 이후 해제된 이전 identity가 새 파일에 재사용되면 원래 ID는 이동 Artifact가 계속 소유하므로 `(source workspace, source artifact, first event fingerprint)` 기반 보조 ID를 사용한다. 이 예외는 이동 Artifact/Risk continuity와 경로 재사용을 동시에 보장한다.
5. 알려지지 않은 Artifact의 DELETE는 tombstone을 생성한다.
   - out-of-order webhook과 최초 관찰이 DELETE인 경우에도 event와 unavailable 상태를 보존하기 위한 결정이다. Risk는 없으므로 생성·해소되지 않으며 이후 CREATE가 같은 canonical Artifact를 AVAILABLE로 되돌릴 수 있다.
6. ChangeEvent 자체를 최소 operational record로 사용하고 SourceChange마다 AuditEvent를 추가하지 않는다.
   - 현재 AuditEvent taxonomy는 VWS 운영/보안 활동 중심이며 원문 없는 source processing 이력은 ChangeEvent status/attempt/error에 기록한다. Phase 8/12에서 ANALYSIS_FAILED 운영 알림·Audit 연결을 추가한다.
7. `safe_metadata`는 Frozen Contract가 보장한 JSON-safe content-free 값만 ChangeEvent에 보존한다.
   - token/raw source/local absolute path는 Contract에서 금지되며 queue에는 metadata도 전달하지 않는다. Phase 12 logging deny-list가 이 경계를 다시 검증한다.
8. SourceChange intake의 optimistic conflict 재시도는 최대 3회다.
   - 외부 side effect 이전의 persistence 구간만 재실행하므로 안전하다. queue는 성공 commit 뒤 한 번 호출되며 duplicate redelivery는 idempotent enqueue를 수행한다.
9. package root에서는 service를 재-export하지 않고 명시적 `application.*.service` import를 사용한다.
   - repository protocol이 aggregate model을 참조하는 현재 dependency graph에서 service까지 package root에 export하면 순환 import가 생긴다. Phase 10 public facade가 Integration용 안정 surface를 제공할 예정이다.

#### 검증 결과

```text
pnpm run generate                                      PASS
tests/control                                          122 passed, 1 skipped
shared/contracts/tests + tests/control                 149 passed, 1 skipped
Phase 5 focused in-memory/Firestore tests               29 passed
Python compileall                                      PASS
pip check                                              PASS
pnpm run typecheck                                     PASS
pnpm run verify:resolution                             PASS
generated files tracked diff after generation/tests   NONE
```

#### 제안 커밋 메시지

```text
feat: implement idempotent SourceChange orchestration
```

### 2026-08-16 — 이전 Phase 보완 및 Phase 4 완료

아래 미구현/검토 항목은 Phase 4 종료 당시의 상태다. SourceChange 관계 검증, Artifact MOVE identity 이전과 AnalysisJob queue/CAS 등 Phase 5에서 해결된 내용은 위 최신 로그를 우선한다.

#### 구현 완료 항목

1. Phase 3 repository contract의 Firestore parity 경로를 보완했다.
   - 같은 `WorkspaceAdministrationService`를 in-memory와 Firestore UoW에 주입할 수 있다.
   - 두 구현이 동일한 commit, implicit rollback, lookup과 unique violation contract scenario를 통과한다.
   - Firestore 구현이 Phase 3 protocol의 모든 repository method surface를 제공함을 확인했다.
2. 정확히 16개의 canonical collection을 코드 상수로 고정했다.
   - `users`, `risk_workspaces`, `memberships`, `source_connections`, `source_workspaces`
   - `workspace_mounts`, `artifacts`, `artifact_states`, `change_events`, `analysis_jobs`
   - `risks`, `risk_evidence`, `risk_events`, `audit_events`, `source_access_events`, `notifications`
   - unique 처리나 emulator 편의를 위한 별도 collection을 추가하지 않았다.
3. 모든 canonical domain record의 strict document mapper를 구현했다.
   - 모든 document는 `schema_version=1`과 명시적 `record_kind`를 가진다.
   - unknown/missing field와 미지원 schema version을 거부한다.
   - Domain의 enum, UTC datetime, immutable safe mapping/tuple을 Firestore-compatible 값으로 변환하고 역변환 시 Domain constructor validation을 다시 통과시킨다.
   - document path ID와 record identity가 다르면 repository가 corruption으로 거부한다.
4. Phase 2~3 검토 항목이었던 Membership/Invitation persisted discriminator를 완료했다.
   - 두 record를 같은 `memberships` collection에 저장한다.
   - 각각 `membership`, `membership_invitation` record kind를 사용한다.
   - list/query는 record kind를 명시하고 잘못된 kind의 direct lookup을 거부한다.
5. Firestore에서 실제 동시 unique 삽입을 막는 deterministic unique-key sentinel을 구현했다.
   - User Google subject
   - Mount `(VWS, normalized/casefold alias)`와 SourceWorkspace 단일 Mount
   - Artifact `(source_workspace_id, source_artifact_id)`
   - ChangeEvent `event_fingerprint`
   - Risk `risk_key`
   - sentinel ID는 stable hash이며 raw unique component를 sentinel document에 중복 저장하지 않는다.
   - sentinel은 대상 canonical collection 내부의 `record_kind=unique_key` document이므로 collection 목록을 늘리지 않는다.
6. query 부재 검사만으로는 생길 수 있는 phantom unique race를 제거했다.
   - 경쟁 transaction이 같은 sentinel을 `create`하면 한 transaction만 성공한다.
   - alias rename/remove 시 이전 sentinel 해제와 신규 sentinel 획득을 Mount write와 같은 transaction에서 수행한다.
   - sentinel이 missing owner를 가리키거나 namespace/shape가 잘못되면 mapping corruption으로 거부한다.
7. Google Firestore SDK를 격리한 production backend를 구현했다.
   - `google.cloud.firestore_v1.AsyncClient`와 transaction 객체는 `backend.py` 밖으로 노출하지 않는다.
   - application/core/repository protocol은 SDK 타입을 import하지 않는다.
   - AlreadyExists, NotFound, Aborted/FailedPrecondition과 retry exhaustion을 Agent 1 repository error로 변환한다.
8. public SDK API만 사용하는 optimistic transaction session을 구현했다.
   - application read는 local cache/overlay로 read-your-writes를 제공한다.
   - 최초 document/query 결과를 expectation으로 기록한다.
   - commit callback의 Firestore transaction 안에서 모든 expectation을 다시 읽고 비교한 뒤 buffered create/set/delete를 적용한다.
   - lost update나 query phantom이 있으면 write 전에 `ConcurrencyConflictError`로 중단한다.
   - Google SDK의 private `_begin`/`_rollback` API에는 의존하지 않는다.
9. Phase 4 핵심 원자 연산을 검증했다.
   - Workspace + Owner Membership + Audit
   - invitation 생성/수락
   - Source Manager 제거 + Mount 보존/상태 전환 + Notification + Audit
   - Artifact/ArtifactState + ChangeEvent + AnalysisJob
   - Risk + RiskEvidence + append-only RiskEvent
   - optimistic Risk review projection + review event에서 stale transaction 거부
10. append-only 경계를 Firestore repository에서도 유지했다.
    - AuditEvent, SourceAccessEvent, RiskEvent는 append/list만 제공한다.
    - create 충돌은 과거 event overwrite가 아니라 unique violation이다.
11. Firestore dependency를 독자적으로 선택하고 Python 3.14.7 호환성을 확인했다.
    - `google-cloud-firestore==2.28.1` 설치/import 성공
    - package `Requires-Python >=3.10`
    - `grpcio==1.83.0` CPython 3.14 Windows wheel 설치 성공
    - 전체 dependency graph `pip check` 통과
    - Root manifest/lockfile은 수정하지 않고 Integration pin 후보만 dependency 문서에 기록했다.
12. 실제 Emulator 검증 경로를 추가했다.
    - `FIRESTORE_EMULATOR_HOST`가 설정된 경우 `AnonymousCredentials`와 격리된 test project/user ID를 사용한다.
    - production `AsyncClient -> GoogleFirestoreBackend -> Firestore UoW` 경로로 create/read transaction을 실행하고 생성 record를 정리한다.

#### 구현 미완료 항목 및 사유

1. 현재 로컬 환경에서 실제 Firestore Emulator test 실행은 완료하지 못했다.
   - `FIRESTORE_EMULATOR_HOST`, `gcloud`와 Firebase CLI가 구성되어 있지 않아 test 1건이 명시적으로 skip됐다. test 코드와 credential-free 실행 경로는 구현됐으며 Integration/CI가 Emulator host를 제공하면 자동 실행된다.
2. composite index의 실제 배포는 수행하지 않았다.
   - 필요한 query field 조합은 `REQUIRED_COMPOSITE_INDEXES`로 선언했다. `deploy/**`와 production project 설정은 Agent 1 소유 범위가 아니므로 Integration 단계에서 index 파일/배포 설정으로 반영해야 한다.
3. Root dependency pin과 lockfile 갱신은 수행하지 않았다.
   - 사용자 지시 및 Agent 소유 경계에 따라 검증 버전만 `agent-deliverables/agent-1-dependencies.md`에 기록했다. Integration 단계에서 다른 Agent package와 충돌을 검토한 뒤 반영한다.
4. 기존 Firestore document의 schema migration/backfill 도구는 구현하지 않았다.
   - 현재 프로젝트에는 production data나 이전 schema가 없으며 모든 새 document가 version 1로 시작한다. 향후 mapper version이 증가할 때 migration 계획이 별도로 필요하다.
5. 실제 `register_source_change` idempotent use case는 미구현이다.
   - Phase 4에서는 Artifact/ChangeEvent/AnalysisJob을 같은 transaction에서 저장할 primitive와 uniqueness를 완성했다. SourceChange 관계 검증, CREATE/UPDATE/MOVE/DELETE와 queue 연결은 Phase 5에서 구현한다.
6. AnalysisResult 기반 Risk set reconciliation use case는 미구현이다.
   - Risk/Evidence/Event atomic persistence는 검증했다. authoritative result 판정과 set reconcile은 Phase 7 범위다.
7. Human review API의 명시적 client version/precondition은 미구현이다.
   - 현재 UoW는 read document 전체를 재검증해 stale write를 차단한다. API request version과 safe conflict response는 Phase 8~9에서 추가한다.
8. Firestore Security Rules 및 IAM 배포는 수행하지 않았다.
   - application repository는 append-only/create-only 경계를 강제하지만, deploy-level deny 정책은 Integration 소유 설정과 production service account 설계가 필요하다.
9. pagination/cursor 기반 large collection query는 미구현이다.
   - 현재 repository protocol은 deterministic tuple 반환을 사용한다. 실제 API pagination은 Phase 9, scale/관측성 검증은 Phase 12에서 query contract를 확장한다.

#### 추가 검토가 필요한 사항

1. unique sentinel은 별도 collection 대신 해당 canonical collection에 함께 저장한다.
   - canonical collection 제한과 강한 uniqueness를 동시에 만족하는 선택이다. 따라서 sentinel이 존재하는 collection의 list query는 반드시 domain `record_kind`를 filter해야 하며, direct unique lookup만 sentinel을 읽는다.
2. unique sentinel에는 raw Google subject, event fingerprint, risk key 또는 source identity component를 저장하지 않는다.
   - stable hash document ID와 namespace/owner ID만 저장해 중복 민감 식별자 노출을 줄였다. 실제 domain document에는 명세상 필요한 canonical field가 계속 존재한다.
3. Firestore UoW는 transaction 밖에서 application read를 수행한 뒤 commit transaction 안에서 동일 document/query를 재검증한다.
   - arbitrary application callback을 SDK transaction decorator 안에서 실행하거나 SDK private API에 의존하지 않기 위한 구조다. 비교 후 write가 같은 server transaction에 있으므로 stale state는 commit되지 않는다.
4. expectation은 update timestamp가 아니라 canonical document 전체 값을 비교한다.
   - 값이 동일하게 되돌아온 경우에는 유효한 동일 상태로 간주한다. Phase 8에서 사용자에게 노출할 명시적 revision token이 필요하면 별도 version field를 도입한다.
5. strict mapper는 unknown field를 거부한다.
   - 무계획 schema drift를 조기에 드러내는 대신 rolling deployment에서 신규/구버전 reader 호환 계획이 필요하다. version 2 도입 시 dual-read 또는 순차 배포 전략을 반드시 정의한다.
6. Source Manager가 매우 많은 Mount를 소유하면 한 Firestore transaction의 read/write 한도에 접근할 수 있다.
   - 원자성 때문에 단순 batch 분할은 허용할 수 없다. Phase 9/12에서 workspace/mount 규모 제한 또는 asynchronous state-machine 전환 필요성을 실제 제품 한도와 함께 검토한다.
7. production SDK adapter의 Emulator test는 현재 환경에서 실행되지 않았다.
   - fake backend는 transaction semantics, mapper와 repository 동작을 검증하지만 wire protocol/emulator 동작을 대체하지 않는다. Integration 전에 Emulator test 통과를 필수 gate로 유지한다.
8. composite index declaration은 application query 기준 후보 목록이다.
   - Emulator/production이 equality index merge로 처리하는 항목도 있을 수 있다. 실제 index error와 query explain 결과를 확인한 뒤 최소 index만 배포한다.
9. Firestore package 2.28.1은 현재 Python 3.14.7 환경에서 설치·검증됐다.
   - Integration pin 시 Google auth/grpc/protobuf dependency가 다른 Agent와 충돌하는지 다시 확인하며, 충돌이 없으면 이 버전을 우선 반영한다.

#### 검증 결과

```text
tests/control                                          103 passed, 1 skipped
shared/contracts/tests + tests/control                 130 passed, 1 skipped
Firestore mapper/repository tests                      30 passed
Firestore emulator production-adapter test             1 skipped (host 미설정)
google-cloud-firestore                                 2.28.1 / Python >=3.10
grpcio                                                 1.83.0 CPython 3.14 wheel
pip check                                              PASS
Python compileall                                      PASS
```

#### 제안 커밋 메시지

```text
feat: implement canonical Firestore persistence
```

### 2026-08-16 — Phase 2 보완 및 Phase 3 완료

아래 미구현/검토 항목은 Phase 3 종료 당시의 상태다. Firestore mapper/persistence는 Phase 4, SourceChange 관계 검증과 AnalysisJob queue/CAS는 Phase 5에서 해결됐으므로 위 최신 로그를 우선한다.

#### 구현 완료 항목

1. Phase 2 mutation plan의 실제 원자적 적용 경로를 완성했다.
   - Workspace, Owner Membership, AuditEvent 생성을 한 Unit of Work에서 commit한다.
   - invitation 생성/수락/취소와 Membership 변환을 transaction으로 묶었다.
   - ownership transfer는 Workspace와 이전/신규 Owner Membership 및 AuditEvent를 함께 commit한다.
   - member role 변경/제거, 관련 Mount 상태, Owner Notification과 AuditEvent를 함께 commit한다.
   - Mount rename/disable/remove와 AuditEvent를 함께 commit한다.
   - 중간 unique violation 또는 domain error가 발생하면 snapshot 전체를 폐기한다.
2. Phase 2의 부분 `candidate_mounts` 입력 위험을 application service에서 제거했다.
   - caller가 Mount 목록을 제공하지 않는다.
   - role 변경/멤버 제거 transaction 안에서 `(VWS, target user)`에 해당하는 Mount 전체를 repository로 조회한다.
   - active/non-disabled owned Mount만 domain plan 규칙에 따라 `MANAGER_ACTION_REQUIRED`로 바뀐다.
3. persistence-neutral async repository protocol을 정의했다.
   - User, Workspace, Membership/Invitation, SourceConnection/SourceWorkspace metadata, Mount
   - Artifact/ArtifactState, ChangeEvent, AnalysisJob
   - Risk/RiskEvidence/RiskEvent, AuditEvent/SourceAccessEvent, Notification
   - 모든 repository는 SDK 타입 없이 domain/application 모델만 사용한다.
4. `ControlUnitOfWork`/factory protocol과 typed repository error를 정의했다.
   - explicit commit/rollback
   - record not found
   - unique constraint violation
   - optimistic concurrency conflict
   - closed transaction access
5. deterministic in-memory store를 구현했다.
   - transaction 시작 시 독립 snapshot과 base revision을 얻는다.
   - commit 시 store revision을 비교해 lost update를 거부한다.
   - commit되지 않은 context exit와 예외 경로는 전체 rollback한다.
   - 반환 목록은 ID 또는 `(occurred_at, id)` 기준으로 정렬해 테스트 결정성을 유지한다.
6. cross-record unique index를 구현했다.
   - User Google subject
   - Membership deterministic record ID
   - Mount `(risk_workspace_id, casefold(normalized_alias))`
   - SourceWorkspace의 단일 Mount
   - Artifact `(source_workspace_id, source_artifact_id)`
   - ChangeEvent `event_fingerprint`
   - Risk `risk_key`
7. identity를 구성하는 저장 필드의 변경을 차단했다.
   - Google subject, Membership VWS/User, Invitation VWS/email
   - Mount VWS/SourceWorkspace
   - Artifact source identity, ChangeEvent fingerprint, Risk key
   - 이 필드가 변경되면 기존 deterministic ID/index와 모순되므로 update가 아니라 새 identity로 처리해야 한다.
8. append-only event 경계를 API 형태로 강제했다.
   - AuditEvent, SourceAccessEvent와 RiskEvent에는 append/list만 제공한다.
   - event save/update/delete/remove API는 존재하지 않는다.
   - 중복 event ID append는 unique violation이다.
9. 자체 검토에서 발견한 `WorkspaceRepository.list_for_user()`의 잠재 오류를 보완했다.
   - 존재하지 않는 `Membership.is_active` 편의 속성 대신 canonical `MembershipStatus.ACTIVE`를 직접 검사한다.
   - active membership을 가진 사용자의 VWS만 반환하는 회귀 테스트를 추가했다.
10. 신규 dependency 없이 Phase 3 Control 테스트 11건을 추가하고 전체 검증을 통과했다.

#### 구현 미완료 항목 및 사유

1. Firestore production repository와 document mapper는 미구현이다.
   - Phase 3은 persistence-neutral contract와 fake를 완성하는 범위다. 명세의 canonical collection, transaction, document serialization과 Firestore SDK 격리는 Phase 4에서 구현한다.
2. `Membership | MembershipInvitation`의 영속 document discriminator는 미구현이다.
   - In-memory 저장소는 Python runtime type으로 두 record를 안전하게 구분한다. Firestore에서는 runtime type이 사라지므로 Phase 4 mapper가 같은 `memberships` collection 안에 명시적 `record_kind`를 기록하고 잘못된 역직렬화를 거부해야 한다.
3. In-memory/Firestore 공용 repository contract test fixture와 emulator parity 검증은 미구현이다.
   - 현재 suite는 in-memory contract와 실패 조건을 고정한다. Firestore adapter가 존재해야 같은 scenario factory를 재사용할 수 있으므로 Phase 4에서 emulator fixture와 함께 추출한다.
4. Firestore의 세부 optimistic transaction/CAS와 재시도 정책은 미구현이다.
   - In-memory fake는 store 전체 revision으로 lost update를 보수적으로 차단한다. document 단위 precondition, transaction retry와 충돌 오류 변환은 Phase 4가 담당한다.
5. Source metadata와 Mount/Artifact/ChangeEvent 사이의 전체 referential integrity는 아직 application use case로 연결하지 않았다.
   - repository는 저장과 unique index만 담당한다. 실제 SourceChange 입력 관계 검증, Mount 처리 가능 상태와 Artifact upsert 규칙은 Phase 5 intake 범위에서 transaction 안에 구현한다.
6. AnalysisJob claim/finish의 compare-and-set과 queue enqueue는 미구현이다.
   - repository의 기본 add/save/list contract만 준비했다. retry-safe orchestration과 queue payload 제한은 Phase 5 범위다.
7. Risk reconciliation과 review 단위의 세밀한 optimistic update는 미구현이다.
   - Risk/RiskEvidence/RiskEvent 저장 경계만 제공한다. AnalysisResult reconciliation은 Phase 7, human review version check는 Phase 8에서 완료한다.
8. Google OIDC가 보증한 identity와 transaction을 연결한 User upsert는 미구현이다.
   - Google subject unique/immutable 저장 규칙은 완료했지만 token 검증, last-login update와 session binding은 Phase 9 범위다.
9. 동시성 충돌의 자동 재시도는 구현하지 않았다.
   - 현재 application service는 `ConcurrencyConflictError`를 호출자에게 명시적으로 전달한다. 무조건 재시도하면 ID/시간 또는 외부 side effect를 중복 생성할 수 있으므로 Phase 4 transaction adapter 및 Phase 9 API 정책에서 idempotency가 보장된 연산만 제한적으로 재시도한다.
10. 신규 dependency 설치는 수행하지 않았다.
    - async protocol, in-memory snapshot/lock과 test는 Python 3.14.7 표준 library 및 기존 pytest로 구현 가능했다. Firestore package 선택과 실제 Python 3.14.7 호환성 검사는 Phase 4에서 수행한다.

#### 추가 검토가 필요한 사항

1. In-memory transaction은 document별 version이 아니라 store 전체 revision을 사용한다.
   - 서로 무관한 두 write도 동시에 commit하면 한쪽이 conflict가 된다. 테스트 fake에서는 lost update를 확실히 드러내는 보수적 선택이며, production 성능/충돌 범위는 Phase 4 Firestore transaction이 canonical document read set에 맞춰 제한한다.
2. SourceWorkspace는 MVP에서 동시에 하나의 Mount만 가질 수 있도록 global unique index를 두었다.
   - `SourceWorkspace -> exactly one VWS Mount` 명세를 따른 결정이다. 향후 공유 Mount 요구가 생기면 schema migration이므로 단순히 index만 제거하지 않고 identity/authorization/history 영향을 함께 검토해야 한다.
3. Mount alias uniqueness는 trim/path validation 후 Unicode casefold key를 사용한다.
   - `Backend`와 `backend`를 같은 VWS에서 충돌로 처리하고 다른 VWS에서는 허용한다. Firestore가 같은 normalization 함수를 그대로 사용하도록 Phase 4 contract test에 포함한다.
4. Deterministic identity field는 repository save에서 immutable로 취급한다.
   - key 변경을 허용해 secondary index만 옮기면 stable ID 정의와 불일치하므로 거부한다. rename이 허용되는 Mount alias는 identity가 아니라 presentation field라 예외적으로 변경 가능하다.
5. In-memory Membership/Invitation 구분은 runtime type 기반이다.
   - 이 방식은 fake 내부에서는 canonical collection을 추가하지 않고 안전하다. Phase 4에서는 명시적 discriminator와 strict mapper validation으로 대체되며, 외부 API에 discriminator 저장 형식을 노출하지 않는다.
6. append-only는 repository surface와 duplicate ID 검사로 강제했다.
   - Python object 자체는 frozen dataclass이고 과거 event를 바꾸는 save/delete method가 없다. Phase 4 Firestore security/application write path에서도 create-only semantics를 재검증해야 한다.
7. `WorkspaceAdministrationService`는 Notification이 실제 필요한지 확정하기 전에 notification ID를 할당할 수 있다.
   - 사용되지 않은 ID gap은 canonical state나 결정성에 영향을 주지 않으며 단순하고 side-effect-free한 factory를 전제로 한다. 향후 ID factory가 외부 I/O를 수행하게 해서는 안 된다.
8. repository는 cross-aggregate business rule을 임의로 중복 구현하지 않는다.
   - unique/identity/append-only invariant만 저장소가 강제하고 authorization, lifecycle과 SourceChange 관계 검증은 application/domain 계층에 유지한다.

#### 검증 결과

```text
pnpm run generate                                      PASS
shared/contracts/tests + tests/control                 100 passed
tests/control                                          73 passed
Python compileall                                      PASS
pnpm run typecheck                                     PASS
pnpm run verify:resolution                             PASS
generated files tracked diff after generation/tests   NONE
```

#### 제안 커밋 메시지

```text
feat: add transactional Control Plane repositories
```

### 2026-08-16 — Phase 1 보완 및 Phase 2 완료

아래 미구현/검토 항목은 Phase 2 종료 당시의 상태다. Phase 3에서 해결된 내용은 위 최신 로그를 우선한다.

#### 구현 완료 항목

1. 추가 검토 처리 정책을 확정했다.
   - 중대하지 않은 검토 사항은 Agent 1이 자체 판단으로 구현·검증한다.
   - 결과와 판단 근거는 답변과 이 문서에 기록한다.
   - 개발자가 다음 Phase 지시와 함께 변경 방향을 주면 해당 결정을 재검토한다.
2. Pending invitation 표현을 확정했다.
   - 새 collection을 추가하지 않는다.
   - `MembershipInvitation`을 memberships persistence boundary에 함께 저장할 domain record로 정의했다.
   - email은 trim + Unicode casefold만 수행하고 Google/Gmail별 dot·plus rewriting은 하지 않는다.
   - deterministic ID는 `VWS + normalized email`로 생성한다.
3. Invitation lifecycle을 구현했다.
   - Owner의 non-owner role 초대
   - OIDC layer가 제공하는 verified email과 invitation email 일치 검증
   - expiration 검증 후 ACTIVE Membership 생성
   - pending invitation 취소
   - OWNER 지정은 ownership transfer로만 허용
4. `authorize_vws_action`을 구현했다.
   - actor와 Membership identity 일치
   - ACTIVE Membership
   - permission mapping
   - Mount/VWS 관계
   - own-mount requirement
   - Owner-only administrative action
5. Provider authority를 Application Role과 분리했다.
   - `SOURCE_MOUNT`, source operation, reconnect, scope manage는 provider authority 재검증 필요를 반환한다.
   - Control context에 credential owner가 주어졌을 때 actor와 다르면 즉시 거부한다.
   - Owner라도 타인의 Mount scope/reconnect를 수행하지 못한다.
6. Workspace/member mutation plan을 구현했다.
   - Workspace + Owner membership + audit 생성
   - Role 변경과 direct OWNER assignment 차단
   - Ownership transfer 시 Workspace와 두 Membership 동시 변경
   - MVP에서 이전 Owner는 SOURCE_MANAGER로 유지
   - Workspace deletion은 즉시 삭제하지 않고 DELETING 상태로 전환
7. Source Manager 제거/강등 안전 처리를 구현했다.
   - Mount와 Risk history를 삭제하지 않는다.
   - 활성 custodian Mount를 `MANAGER_ACTION_REQUIRED`로 전환한다.
   - disabled Mount는 기존 상태를 보존한다.
   - Owner에게 in-app notification을 생성한다.
8. Mount 관리 plan을 구현했다.
   - Source Manager의 own-mount rename
   - Owner의 모든 Mount administrative disable/remove
   - rename 후 Mount/SourceWorkspace identity 유지
9. Phase 1~2 Control test 62개와 전체 Frozen+Control test 89개를 통과했다.

#### 구현 미완료 항목 및 사유

1. Mutation plan의 실제 저장과 원자성은 미구현이다.
   - Phase 2는 repository-independent domain decision을 완료했다. Workspace/Owner Membership/Audit, ownership transfer, member removal/Mount/Notification은 Phase 3 Unit of Work가 한 transaction으로 적용해야 한다.
2. Cross-record uniqueness와 동시성 처리는 미구현이다.
   - membership/invitation deterministic ID는 생성하지만 duplicate invite, alias collision, simultaneous ownership transfer를 저장소에서 차단하려면 Phase 3 repository compare-and-set이 필요하다.
3. Invitation acceptance에서 `verified_email`의 실제 신뢰 근원은 미구현이다.
   - domain service는 OIDC layer가 검증한 email만 받는다는 port contract를 전제로 한다. Google token 검증과 session binding은 Phase 9 범위다.
4. Source Provider의 실제 credential authority 검증은 미구현이다.
   - Control은 `provider_authority_required`와 명백한 mismatch만 판단한다. 실제 Drive/GitHub/Local authority는 Agent 2/Integration이 반드시 재검증한다.
5. Mount remove는 delete intent와 AuditEvent만 생성하며 실제 record 삭제/retention 처리는 미구현이다.
   - Risk/history 보존 규칙과 repository transaction을 함께 적용해야 하므로 Phase 3~4 범위다.
6. Workspace deletion은 DELETING projection까지만 구현됐다.
   - canonical data retention, async cleanup과 최종 DELETED 전환은 persistence/orchestration 정책이 필요한 후속 Phase다.
7. Google User upsert, session, API middleware는 미구현이다.
   - Domain authorization 입력은 이미 인증된 actor ID를 전제로 하며 OIDC/API 연결은 Phase 9에서 수행한다.
8. 신규 dependency 설치는 수행하지 않았다.
   - Phase 2도 표준 library와 기존 Contract만으로 구현 가능했다. Phase 3 역시 in-memory protocol까지는 신규 package 없이 시작할 수 있다.

#### 추가 검토가 필요한 사항

1. Phase 3 memberships repository는 `Membership | MembershipInvitation`을 같은 canonical collection에 저장하되 명시적인 record discriminator를 사용해야 한다.
   - 새 canonical collection은 만들지 않는다. mapper가 두 record를 잘못 역직렬화하지 않는 repository contract test를 추가한다.
2. Role change/member removal plan의 `candidate_mounts`는 해당 VWS에서 target user가 custodian인 Mount 전체여야 한다.
   - Phase 3 application service가 transaction 안에서 전부 조회하고 plan에 전달하도록 강제한다. 부분 목록을 caller가 임의 제공하는 public API는 만들지 않는다.
3. Invitation accept의 expiration check와 duplicate Membership 생성은 같은 transaction에서 재검증해야 한다.
   - pure plan의 시간 검증만으로 concurrent accept를 막을 수 없으므로 Phase 3 compare-and-set 대상이다.
4. Ownership transfer 시 이전 Owner를 SOURCE_MANAGER로 유지하기로 결정했다.
   - 기존 provider/Mount custodianship을 잃지 않는 보수적 MVP 정책이다. 다른 role이 필요하면 개발자의 후속 지시와 함께 변경한다.
5. Email normalization은 provider-independent casefold만 사용한다.
   - Gmail dot/plus 규칙을 application identity에 적용하면 다른 provider/domain 의미를 훼손할 수 있으므로 사용하지 않는다.
6. Authorization denial은 현재 typed reason과 exception을 제공한다.
   - Phase 9 API error category 매핑 시 raw membership/provider 정보를 노출하지 않도록 safe message table을 별도로 둔다.

#### 검증 결과

```text
shared/contracts/tests + tests/control                 89 passed
tests/control                                          62 passed
Python compileall                                      PASS
pnpm run typecheck                                     PASS
pnpm run verify:resolution                             PASS
generated files tracked diff after tests              NONE
```

#### 제안 커밋 메시지

```text
feat: implement VWS authorization and workspace control policies
```

### 2026-08-16 — Phase 0 보완 및 Phase 1 완료

아래 미구현/검토 항목은 Phase 1 종료 당시의 상태다. Phase 2에서 해결된 내용은 위 최신 로그를 우선한다.

#### 구현 완료 항목

1. Frozen Contract 공식 생성 정책을 확정하고 `pnpm run generate`를 실행했다.
2. Pydantic source 변경 없이 생성 schema/TypeScript 파일에 tracked diff가 없음을 생성 직후와 결정성 test 이후 각각 확인했다.
3. Python 3.14.7, Node.js 24.19.0, pnpm 11.19.0 기준 명령을 확정했다.
4. Domain 공통 기반을 구현했다.
   - non-empty identifier/name validation
   - timezone-aware datetime의 UTC 정규화와 시간 순서 검증
   - `DomainInvariantError`
   - JSON-safe metadata의 재귀 validation과 immutable freeze
   - component ambiguity가 없는 versioned SHA-256 stable key
5. Control canonical entity/state를 구현했다.
   - User, RiskWorkspace, Membership/Role/Permission
   - SourceConnection metadata, SourceWorkspace metadata, WorkspaceMount
   - Artifact, ArtifactState, ChangeEvent, AnalysisJob
   - Risk, RiskEvidence, RiskEvent
   - AuditEvent, SourceAccessEvent, Notification
6. stable identity를 구현했다.
   - Artifact: `source_workspace_id + source_artifact_id`
   - ChangeEvent: `event_fingerprint`
   - Patent Risk: `artifact_id + normalized_application_number`
   - License Risk: artifact/ecosystem/package/resolution-state/version/license expression
7. Machine lifecycle와 Human review를 분리한 순수 decision 함수를 구현했다.
   - `SUCCEEDED + COMPLETE`만 authoritative
   - incomplete/failure에서는 기존 Risk 유지 및 신규 Risk 생성 차단
   - DETECTED, CONFIRMED, RESOLVED, REOPENED 결정
   - review disposition 변경은 lifecycle input/output을 갖지 않음
8. raw-source permission이 없는 4단계 Role permission hierarchy를 정의했다.
9. System AuditEvent와 User-authored event의 actor invariant를 분리했다.
10. Phase 1 Control test 32개와 전체 Frozen+Control test 59개를 통과했다.

#### 구현 미완료 항목 및 사유

1. Google identity User upsert와 OIDC flow는 미구현이다.
   - Phase 1은 entity와 invariant만 다루며, 실제 login/provider/session use case는 Phase 2와 Phase 9 범위다.
2. Membership invitation의 pending email 처리 방식은 미구현이다.
   - 현재 Membership은 canonical `user_id`를 요구한다. 아직 가입하지 않은 email 초대를 placeholder User로 표현할지 pending Membership metadata로 표현할지는 Phase 2 use case와 canonical persistence 제약을 함께 검토해야 한다.
3. SourceWorkspace 단일 VWS Mount, Mount alias uniqueness와 Google `sub` uniqueness는 저장소 수준에서 아직 강제되지 않는다.
   - entity 하나만으로 cross-record uniqueness를 판정할 수 없으며 Phase 3 repository transaction/unique-key 전략이 필요하다.
4. ChangeEvent와 AnalysisJob은 상태 모델만 존재하며 intake, claim, retry, queue enqueue 동작은 미구현이다.
   - SourceChange orchestration은 Phase 5 범위다.
5. Risk transition은 단일 candidate에 대한 순수 결정만 제공하며 Risk set reconciliation, Evidence retention, append transaction은 미구현이다.
   - repository/transaction과 AnalysisResult intake가 필요한 Phase 7 범위다.
6. DELETE/MOVE 처리, Source Manager 제거 후 Mount 상태 전환, append-only repository 강제는 미구현이다.
   - 각각 Phase 5, Phase 2, Phase 3에서 cross-aggregate use case로 구현한다.
7. Security Gate, Firestore, API, frontend는 미구현이다.
   - Phase 4 이후의 독립 범위이며 Phase 1에 외부 SDK dependency를 도입하지 않았다.
8. 신규 dependency 설치는 수행하지 않았다.
   - Phase 0~1 구현은 Python 표준 library, 기존 Pydantic/pytest와 Frozen Contract만으로 완결됐다. 각 package는 최초 사용 Phase에서 실제 호환성을 검사해 선택한다.

#### 추가 검토가 필요한 사항

1. Phase 2의 transactional workspace/membership use case가 Phase 3 repository protocol보다 먼저 계획돼 있다.
   - Phase 2에서는 authorization와 aggregate policy를 순수 service로 우선 구현하고, 필요한 최소 port signature를 정의한다. 실제 atomic repository 구현과 전체 Unit of Work는 Phase 3에서 완성하는 방식으로 경계를 유지한다.
2. Pending invitation의 canonical 표현을 결정해야 한다.
   - 새 canonical collection을 임의 추가할 수 없으므로 기존 `memberships` collection 안에서 명확한 deterministic ID와 status를 사용할 수 있는지 우선 검토한다. Frozen Contract 변경은 필요하지 않을 것으로 예상한다.
3. JSON-safe metadata는 domain에서 `MappingProxyType`과 tuple로 immutable하게 보관된다.
   - Phase 4 Firestore mapper는 이를 JSON-compatible dict/list로 명시적으로 변환하고, 역직렬화 시 다시 domain validation을 통과시켜야 한다.
4. Stable key는 `v1` hash format을 사용한다.
   - persistence 이후 format 변경은 identity migration이 되므로 Phase 3 deterministic document ID 설계 시 현재 format을 재확인하고 고정한다.
5. Risk review priority는 Frozen Contract의 `ReviewPriority`를 재사용한다.
   - Intelligence의 suggested priority를 Control projection에 반영하는 정책은 Phase 7에서 deterministic mapping/update rule로 확정해야 한다.
6. Windows Git은 generated LF 파일에 CRLF 경고를 출력하지만 실제 tracked diff는 0이다.
   - 생성 결과의 correctness 판단은 경고가 아니라 `git diff --exit-code -- shared/contracts/schemas shared/contracts/typescript/generated/contracts.ts` 결과로 유지한다.

#### 검증 결과

```text
pnpm run generate                                      PASS
shared/contracts/tests + tests/control                 59 passed
tests/control                                          32 passed
Python compileall                                      PASS
pnpm run typecheck                                     PASS
pnpm run verify:resolution                             PASS
generated files tracked diff after generation/tests   NONE
```

#### 제안 커밋 메시지

```text
feat: establish Control Plane domain models and invariants
```
