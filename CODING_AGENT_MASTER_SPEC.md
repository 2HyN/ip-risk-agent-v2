# IP Risk Agent — Coding Agent Master Development Specification

> **문서 역할**: 세 개의 병렬 Coding Agent와 최종 Integration Agent가 공통으로 따라야 하는 최상위 개발 명세
> 
> **대상 독자**: Codex / Claude Coding Agent 및 최종 통합 담당자
> 
> **이 문서가 고정하는 것**: 도메인 용어, 시스템 경계, 공통 Contract, 보안 invariant, 파일 ownership, 데이터 흐름, lifecycle 의미, 통합 규칙, 테스트·완료 기준
> 
> **이 문서가 고정하지 않는 것**: 각 개발축 내부의 세부 class 분해, 구체적 UI 디자인, 개별 prompt 전문, 각 provider SDK의 세부 구현 방식

---

# 0. 최상위 목표

이 프로젝트는 **Local Directory / GitHub Repository / Google Drive** 등 서로 다른 실제 협업 Source Workspace를 하나의 **Risk Workspace**에 연결하고, 변경을 지속적으로 감지하여 **Patent / Open-source License 중심의 잠재적 IP Risk**를 근거 기반으로 분석하고, 사용자가 장기적으로 검토·추적·감사할 수 있게 하는 **Secure Human-in-the-Loop AI Risk Management System**이다.

핵심 목표는 단순 Scanner가 아니다.

1. **Continuous Monitoring** — Source의 변경을 지속적으로 감지한다.
2. **Least-Privilege Source Access** — 사용자가 명시적으로 연결한 범위만 접근한다.
3. **Data Minimization** — 원본 전체보다 변경된 최소 context를 우선 처리한다.
4. **Evidence-grounded Analysis** — AI 결과는 근거와 함께 검증 가능해야 한다.
5. **Deterministic Risk Lifecycle** — Risk state와 provider failure를 LLM이 결정하지 않는다.
6. **Human-in-the-Loop Management** — 사용자의 Review 판단과 시스템 Risk lifecycle을 분리한다.
7. **Auditable History** — Risk 변화, Source 설정, 데이터 접근 이력을 추적 가능하게 한다.
8. **GCP-native Managed Architecture** — Cloud Run, Firestore, Cloud Tasks, Secret Manager, Vertex AI/RAG Engine 등 관리형 서비스를 적극 활용한다.

---

# 1. 이 명세의 우선순위

모든 Coding Agent는 다음 우선순위를 따른다.

```text
1. Security invariants
2. Frozen Contracts
3. Domain/lifecycle invariants
4. File ownership boundaries
5. Test/acceptance criteria
6. Individual implementation preference
```

개별 Agent의 편의나 SDK 특성 때문에 상위 규칙을 우회해서는 안 된다.

이 문서와 개별 Agent 문서가 충돌하면 **이 Master Specification이 우선**한다.

---

# 2. 확정 도메인 용어

## 2.1 Risk Workspace (`RiskWorkspace`, VWS)

애플리케이션 내부의 논리적 IP Risk 관리·협업·보안 경계.

VWS가 소유하는 개념:

- Membership / Role
- Workspace Mount
- VWS-wide security policy
- Risk / Review / History
- Audit / Activity
- Notification

VWS는 실제 filesystem이 아니다.

---

## 2.2 Source Workspace (`SourceWorkspace`, WS)

실제 provider 또는 local machine에 존재하는 **사용자가 VWS에 연결한 관리 가능한 Source 범위**.

지원 타입:

```text
GOOGLE_DRIVE
GITHUB
LOCAL
```

동일 provider type을 한 VWS에 여러 개 연결할 수 있다.

---

## 2.3 Source Connection (`SourceConnection`)

Provider 계정/installation/device와 애플리케이션 사이의 인증·연결 관계.

예:

- Google Drive OAuth credential for `research@company.com`
- GitHub App installation for `company-org`
- Local Desktop device registration

`SourceConnection`과 `SourceWorkspace`는 1:1이 아니다.

하나의 Connection으로 여러 SourceWorkspace를 만들 수 있다.

---

## 2.4 Workspace Mount (`WorkspaceMount`, Mount)

SourceWorkspace를 특정 RiskWorkspace에 연결하는 논리적 Mount.

예:

```text
/backend   -> GitHub SourceWorkspace
/design    -> Google Drive SourceWorkspace
/prototype -> Local SourceWorkspace
```

Mount alias/path는 **presentation namespace**일 뿐 identity가 아니다.

---

## 2.5 Artifact

분석 가능한 Source 항목의 애플리케이션 내부 identity.

Artifact identity는 다음을 기준으로 유지한다.

- internal `artifact_id`
- provider/source stable identifier
- mount relationship
- revision/fingerprint

Virtual path 변경은 Artifact identity 변경을 의미하지 않는다.

---

# 3. 최종 기술 방향

## Application Plane

- **Frontend**: React + TypeScript + Vite
- **Desktop Shell**: Electron
- **Backend**: Python + FastAPI + Pydantic
- **Runtime**: Cloud Run
- **Application DB**: Firestore Native mode
- **Async Work Queue**: Cloud Tasks
- **Credentials / Secrets**: Secret Manager + provider credential vault abstraction
- **Scheduled Safety Work**: Cloud Scheduler
- **Observability**: Cloud Logging / Monitoring / Audit Logs

## AI / Analysis

- **Core model**: Gemini 3.6 Flash
- **Patent external source**: KIPRIS
- **License identity/reference**: SPDX + package metadata
- **RAG**: Vertex AI RAG Engine
- **RAG backend**: RagManagedDb Basic as initial managed backend
- **RAG placement**: external GA region

## Region Strategy

```text
Application/API/Firestore/Risk state
-> Seoul Application Plane

RAG Engine
-> External GA region
```

이 Hybrid Region 구조는 임시 우회가 아니라 의도적인 architecture decision이다.

## 명시적 비채택

현재 구현과 문서에서 다음은 사용하지 않는다.

- user PAT 기반 GitHub authentication
- raw source proxy/viewer
- Preview RAG Engine region을 Core에 사용

---

# 4. 3개 개발축

## Agent 1 — Platform & Control Plane

책임 한 문장:

> 누가 어떤 Risk Workspace에서 무엇을 관리할 수 있고, Source 및 Intelligence 결과를 어떻게 신뢰 가능한 application state / Risk lifecycle / 사용자 경험으로 만드는가.

주요 소유 영역:

- App authentication
- RiskWorkspace / Membership / Role
- WorkspaceMount metadata
- VWS security policy
- Security Gate
- Firestore canonical schema
- Change/Analysis orchestration
- Risk lifecycle / Review disposition
- RiskEvent / AuditEvent / SourceAccessEvent
- Notifications
- Product web UI

---

## Agent 2 — Source Integration & Desktop

책임 한 문장:

> Google Drive / GitHub / Local Source를 최소권한으로 연결하고, 실제 변경을 안전하게 감지·정규화하여 표준 Source Contract로 전달하는가.

