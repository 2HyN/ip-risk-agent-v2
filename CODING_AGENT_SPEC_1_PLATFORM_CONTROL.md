# IP Risk Agent — Agent 1 Development Specification
## Platform & Control Plane

> **이 문서는 `CODING_AGENT_MASTER_SPEC.md`와 함께 Agent 1에게 전달한다.**  
> Master Spec이 상위 규약이며, 충돌 시 Master Spec을 우선한다.  
> Agent 1은 이 문서에서 지정한 파일만 소유하며 `shared/contracts/**`, Integration-only 영역, Agent 2/3 소유 영역을 수정하지 않는다.

---

# 0. Agent 1 임무

Agent 1의 책임은 다음 한 문장으로 정의한다.

> **사용자·Risk Workspace·권한·Mount·보안 정책·분석 orchestration·Risk lifecycle·감사 이력을 canonical application state로 관리하고, 이를 Web Product UI로 제공한다.**

Agent 1은 Source Provider API의 내부 구현이나 AI Analyzer 내부 구현을 알지 않는다.

입력은 Frozen Contract와 Integration Layer가 주입하는 port이며, 출력은 application state/API/UI다.

---

# 1. 절대 경계

## Agent 1 MUST

- Google OIDC 기반 App login을 구현한다.
- RiskWorkspace / Membership / Role을 canonical하게 관리한다.
- SourceConnection / SourceWorkspace / WorkspaceMount의 **application metadata**를 관리한다.
- VWS-wide `.ipriskignore`와 Security Gate를 소유한다.
- `SourceChange`를 idempotently 수용하고 analysis job을 생성한다.
- `SourceSnapshot -> AnalysisArtifact` 변환을 단독 소유한다.
- `AnalysisResult -> Risk/RiskEvidence/RiskEvent` reconciliation을 단독 소유한다.
- Risk machine lifecycle과 Human review disposition을 분리한다.
- Firestore canonical collection schema를 소유한다.
- Product Web UI를 소유한다.
- Audit/History/Security & Data Access 기능을 구현한다.

## Agent 1 MUST NOT

- Google Drive API를 호출하지 않는다.
- GitHub API/App token을 직접 처리하지 않는다.
- Local filesystem을 직접 읽지 않는다.
- Gemini/KIPRIS/RAG Engine/SPDX registry를 직접 호출하지 않는다.
- `connectors/**`, `intelligence/**`, `apps/desktop/**`를 수정하지 않는다.
- Frozen Contract를 수정하지 않는다.
- Integration-only `main.py`, `worker.py`, `composition/**`, root manifests를 수정하지 않는다.

---

# 2. 소유 파일

Agent 1의 exclusive ownership은 다음과 같다.

```text
backend/src/ip_risk_agent/
├─ core/
│  ├─ auth/
│  ├─ workspaces/
│  ├─ memberships/
│  ├─ mounts/
│  ├─ artifacts/
│  ├─ security/
│  ├─ risk/
│  ├─ audit/
│  └─ notifications/
│
├─ application/
│  ├─ process_change/
│  ├─ security_gate/
│  ├─ analysis_jobs/
│  ├─ risk_reconcile/
│  └─ public_facade/
│
├─ persistence/
│  └─ core_firestore/
│
└─ api/
   ├─ auth/
   ├─ workspaces/
   ├─ risks/
   ├─ history/
   ├─ security/
   └─ notifications/

frontend/src/
├─ app/
├─ auth/
├─ workspace/
├─ risk/
├─ history/
├─ security/
└─ shared/

tests/control/**
```

`frontend/src/sources/**`는 Agent 2 소유다.

---

# 3. Agent 1이 제공해야 할 Integration-facing Facade

다른 Agent가 Agent 1 내부를 import하지 않도록 Integration Layer가 사용할 public facade를 Agent 1 영역 안에 제공한다.

권장 위치:

```text
backend/src/ip_risk_agent/application/public_facade/
```

최소 facade:

```python
class ControlPlaneFacade:
    async def authorize_vws_action(...): ...
    async def register_source_change(change: SourceChange): ...
    async def register_source_access(receipt_context): ...
    async def build_analysis_artifact(snapshot: SourceSnapshot, job_id: str): ...
    async def accept_analysis_result(result: AnalysisResult): ...
    async def get_mount_ref(mount_id: str): ...
    async def get_source_workspace_context(source_workspace_id: str): ...
```

