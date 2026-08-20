# Agent 1 — Platform & Control Plane 통합 참조

> 문서 상태: Agent 1 분산 문서 통합본
> 코드 기준: `platform-control` merge 결과 (`de1dacce05474d4e3e6c7c2567f6b8a6bbdbeb64`)
> 적용 branch: `integration-v2`
> 최종 dependency 결정: [`../INTEGRATION_V2_DEPENDENCY_BASELINE.md`](../INTEGRATION_V2_DEPENDENCY_BASELINE.md)
> 전체 조립 계획: [`../INTEGRATION_V2_EXECUTION_PLAN.md`](../INTEGRATION_V2_EXECUTION_PLAN.md)

이 문서는 Agent 1의 인계, 구현 추적, dependency 요청과 로컬 실행 가이드를 하나로 정리한 유지 문서다. 과거 agent 검증값과 현재 통합 결정이 다르면 두 통합 기준 문서가 우선한다.

## 1. 통합한 원본과 보존 범위

| 원본 | 이 문서에 흡수한 내용 |
|---|---|
| `AGENT_1_DELIVERY.md` | 최종 구현 범위, public surface, wiring, 환경, 검증, 제약 |
| `AGENT_1_PLATFORM_CONTROL_IMPLEMENTATION_PLAN.md` | Phase 0~13 최종 상태, 구조, 불변식, 완료 정의와 주요 판단 |
| `agent-deliverables/agent-1-dependencies.md` | Agent 1이 검증한 package/runtime 후보와 환경 요청 |
| `LOCAL_RUN_AND_TEST_GUIDE.md` | local setup, focused scenario, 승인 명령과 실패 판정 |

날짜별 반복 progress log와 제안 commit message는 프로젝트 실행 정보가 아니므로 그대로 복제하지 않았다. 대신 최종 상태, 남은 제약과 재현 가능한 검증 명령을 보존했다. 원본은 전체 통합 검증이 끝나는 Phase 8 전까지 삭제하지 않는다.

## 2. 역할과 절대 경계

Agent 1은 다음을 제공한다.

- canonical Control domain과 lifecycle
- Google App Login, user/session, VWS membership와 RBAC
- SourceConnection, SourceWorkspace, WorkspaceMount의 canonical metadata
- SourceChange intake, Artifact/ChangeEvent/AnalysisJob orchestration
- Security Gate, minimization, redaction과 source access audit
- AnalysisResult 검증, Risk/RiskEvidence/RiskEvent reconciliation
- Human review, history, audit, notification
- Firestore repository/transaction implementation
- Control REST API와 Product Web UI
- structured safe observability
- Integration이 사용할 단일 public facade와 UI integration slot

Agent 1이 제공하지 않는 것:

- Drive/GitHub provider API 및 credential 처리
- local filesystem 접근과 Electron shell
- Gemini/KIPRIS/RAG/SPDX provider 구현
- 실제 Cloud Tasks adapter
- 최종 `composition/**`, `main.py`, `worker.py`, deploy와 root manifest/lock
- GCP console/resource 구성

### 유지해야 할 불변식

- raw source와 `SourceSnapshot`을 장기 저장하지 않는다.
- provider credential/token을 contract, canonical metadata, task, log에 넣지 않는다.
- Gate가 승인한 `AnalysisArtifact`만 Intelligence로 보낸다.
- backend authorization이 최종 권한 판단자다.
- Control RBAC 통과와 provider authority 통과를 별도로 검증한다.
- FAILED, INCONCLUSIVE, PARTIAL, NONE 및 DELETE는 기존 Risk를 자동 resolve하지 않는다.
- human `EXCLUDED`와 machine `RESOLVED`를 같은 상태로 취급하지 않는다.
- RiskEvent는 append-only이며 reconciliation은 transaction으로 처리한다.

## 3. 구현 상태

Agent 1 내부 Phase 0~13은 완료 상태로 인계됐다.

| 영역 | 상태 | 대표 검증 |
|---|---|---|
| Domain/RBAC/VWS/Mount | 완료 | model, transition, permission matrix |
| Repository/in-memory transaction | 완료 | repository/unit-of-work tests |
| Firestore persistence | 완료 | mapper/repository tests, emulator 선택 test |
| SourceChange/AnalysisJob | 완료 | idempotency, retry, concurrency tests |
| Security Gate | 완료 | approve/deny/minimize/redact tests |
| Risk reconciliation | 완료 | status/coverage/evidence/lifecycle tests |
| Review/history/audit/notification | 완료 | service/API tests |
| Google OIDC/Control API | 완료 | router/session/CSRF/error tests |
| Public facade | 완료 | delivery contract/facade tests |
| Product Web UI | 완료 | component/client/pagination/capability tests |
| Observability/hardening | 완료 | safe error/log deny-list/host/CORS tests |