주요 소유 영역:

- Google Drive OAuth / Picker / tracking / changes
- GitHub App / private repo / webhook / tracking
- Electron Desktop / folder picker / watcher / local registry
- Source-level scope
- Original source locator
- Local transient staging
- Source runtime/reconcile state
- Source management UI

---

## Agent 3 — Risk Intelligence & RAG

책임 한 문장:

> 보안 필터를 통과한 Artifact를 Patent / License 관점에서 근거 기반으로 분석하여 재현 가능한 AnalysisResult를 만드는가.

주요 소유 영역:

- Analyzer interface
- Patent analyzer
- License analyzer
- Gemini integration
- KIPRIS integration
- SPDX / package metadata
- RAG Engine ingestion / retrieval
- Evidence validation
- AnalysisResult generation

---

# 5. 절대 의존성 규칙

세 개발축은 서로의 내부 구현을 직접 import하지 않는다.

## 금지

```text
Control -> connectors internal modules       FORBIDDEN
Control -> intelligence internal modules     FORBIDDEN

Source -> core/application internals         FORBIDDEN
Source -> intelligence internals             FORBIDDEN

Intelligence -> core/application internals   FORBIDDEN
Intelligence -> connectors internals         FORBIDDEN
```

## 허용

```text
Control -> shared contracts                  ALLOWED
Source -> shared contracts                   ALLOWED
Intelligence -> shared contracts             ALLOWED

Integration layer -> all implementations     ALLOWED
```

### 핵심 원칙

> Source Plane은 Risk를 모른다.  
> Intelligence Plane은 Source provider를 모른다.  
> Control Plane은 provider와 analyzer 내부 구현을 모른다.  
> Integration Layer만 실제 구현체를 조립한다.

---

# 6. Repository Layout — 최종 기준

```text
/
├─ README.md
├─ docs/
│  ├─ MEETING_BLUEPRINT.md
│  ├─ CODING_AGENT_MASTER_SPEC.md
│  └─ ...
│
├─ shared/
│  └─ contracts/
│     ├─ README.md
│     ├─ python/
│     │  └─ iprisk_contracts/
│     │     ├─ common.py
│     │     ├─ source_adapter.py
│     │     ├─ source_change.py
│     │     ├─ source_snapshot.py
│     │     ├─ analysis_artifact.py
│     │     └─ analysis_result.py
│     ├─ schemas/
│     ├─ typescript/
│     │  └─ generated/
│     └─ tests/
│
├─ backend/
│  └─ src/ip_risk_agent/
│     ├─ core/                 # Agent 1
│     ├─ application/          # Agent 1
│     ├─ persistence/          # Agent 1
│     ├─ api/                  # Agent 1 + source-owned isolated routers
│     ├─ connectors/           # Agent 2
│     ├─ intelligence/         # Agent 3
│     ├─ composition/          # Integration only
│     ├─ main.py               # Integration only
│     └─ worker.py             # Integration only
│
├─ frontend/
│  └─ src/
│     ├─ app/                  # Agent 1
│     ├─ auth/                 # Agent 1
│     ├─ workspace/            # Agent 1
│     ├─ risk/                 # Agent 1
│     ├─ history/              # Agent 1
│     ├─ security/             # Agent 1
│     ├─ sources/              # Agent 2
│     └─ shared/               # Agent 1 owns shared UI primitives
│
├─ apps/
│  └─ desktop/                 # Agent 2
│
├─ rag-corpus/                 # Agent 3
│
├─ tests/
│  ├─ control/                 # Agent 1
│  ├─ connectors/              # Agent 2
│  ├─ intelligence/            # Agent 3
│  ├─ integration/             # Integration only
│  └─ e2e/                     # Integration only
│
├─ deploy/                     # Integration only
└─ root toolchain/config files # Integration only
```

---

# 7. Frozen Shared Contracts

`shared/contracts/**`는 **개발 시작 전 생성·동결**한다.

세 병렬 Coding Agent는 이 영역을 수정하지 않는다.

Contract 수정이 필요하면 직접 변경하지 말고 다음 형태의 요청만 남긴다.

```text
contract-change-requests/
  agent1-001.md
  agent2-001.md
  agent3-001.md
```

최종 Integration Agent가 변경 필요성을 판단한다.

## Contract version

MVP는 모든 데이터 Contract에:

```text
contract_version = "1"
```

을 사용한다.

Pydantic model은 기본적으로:

```python
ConfigDict(extra="forbid")
```

를 사용하여 암묵적 custom field를 금지한다.

---

# 8. 공통 Enum / Value Object

아래 타입은 `common.py`에 위치하며 모든 Plane에서 동일 의미를 가진다.

## `SourceType`

```text
GOOGLE_DRIVE
GITHUB
LOCAL
```

## `ChangeType`

```text
CREATE
UPDATE
DELETE
MOVE
```

## `ArtifactKind`

최소 MVP:

```text
TEXT
SOURCE_CODE
MANIFEST
LOCKFILE
DOCUMENT_TEXT
UNKNOWN
```

실제 MIME type은 별도 문자열 field로 유지한다.

## `ContentScope`

```text
FULL_TEXT
CHANGESET_WITH_CONTEXT
METADATA_ONLY
UNSUPPORTED
```

## `AnalysisType`

```text
PATENT
LICENSE
```

하나의 Artifact에 둘 이상의 AnalysisType이 적용될 수 있다.

## `AnalysisStatus`

```text
SUCCEEDED
FAILED
INCONCLUSIVE
SKIPPED
```

## `AnalysisCoverage`

```text
COMPLETE
PARTIAL
NONE
```

## `OriginalSourceType`

```text
PROVIDER_URL
LOCAL_DEVICE
UNAVAILABLE
```

---

# 9. Contract 1 — `SourceAdapter`

`SourceAdapter`는 Source Plane이 구현하고 Control Plane이 소비하는 행동 계약이다.

권장 Protocol:

```python
class SourceAdapter(Protocol):
    source_type: SourceType

    async def health(self, mount: MountRef) -> SourceHealth: ...

    async def fetch_snapshot(
        self,
        change: SourceChange,
    ) -> SourceSnapshot: ...

    async def resolve_original(
        self,
        artifact: SourceArtifactRef,
    ) -> OriginalSourceLocator: ...

    async def reconcile(
        self,
        mount: MountRef,
        cursor: str | None,
    ) -> ReconcileResult: ...
```

## SourceAdapter MUST

- Provider credential을 Connector 내부에 격리한다.
- Input/Output은 shared Contract만 사용한다.
- Risk/Review state를 직접 읽거나 쓰지 않는다.
- Analyzer/Gemini/KIPRIS를 호출하지 않는다.
- `fetch_snapshot()`에서 Source access log에 필요한 receipt 정보를 생성한다.

## `resolve_original()` 의미

### Drive

```text
PROVIDER_URL -> Google Drive original URL
```

### GitHub

```text
PROVIDER_URL -> GitHub blob/file URL
```

### Local

```text
LOCAL_DEVICE -> device_id + artifact opaque id
```

