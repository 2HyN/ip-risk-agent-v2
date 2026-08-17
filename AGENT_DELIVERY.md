# Agent 1 — Platform & Control Plane Delivery

## 1. 구현 범위

Agent 1은 canonical Control domain, authorization, Firestore persistence, SourceChange/AnalysisJob orchestration, Security Gate, AnalysisResult/Risk reconciliation, review/history/audit/notification, Google App Login, Control API, Product Web UI와 Integration-facing facade를 제공한다.

Provider API, credential 내용, local filesystem, analyzer/Gemini/KIPRIS/RAG 구현은 포함하지 않는다. Control Plane은 raw source를 저장하거나 API로 proxy하지 않는다.

## 2. Integration public surface

Integration Agent가 사용하는 안정된 import path는 다음 하나다.

```python
from ip_risk_agent.application.public_facade import (
    ControlPlaneFacade,
    ControlPlaneFacadeConfig,
    PublicVwsAction,
    SourceAccessReceiptContext,
    SourceAuthorizationCallback,
    SourceMetadataRegistrationCallback,
    SourceMetadataRegistrationCommand,
    SourceScopeInput,
)
```

다른 Plane은 `application.process_change`, `application.security_gate`, `application.risk_reconcile`, `core` 또는 repository 구현을 직접 import하지 않는다.

`ControlPlaneFacade`가 제공하는 integration entrypoint:

- `authorize_vws_action()`
- `register_source_metadata()`
- `register_source_change()`
- `claim_analysis()` / `fail_analysis()` / `retry_failed_analysis()`
- `register_source_access()`
- `build_analysis_artifact()`
- `accept_analysis_result()`
- `get_mount_ref()`
- `get_source_workspace_context()`
- `get_original_source_request()`

## 3. Repository와 facade 생성

Production repository constructor:

```python
from google.cloud.firestore_v1 import AsyncClient

from ip_risk_agent.application.public_facade import (
    ControlPlaneFacade,
    ControlPlaneFacadeConfig,
)
from ip_risk_agent.persistence.core_firestore import (
    FirestoreControlUnitOfWorkFactory,
)

client = AsyncClient(project=gcp_project_id, database=firestore_database)
uow_factory = FirestoreControlUnitOfWorkFactory.from_client(client)

facade = ControlPlaneFacade(
    unit_of_work_factory=uow_factory,
    task_enqueuer=cloud_tasks_enqueuer,
    clock=utc_clock,
    id_factory=id_factory,
    config=ControlPlaneFacadeConfig(),
)
```

`task_enqueuer`는 raw-free `change_event_id` 하나만 받고 같은 ID를 de-duplicate해야 한다. `clock`은 timezone-aware UTC datetime을, `id_factory(kind)`는 non-empty opaque ID를 반환해야 한다.

Fake wiring은 `InMemoryControlStore`와 `InMemoryTaskEnqueuer`로 구성할 수 있으며 실행 예제는 `tests/control/test_public_facade.py`에 있다.

## 4. Source Plane callback wiring

Source router에는 bound facade method를 protocol로 주입한다.

```python
authorization: SourceAuthorizationCallback = facade.authorize_vws_action
register_metadata: SourceMetadataRegistrationCallback = (
    facade.register_source_metadata
)
```

Provider 연결이 검증된 뒤 Source Plane은 token 자체가 아닌 opaque `credential_ref`와 content-free canonical metadata만 `SourceMetadataRegistrationCommand`에 넣는다. `registration_key`, `connection_key`, `source_workspace_key`는 retry 시 동일해야 하며 Control이 deterministic canonical ID로 변환한다.

Control authorization의 `provider_authority_required=True`는 application permission만 통과했다는 의미다. Source Plane/provider가 실제 credential 및 원본 접근 권한을 다시 검증해야 한다.

## 5. Pipeline 사용 순서