실제 타입 signature는 shared contract를 침범하지 않는 범위에서 Agent 1 내부 모델을 사용해도 된다.

Integration Agent만 이 facade를 직접 import한다.

---

# 4. 핵심 Domain Model

Master Spec의 이름을 유지한다.

## 4.1 User

```text
User
- id
- google_subject
- email
- display_name
- avatar_url optional
- created_at
- last_login_at
- status
```

Identity key는 email이 아니라 `google_subject`다.

---

## 4.2 RiskWorkspace

```text
RiskWorkspace
- id
- name
- description optional
- owner_user_id
- security_policy_version
- retention_policy_version
- created_at
- updated_at
- status
```

VWS는 collaboration/security/risk boundary다.

---

## 4.3 Membership

```text
Membership
- id
- risk_workspace_id
- user_id
- role
- status
- invited_by
- created_at
- updated_at
```

Role:

```text
OWNER
SOURCE_MANAGER
RISK_REVIEWER
VIEWER
```

Role 자체보다 permission mapping을 내부적으로 사용한다.

권장 Permission:

```text
VWS_VIEW
RISK_VIEW
RISK_REVIEW
SOURCE_MOUNT
OWN_SOURCE_MANAGE
VWS_SECURITY_MANAGE
MEMBER_MANAGE
AUDIT_VIEW
AUDIT_EXPORT
WORKSPACE_DELETE
OWNERSHIP_TRANSFER
```

MVP role mapping:

```text
VIEWER
  VWS_VIEW, RISK_VIEW

RISK_REVIEWER
  VIEWER + RISK_REVIEW

SOURCE_MANAGER
  RISK_REVIEWER + SOURCE_MOUNT + OWN_SOURCE_MANAGE

OWNER
  all application permissions
```

Raw source permission은 여기에 포함하지 않는다.

---

# 5. SourceConnection / SourceWorkspace / WorkspaceMount — Control 측 Metadata

Agent 2가 provider runtime을 소유하지만, application 상 canonical 관계는 Agent 1이 저장한다.

## SourceConnection

```text
SourceConnection
- id
- provider: GOOGLE_DRIVE | GITHUB | LOCAL
- authorized_by_user_id
- provider_subject optional
- provider_account_label optional
- credential_ref optional opaque string
- status
- created_at
- updated_at
```

`credential_ref`는 credential 자체가 아니다.

Agent 1은 credential 내용에 접근하지 않는다.

## SourceWorkspace

```text
SourceWorkspace
- id
- source_connection_id
- source_type
- external_scope_id
- display_name
- tracking_config_safe
- status
- created_at
- updated_at
```

`external_scope_id` 예:

- Drive logical selected collection ID/internal scope ID
- GitHub repository stable identifier
- Local device mount opaque ID

## WorkspaceMount

```text
WorkspaceMount
- id
- risk_workspace_id
- source_workspace_id
- alias
- mounted_by_user_id
- source_connection_id
- status
- created_at
- updated_at
```

Mount alias는 VWS 안에서 unique다.

Alias 변경은 artifact/risk identity를 변경하지 않는다.

---

# 6. Mount 권한 규칙

## Source Manager

Source Manager는 Mount 생성 가능.

자신이 만든 Mount에 대해서만:

- rename
- source-operation 요청 시작
- reconnect/disconnect 요청
- tracking scope 관리 요청

가능하다.

## Owner

Owner는 모든 Mount에 대해:

- disable
- administrative remove
- 상태 확인

가능하다.

하지만 타인의 OAuth/provider credential을 사용해 scope를 확대할 수 없다.

## Provider credential operation

Control Plane은 다음을 판정할 수 있다.

```text
role >= SOURCE_MANAGER
AND mount ownership requirement satisfied
```

하지만 실제 credential authority 판정은 Source Plane/provider flow에서 다시 수행한다.

즉 두 단계 모두 통과해야 한다.

---

# 7. Source Manager 탈퇴/제거

Source Manager가 membership에서 제거되더라도 Mount와 Risk history를 즉시 삭제하지 않는다.

권장 상태:

```text
ACTIVE
REAUTH_REQUIRED
MANAGER_ACTION_REQUIRED
SOURCE_OFFLINE
DISABLED
```

탈퇴 처리 시:

1. 해당 사용자가 custodian인 Mount 조회.
2. Mount를 `MANAGER_ACTION_REQUIRED` 또는 source 상태에 맞는 non-active state로 변경.
3. AuditEvent 기록.
4. Owner에게 notification 생성.
5. credential은 다른 사용자에게 이전하지 않는다.

Local의 경우 replacement local source 연결이 기본 해결 방식이다.

---

# 8. Artifact Canonical Model

```text
Artifact
- id
- risk_workspace_id
- mount_id
- source_workspace_id
- source_type
- source_artifact_id
- display_name
- logical_path
- original_locator_metadata_safe optional
- status
- first_seen_at
- last_seen_at
```

Identity는 `artifact.id`가 canonical이다.

Source provider stable identity와의 mapping은 unique constraint/index로 관리한다.

추천 unique key:

```text
source_workspace_id + source_artifact_id
```

`logical_path`는 presentation이다.

---

# 9. ArtifactState

```text
ArtifactState
- artifact_id
- latest_revision
- latest_checksum optional
- latest_successful_analysis_revision_by_type
- availability_state
- updated_at
```

SourceSnapshot 원문은 저장하지 않는다.

---

# 10. ChangeEvent Canonical State

`SourceChange` 수신 후 canonical ChangeEvent를 만든다.

```text
ChangeEvent
- id
- event_fingerprint unique
- provider_event_id optional
- risk_workspace_id
- mount_id
- source_workspace_id
- artifact_id optional until resolved
- source_artifact_id
- change_type
- revision
- previous_revision
- observed_at
- status
- attempts
- last_error_safe optional
- created_at
- updated_at
```

State:

```text
PENDING
PROCESSING
DONE
FAILED
```

### Idempotency

`event_fingerprint`는 unique해야 한다.

동일 event 재수신:

- duplicate row 생성 금지
- duplicate Risk 생성 금지
- already DONE이면 무해하게 ACK
- retry 가능한 FAILED이면 정책에 따라 재처리 가능

---

# 11. AnalysisJob

하나의 Artifact revision에 여러 Analyzer가 실행될 수 있다.

```text
AnalysisJob
- id
- change_event_id
- artifact_id
- revision
- requested_analysis_types[]
- status
- created_at
- started_at optional
- completed_at optional
- failure_safe optional
```

State:

```text
QUEUED
RUNNING
SUCCEEDED
FAILED
INCONCLUSIVE
```

개별 `AnalysisResult`는 `analysis_type`별로 별도 저장/처리할 수 있다.

---

# 12. SourceChange Intake

Agent 1이 제공할 핵심 use-case:

```text
register_source_change(SourceChange)
```

처리 순서:

1. Contract validation은 이미 shared model에서 수행.
2. `risk_workspace_id`, `mount_id`, `source_workspace_id` 관계 검증.
3. Mount가 ACTIVE/DISABLED 등 처리 가능한 상태인지 확인.
4. `event_fingerprint` idempotent insert.
5. SourceArtifactRef를 canonical Artifact에 resolve/upsert.
6. ChangeEvent 생성.
7. DELETE/MOVE semantics 적용.
8. Cloud Tasks enqueue 요청에 필요한 record 생성.
9. Audit/operational log 최소 기록.

Agent 1은 실제 SourceSnapshot fetch를 구현하지 않는다.

Integration Worker가 Agent 2 SourceAdapter를 호출한다.

---

# 13. Cloud Tasks 관련 Agent 1 책임

Agent 1은 task payload에 raw source를 넣지 않는다.

권장 payload:

```text
process_change
- change_event_id
```

Integration Worker가 change record를 조회하고 SourceAdapter를 사용한다.

Agent 1은:

- enqueue service abstraction
- job claim
- retry-safe state transition

을 구현한다.

실제 Cloud Tasks SDK wiring/config는 Integration 단계에서 연결 가능하도록 port로 둔다.

---

# 14. Security Gate — 핵심 구현

Agent 1의 가장 중요한 보안 컴포넌트다.

입력:

```text
SourceSnapshot
```

출력:

```text
AnalysisArtifact | Denied/Skipped decision
```

순서 MUST:

1. Canonical Mount/SourceWorkspace 존재 확인.
2. Source Plane이 전달한 source-scope-safe metadata 검증.
3. VWS global `.ipriskignore` 적용.
4. Source-level ignore result/metadata가 제공된 경우 deny 병합.
5. file type allow/deny.
6. max content size policy.
7. secret/credential redaction.
8. data minimization.
9. analyzer eligibility routing.
10. `analysis_input_checksum` 계산.
11. `security_context.approved=true`인 AnalysisArtifact 생성.
12. SourceAccessReceipt를 SourceAccessEvent로 기록.

### Deny wins

어떤 policy라도 deny하면 Analyzer로 전달하지 않는다.

### SourceSnapshot transient

Security Gate가 끝난 뒤 SourceSnapshot을 canonical DB에 저장하지 않는다.

---

# 15. `.ipriskignore` 구현

VWS-wide logical policy다.

초기 문법은 gitignore-style glob subset을 권장한다.

MVP 기능:

- `*`, `**`, `?` 정도 지원
- `/mount-alias/path` 기준 logical path에 적용
- deny-only
- negation `!`은 MVP에서 지원하지 않아도 된다. 보안 정책은 단순할수록 좋다.

예:

```gitignore
/backend/**/.env*
/backend/**/secrets/**
/backend/**/*.pem
/prototype/customer-data/**
/design/private-hr/**
```

정책 변경 시:

- version 증가
- AuditEvent 기록
- 기존 Risk를 자동 삭제하지 않음
- 향후 분석부터 새 policy 적용

---

# 16. Secret/Credential Filter

MVP는 deterministic pattern 기반으로 구현한다.

최소 탐지/제거 후보:

- PEM private key block
- `.env` 스타일 credential lines
- common token/secret assignment patterns
- OAuth bearer/token-like data

목표는 완전한 DLP가 아니라 accidental secret forwarding을 줄이는 것이다.

Redaction 방식은:

```text
[REDACTED_SECRET]
```

등 deterministic placeholder를 사용한다.

`redaction_count`를 SecurityContext에 기록한다.

원문 secret은 log/evidence에 남기지 않는다.

---

# 17. Data Minimization

가능하면 `CHANGESET_WITH_CONTEXT`를 유지한다.

FULL_TEXT snapshot이 들어와도 Analyzer 종류와 파일 크기에 따라 최소 segment만 전달할 수 있다.

단, Agent 1은 AI reasoning을 구현하지 않는다.

MVP deterministic rule 예:

- MANIFEST/LOCKFILE: 전체 텍스트가 필요하면 full 허용.
- SOURCE_CODE: changed + context segment 우선.
- DOCUMENT_TEXT: size threshold 이내 full, 초과 시 chunk/segment 축소.

정확한 threshold는 config로 둔다.

---

# 18. Analyzer Routing

Agent 1은 Analyzer 내부를 모르므로 static eligibility matrix만 관리한다.

MVP 예:

```text
MANIFEST -> LICENSE
LOCKFILE -> LICENSE
SOURCE_CODE -> PATENT
DOCUMENT_TEXT -> PATENT
TEXT -> PATENT if supported policy
UNKNOWN -> none
```

하나의 Artifact에 여러 AnalysisType을 넣을 수 있다.

Agent 3가 최종적으로 unsupported 판단하여 SKIPPED를 반환할 수 있다.

---

# 19. AnalysisResult Intake

핵심 use-case:

```text
accept_analysis_result(AnalysisResult)
```

처리 순서:

1. analysis_job_id 검증.
2. artifact/revision 일치 검증.
3. result status/coverage 기록.
4. Evidence canonicalization/minimal retention.
5. `SUCCEEDED + COMPLETE`인 경우 candidate reconciliation.
6. 그 외는 기존 active Risk resolution 금지.
7. AnalysisJob aggregate 상태 업데이트.
8. RiskEvent/Notification/AuditEvent 생성.

---

# 20. Risk Canonical Model