Local absolute path는 Contract로 전달하지 않는다.

---

# 10. Contract 2 — `SourceChange`

의미:

> Source에서 Artifact에 변경이 관찰되었음을 표현하는 content-free event.

권장 필드:

```text
SourceChange
- contract_version: "1"
- event_id: UUID/string
- provider_event_id: optional string
- event_fingerprint: string

- risk_workspace_id: string
- mount_id: string
- source_workspace_id: string
- source_type: SourceType

- artifact: SourceArtifactRef
- previous_artifact: optional SourceArtifactRef

- change_type: ChangeType
- revision: optional string
- previous_revision: optional string

- observed_at: UTC datetime
- safe_metadata: dict[str, JSON-safe primitive]
```

## `SourceArtifactRef`

```text
- source_artifact_id: string
- display_name: string
- path_hint: optional string
```

`path_hint`는 presentation/trace용이다. identity key로 사용하지 않는다.

## SourceChange MUST NOT contain

- raw source content
- OAuth token / refresh token
- GitHub installation token
- local absolute path
- credential material
- prompt text

## Idempotency

각 Connector는 `event_fingerprint`를 안정적으로 생성한다.

Control Plane은 이를 기반으로 duplicate event를 무해하게 처리해야 한다.

Source별 예시:

```text
GitHub: repo + tracked branch + commit SHA + path
Drive: file ID + source revision/version
Local: mount/device + relative path + content/change fingerprint
```

정확한 hash algorithm은 Connector 구현 내부에서 결정 가능하지만 결과는 deterministic해야 한다.

---

# 11. Contract 3 — `SourceSnapshot`

의미:

> SourceAdapter가 실제 Source를 읽어 획득한 **Security Gate 이전의 transient analysis input**.

권장 필드:

```text
SourceSnapshot
- contract_version: "1"

- risk_workspace_id
- mount_id
- source_workspace_id
- source_type
- source_artifact_id

- resolved_revision
- retrieved_at

- display_name
- logical_path_hint
- mime_type
- artifact_kind
- content_scope

- text_segments: list[TextSegment]

- checksum
- byte_size
- source_access_receipt
```

## `TextSegment`

```text
- segment_id
- text
- line_start: optional int
- line_end: optional int
- segment_kind:
    FULL
    CHANGED
    CONTEXT
```

## `SourceAccessReceipt`

```text
- access_type:
    METADATA
    DIFF
    PARTIAL_CONTENT
    FULL_CONTENT
- provider_request_id: optional
- content_bytes: int
- occurred_at
```

이 receipt는 Control Plane이 `SourceAccessEvent`를 생성할 수 있게 한다.

## Snapshot lifecycle

`SourceSnapshot`은 원칙적으로 transient다.

MUST NOT:

- canonical Firestore record로 장기 저장
- RiskEvent payload에 그대로 저장
- 로그에 원문 전체를 출력

---

# 12. Local Snapshot Staging

Local Source는 cloud Worker가 나중에 OS filesystem에 직접 접근할 수 없다.

따라서 Local Connector는 transient staging을 허용한다.

권장 구조:

```text
Electron Desktop
 -> selected/changed content
 -> private temporary staging object
 -> LocalAdapter.fetch_snapshot()
 -> Security Gate
 -> delete ASAP
```

Staging 요구조건:

- Seoul Application Plane에 배치
- private bucket/object
- opaque random object ID
- short TTL lifecycle auto-delete
- Source Manager 또는 일반 user에게 직접 public URL 제공 금지
- analysis completion 후 best-effort 즉시 삭제
- logs에 content/path 기록 금지

Firestore나 Cloud Tasks payload에 Local 전체 원문을 직접 넣지 않는다.

---

# 13. Contract 4 — `AnalysisArtifact`

의미:

> Control Plane Security Gate를 통과해 Risk Intelligence가 처리해도 되는 **승인된 최소 분석 입력**.

이 Contract가 시스템의 주요 보안 경계다.

권장 필드:

```text
AnalysisArtifact
- contract_version: "1"
- analysis_job_id

- risk_workspace_id
- mount_id
- artifact_id

- logical_path
- revision
- artifact_kind
- mime_type

- requested_analyzers: list[AnalysisType]
- content_scope
- text_segments

- security_context: AnalysisSecurityContext
- created_at
```

## `AnalysisSecurityContext`

```text
- approved: bool
- policy_version: string
- redaction_count: int
- original_checksum: string
- analysis_input_checksum: string
```

## Critical invariant

Risk Intelligence는 다음 조건이 아닌 Artifact를 분석해서는 안 된다.

```text
security_context.approved == true
```

Intelligence layer는 defense-in-depth 차원에서 이를 직접 검증한다.

## Intelligence MUST NOT

- Drive API 호출
- GitHub API 호출
- local file open
- Source credential 접근
- VWS `.ipriskignore` 재해석
- unfiltered SourceSnapshot 요청

---

# 14. Security Gate — Control Plane 소유

`SourceSnapshot -> AnalysisArtifact` 변환은 Control Plane의 단일 Security Gate가 담당한다.

처리 순서:

```text
1. Provider authorization already verified by Connector
2. Source Workspace tracking scope check
3. VWS global .ipriskignore
4. optional Source-level .ipriskignore result
5. file type / size policy
6. secret / credential filtering
7. data minimization
8. analyzer eligibility routing
9. analysis-input checksum
10. approved AnalysisArtifact creation
```

## deny wins

어느 단계에서든 deny면 아래 단계로 전달하지 않는다.

## Global invariant

> Effective tracked scope 밖의 Artifact는 Analyzer 또는 AI Provider에 도달해서는 안 된다.

---

# 15. `.ipriskignore`

VWS-wide security policy를 논리적인 `.ipriskignore`로 표현한다.

실제 Source filesystem에 존재할 필요는 없다.

예:

```gitignore
/backend/**/.env*
/backend/**/secrets/**
/backend/**/*.pem
/prototype/customer-data/**
/design/private-hr/**
```

Source-level `.ipriskignore`는 Local/GitHub에서 optional 추가 deny source로 사용할 수 있다.

우선순위:

```text
Provider / Source scope
AND
VWS policy
AND
Source policy
```

모든 deny는 허용보다 우선한다.

---

# 16. Contract 5 — `AnalysisResult`

의미:

> Risk Intelligence가 Control에 반환하는 분석 결과. **Risk state 자체가 아니다.**

권장 필드:

```text
AnalysisResult
- contract_version: "1"

- analysis_job_id
- artifact_id
- revision
- analysis_type

- status: AnalysisStatus
- coverage: AnalysisCoverage

- candidates: list[Candidate]
- evidence: list[Evidence]
- provider_failures: list[ProviderFailure]

- versions: AnalysisVersions

- started_at
- completed_at
```

## `AnalysisVersions`

```text
- analyzer_version
- model_id: optional
- prompt_version: optional
- policy_version: optional
- rag_corpus_version: optional
```

## `ProviderFailure`