여기서 “완료”는 Agent 1 독립 범위가 완료됐다는 뜻이다. Cloud Tasks, Source/Intelligence 연결, final app/worker와 실 GCP 검증은 Integration 범위다.

## 4. 코드 지도

```text
backend/src/ip_risk_agent/
  core/
    artifacts/ auth/ audit/ memberships/ mounts/
    notifications/ risk/ workspaces/
  application/
    auth/ workspace_admin/ repositories/
    process_change/ analysis_jobs/ security_gate/
    risk_reconcile/ risk_review/ history/
    notifications/ security_policy/ public_facade/
  persistence/core_firestore/
  api/

frontend/src/
  app/ auth/ workspace/ risk/ history/ security/ shared/

tests/control/
```

Integration은 Plane 내부 service/repository를 임의 조합하기 전에 public facade와 공개 API factory로 해결 가능한지 먼저 확인한다.

## 5. Integration public surface

권장 import:

```python
from ip_risk_agent.application.public_facade import (
    ControlPlaneFacade,
    ControlPlaneFacadeConfig,
    CorrelationIds,
    PublicVwsAction,
    SourceAccessReceiptContext,
    SourceAuthorizationCallback,
    SourceMetadataRegistrationCallback,
    SourceMetadataRegistrationCommand,
    SourceScopeInput,
    StructuredEventSink,
    StructuredLogger,
)
```

### `ControlPlaneFacade`

```python
ControlPlaneFacade(
    *,
    unit_of_work_factory,
    task_enqueuer,
    clock,
    id_factory,
    config: ControlPlaneFacadeConfig,
    observer: StructuredLogger | None = None,
)
```

| Method | Input/meaning |
|---|---|
| `authorize_vws_action` | actor/VWS/action, optional mount/provider owner |
| `register_source_metadata` | stable-key canonical source metadata command |
| `register_source_change` | frozen `SourceChange`; persist/idempotency/enqueue |
| `claim_analysis` | content-free `change_event_id` claim |
| `fail_analysis` | safe failure로 running execution 종료 |
| `retry_failed_analysis` | failed execution 재queue |
| `register_source_access` | content-free provider access receipt 기록 |
| `build_analysis_artifact` | transient snapshot을 Gate 처리 |
| `accept_analysis_result` | result 검증 및 Risk reconciliation |
| `get_mount_ref` | canonical mount lookup |
| `get_source_workspace_context` | source workspace/connection context lookup |
| `get_original_source_request` | 권한을 재검증한 Open Original 요청 |

`tests/control/test_delivery_contract.py`가 이 공개 surface와 index manifest drift를 감지한다.

### Integration에서 보강할 public gap

현재 claim DTO만으로 worker가 `SourceAdapter.fetch_snapshot(SourceChange)`에 필요한 원본 metadata-only `SourceChange`를 복구할 수 없다. Integration 실행 계획의 P0-1에 따라 canonical ChangeEvent/claim read model을 보강한다. Control 내부 repository를 worker가 직접 import하는 우회는 허용하지 않는다.

또한 worker crash 및 Cloud Tasks 재전달을 위한 bounded lease/reclaim 의미가 필요하다. 이는 P0-2에서 facade/service 상태 전이를 최소 확장하고 Control 회귀 test로 고정한다.

## 6. Canonical state와 Source 등록

`SourceMetadataRegistrationCommand`의 핵심 필드:

```text
registration_key, actor_user_id, risk_workspace_id, source_type,
connection_key, source_workspace_key, external_scope_id,
source_workspace_display_name, mount_alias,
provider_subject?, provider_account_label?, credential_ref?,
tracking_config_safe
```

규칙:

- 세 stable key는 retry 동안 동일해야 한다.
- `credential_ref`는 compact opaque reference만 허용한다.
- `tracking_config_safe`에서 token/secret/password 등 민감 key는 거부된다.
- active user/workspace와 `SOURCE_MOUNT` 권한이 필요하다.
- Control이 deterministic connection/workspace/mount ID를 만든다.

Source OAuth callback과 mount 선택 시점이 분리된 문제는 Integration의 persistent pending connection으로 해결한다. placeholder canonical mount를 만들지 않는다.

## 7. Change/Analysis/Risk 상태 의미