```text
Risk
- id
- risk_workspace_id
- artifact_id
- analysis_type
- risk_key unique
- lifecycle_state
- review_disposition
- review_priority
- summary
- first_seen_at
- last_seen_at
- resolved_at optional
- latest_analysis_job_id
- latest_evidence_revision optional
- updated_at
```

Machine lifecycle:

```text
NEW
EXISTING
RESOLVED
```

`REOPENED`는 event로 기록하고 current state는 NEW/EXISTING 중 정책에 따라 active로 둘 수 있다.

추천: current state는 `NEW | EXISTING | RESOLVED`, 재등장 시 `EXISTING` + `RISK_REOPENED` event.

---

# 21. Stable Risk Identity

## Patent

```text
artifact_id + "PATENT" + normalized_application_number
```

## License

```text
artifact_id
+ "LICENSE"
+ ecosystem
+ normalized_package_name
+ resolved_version_or_marker
+ normalized_license_expression
```

Hash algorithm은 deterministic하게 고정하고 unit test한다.

Mount alias는 key에 포함하지 않는다.

---

# 22. Risk Reconcile Algorithm

`SUCCEEDED + COMPLETE`에 대해서만 실행.

Pseudo flow:

```text
existing active risks for artifact + analysis_type
        ↓
new candidate stable keys
        ↓
intersection -> EXISTING / update evidence
new-only      -> NEW
old-only      -> RESOLVED
```

Transaction 안에서:

- Risk update/create
- RiskEvent append
- Evidence reference update

를 원자적으로 처리한다.

FAILED/INCONCLUSIVE/PARTIAL/NONE이면 old-only resolution logic을 호출하지 않는다.

DELETE event도 자동 resolve하지 않는다.

---

# 23. Human Review

Disposition:

```text
UNREVIEWED
MONITORING
ACCEPTED_RISK
EXCLUDED
```

`review_disposition` 변경은 Risk lifecycle과 별개다.

API는 optimistic/version check 또는 transaction을 사용한다.

ReviewEvent에:

- actor
- previous/new disposition
- comment optional
- timestamp

를 남긴다.

---

# 24. RiskEvidence

전체 SourceSnapshot을 저장하지 않는다.

```text
RiskEvidence
- id
- risk_id
- analysis_job_id
- evidence_id_from_result
- evidence_type
- excerpt
- reference
- metadata_safe
- source_revision
- created_at
```

Evidence retention은 Balanced가 기본이다.

`excerpt`는 Agent 3 결과를 그대로 무제한 저장하지 말고 설정된 최대 길이를 적용할 수 있다.

---

# 25. RiskEvent — Append Only

```text
RiskEvent
- id
- risk_id
- event_type
- actor_type SYSTEM|USER
- actor_user_id optional
- previous_state_safe
- new_state_safe
- analysis_job_id optional
- evidence_refs[]
- reason_safe
- occurred_at
- previous_event_hash optional
- event_hash optional
```

MVP에서 hash chain을 구현할 수 있으면 권장하나, 핵심은 append-only다.

금지:

- 과거 event update
- 과거 event overwrite

---

# 26. AuditEvent

최소 event type:

```text
WORKSPACE_CREATED
WORKSPACE_UPDATED
MEMBER_INVITED
MEMBER_ROLE_CHANGED
MEMBER_REMOVED
SOURCE_CONNECTED
SOURCE_DISCONNECTED
MOUNT_CREATED
MOUNT_RENAMED
MOUNT_DISABLED
MOUNT_REMOVED
SECURITY_POLICY_CHANGED
ANALYSIS_FAILED
```

Risk 상세 이벤트는 RiskEvent에 두고, AuditEvent는 VWS 운영/보안 활동 중심으로 둔다.

---

# 27. SourceAccessEvent

SourceSnapshot의 receipt를 기반으로 만든다.

```text
SourceAccessEvent
- id
- risk_workspace_id
- mount_id
- artifact_id
- analysis_job_id optional
- access_type
- revision
- content_bytes
- provider_request_id optional
- occurred_at
```

원문/path secret/token은 저장하지 않는다.

---

# 28. Notifications

MVP는 Firestore/in-app notification만 필수.

예:

```text
RISK_HIGH_DETECTED
RISK_REOPENED
ANALYSIS_FAILED
MOUNT_REAUTH_REQUIRED
SOURCE_OFFLINE
```