```text
- provider
- category
- retryable
- safe_message
```

credential/token/raw response 전체를 넣지 않는다.

---

# 17. Analysis Status 의미 — 고정

## `SUCCEEDED`

정상적으로 분석이 완료되었다.

후보 0건이어도 SUCCEEDED일 수 있다.

## `FAILED`

필수 external/provider/system 단계가 실패하여 정상 분석을 완료하지 못했다.

예:

- KIPRIS timeout
- Gemini request failure
- required RAG failure
- malformed output after retry budget exhausted

## `INCONCLUSIVE`

pipeline 자체는 실행되었으나 입력 또는 근거 부족으로 결론을 낼 수 없다.

예:

- insufficient technical context
- unresolved/unknown license metadata

## `SKIPPED`

해당 analyzer 적용 대상이 아니거나 명시적으로 분석 불필요로 판정되었다.

---

# 18. Coverage 의미 — 고정

## `COMPLETE`

이 AnalysisResult가 해당 revision에서 analyzer가 평가해야 할 전체 범위를 성공적으로 평가했다.

## `PARTIAL`

일부 후보/일부 데이터만 평가되었다.

## `NONE`

유효한 분석 범위가 없다.

### Risk Resolution Rule — MUST

기존 Risk를 자동 해소할 수 있는 것은 원칙적으로:

```text
status == SUCCEEDED
AND
coverage == COMPLETE
```

인 Result뿐이다.

다음은 기존 Risk를 자동 resolve할 수 없다.

```text
FAILED
INCONCLUSIVE
PARTIAL coverage
NONE coverage
```

---

# 19. Candidate Contract

Intelligence는 Risk ID/lifecycle을 만들지 않는다.

## Patent Candidate

최소 canonical fields:

```text
- normalized_application_number
- title
- suggested_review_priority
- matched_elements
- evidence_ids
- provider_metadata_safe
```

Control Plane의 stable identity input:

```text
artifact_id + PATENT + normalized_application_number
```

## License Candidate

최소 canonical fields:

```text
- ecosystem
- normalized_package_name
- resolved_version: optional
- normalized_license_expression
- policy_outcome
- evidence_ids
- uncertainty_flags
```

Control Plane의 stable identity input:

```text
artifact_id
+ LICENSE
+ ecosystem
+ normalized_package_name
+ resolved_version
+ normalized_license_expression
```

실제 risk key hash 구현은 Control Plane 내부 책임이다.

---

# 20. Evidence Contract

```text
Evidence
- evidence_id
- evidence_type
- excerpt
- reference
- metadata_safe
```

MVP EvidenceType 예:

```text
SOURCE_EXCERPT
PATENT_CLAIM
PATENT_ABSTRACT
LICENSE_REFERENCE
RAG_REFERENCE
PACKAGE_METADATA
```

## Evidence rules

- 전체 raw source를 Evidence로 저장하지 않는다.
- source excerpt는 Risk 검토에 필요한 최소 범위로 제한한다.
- patent/license external evidence는 원본 reference를 유지한다.
- model이 참조한 evidence ID가 실제 evidence 목록에 존재하는지 code로 검증한다.

---

# 21. 전체 Processing Pipeline — 고정

```text
Source event
   ↓
Connector verify / normalize
   ↓
SourceChange
   ↓
Control persist + idempotency
   ↓
Cloud Tasks
   ↓
SourceAdapter.fetch_snapshot()
   ↓
SourceSnapshot
   ↓
SourceAccessEvent record
   ↓
Control Security Gate
   ↓
AnalysisArtifact
   ↓
Analyzer Registry
   ↓
Patent / License Analyzer
   ↓
AnalysisResult
   ↓
Control validates result
   ↓
Risk Lifecycle reconcile transaction
   ↓
Risk / RiskEvidence / RiskEvent
   ↓
Notification / UI
```

Source Plane과 Intelligence Plane 사이에는 직접 호출 경로가 없다.

---

# 22. Risk Lifecycle — Control Plane 전용

Machine lifecycle:

```text
NEW -> EXISTING -> RESOLVED
         ^          |
         |----------|
          REOPEN
```

구현 enum은 필요에 따라 명명할 수 있으나 의미는 유지한다.

## Rules

- Candidate 최초 등장 -> NEW
- 다음 complete successful analysis에서도 존재 -> EXISTING
- complete successful analysis에서 사라짐 -> RESOLVED
- RESOLVED candidate가 다시 등장 -> REOPEN/active
- FAILED / INCONCLUSIVE analysis -> 기존 active state 유지
- Source DELETE -> Risk 자동 RESOLVED 금지

Source 삭제/연결 해제와 IP Risk 해소는 동일 의미가 아니다.

---

# 23. Human Review Disposition — Machine Lifecycle과 분리

권장 상태:

```text
UNREVIEWED
MONITORING
ACCEPTED_RISK
EXCLUDED
```

사용자 disposition 변경이 machine lifecycle을 변경하지 않는다.

예:

```text
EXCLUDED != RESOLVED
```

반대로 machine Risk가 RESOLVED되어도 review/history는 보존한다.

---

# 24. Application Role — 확정

```text
OWNER
SOURCE_MANAGER
RISK_REVIEWER
VIEWER
```

상위 역할은 기본 UI capability 상 하위 기능을 포함한다.

## Viewer

- VWS 조회
- Risk 조회
- Risk history/activity 조회
- 허용된 최소 Evidence 조회

## Risk Reviewer

Viewer +

- review disposition 변경
- review comment
- monitoring/accepted/excluded 판단

## Source Manager

Risk Reviewer +

- SourceWorkspace Mount 생성
- 자신이 Mount한 Source의 custodian
- 자신의 Mount scope/reconnect/disconnect/rename 관리

다른 Source Manager의 Mount를 관리하지 않는다.

## Workspace Owner

- VWS 최고 관리자
- Member / Role 관리
- VWS security / retention policy
- global `.ipriskignore`
- Audit 관리
- Mount administrative disable/remove
- VWS deletion / ownership transfer

### Critical authority rule

```text
VWS Role != Source Provider Authority
```

Owner라도 타인의 provider credential을 사용할 수 없다.

---

# 25. Mount Ownership

`WorkspaceMount`에는 최소:

```text
mounted_by_user_id
source_connection_id
```

가 존재한다.

Source Manager가 provider scope를 확대하려면:

```text
Role >= SOURCE_MANAGER
AND
mount.mounted_by_user_id == current_user
AND
source credential authority belongs to current user
```

가 필요하다.

Owner는 다른 Mount를 administrative disable/remove할 수 있지만 타인의 OAuth credential을 사용한 scope 확대는 불가능하다.

---

# 26. Source Manager 제거/탈퇴

Mount를 즉시 삭제하지 않는다.

가능한 operational state:

```text
ACTIVE
REAUTH_REQUIRED
MANAGER_ACTION_REQUIRED
SOURCE_OFFLINE
DISABLED
```

Provider별 처리:

- Drive: 새 관리자가 자신의 credential로 재연결 가능
- GitHub: installation authority를 재확인 후 재연결/재지정 가능
- Local: 기존 device source ownership transfer보다 replacement source 재연결을 사용

타인의 refresh token을 사용자 간 이전하지 않는다.

---

# 27. App Login / Drive Authorization

앱 사용자는 Google OIDC로 로그인한다.

App authentication과 Drive authorization은 별도 credential/context이다.

하나의 App User가 여러 Google account의 Drive Connection을 동시에 유지할 수 있어야 한다.

```text
App User
  login: alice@gmail.com

Drive Connections
  research@company.com
  patent-team@company.com
  alice@gmail.com
```

Drive Picker는 App login identity가 아니라 **선택된 Drive SourceConnection의 access token**으로 동작한다.

Drive SourceWorkspace는 `drive.file` + Picker를 기본 보안 모델로 한다.

---

# 28. GitHub Authorization

GitHub는 **GitHub App**을 사용한다.

MUST:

- selected repository installation 지원
- private repository 지원
- repository contents는 Read-only 우선
- webhook signature 검증
- short-lived installation access token 사용
- user PAT 장기보관 금지

MVP GitHub SourceWorkspace는 **tracked branch 1개**를 사용한다.

기본값은 repository default branch.

Application-level path include/exclude tracking scope를 추가로 적용한다.

전체 repository clone은 기본 방식으로 사용하지 않는다.

변경된 tracked path 중심으로 fetch한다.

---

# 29. Google Drive Source Model

Google Drive는 filesystem mirror로 취급하지 않는다.

Drive SourceWorkspace는 Picker에서 선택된 Artifact collection이다.

```text
/design
  architecture.docx
  algorithm.pdf
  idea.docx
```

각 파일은 Drive stable file ID로 identity를 유지한다.

실제 parent hierarchy는 display metadata일 뿐 VWS identity가 아니다.

Drive monitoring은:

```text
push/change notification
+ changes cursor
+ periodic reconcile safety net
```

구조를 사용한다.

---

# 30. Local Source Model

Local SourceWorkspace는 Desktop Native Folder Picker로 선택한 하나의 root를 기본 단위로 한다.

MUST:

- selected root 밖 접근 금지
- canonicalize path 후 root descendant 검증
- symlink escape 방지
- renderer에 arbitrary filesystem API 노출 금지
- local absolute path backend persistence 지양
- debounce / temp/build output filtering
- VWS + source `.ipriskignore` 적용 가능

Desktop privileged operation은 Electron main/preload boundary에서 수행한다.

Renderer API 예:

```text
openTrackedArtifact(artifactId)
chooseTrackedDirectory()
```

금지 예:

```text
readAnyFile(path)
openAnyPath(path)
listAnyDirectory(path)
```

---

# 31. Raw Source Policy — 고정

> IP Risk Agent는 raw source proxy/viewer가 아니다.

## Drive

`Open Original` -> Google Drive URL -> Google authorization

## GitHub

`Open Original` -> GitHub URL -> GitHub authorization

## Local

Web backend가 raw source를 반환하지 않는다.

Desktop owning device에서만 local artifact registry를 통해 OS/editor로 연다.

### Global rule

VWS permission만으로 raw source access가 가능해져서는 안 된다.

---

# 32. Mount의 공유 의미

SourceWorkspace를 VWS에 Mount한다고 해서 VWS Member가 raw source permission을 획득하는 것은 아니다.

다만 분석으로 생성되는 다음 데이터는 VWS permission 범위에서 공유될 수 있다.

- Risk state
- minimal Risk Evidence
- Review disposition/comment
- Risk history
- audit/activity

Mount UI에서 이 의미를 명확하게 고지한다.

---

# 33. Analyzer Registry

Artifact는 한 개의 analyzer만 선택하는 방식이 아니다.

```text
Analyzer.supports(AnalysisArtifact) -> bool / routing metadata
```

하나의 Artifact가 PATENT와 LICENSE 모두에 해당할 수 있다.

예:

```text
requirements.txt -> LICENSE primarily
source code -> PATENT, future provenance/copyright possible
design document -> PATENT
```

MVP registry는 PATENT / LICENSE만 포함한다.

---

# 34. Patent Analysis Specification — 공통 수준

목표는 법적 침해 판정이 아니라 **Review Priority + grounded evidence**다.

권장 flow:

```text
AnalysisArtifact
 -> technical element extraction
 -> search-query generation
 -> KIPRIS search
 -> candidate dedup/ranking
 -> patent detail / claims / abstract
 -> evidence chunks
 -> Gemini grounded comparison
 -> evidence-reference validation
 -> suggested review priority
 -> PatentCandidate(s)
```

MUST:

- KIPRIS 0 candidates와 KIPRIS failure 구분
- application number normalize/dedup
- model evidence ID 검증
- legal conclusion 표현을 결과 contract로 강제하지 않음
- provider failure를 low-risk 결과로 바꾸지 않음

---

# 35. License Analysis Specification — 공통 수준

원칙:

```text
License decision = deterministic policy
Gemini/RAG = evidence explanation
```

권장 flow:

```text
manifest/lockfile
 -> dependency extraction
 -> resolved version preference
 -> package metadata
 -> SPDX normalization
 -> deterministic workspace policy
 -> evidence/RAG explanation
 -> LicenseCandidate(s)
```

MUST:

- lockfile/resolved version 우선
- version uncertainty 표시
- unknown/non-standard license를 임의 허용으로 해석하지 않음
- LLM이 deterministic policy outcome override 금지

---

# 36. RAG Architecture — 확정

RAG Engine은 **reference knowledge plane**이다.

Persistent corpus에 넣는 것:

- SPDX / license texts
- license obligation/reference documents
- curated IP guidance
- organization/internal policy reference if approved
- future copyright/IP reference

Persistent corpus에 기본적으로 넣지 않는 것:

- private GitHub repo 전체
- private Drive project documents 전체
- Local source 전체
- unpublished workspace source corpus

핵심 구분:

```text
Source Workspace = analysis target
RAG Corpus       = reference knowledge
```

RAG corpus는 version을 가진다.

`AnalysisResult.versions.rag_corpus_version`에 기록 가능해야 한다.

---

# 37. Firestore Canonical Collections — Control Plane 전용

최소 collection 개념:

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

Canonical collection schema의 최종 소유자는 Agent 1이다.

Agent 2/3은 이 collection에 arbitrary direct write를 하지 않는다.

필요 persistence는 Control-owned repository/port 또는 자기 Plane의 isolated operational store를 사용한다.

---

# 38. Source Operational State

Agent 2는 connector operation에 필요한 state를 별도 namespace/store에서 관리할 수 있다.

예:

- Drive cursor
- watch channel ID/expiry
- GitHub installation metadata cache
- webhook runtime state
- Local device registration
- local staging object metadata

이 state는 Risk/Membership/Review domain을 포함해서는 안 된다.

---

# 39. ChangeEvent / AnalysisJob State

Control Plane의 persistence state는 retry/idempotency를 지원해야 한다.

