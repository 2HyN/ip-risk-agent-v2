# Agent 1 — Platform & Control Plane 인계 문서

## 1. 인계 상태와 구현 범위

- 상태: Phase 0~13 구현 완료, Integration 조립 준비 완료
- 기준 런타임: CPython 3.14.7, Node.js 24.19.0, pnpm 11.19.0
- 기준 branch: `platform-control`
- Agent 1은 commit/push를 수행하지 않는다.

Agent 1은 canonical Control domain, RBAC와 provider authority 경계, Firestore persistence, SourceChange/AnalysisJob orchestration, Security Gate, AnalysisResult/Risk reconciliation, human review/history/audit/notification, Google App Login, Control API, Product Web UI와 structured observability를 제공한다.

Provider API/credential 처리, local filesystem 접근, analyzer/Gemini/KIPRIS/RAG, Cloud Tasks adapter, 최종 FastAPI app/worker 조립과 배포 설정은 Agent 1 범위가 아니다. Control Plane은 raw source를 장기 저장하거나 HTTP API로 proxy하지 않는다.

## 2. 변경 파일 목록

Agent 1 branch가 공통 기준 이후 추가·수정한 범위는 다음과 같다.

| 경로 | 내용 |
|---|---|
| `backend/src/ip_risk_agent/core/**` | canonical entity, identity, lifecycle, RBAC, workspace/mount policy |
| `backend/src/ip_risk_agent/application/**` | auth, administration, intake/jobs, Gate, reconciliation, review/history/notification, facade, observability |
| `backend/src/ip_risk_agent/persistence/core_firestore/**` | mapper, transaction/session, repository, unique key, schema/index manifest |
| `backend/src/ip_risk_agent/api/**` | OIDC/session, Control routers, cursor, error handling, hardening, API bundle |
| `frontend/**` | Agent 1 React/Vite Product Web UI와 public integration slot |
| `tests/control/**` | domain부터 API/E2E/stress/delivery contract까지 Agent 1 검증 |
| `AGENT_1_PLATFORM_CONTROL_IMPLEMENTATION_PLAN.md` | 전체 구현 현황과 판단 기록 |
| `agent-deliverables/agent-1-dependencies.md` | 검증 dependency와 Integration 요청 |
| `LOCAL_RUN_AND_TEST_GUIDE.md` | 삭제 가능한 상세 로컬 실행/시나리오 가이드 |
| `AGENT_DELIVERY.md` | 본 최종 인계 문서 |

수정하지 않은 경계: Frozen Pydantic source, Agent 2/3 소유 코드, `frontend/src/sources/**`, `apps/desktop/**`, Integration의 `composition/**`/`main.py`/`worker.py`, root dependency manifest/lock. 공식 생성 결과에도 tracked diff가 없다.

## 3. 안정된 Integration public surface

Integration과 다른 Plane은 가능한 한 다음 public module만 import한다.

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

`ControlPlaneFacade` 생성자:

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

공개 async method signature:

| 메서드 | 입력 |
|---|---|
| `authorize_vws_action` | `*, actor_user_id, risk_workspace_id, action, mount_id=None, provider_credential_owner_user_id=None` |
| `register_source_metadata` | `command: SourceMetadataRegistrationCommand` |
| `register_source_change` | `change: SourceChange` |
| `claim_analysis` | `change_event_id: str` |
| `fail_analysis` | `change_event_id: str, *, failure_safe: str` |
| `retry_failed_analysis` | `change_event_id: str` |
| `register_source_access` | `context: SourceAccessReceiptContext` |
| `build_analysis_artifact` | `snapshot: SourceSnapshot, analysis_job_id: str, *, source_scope=None` |
| `accept_analysis_result` | `result: AnalysisResult` |
| `get_mount_ref` | `mount_id: str` |
| `get_source_workspace_context` | `source_workspace_id: str` |
| `get_original_source_request` | `*, actor_user_id, risk_workspace_id, artifact_id` |

`tests/control/test_delivery_contract.py`가 핵심 생성자, callback, queue, API factory와 index manifest의 드리프트를 탐지한다.

## 4. Repository와 facade 조립

Production repository constructor:

```python
from google.cloud.firestore_v1 import AsyncClient

from ip_risk_agent.application.public_facade import (
    ControlPlaneFacade,
    ControlPlaneFacadeConfig,
    StructuredLogger,
)
from ip_risk_agent.persistence.core_firestore import (
    FirestoreControlUnitOfWorkFactory,
)

client = AsyncClient(project=gcp_project_id, database=firestore_database)
uow_factory = FirestoreControlUnitOfWorkFactory.from_client(
    client,
    max_attempts=5,
)
observer = StructuredLogger(integration_safe_sink)
facade = ControlPlaneFacade(
    unit_of_work_factory=uow_factory,
    task_enqueuer=cloud_tasks_enqueuer,
    clock=utc_clock,
    id_factory=id_factory,
    config=ControlPlaneFacadeConfig(),
    observer=observer,
)
```

- `clock()`은 timezone-aware UTC `datetime`을 반환한다.
- `id_factory(kind)`는 non-empty opaque ID를 반환하며 외부 I/O를 수행하지 않는다.
- `TaskEnqueuer.enqueue_change(change_event_id: str) -> None`은 raw-free ID 하나만 받고 같은 ID를 de-duplicate해야 한다.
- fake wiring 예제는 `tests/control/test_public_facade.py`, 전체 fake pipeline은 `tests/control/test_phase12_stress_and_e2e.py`에 있다.

## 5. Source Plane callback과 pipeline

Source router에는 bound method를 protocol로 주입한다.

```python
authorization: SourceAuthorizationCallback = facade.authorize_vws_action
register_metadata: SourceMetadataRegistrationCallback = facade.register_source_metadata
```

Source metadata 등록에는 token이 아닌 opaque `credential_ref`와 content-free metadata만 넣는다. `registration_key`, `connection_key`, `source_workspace_key`는 retry 동안 동일해야 하며 Control이 deterministic canonical ID로 변환한다. `provider_authority_required=True`는 Control RBAC 통과만 의미한다. Source Plane/provider는 실제 credential과 원본 접근 권한을 다시 검증해야 한다.

권장 pipeline 순서:

```python
registration = await facade.register_source_change(source_change)
claim = await facade.claim_analysis(registration.change_event_id)
if claim is None:
    return

try:
    snapshot = await source_adapter.fetch_snapshot(source_change)
except Exception:
    await facade.fail_analysis(
        registration.change_event_id,
        failure_safe="PROVIDER_UNAVAILABLE",
    )
    raise

gate = await facade.build_analysis_artifact(
    snapshot,
    claim.analysis_job_id,
    source_scope=SourceScopeInput(in_scope=True),
)
if not gate.approved:
    return

for analyzer in analyzer_registry.supporting(gate.analysis_artifact):
    result = await analyzer.analyze(gate.analysis_artifact)
    await facade.accept_analysis_result(result)
```

실패를 empty success/zero candidate로 바꾸면 안 된다. retry 허용 시 `retry_failed_analysis(change_event_id)`가 같은 content-free ID만 재enqueue한다. Source adapter가 Gate 전에 access receipt를 얻는 구조라면 `register_source_access()`를 호출한다.

## 6. Security Gate constructor/config

Integration은 보통 facade가 내부 조립한 Gate를 사용한다. 별도 조립이 꼭 필요한 경우 signature는 다음과 같다.

```python
SecurityGateService(
    *,
    unit_of_work_factory,
    policy_resolver,
    clock,
    concurrency_attempts=3,
    use_canonical_workspace_policy_text=False,
)
```

정책 threshold는 `ControlPlaneFacadeConfig.security_gate: SecurityGatePolicyConfig`, Evidence 제한은 `.evidence_retention: EvidenceRetentionConfig`로 설정한다. VWS `.ipriskignore` 원문과 version은 canonical workspace security API가 관리하며 facade는 canonical policy text를 사용한다. `SourceSnapshot`은 transient이고 persistence에는 승인된 최소 `AnalysisArtifact`, content-free access event, bounded Evidence만 남는다.

## 7. Control API router factory 조립

공개 factory:

```python
from ip_risk_agent.api import (
    ApplicationHardeningConfig,
    ApplicationSessionConfig,
    ControlApiDependencies,
    create_control_api_bundle,
)

bundle = create_control_api_bundle(ControlApiDependencies(...))
bundle.install(app)
```