Email/Slack/FCM은 후속.

---

# 29. Firestore Canonical Collections

Agent 1이 소유한다.

```text
users
risk_workspaces
memberships
source_connections
source_workspaces
workspace_mounts
artifacts
artifact_states
change_events
analysis_jobs
risks
risk_evidence
risk_events
audit_events
source_access_events
notifications
```

## Index/uniqueness requirements

Firestore 자체 unique constraint가 없으므로 transaction + deterministic document IDs 또는 unique-key documents 사용.

추천:

- `event_fingerprint` deterministic change event doc id
- `risk_key` deterministic risk doc id or unique mapping
- membership `(vws_id,user_id)` deterministic id
- artifact `(source_workspace_id, source_artifact_id)` mapping

---

# 30. Persistence Abstraction

Domain/application logic은 Firestore SDK object에 직접 종속되지 않게 한다.

Repository protocols는 Agent 1 내부에서 정의 가능하다.

예:

```text
UserRepository
WorkspaceRepository
MembershipRepository
MountRepository
ArtifactRepository
ChangeEventRepository
AnalysisJobRepository
RiskRepository
AuditRepository
NotificationRepository
```

In-memory fake implementation을 unit test용으로 제공하는 것을 권장한다.

Production Firestore implementation도 반드시 존재해야 한다.

---

# 31. Authentication

Google OIDC App Login만 Agent 1 책임이다.

MVP flow:

```text
GET /api/v1/auth/google/login
GET /api/v1/auth/google/callback
POST /api/v1/auth/logout
GET /api/v1/auth/me
```

Drive OAuth는 Agent 2다.

App auth token/session과 source token을 절대 혼합하지 않는다.

Session은 secure HTTP-only cookie 기반을 우선한다.

---

# 32. API Routes — Agent 1

정확한 request/response model은 구현하면서 정의하되 아래 capability를 모두 제공한다.

## Auth

```text
GET  /api/v1/auth/google/login
GET  /api/v1/auth/google/callback
POST /api/v1/auth/logout
GET  /api/v1/auth/me
```

## Workspaces

```text
POST   /api/v1/workspaces
GET    /api/v1/workspaces
GET    /api/v1/workspaces/{vws_id}
PATCH  /api/v1/workspaces/{vws_id}
DELETE /api/v1/workspaces/{vws_id}
```

## Membership

```text
GET    /api/v1/workspaces/{vws_id}/members
POST   /api/v1/workspaces/{vws_id}/members/invitations
PATCH  /api/v1/workspaces/{vws_id}/members/{user_id}
DELETE /api/v1/workspaces/{vws_id}/members/{user_id}
```

초기 invitation 구현은 email identity 기반 pending record 등 간단한 형태 가능.

## Mount metadata

Agent 2가 source operation route를 소유하므로 Agent 1은 read/admin metadata 중심:

```text
GET   /api/v1/workspaces/{vws_id}/mounts
GET   /api/v1/workspaces/{vws_id}/mounts/{mount_id}
PATCH /api/v1/workspaces/{vws_id}/mounts/{mount_id}/alias
POST  /api/v1/workspaces/{vws_id}/mounts/{mount_id}/disable
DELETE /api/v1/workspaces/{vws_id}/mounts/{mount_id}
```

실제 create flow는 Agent 2 provider flow + Integration에서 canonical Mount creation use-case와 연결한다.

## Risks

```text
GET   /api/v1/workspaces/{vws_id}/risks
GET   /api/v1/workspaces/{vws_id}/risks/{risk_id}
PATCH /api/v1/workspaces/{vws_id}/risks/{risk_id}/review
GET   /api/v1/workspaces/{vws_id}/risks/{risk_id}/timeline
```

## History/Audit

```text
GET /api/v1/workspaces/{vws_id}/activity
GET /api/v1/workspaces/{vws_id}/audit
GET /api/v1/workspaces/{vws_id}/source-access
```

## Security

```text
GET  /api/v1/workspaces/{vws_id}/security
PUT  /api/v1/workspaces/{vws_id}/security/ipriskignore
GET  /api/v1/workspaces/{vws_id}/security/data-access-summary
```

## Notifications

```text
GET  /api/v1/notifications
POST /api/v1/notifications/{id}/read
```