```text
SourceChange
 -> Artifact upsert + ChangeEvent(PENDING)
 -> AnalysisJob(QUEUED)
 -> claim: PROCESSING/RUNNING
 -> Security Gate
 -> AnalysisResult per requested type
 -> aggregate terminal state
 -> Risk/RiskEvidence/RiskEvent transaction
```

### Idempotency

- `event_fingerprint`는 unique다.
- duplicate pending은 동일 task ID를 재사용할 수 있다.
- processing/done duplicate는 새 Risk를 만들지 않는다.
- retry 가능한 failed event는 정책에 따라 재처리한다.
- DELETE는 job을 만들지 않고 Risk를 resolve하지 않는다.

### Result aggregate

모든 `requested_analysis_types`의 outcome이 모이기 전 job은 terminal이 아니다.

- 하나라도 FAILED면 job/event FAILED
- 모두 SUCCEEDED+COMPLETE면 SUCCEEDED
- 그 밖의 완결된 result set은 INCONCLUSIVE

Integration worker는 Intelligence가 일부 analyzer를 조용히 누락하지 못하도록 requested/result type 집합을 대조해야 한다.

## 8. Security Gate와 retention

Facade가 기본적으로 Gate를 내부 조립한다. 설정 entrypoint:

- `ControlPlaneFacadeConfig.security_gate: SecurityGatePolicyConfig`
- `ControlPlaneFacadeConfig.evidence_retention: EvidenceRetentionConfig`
- `ControlPlaneFacadeConfig.requested_analysis_types`

Gate 순서:

1. canonical VWS/mount/source/job 관계 검증
2. source-level scope와 canonical VWS ignore policy 결합
3. input size/MIME/kind 제한
4. redaction/minimization
5. eligible analyzer 계산
6. approved `AnalysisArtifact` 생성 또는 terminal deny
7. content-free SourceAccessEvent 기록

Evidence/excerpt/reference/metadata/failure message는 bounded retention policy를 적용한다.

## 9. Firestore wiring

Production 조립:

```python
from google.cloud.firestore_v1 import AsyncClient
from ip_risk_agent.persistence.core_firestore import (
    FirestoreControlUnitOfWorkFactory,
)

client = AsyncClient(project=project_id, database=database_id)
uow_factory = FirestoreControlUnitOfWorkFactory.from_client(
    client,
    max_attempts=5,
)
```

`CANONICAL_COLLECTIONS`가 canonical collection 목록, `REQUIRED_COMPOSITE_INDEXES`가 query 요구사항의 코드 기준이다. Integration은 이를 실제 deploy format으로 변환하고 emulator/production query로 검증한다.

주요 composite index 요구:

| Collection | Fields |
|---|---|
| memberships | `record_kind`, `risk_workspace_id` |
| memberships | `record_kind`, `user_id`, `status` |
| memberships | `record_kind`, `email` |
| workspace_mounts | `record_kind`, `risk_workspace_id` |
| workspace_mounts | `record_kind`, `risk_workspace_id`, `mounted_by_user_id` |
| risks | `record_kind`, `artifact_id`, `analysis_type`, `lifecycle_state` |
| risks | `record_kind`, `risk_workspace_id` |
| change_events | `risk_workspace_id` |

## 10. Control API 조립

공개 factory:

```python
from ip_risk_agent.api import ControlApiDependencies, create_control_api_bundle

bundle = create_control_api_bundle(ControlApiDependencies(...))
bundle.install(app)
```

`ControlApiDependencies`:

```text
auth, workspaces, risks, history, security, notifications,
session, hardening, observer
```

필요 application services:

- `AuthenticationService`
- `WorkspaceAdministrationService`
- `RiskReviewService`
- `HistoryQueryService`
- `NotificationService`
- `WorkspaceSecurityService`
- `CursorCodec`
- `AuthlibGoogleOidcClient` + `GoogleOidcConfig`

Production hardening:

- exact trusted host와 HTTPS origin
- credentialed wildcard CORS 금지
- 최소 32자 session/cursor secret
- signed session version validation
- mutation CSRF guard
- safe error handler
- forwarded header/proxy trust는 Integration/deploy에서 명시
- built-in process-local limiter를 global quota로 오인하지 않음

## 11. Frontend integration surface

```tsx
import { ControlPlaneApp } from "@iprisk/frontend";

<ControlPlaneApp
  apiBaseUrl=""
  router="browser"
  integration={{ sourceNavigation, sourcePanel, openOriginal }}
/>
```

- Web은 browser router, Electron renderer는 hash router를 지원한다.
- `sourceNavigation`/`sourcePanel`이 Source UI slot이다.
- `openOriginal`이 없으면 button은 fail closed한다.
- callback에는 VWS/Artifact ID, action, safe source type만 전달한다.
- backend는 `get_original_source_request()`로 권한을 다시 검사한다.
- production API는 same-origin `/api/v1`을 사용한다.