`ControlApiDependencies` field 순서는 `auth`, `workspaces`, `risks`, `history`, `security`, `notifications`, `session`, `hardening`, `observer`다. 세부 dependency 생성자는 다음과 같다.

```python
from ip_risk_agent.api.auth import (
    AuthRouterDependencies,
    AuthlibGoogleOidcClient,
    GoogleOidcConfig,
)
from ip_risk_agent.api.common import CursorCodec
from ip_risk_agent.api.history import HistoryRouterDependencies
from ip_risk_agent.api.notifications import NotificationRouterDependencies
from ip_risk_agent.api.risks import RiskRouterDependencies
from ip_risk_agent.api.security import SecurityRouterDependencies
from ip_risk_agent.api.workspaces import WorkspaceRouterDependencies
from ip_risk_agent.application.auth import AuthenticationService
from ip_risk_agent.application.history import HistoryQueryService
from ip_risk_agent.application.notifications import NotificationService
from ip_risk_agent.application.risk_review import RiskReviewService
from ip_risk_agent.application.security_policy import WorkspaceSecurityService
from ip_risk_agent.application.workspace_admin import WorkspaceAdministrationService

authentication = AuthenticationService(
    unit_of_work_factory=uow_factory, clock=utc_clock, concurrency_attempts=3
)
administration = WorkspaceAdministrationService(
    unit_of_work_factory=uow_factory, clock=utc_clock, id_factory=id_factory
)
review = RiskReviewService(unit_of_work_factory=uow_factory, clock=utc_clock)
history = HistoryQueryService(unit_of_work_factory=uow_factory, clock=utc_clock)
notifications = NotificationService(unit_of_work_factory=uow_factory, clock=utc_clock)
security = WorkspaceSecurityService(
    unit_of_work_factory=uow_factory, clock=utc_clock, id_factory=id_factory
)
cursor_codec = CursorCodec(session_secret)

oidc_config = GoogleOidcConfig(
    client_id=google_client_id,
    client_secret=google_client_secret,
    redirect_uri=google_redirect_uri,
    post_login_uri=app_public_base_url,
)
oidc = AuthlibGoogleOidcClient(oidc_config)

dependencies = ControlApiDependencies(
    auth=AuthRouterDependencies(oidc, oidc_config, authentication),
    workspaces=WorkspaceRouterDependencies(
        uow_factory, administration, authentication, cursor_codec
    ),
    risks=RiskRouterDependencies(
        uow_factory, review, history, authentication, cursor_codec
    ),
    history=HistoryRouterDependencies(history, authentication, cursor_codec),
    security=SecurityRouterDependencies(security, authentication),
    notifications=NotificationRouterDependencies(
        notifications, authentication, cursor_codec
    ),
    session=ApplicationSessionConfig(secret_key=session_secret),
    hardening=ApplicationHardeningConfig(
        trusted_hosts=(public_host,),
        allowed_origins=(app_public_base_url,),
    ),
    observer=observer,
)
```

Production에서는 exact HTTPS origin/host를 넣는다. wildcard credentialed CORS는 거부된다. forwarded header trust, service-account/IAM, distributed rate limit, Agent 2 routes, worker/callback routes와 최종 app lifespan은 Integration 소유다. built-in limiter는 단일 process 안전망일 뿐 전역 quota가 아니다.

## 8. Frontend export, Source UI slot과 Open Original

공개 entrypoint:

```tsx
import { ControlPlaneApp } from "@iprisk/frontend";
import type {
  ControlPlaneIntegration,
  OpenOriginalRequest,
} from "@iprisk/frontend";

<ControlPlaneApp
  apiBaseUrl=""
  router="browser"
  integration={{
    sourceNavigation,
    sourcePanel,
    openOriginal: async ({ workspaceId, artifactId, action, sourceType }) => {
      // Agent 2 adapter 또는 owning desktop으로 전달
    },
  }}
/>
```

- `router="browser"`는 Web, `router="hash"`는 Electron renderer용이다.
- `sourceNavigation`과 `sourcePanel`이 Agent 2 UI의 public slot이다. Agent 1 파일에서 `frontend/src/sources/**`를 직접 import하지 않는다.
- callback이 없으면 provider별 Open Original button은 이유와 함께 disabled로 fail closed한다.
- UI callback에는 VWS/Artifact ID, opaque action, safe source type만 전달한다. raw content, provider credential/URL 또는 local absolute path를 넣지 않는다.
- Backend resolver는 먼저 `facade.get_original_source_request(...)`로 현재 사용자 권한을 재검증한 뒤 `request.mount.source_type`에 맞는 adapter를 선택한다.
- Vite dev server는 `/api`를 `http://127.0.0.1:8000`으로 proxy하며 production은 same-origin `/api/v1`을 사용한다.