---

# 33. Product Frontend

React + TypeScript + Vite.

Agent 1은 global app shell과 shared component primitives를 소유한다.

필수 page:

1. Login
2. Workspace list/create
3. VWS Dashboard
4. Risk list
5. Risk detail
6. Risk timeline
7. Members/roles
8. Workspace activity
9. Security & Data Access
10. Notifications

Source 연결 wizard 자체는 Agent 2 소유 component를 삽입한다.

---

# 34. VWS Dashboard

최소 metric:

```text
Needs Review
High Priority
Monitoring
Resolved Recently
Analysis Failed
Source Health Summary
```

숫자는 canonical Risk/AnalysisJob state에서 계산한다.

---

# 35. Risk List

필터:

- active/resolved
- PATENT/LICENSE
- priority
- review disposition
- mount/source

표시:

- Risk type
- Artifact logical path
- priority
- machine lifecycle
- human review state
- last seen
- source mount

---

# 36. Risk Detail

필수 섹션:

```text
Current Status
Why This Risk
Minimal Evidence
Affected Artifact
Open Original action placeholder/integration
Reviewer Decision
Timeline
Analysis metadata
```

`Open Original`은 Agent 1이 raw content를 fetch하지 않는다.

Integration/Agent2 locator action을 통해 provider URL/local device semantics만 사용한다.

---

# 37. Security & Data Access UI

필수:

## Connected Sources summary

- Mount alias
- source type
- provider account label
- status
- tracking scope summary
- mounted by

## Global Protection

- `.ipriskignore`
- source retention summary
- evidence retention summary
- secret filtering enabled
- RAG persistence = reference knowledge only

## Recent Source Access

- mount
- artifact logical name/path
- access type
- bytes
- occurred time

원문 자체는 표시하지 않는다.

---

# 38. Authorization Middleware

모든 VWS route는:

1. authenticated user
2. membership
3. required permission

검증을 거친다.

공통 helper/service를 만든다.

Source Agent가 자신의 route에서 사용할 수 있도록 Integration에서 주입 가능한 authorization function/facade를 제공한다.

Agent 2가 Agent 1 내부 dependency를 직접 import하게 만들면 안 된다.

---

# 39. Error Model

Product API error category는 최소:

```text
UNAUTHENTICATED
FORBIDDEN
NOT_FOUND
CONFLICT
VALIDATION_ERROR
SOURCE_ACTION_REQUIRED
ANALYSIS_NOT_AVAILABLE
INTERNAL_ERROR
```

raw provider error/token을 사용자에게 노출하지 않는다.

Audit에는 safe category만 남긴다.

---

# 40. Observability

Structured log 공통 field:

```text
request_id
risk_workspace_id optional
mount_id optional
artifact_id optional
change_event_id optional
analysis_job_id optional
operation
status
latency_ms
```

Source 원문/evidence 전체/token은 로그에 남기지 않는다.

---

# 41. Agent 1 Unit/Domain Tests

`tests/control/**`

MUST cover:

1. Google identity user upsert
2. Membership role permission matrix
3. Source Manager own-mount restriction
4. Owner provider credential impersonation 불가 모델
5. Mount alias uniqueness
6. Mount rename does not change artifact/risk identity
7. duplicate SourceChange idempotency
8. Artifact mapping stability
9. DELETE does not resolve Risk
10. `.ipriskignore` deny wins
11. secret redaction
12. SourceSnapshot transient policy helper
13. only approved AnalysisArtifact creation
14. `FAILED` result preserves existing risks
15. `INCONCLUSIVE` preserves existing risks
16. `PARTIAL` preserves existing risks
17. successful complete zero candidate resolves prior risks
18. candidate reappearance creates reopen event
19. Human EXCLUDED != machine RESOLVED
20. RiskEvent append-only
21. SourceAccessReceipt -> SourceAccessEvent
22. removed Source Manager -> action-required mount state

---

# 42. Firestore Tests

가능하면 emulator를 사용.

검증:

- transaction risk reconcile
- duplicate change event deterministic ID
- concurrent review update
- membership consistency
- risk event append atomicity

실제 production credential을 test에 요구하지 않는다.

---

# 43. Integration Wiring Points — Agent 1이 문서화할 것