권장 ChangeEvent processing state:

```text
PENDING
PROCESSING
DONE
FAILED
```

권장 AnalysisJob state:

```text
QUEUED
RUNNING
SUCCEEDED
FAILED
INCONCLUSIVE
```

동일 event/job의 중복 실행이 중복 Risk를 생성하지 않아야 한다.

---

# 40. Cloud Tasks Boundary

Webhook/source event handler는 무거운 분석을 동기식으로 실행하지 않는다.

```text
receive event
 -> verify
 -> normalize
 -> persist idempotently
 -> enqueue Cloud Task
 -> ACK
```

Worker가 SourceSnapshot fetch, Security Gate, analysis, reconcile을 수행한다.

Cloud Tasks는 retry/rate/concurrency 제어의 공통 boundary다.

---

# 41. API Namespace Ownership

정확한 route는 Agent별 상세 명세에서 확정하되 namespace 충돌을 피하기 위해 다음 ownership을 고정한다.

## Agent 1

```text
/api/v1/auth/**
/api/v1/workspaces/**
/api/v1/risks/**
/api/v1/history/**
/api/v1/security/**
/api/v1/notifications/**
```

## Agent 2

```text
/api/v1/source-connections/**
/api/v1/source-workspaces/**
/api/v1/mounts/{mount_id}/source-operations/**
/webhooks/google-drive/**
/webhooks/github/**
/desktop/**  # server-facing desktop protocol if needed
```

Agent 2 router는 VWS authorization 결정을 자체 구현하지 않고 Control Plane이 제공하는 authorization port를 사용하도록 통합한다.

## Internal / Integration

```text
/internal/tasks/**
/internal/scheduled/**
```

최종 route wiring은 Integration Layer가 담당한다.

---

# 42. Frontend Ownership

## Agent 1 owns

```text
app shell
auth
VWS navigation
membership/roles
risk dashboard
risk detail
risk timeline
workspace activity
security & data access shell
shared design primitives
```

## Agent 2 owns

```text
source connection flows
Drive connection/picker UX
GitHub installation/repo UX
Local mount UX
source status/scope components
Desktop-only UX
```

## Agent 3

직접 product frontend를 소유하지 않는다.

Agent 3는 Evidence/AnalysisResult가 UI에 필요한 정보를 contract로 제공한다.

Risk UI 표시 책임은 Agent 1이다.

---

# 43. Security & Data Access UI — 필수 제품 기능

최소 표시:

- 연결된 Mount와 provider/account/device
- tracking scope summary
- VWS `.ipriskignore` 활성 상태
- source retention policy
- external RAG가 reference knowledge만 저장한다는 설명
- 최근 SourceAccessEvent
- source connection health
- disconnect/manage actions subject to role/authority

사용자가 다음을 확인할 수 있어야 한다.

```text
현재 시스템이 어떤 자료를 볼 수 있는가?
실제로 어떤 자료를 읽었는가?
어떤 데이터가 장기 보존되는가?
```

---

# 44. Audit / History

## RiskEvent

Risk lifecycle/review history.

append-only.

## AuditEvent

관리/보안 이벤트.

예:

```text
SOURCE_CONNECTED
SOURCE_DISCONNECTED
MOUNT_CREATED
MOUNT_SCOPE_CHANGED
SECURITY_POLICY_CHANGED
MEMBER_INVITED
MEMBER_REMOVED
ROLE_CHANGED
ANALYSIS_FAILED
```

## SourceAccessEvent

고빈도 Source data access record.

MUST NOT store actual source content.

---

# 45. Data Retention

기본 원칙:

- raw source long-term persistence 최소화
- SourceSnapshot transient
- Local staging short TTL
- Evidence minimal excerpt
- revision/hash/reference 저장
- OAuth token / refresh token / private key logs 금지
- full prompt logs 금지
- full Gemini raw response logs 금지
- local absolute path cloud persistence 지양

기본 Evidence retention mode는 **Balanced**를 기준으로 구현한다.

---

# 46. Analysis Reproducibility

AnalysisJob / Result / evidence history에서 다음 정보를 추적 가능하게 한다.

```text
source revision
analyzer version
model id
prompt version
policy version
RAG corpus version
```

모든 field가 모든 analyzer에 필수일 필요는 없지만 가능한 경우 기록한다.

---

# 47. Credentials and Secret Ownership

## Google App Login

Control Plane authentication configuration.

## Drive OAuth

Source Plane connector credential.

한 App User가 여러 Google account의 Drive credential을 가질 수 있다.

## GitHub

GitHub App private key / webhook secret은 Secret Manager.

API access는 short-lived installation token.

## GCP

service-account JSON key 파일 생성/배포 금지.

Cloud Run attached service identities 사용.

---

# 48. Service Accounts — 권장 분리

## `app-api-sa`

- Control/API runtime
- Firestore application operations
- Cloud Tasks enqueue
- 필요한 connector callback orchestration

## `analysis-worker-sa`

- Worker runtime
- Firestore analysis/risk operations via application layer
- Gemini
- RAG retrieval
- 필요한 provider secret read

## `scheduler-sa`

- scheduled internal endpoint invoke
- Drive watch renewal / reconcile trigger

## `deploy-sa`

- build/deploy
- Artifact Registry / Cloud Run deployment
- runtime private data read 금지

필요하면 RAG ingestion identity를 추후 분리할 수 있다.

---

# 49. Observability

모든 Plane은 structured logging을 사용한다.

공통 correlation IDs:

```text
event_id
analysis_job_id
risk_workspace_id
mount_id
artifact_id
```

로그에 남겨도 되는 것:

- internal IDs
- source type
- analyzer type
- provider status category
- latency
- candidate count
- coverage
- model/prompt version

로그 금지:

- OAuth/refresh/access token
- source full text
- local absolute sensitive path where unnecessary
- full AI prompt
- full raw model response
- private keys

---

# 50. Error Semantics

모든 external integration은 error를 명시적으로 분류한다.

권장 category:

```text
AUTH
PERMISSION
NOT_FOUND
RATE_LIMIT
TIMEOUT
PROVIDER_UNAVAILABLE
INVALID_RESPONSE
UNSUPPORTED
INTERNAL
```

사용자에게 보여줄 safe message와 internal log context를 분리한다.

Provider error를 `no risk` 또는 빈 candidate result로 변환하지 않는다.

---

# 51. Shared Contract Tests

`shared/contracts/tests/**`는 frozen test suite다.

최소 검증:

- strict serialization/deserialization
- unknown fields rejected
- enum values fixed
- required fields enforced
- content-free SourceChange
- approved AnalysisArtifact requirement helper
- AnalysisResult status/coverage combinations validation

세 Agent의 CI/unit test는 shared contract tests를 반드시 포함한다.

---

# 52. Agent 1 Test Ownership

`tests/control/**`

필수 invariant tests:

- duplicate SourceChange idempotent
- failed/inconclusive analysis cannot resolve active Risk
- successful complete zero-candidate result can resolve prior Risk
- user EXCLUDED does not equal machine RESOLVED
- Mount alias rename does not change Risk identity
- VWS role enforcement
- Source Manager only manages own Mount
- Owner cannot impersonate provider credential owner
- `.ipriskignore` deny wins
- append-only RiskEvent semantics
- DELETE does not automatically resolve Risk

---

# 53. Agent 2 Test Ownership

`tests/connectors/**`

필수 contract tests:

- Drive/GitHub/Local all produce valid `SourceChange`
- duplicate webhook/event fingerprint stability
- Drive file ID identity
- GitHub branch/path tracking enforcement
- GitHub webhook signature verification
- Local root escape/symlink prevention
- local absolute path not emitted to cloud Contract
- OriginalSourceLocator provider/local semantics
- source scope excludes untracked items
- transient local staging cleanup

---

# 54. Agent 3 Test Ownership

`tests/intelligence/**`

필수 tests:

- reject unapproved AnalysisArtifact
- Patent zero candidate = valid success
- KIPRIS failure != zero candidate
- malformed Gemini output handling
- evidence ID validation
- Patent application number normalization/dedup
- License deterministic policy not overridden by model
- lockfile/resolved version preference
- unknown license -> uncertainty/review semantics
- RAG unavailable failure semantics
- AnalysisResult strict Contract compliance

---

# 55. Integration Tests — Integration Agent only

`tests/integration/**`, `tests/e2e/**`

최소 end-to-end logical flow:

```text
SourceChange
 -> SourceAdapter.fetch_snapshot
 -> SourceSnapshot
 -> Security Gate
 -> AnalysisArtifact
 -> Analyzer
 -> AnalysisResult
 -> Risk reconcile
 -> RiskEvent
```

필수 scenarios:

1. Drive change -> Patent Risk detected
2. GitHub dependency change -> License Risk detected
3. Local source change -> Patent analysis flow
4. duplicate SourceChange -> no duplicate Risk
5. provider failure -> prior Risk preserved
6. complete re-analysis with no candidate -> Risk resolved
7. `.ipriskignore` blocked Artifact -> analyzer never called
8. unauthorized raw original -> provider/OS blocks, app does not proxy

---

# 56. Root / Integration-only Files

병렬 Agent는 아래 파일을 직접 수정하지 않는다.

```text
shared/contracts/**
backend/src/ip_risk_agent/composition/**
backend/src/ip_risk_agent/main.py
backend/src/ip_risk_agent/worker.py
deploy/**
root package/toolchain manifests
root lockfiles
root Dockerfile(s)
root CI/CD config
tests/integration/**
tests/e2e/**
```

각 Agent는 필요한 dependency/config 변경을 자신의 deliverable manifest에 기록한다.

Integration Agent가 root 설정을 합친다.

---

# 57. Dependency Requests

병렬 Agent가 root dependency file을 수정하지 않기 때문에 각 Agent는 다음 파일을 제출한다.

예:

```text
agent-deliverables/
  agent-1-dependencies.md
  agent-2-dependencies.md
  agent-3-dependencies.md
```

내용:

- required package
- purpose
- minimum/compatible version requirement if necessary
- runtime/dev dependency 구분
- environment variables
- external API/service dependency

불필요한 framework 추가를 피한다.

---

# 58. Coding Standards

## Python

- type hints 필수
- Pydantic for external/shared models
- domain logic과 SDK/client logic 분리
- async external I/O 일관성 유지
- pure deterministic logic은 가능한 pure function/service로 분리
- broad `except Exception` 후 성공 처리 금지

## TypeScript / Electron

- strict typing
- renderer에 privileged Node APIs 노출 금지
- preload bridge는 최소 capability만 제공
- source-specific UI와 product shared UI 경계 유지

## General

- secret hardcode 금지
- test에서 실제 credential 요구 금지
- provider SDK object를 shared Contract로 누출 금지
- business state를 provider payload raw JSON에 종속시키지 않음

---

# 59. Coding Agent 금지사항

모든 병렬 Agent에 공통으로 명시한다.

1. Frozen Contract를 임의 수정하지 않는다.
2. 타 Agent ownership directory를 수정하지 않는다.
3. root manifest/deploy/composition 파일을 수정하지 않는다.
4. 임시 편의를 위해 shared DB collection을 새로 만들지 않는다.
5. Source Plane에서 Risk lifecycle을 구현하지 않는다.
6. Intelligence Plane에서 Firestore Risk collection을 직접 쓰지 않는다.
7. Intelligence Plane에서 Source provider를 직접 호출하지 않는다.
8. Control Plane에서 provider-specific API 세부사항을 구현하지 않는다.
9. provider failure를 성공/빈 Risk로 숨기지 않는다.
10. raw source 전체를 로그/이력에 저장하지 않는다.
11. 테스트 통과를 위해 security validation을 disable하지 않는다.
12. mock-only implementation으로 완료를 주장하지 않는다. 외부 API는 mockable adapter를 만들되 production implementation skeleton/behavior가 존재해야 한다.

---

# 60. 각 Agent Deliverable 형식

각 Agent는 코드 외에 반드시 다음을 제출한다.

```text
AGENT_DELIVERY.md
```

필수 내용:

1. 구현한 범위
2. 변경한 파일 목록
3. 외부 dependency 목록
4. 필요한 environment variables
5. 실행 방법
6. test 실행 방법과 결과
7. shared Contract 준수 여부
8. contract-change request 목록
9. Integration Agent가 알아야 할 wiring point
10. 미완성/제약/known issue

Integration Agent는 이 파일을 먼저 읽고 통합한다.

---

# 61. Integration Layer 책임

Integration Agent는 세 Plane의 내부 구현을 재작성하는 것이 목적이 아니다.

주요 책임:

```text
1. dependency/root config merge
2. SourceAdapter registry wiring
3. Analyzer registry wiring
4. repository/store wiring
5. API router composition
6. Cloud Tasks worker composition
7. scheduler composition
8. environment config merge
9. integration/e2e tests
10. contract change requests reconciliation
```

대표 composition:

```text
SourceType.GOOGLE_DRIVE -> GoogleDriveAdapter
SourceType.GITHUB       -> GitHubAdapter
SourceType.LOCAL        -> LocalAdapter

AnalysisType.PATENT  -> PatentAnalyzer
AnalysisType.LICENSE -> LicenseAnalyzer
```

---

# 62. 통합 시 Contract 변경 정책

Integration Agent만 Contract v1 수정 여부를 판단할 수 있다.

가능하면 additive/internal adapter로 해결하고 Contract 수정은 최소화한다.

Breaking change가 불가피한 경우:

- 세 Agent deliverable과 tests를 모두 검토
- schema update
- generated TS type 재생성
- shared contract tests 수정
- affected Plane adapter 수정
- `contract_version` 전략 재평가

MVP 중에는 가능한 한 v1을 유지한다.

---

# 63. SourceWorkspace 재사용 정책

MVP에서 **하나의 SourceWorkspace instance를 여러 VWS에 공유하지 않는다.**