## 9. 환경 변수

| 변수 | 용도/검증 |
|---|---|
| `GOOGLE_LOGIN_CLIENT_ID` | Google OIDC client ID, non-empty |
| `GOOGLE_LOGIN_CLIENT_SECRET` | Google OIDC secret, secret store에서 주입 |
| `GOOGLE_LOGIN_REDIRECT_URI` | 등록된 exact HTTPS callback URI; local만 HTTP 허용 |
| `SESSION_SECRET` | session/cursor signing, 최소 32자, 환경별 rotation 계획 필요 |
| `APP_PUBLIC_BASE_URL` | 로그인 후 이동과 exact CORS origin의 public base URL |
| `GCP_PROJECT_ID` | Firestore/Cloud Tasks project |
| `FIRESTORE_DATABASE` | Firestore database ID |
| `FIRESTORE_EMULATOR_HOST` | emulator test에서만 사용; production에 설정 금지 |

실제 값이나 예제 secret을 source, fixture, task payload 또는 log에 기록하지 않는다.

## 10. Firestore collection과 index wiring

`ip_risk_agent.persistence.core_firestore.CANONICAL_COLLECTIONS`가 16개 collection, `REQUIRED_COMPOSITE_INDEXES`가 아래 query 요구사항의 단일 코드 manifest다.

| Collection | Fields |
|---|---|
| `memberships` | `record_kind`, `risk_workspace_id` |
| `memberships` | `record_kind`, `user_id`, `status` |
| `memberships` | `record_kind`, `email` |
| `workspace_mounts` | `record_kind`, `risk_workspace_id` |
| `workspace_mounts` | `record_kind`, `risk_workspace_id`, `mounted_by_user_id` |
| `risks` | `record_kind`, `artifact_id`, `analysis_type`, `lifecycle_state` |
| `risks` | `record_kind`, `risk_workspace_id` |
| `change_events` | `risk_workspace_id` |

이 tuple은 코드 query의 equality/IN lookup 요구사항이지 바로 배포 가능한 `firestore.indexes.json` 형식은 아니다. Integration은 실제 project에서 Firestore가 요구하는 index를 이 manifest와 대조해 배포 config에 병합하고 emulator/production query를 재검증한다. 정렬은 현재 application memory에서 deterministic하게 수행한다.

## 11. Dependency와 실행

직접 검증한 exact 후보는 `agent-deliverables/agent-1-dependencies.md`에 기록되어 있다. 핵심 production 후보는 다음과 같다.

- Python: `google-cloud-firestore==2.28.1`, `fastapi==0.141.1`, `authlib==1.7.2`, `httpx==0.28.1`, `itsdangerous==2.2.0`
- Python test: `pytest==9.1.1`, `httpx2==2.10.0`
- Frontend: `react==19.2.8`, `react-dom==19.2.8`, `react-router-dom==7.18.2`
- Frontend build/test exact 후보는 dependency 문서와 `frontend/package.json` 참조

Uvicorn은 Agent 1 코드가 직접 import하지 않는 ASGI runtime이므로 Integration이 전체 app/deployment와 함께 선택한다. Agent 1 async test는 `asyncio.run` 기반이므로 `pytest-asyncio`가 필수 dependency가 아니다. root manifest/lock 최종 병합은 Integration 소유다.

상세 초기 구성, backend/frontend 실행과 focused scenario는 삭제 가능한 `LOCAL_RUN_AND_TEST_GUIDE.md`에 있다. 최종 승인 명령은 다음과 같다.

```text
pnpm run generate
.venv/Scripts/python.exe -m pytest shared/contracts/tests tests -q
.venv/Scripts/python.exe -m compileall -q backend/src shared/contracts/python scripts
.venv/Scripts/python.exe -m pip check
pnpm run typecheck
pnpm run verify:resolution
pnpm --filter @iprisk/frontend test
pnpm --filter @iprisk/frontend build
```