`AGENT_DELIVERY.md`에 최소 다음을 명시한다.

1. `ControlPlaneFacade` import path
2. required repository constructors
3. SecurityGate constructor dependencies
4. `register_source_change()` 사용 예
5. `build_analysis_artifact()` 사용 예
6. `accept_analysis_result()` 사용 예
7. Cloud Tasks enqueue port binding point
8. Source original locator UI callback binding point
9. Agent 2 source router authorization injection point
10. required env vars

---

# 44. Environment Variables — 요청 목록에 기록

예상 필요:

```text
GOOGLE_LOGIN_CLIENT_ID
GOOGLE_LOGIN_CLIENT_SECRET
GOOGLE_LOGIN_REDIRECT_URI
SESSION_SECRET
GCP_PROJECT_ID
FIRESTORE_DATABASE
APP_PUBLIC_BASE_URL
```

실제 root `.env.example`은 수정하지 않고 dependency request/delivery 문서에 기록한다.

---

# 45. 구현 순서

권장 순서:

## Phase A — Pure Domain

- roles/permissions
- VWS/membership
- mount/artifact
- risk lifecycle
- review disposition
- repository protocols

## Phase B — Persistence

- InMemory repositories
- Firestore repositories
- transaction primitives

## Phase C — Security/Orchestration

- SourceChange intake
- SecurityGate
- AnalysisJob
- AnalysisResult intake
- Risk reconcile

## Phase D — Auth/API

- Google login
- workspace/member APIs
- risk/history/security APIs

## Phase E — Web UI

- app shell
- dashboard
- risks
- history
- security

## Phase F — Hardening

- audit
- notifications
- concurrency/idempotency
- tests
- delivery docs

---

# 46. Acceptance Criteria

Agent 1은 아래가 모두 충족되어야 완료다.

### Domain

- VWS/User/Membership/Mount/Artifact/Risk domain이 구현됨.
- Role과 Mount ownership이 강제됨.
- Machine lifecycle과 Human review가 분리됨.

### Security

- SecurityGate가 `SourceSnapshot -> AnalysisArtifact`를 유일하게 수행함.
- `.ipriskignore` deny wins.
- secret redaction/minimization이 존재함.
- unapproved artifact가 생성되지 않음.

### Orchestration

- duplicate SourceChange가 무해함.
- AnalysisJob state가 retry-safe함.
- FAILED/INCONCLUSIVE/PARTIAL이 Risk를 resolve하지 않음.

### Persistence

- canonical Firestore repositories 존재.
- Risk reconcile transaction 존재.
- append-only history가 구현됨.

### Product

- VWS/Risk/History/Security 핵심 Web UI가 존재.
- source UI를 삽입할 integration slot이 존재.
- raw source를 app이 proxy하지 않음.

### Testing

- Shared Contract tests 통과.
- `tests/control/**` 핵심 invariant tests 통과.

### Delivery

- `AGENT_DELIVERY.md`
- dependency request
- known issues
- wiring points

가 제공됨.

---

# 47. Agent 1이 결정하지 말아야 할 사항

다음은 Agent 1이 임의 변경하지 않는다.

- Drive OAuth scope/Picker 구현
- GitHub App permissions implementation
- Local staging implementation
- KIPRIS search policy
- Gemini prompts
- RAG Engine region/backend config 세부
- SPDX/license analyzer 알고리즘
- Contract fields/version
- root deployment configuration

필요 시 `contract-change-requests/agent1-XXX.md` 또는 `AGENT_DELIVERY.md`에 요청/제약을 남긴다.

---

# 48. 최종 성공 정의

Agent 1 구현만 단독으로 놓았을 때 실제 Drive/GitHub/Gemini 구현이 없어도 fake ports를 사용해 다음 시나리오가 실행되어야 한다.

```text
Fake SourceChange
 -> canonical ChangeEvent
 -> Fake SourceSnapshot
 -> Security Gate
 -> AnalysisArtifact
 -> Fake AnalysisResult
 -> Risk reconciliation
 -> RiskEvent
 -> Web/API에서 Risk 조회 및 Review
```

이 시나리오가 실제 Provider/Analyzer 없이도 완결되어야 Agent 1이 독립적으로 잘 분리된 것이다.