```python
registration = await facade.register_source_change(source_change)
claim = await facade.claim_analysis(registration.change_event_id)
if claim is None:
    return

snapshot = await source_adapter.fetch_snapshot(source_change)
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

Source adapter가 Security Gate 호출과 별도로 access receipt를 먼저 전달해야 하는 경우 `register_source_access()`를 사용한다. 같은 analysis job/revision/receipt를 Gate가 다시 기록해도 event ID가 같아 idempotent하다.

Snapshot fetch 자체가 실패해 `AnalysisResult`를 만들 수 없으면 safe category만 담아 `fail_analysis()`를 호출한다. retry policy가 허용할 때 `retry_failed_analysis()`가 같은 content-free task ID를 다시 enqueue한다.

## 6. Security Gate 설정

`ControlPlaneFacadeConfig.security_gate`가 MIME 및 byte/segment limit을 제공한다. VWS `.ipriskignore` 원문과 version은 canonical `RiskWorkspace` document에서 읽으므로 Security 설정 API의 변경이 다음 분석부터 자동 적용된다.

Security Gate 입력 `SourceSnapshot`은 transient이며 repository에 저장하지 않는다. 승인된 최소 `AnalysisArtifact`만 analyzer에 전달한다.

## 7. Open Original binding

Risk API는 opaque `SOURCE_OPEN_ORIGINAL + artifact_id` action만 반환한다. Integration은 현재 application user와 VWS를 사용해 다음을 호출한다.

```python
request = await facade.get_original_source_request(
    actor_user_id=current_user_id,
    risk_workspace_id=vws_id,
    artifact_id=artifact_id,
)
locator = await source_adapter.resolve_original(request.artifact)
```

`request.mount.source_type`으로 adapter를 선택한다. Provider URL은 provider authorization을 그대로 거치고, Local locator는 owning device의 registry에서만 처리한다. Backend가 raw source나 local absolute path를 반환해서는 안 된다.

## 8. Control API wiring

`ip_risk_agent.api.create_control_api_bundle()`이 기존 FastAPI app에 Agent 1 router, session middleware와 safe error handler를 설치한다. 최종 app 생성, Agent 2 router, internal worker/callback route, CORS/TrustedHost/proxy 설정은 Integration 소유다.

## 9. Dependency와 환경 변수

검증된 정확한 dependency 후보는 `agent-deliverables/agent-1-dependencies.md`에 있다. Integration에서 root manifest/lock을 병합해야 한다.

필수 production 환경 변수:

```text
GOOGLE_LOGIN_CLIENT_ID
GOOGLE_LOGIN_CLIENT_SECRET
GOOGLE_LOGIN_REDIRECT_URI
SESSION_SECRET
APP_PUBLIC_BASE_URL
GCP_PROJECT_ID
FIRESTORE_DATABASE
```

`FIRESTORE_EMULATOR_HOST`는 emulator test에서만 사용한다. 실제 secret은 source, fixture, log 또는 task payload에 기록하지 않는다.

## 10. 검증 명령

```text
pnpm run generate
python -m pytest shared/contracts/tests tests/control -q
pnpm typecheck
pnpm verify:resolution
pnpm --filter @iprisk/frontend test
pnpm --filter @iprisk/frontend build
python -m pip check
```

공식 contract 생성 후 `shared/contracts/schemas/**`와 `shared/contracts/typescript/generated/contracts.ts`에 tracked diff가 없어야 한다.

## 11. Contract 준수와 change request

- Frozen Pydantic source는 변경하지 않았다.
- 공식 생성 파일을 수동 편집하지 않았다.
- contract-change request는 현재 없다.
- facade 입출력의 cross-plane payload는 Frozen Contract 또는 facade-owned content-free DTO다.

## 12. Frontend public surface와 Source UI slot

Integration은 Agent 1 내부 component를 직접 조립하지 않고 다음 public entrypoint를 사용한다.

```tsx
import { ControlPlaneApp } from "@iprisk/frontend";

<ControlPlaneApp
  apiBaseUrl=""
  router="browser"
  integration={{
    sourceNavigation: sourceNavigation,
    sourcePanel: sourcePanel,
    openOriginal: async ({ workspaceId, artifactId, action, sourceType }) => {
      // Resolve through the bound Agent 2 adapter / owning desktop.
    },
  }}
/>
```

- `router="browser"`는 Web, `router="hash"`는 Electron renderer 조립점이다.
- `sourceNavigation`과 `sourcePanel`은 `frontend/src/sources/**`를 Agent 1이 import하거나 수정하지 않는 삽입 경계다.
- `openOriginal`에는 opaque action, VWS/Artifact ID와 safe source type만 전달된다. raw content, provider credential, provider URL 또는 local absolute path는 UI state/API에 포함되지 않는다.
- callback이 주입되지 않으면 provider별 Open Original button은 설명과 함께 disabled 상태로 남아 안전하게 fail closed한다.
- Vite development server만 `/api`를 `http://127.0.0.1:8000`으로 proxy하며 production은 same-origin `/api/v1`을 사용한다.

## 13. Known issues와 Integration 확인 사항

- 실제 Google OIDC roundtrip은 staging credential/callback domain에서 확인해야 한다.
- Firestore emulator가 설정되지 않은 환경에서는 emulator test 1개가 skip된다.
- Source metadata callback은 create/idempotent registration만 제공한다. credential rotation, reconnect와 provider status transition endpoint는 Source Plane 요구와 함께 별도 wiring해야 한다.
- Firestore pagination은 현재 signed offset cursor이며 native cursor/대규모 index 검증은 Phase 12 범위다.
- production migration이 필요한 기존 document가 있으면 `User.session_version`과 `RiskWorkspace.global_ignore_text` backfill이 필요하다.
- Cloud Tasks retry/rate/dead-letter, structured logging/correlation, CORS/host/proxy/rate-limit은 Integration/Phase 12에서 확정한다.
- Agent 2 Source panel과 실제 `openOriginal` resolver는 위 public prop에 Integration이 주입해야 한다.
- frontend list 화면은 MVP에서 API 첫 페이지(기본 50건)를 표시한다. signed cursor 기반 incremental loading/virtualization은 Phase 12 scale 검토 항목이다.
- Phase 11 frontend exact version은 `frontend/package.json`과 dependency 문서에 기록했지만 root `pnpm-lock.yaml`은 소유 경계상 변경하지 않았다. Integration이 최종 lock pin을 생성해야 한다.