## 12. Agent 검증 dependency 이력

Agent 1이 독립 branch에서 검증한 핵심 후보:

| 영역 | 검증값 |
|---|---|
| Python | 3.14.7 |
| Pydantic | 2.13.4 |
| Firestore | 2.28.1 |
| FastAPI | 0.141.1 |
| Authlib | 1.7.2 |
| HTTPX | 0.28.1 |
| itsdangerous | 2.2.0 |
| pytest | 9.1.1 |
| httpx2 | 2.10.0 |
| React/React DOM | 19.2.8 |
| React Router DOM | 7.18.2 |
| TypeScript | 5.9.3 |
| Vite/Vitest | 8.2.1 / 4.1.10 |

정확한 통합 direct set은 dependency baseline을 따른다. Agent 1은 Uvicorn, Cloud Tasks, Secret Manager, GCS package를 최종 선택하지 않았으며 Integration이 추가한다.

## 13. 환경 변수

Agent 1이 요구한 이름:

```text
GOOGLE_LOGIN_CLIENT_ID
GOOGLE_LOGIN_CLIENT_SECRET
GOOGLE_LOGIN_REDIRECT_URI
SESSION_SECRET
APP_PUBLIC_BASE_URL
GCP_PROJECT_ID
FIRESTORE_DATABASE
FIRESTORE_EMULATOR_HOST        # test only
```

최종 통합 env group과 production validation은 dependency baseline §10과 실행 계획을 따른다.

## 14. 검증 증거와 재실행

Agent 1 인계 시점 결과:

- delivery/public/index contract: 4 passed
- shared contract + Agent 1 Python: 286 passed, 1 skipped
- frontend: 15 passed
- typecheck, resolution, production build 통과
- Python 3.14.7 compileall 및 pip check 통과
- contract generate 후 tracked diff 없음
- Firestore emulator는 env 미설정 시 1건 skip

통합 후 공식 결과로 다시 대체해야 한다. 기본 명령:

```powershell
pnpm run generate
python -m pytest shared/contracts/tests tests/control -q
python -m compileall -q backend/src shared/contracts/python scripts
python -m pip check
pnpm run typecheck
pnpm run build
pnpm run verify:resolution
pnpm --filter @iprisk/frontend test
```

Focused scenario:

- in-memory SourceChange→Gate→Result→Risk 및 concurrency
- Role/API/UI capability 일치
- secret/log deny-list와 safe error
- workspace/risk/review/history/security API 회귀
- frontend pagination 및 Source integration slot
- optional Firestore emulator transaction/index
- contract generation 결정성

## 15. Integration 의무와 known constraints

### Integration에서 반드시 구현/검증

- root dependency와 lock 수렴
- Firestore/UoW, Cloud Tasks, safe log sink 조립
- Source authz/callback/store/router 연결
- Worker의 ID-only claim, lease/retry/crash recovery
- Gate 뒤 Intelligence 연결과 analyzer result-set 완결성
- final API/Worker lifespan과 IAM
- frontend Source slot/Open Original
- Firestore deploy index
- browser/worker end-to-end
- failure-preserves-risk와 raw-source 비영속 검증

### 알려진 제약

- source metadata facade는 create/idempotent 중심이며 reconnect/rotation/status transition은 추가 조율이 필요하다.
- signed offset pagination은 live write 중 native cursor와 다른 특성이 있다.
- Dashboard failed count는 canonical read이며 scale 근거 없이 projection을 추가하지 않았다.
- Risk list cache는 request scope다.
- RiskEvent는 cryptographic hash chain이 아니다.
- legacy data가 있을 때만 session version/global ignore backfill이 필요하다.
- 초대형 UI table virtualization은 실제 profile 이후 과제다.

이 제약을 보완할 때도 본 문서 §2의 불변식을 유지한다.

## 16. Phase 8 원본 삭제 확인표

Phase 8에서 아래 mapping을 확인한 뒤 원본을 삭제한다.

| 원본 | 대체 section |
|---|---|
| delivery | §2~15 |
| implementation plan | §2~4, §14~15 |
| dependency request | §12~13 |
| local run guide | §14 |

삭제 전 build/test/운영 절차의 원본 파일명 참조를 이 문서 또는 최종 운영 문서로 교체한다. 보호 대상 명세·기준 문서와 provenance/history 구간의 과거 참조는 실행 경로가 아님을 확인한 뒤 보존할 수 있다.