동일 provider resource를 두 VWS에 연결하려면 별도의 SourceWorkspace/Mount를 만든다.

단 SourceConnection은 재사용 가능하다.

```text
SourceConnection
  ├─ SourceWorkspace A -> VWS A
  └─ SourceWorkspace B -> VWS B
```

이유:

- VWS마다 tracking scope가 다를 수 있음
- VWS security policy가 다름
- Risk/history가 다름

---

# 64. Move / Delete semantics

## DELETE

Artifact unavailable/deleted 상태로 기록한다.

Risk 자동 resolve 금지.

## MOVE

- Drive stable file ID: 동일 Artifact 유지
- GitHub/Local rename: `previous_artifact`를 활용하여 Control이 identity continuity 판단

Connector가 Risk identity를 직접 변경하지 않는다.

---

# 65. Web / Desktop 통합 원칙

React UI를 Web과 Electron renderer가 최대한 공유한다.

Desktop-only capability는 adapter boundary로 격리한다.

```text
PlatformAdapter
- platform
- chooseLocalDirectory()
- openTrackedArtifact()
- showNativeNotification() optional
```

Web에서는 local-only 기능을 숨기거나 unavailable 상태로 표시한다.

---

# 66. Product Completion Criteria — 전체

최종 프로젝트는 최소 다음을 만족해야 한다.

## Identity / VWS

- Google Login 가능
- RiskWorkspace 생성/조회
- 4-level Role enforcement
- Membership 관리

## Source

- Google Drive SourceConnection + selected file tracking
- GitHub App + private/selected repo tracking
- Local Desktop selected directory tracking
- 동일 provider 복수 WS Mount 가능
- Mount alias UI

## Monitoring

- 각 Source change가 SourceChange로 normalize
- duplicate-safe processing
- Cloud Tasks based async workflow

## Security

- Provider-native least privilege
- VWS `.ipriskignore`
- Security Gate
- Local root escape protection
- raw source non-proxy
- SourceAccessEvent
- minimal retention

## Intelligence

- Patent analysis end-to-end
- License analysis end-to-end
- Gemini structured result validation
- RAG Engine reference retrieval
- provider failure semantics

## Risk Management

- Risk lifecycle
- Review disposition
- Risk timeline
- Workspace activity
- Security & Data Access view

## Audit / Operations

- structured logs
- service-account separation
- audit events
- test suites

---

# 67. 각 Plane Acceptance Criteria — 공통 관점

각 Agent는 자신의 상세 문서의 acceptance criteria 외에 다음을 만족해야 한다.

### Contract purity

다른 Plane 내부 구현 없이 자신의 unit/contract tests를 실행할 수 있어야 한다.

### Replaceability

같은 Contract를 만족하는 fake/mock implementation으로 다른 Plane을 대체하여 테스트 가능해야 한다.

### No hidden coupling

다른 Plane의 Firestore collection path, SDK type, internal class name에 의존하지 않는다.

### Security preservation

Mock/test convenience 때문에 production security boundary를 완화하지 않는다.

### Integration documentation

Integration Agent가 public constructor/port/router/wiring point를 찾기 쉬워야 한다.

---

# 68. 설계 의도 요약

이 분할은 기능을 세 등분하기 위한 것이 아니라 **의존성의 방향을 통제하기 위한 구조**다.

```text
SOURCE PLANE
  real workspace / provider authority
         |
         | SourceChange / SourceSnapshot
         v
CONTROL PLANE
  identity / policy / security / lifecycle
         |
         | AnalysisArtifact
         v
INTELLIGENCE PLANE
  patent / license / Gemini / RAG
         |
         | AnalysisResult
         v
CONTROL PLANE
  Risk reconciliation / history / UI
```

이 경계를 유지하면:

- Source 종류가 추가되어도 Analyzer 변경이 최소화된다.
- Copyright Analyzer가 추가되어도 Connector 변경이 최소화된다.
- AI/provider failure가 Risk lifecycle을 오염시키지 않는다.
- 보안 정책이 Source별로 중복 구현되지 않는다.
- 세 Coding Agent가 독립적으로 개발 가능하다.
- 마지막 Integration Agent가 연결해야 할 접점이 제한된다.

---

# 69. Coding Agent에게 전달할 최종 핵심 지시

각 Coding Agent는 반드시 다음을 기억해야 한다.

> **자신의 Plane 내부는 완결되게 구현하되, 다른 Plane의 내부를 대신 구현하지 않는다.**

> **공유 Contract는 API가 아니라 프로젝트의 경계 자체다. Contract를 우회하는 직접 호출을 만들지 않는다.**

> **보안상 허용되지 않은 데이터를 다음 Plane으로 넘기지 않는다. 특히 Intelligence는 승인된 AnalysisArtifact 외의 Source를 직접 가져오지 않는다.**

> **Risk lifecycle과 사용자 Review 상태는 Control Plane이 소유하며, AI는 AnalysisResult만 반환한다.**

> **개발 완료의 기준은 코드량이 아니라 Contract 준수, test 통과, integration 가능성, 보안 invariant 유지다.**

---

# Appendix A. 병렬 개발 전 Integration Owner가 먼저 준비할 것

세 Agent를 동시에 시작하기 전에 Integration Owner 또는 초기 skeleton 생성 Agent가 다음을 준비해야 한다.

1. Repository directory skeleton
2. Frozen `shared/contracts/**`
3. Contract tests
4. minimal importable Python packages
5. frontend workspace skeleton
6. 각 ownership directory
7. empty composition layer
8. root dependency/toolchain baseline
9. environment variable naming convention
10. Agent별 `AGENT_DELIVERY.md` template
11. `contract-change-requests/` directory

이 준비 없이 세 Agent가 각자 project skeleton을 생성하게 하면 마지막 통합 비용이 크게 증가한다.

---

# Appendix B. 현재 의도적으로 남겨둔 배포 설정 변수

아래는 architecture decision은 고정했지만 구체 값은 deployment 환경에서 설정한다.

- exact external RAG Engine GA region
- Cloud Run instance/concurrency limits
- Cloud Tasks retry/rate values
- local staging TTL
- evidence excerpt length limits
- provider request timeout/retry counts
- retention day counts

각 Agent가 임의의 전역 상수로 hardcode하지 말고 configuration으로 노출한다.

---

# Appendix C. 후속 개별 개발 문서의 역할

이 Master Specification과 별도로 세 개의 상세 문서를 만든다.

## Agent 1 문서

- exact domain schema
- Firestore schema
- API routes
- Security Gate implementation
- Risk lifecycle algorithms
- UI screens/state

## Agent 2 문서

- Drive/GitHub/Local provider flows
- OAuth/App installation details
- webhook/watch logic
- Electron IPC
- staging/reconcile implementation

## Agent 3 문서

- Patent/License analyzer algorithms
- Gemini schemas/prompts strategy
- KIPRIS/package metadata providers
- RAG corpus/ingestion/retrieval
- evidence validation

세 문서는 모두 이 Master Specification을 수정하지 않고 **구체화만** 해야 한다.