## 12. Shared Contract 준수와 change request

- Frozen Pydantic source를 변경하지 않았다.
- schema와 TypeScript generated contract를 수동 편집하지 않았다.
- 공식 `pnpm run generate` 후 generated tracked diff가 없다.
- cross-plane payload는 Frozen Contract 또는 facade-owned content-free DTO다.
- Phase 13 최종 재확인 결과 Frozen Contract 부족이 없어 Agent 1 contract-change request는 없다.

## 13. 최종 검증 결과

Phase 13 최종 실행 결과는 구현 현황 문서와 함께 이 절에 기록한다.

- delivery public surface/index manifest: `4 passed`
- shared contract + 전체 Agent 1 Python suite: `286 passed, 1 skipped`
- frontend test: `15 passed`; root TypeScript typecheck/resolution과 production build 통과
- Python 3.14.7 compileall 통과; `pip check` broken requirement 없음
- `pnpm run generate` 통과; generated contract tracked diff 없음
- Firestore emulator: `FIRESTORE_EMULATOR_HOST`가 없는 환경에서는 1건 skip; 구성 시 별도 실행

## 14. Integration 조립 순서

1. 전체 Plane dependency를 비교하고 root manifest/lock에 최종 pin한다.
2. 환경 secret/config를 검증하고 Firestore client/UoW, safe log sink, queue adapter를 만든다.
3. `ControlPlaneFacade`와 Agent 2 callback을 연결한다.
4. API 세부 service/router dependency를 만든 뒤 `create_control_api_bundle(...).install(app)`을 호출한다.
5. Agent 2 routes, internal worker/callback route, lifespan과 deployment hardening을 최종 app에 병합한다.
6. Agent 3 analyzer registry를 Gate가 승인한 `AnalysisArtifact` 뒤에만 연결한다.
7. frontend `ControlPlaneApp`에 source slot과 Open Original callback을 주입한다.
8. Firestore index와 Cloud Tasks retry/dead-letter/rate 정책을 배포 환경에 적용한다.
9. staging Google OIDC, Firestore transaction, Source→Gate→Analyzer→Risk browser E2E를 실행한다.
10. allow-list log, raw-source 비영속, 실패 시 Risk 보존과 backend authorization을 배포 환경에서 재확인한다.

## 15. 알려진 제약과 Integration 확인 사항

### 외부 환경이 있어야 완료되는 항목

- 실제 Google credential/callback domain의 OIDC roundtrip
- 실제 Firestore emulator/production transaction과 index deployment
- Cloud Tasks de-dup/retry/dead-letter, distributed ingress quota와 proxy trust
- Agent 2 Source adapter/panel/Open Original resolver, Agent 3 analyzer registry와 browser E2E
- final ASGI app/worker, root dependency lock과 deployment config

### 의도적으로 지원하지 않거나 후속 scale 근거가 필요한 항목

- Source metadata callback은 create/idempotent 등록이다. credential rotation/reconnect/provider status transition은 Source Plane endpoint와 함께 조립한다.
- pagination은 scope-bound signed offset cursor다. live write 중 offset 특성이 있으며 native document cursor/query pushdown은 endpoint 전체의 stable sort/index/snapshot 의미를 함께 설계해야 한다.
- Dashboard failed count는 canonical ChangeEvent→AnalysisJob read를 사용한다. production trace 없이 임의 projection/denormalized schema를 추가하지 않았다.
- Risk list는 request-scope Artifact/Mount cache만 사용한다. process-global cache는 stale authorization 위험 때문에 사용하지 않는다.
- RiskEvent는 append-only/transactional이지만 cryptographic hash chain은 아니다. 규제 요구가 생기면 schema version, key custody, backfill과 verifier를 함께 설계한다.
- legacy document가 존재할 때만 `User.session_version`, `RiskWorkspace.global_ignore_text` backfill migration이 필요하다.
- UI는 signed cursor incremental loading을 지원하지만 초대형 table virtualization은 실제 row/profile 측정 후 적용한다.

위 항목은 Agent 1 내부 미구현 결함이 아니라 Integration 소유 또는 production profile 기반 후속 결정이다. 구현을 확장하더라도 raw source 비영속, provider authority 이중 검증, Gate-only boundary, failure-preserves-risk와 backend-authoritative RBAC invariant를 유지해야 한다.
