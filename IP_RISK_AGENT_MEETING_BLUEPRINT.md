# IP Risk Agent — 프로젝트 청사진 및 아키텍처 회의 문서

> **목적**: 팀원 간 아이디어 공유, 전체 개발 구조 합의, 주요 기술·보안·권한·데이터 흐름 및 병렬 개발 경계 확인을 위한 회의용 문서  
> **문서 성격**: 구현 명세가 아니라 **무엇을 왜 만들고, 시스템을 어떤 경계로 나누며, 어떤 선택을 확정했는지**를 빠르게 공유하기 위한 청사진  
> **작성 기준**: 2026-08-14  
> **구현 명세와의 관계**: 실제 Coding Agent 개발 시에는 별도의 `CODING_AGENT_MASTER_SPEC.md`와 개발축별 상세 명세를 우선한다.

---

## 0. 한 줄 정의

**Local Directory, GitHub Repository, Google Drive 등 여러 실제 협업 Source Workspace를 하나의 Risk Workspace에 연결하고, 변경을 지속적으로 감지하여 Patent·License 중심의 잠재적 IP Risk를 근거 기반으로 분석하고, 사용자가 장기적으로 검토·추적·감사할 수 있게 하는 Secure Human-in-the-Loop AI Risk Management System.**

---

# 1. 프로젝트가 해결하려는 문제

협업 프로젝트의 IP Risk는 정적 검사 한 번으로 끝나지 않는다.

- 코드와 문서는 지속적으로 수정된다.
- dependency와 license가 변경된다.
- 기술 아이디어가 문서화되거나 구현되면서 기존 patent와의 관련성이 달라질 수 있다.
- 같은 Risk도 시간이 지나며 `신규 발견 → 검토 → 변화 → 해소 → 재발`할 수 있다.
- 원본 Source는 매우 민감하므로 분석 편의보다 **접근권한·최소 수집·감사 가능성**이 중요하다.

따라서 이 프로젝트의 핵심은 단순 AI Scanner가 아니라 다음 네 가지다.

1. **Continuous Monitoring** — 실제 Workspace 변화에 반응한다.
2. **Evidence-grounded Risk Analysis** — AI가 임의의 법적 결론을 내리는 대신 근거와 검토 우선순위를 제공한다.
3. **Human Risk Management** — 사용자가 Risk의 생애와 판단 이력을 지속적으로 관리한다.
4. **Security by Architecture** — 무엇을 연결했고 무엇을 실제로 읽었는지, 무엇을 저장하지 않는지를 구조적으로 통제한다.

---

# 2. 핵심 도메인 용어 — 확정

## 2.1 Risk Workspace (`VWS`)

애플리케이션 안에서 사용자가 만들고 협업하는 **논리적 IP Risk 관리 공간**이다.

```text
Risk Workspace: Project Aurora

/
├─ backend/
├─ design/
├─ prototype/
└─ patent-docs/
```

VWS는 실제 filesystem이 아니라 다음을 묶는 **애플리케이션 보안·협업·Risk 관리 경계**다.

- 멤버와 Role
- Source Workspace Mount
- 공통 보안 정책
- Risk / Review / History
- 감사 이력
- 알림

---

## 2.2 Source Workspace (`WS`)

실제로 데이터가 존재하는 외부 Source의 관리 가능한 범위다.

현재 지원 대상:

- **Google Drive Source Workspace**
- **GitHub Source Workspace**
- **Local Source Workspace**

동일 종류의 Source도 하나의 VWS에 여러 개 연결할 수 있다.

```text
VWS
├─ Drive WS #1
├─ Drive WS #2
├─ GitHub WS #1
├─ GitHub WS #2
└─ Local WS #1
```

---

## 2.3 Source Connection

외부 Provider 계정·설치·기기에 대한 **인증/연결 관계**다.

예:

- Google Drive OAuth 계정 하나
- GitHub App Installation 하나
- 등록된 Local Desktop Device 하나

중요한 점은 **Connection 하나가 WS 하나와 동일하지 않다**는 것이다.

```text
Google Drive Connection
└─ 여러 Drive Source Workspace

GitHub App Installation
└─ 여러 GitHub Source Workspace
```

---

## 2.4 Workspace Mount (`Mount`)

Source Workspace를 VWS에 붙이는 논리적 연결이다.

사용자가 지정한 Mount Alias를 통해 VWS에서는 폴더처럼 표현한다.

```text
/backend       → GitHub company/backend
/design        → Google Drive의 선택 파일 집합
/prototype     → Alice PC의 local directory
```

### 핵심 원칙

> **Mount path는 UI namespace이고 Artifact identity가 아니다.**

실제 identity는 internal `artifact_id`, provider stable ID, revision/commit/content fingerprint 등으로 관리한다.

Mount alias를 `/backend` → `/server`로 바꾸더라도 기존 Risk 이력은 변하지 않는다.

---

# 3. Source Workspace별 VWS 표현 방식

## 3.1 Local

실제 선택 directory 구조를 거의 그대로 mirror한다.

```text
/prototype
├─ src/
│  ├─ parser.py
│  └─ model.py
└─ requirements.txt
```

## 3.2 GitHub

선택 repository root를 Mount root로 표현한다.

```text
/backend
├─ src/
├─ docs/
├─ pyproject.toml
└─ README.md
```

MVP에서는 Source Workspace당 tracked branch 1개를 기본으로 하며 repository default branch를 우선한다.

## 3.3 Google Drive

Drive는 실제 filesystem hierarchy를 억지로 재현하지 않는다.

`drive.file + Picker`로 선택한 파일들이 서로 다른 폴더나 Shared Drive에 흩어질 수 있으므로 Drive WS를 **선택 Artifact collection**으로 본다.

```text
/design
├─ architecture.docx
├─ algorithm.pdf
└─ idea-notes.docx
```

각 Artifact detail에서 원래 Drive 위치·파일 링크·계정·revision 등 provider metadata를 보여준다.

동일 파일명이 있어도 내부 `artifact_id`가 다르므로 identity 충돌이 없다.

---

# 4. 전체 사용자 흐름

```text
Google Login
    ↓
Risk Workspace 생성 / 참여
    ↓
Source Workspace Mount
    ├─ Google Drive
    ├─ GitHub
    └─ Local
    ↓
Change Detection
    ↓
Security Gate
    ↓
Cloud Tasks
    ↓
Patent / License Analysis
    ↓
Risk Reconciliation
    ↓
Dashboard / Review / Timeline / Audit
```

---

# 5. 애플리케이션 로그인과 Source 권한은 분리

핵심 원칙:

```text
Application Identity
        ≠
Source Authorization
```

앱 로그인은 **Google Login**으로 통일하며 목적은 “누가 IP Risk App 사용자인가”를 인증하는 것이다.

Drive/GitHub/Local 원본 접근 권한을 의미하지 않는다.

---

# 6. Google Login과 여러 Google Drive 계정

한 사용자가 Google 계정 A로 앱에 로그인한 상태에서 로그아웃하지 않고 Google 계정 B, C의 Drive를 각각 연결할 수 있도록 한다.

```text
App User: Alice
Login Identity
└─ alice@gmail.com

Source Connections
├─ Drive → research@company.com
├─ Drive → patent-team@company.com
└─ Drive → alice@gmail.com
```

구조적으로 앱 로그인 session과 Drive OAuth credential을 분리한다.

Drive 연결 시 계정 선택 OAuth flow를 사용하며, 각 Drive Connection은 독립된 provider identity와 credential lifecycle을 가진다.

Drive Picker에는 **해당 Source Connection의 access token**을 사용한다.

### 선택 기술

- App authentication: Google OIDC
- Drive authorization: 별도 OAuth flow
- Drive scope: `drive.file`
- File selection: Google Picker
- 지속 연결: secure refresh-token storage

---

# 7. GitHub Source Workspace 권한 모델

GitHub 연결은 **GitHub App**을 사용한다.

사용자 PAT 장기 보관 방식은 사용하지 않는다.

```text
Source Manager
   ↓
Install GitHub App
   ↓
Personal account / Organization
   ↓
Repository selection
   ↓
GitHub native authorization / owner approval
   ↓
Installation
   ↓
GitHub Source Workspace Mount
```

Private Repository도 App installation이 해당 repository에 접근할 권한을 받은 경우 연결 가능하다.

서버는 short-lived installation access token을 사용한다.

### MVP permission 방향

- Repository Metadata: Read
- Repository Contents: Read
- 필요한 webhook events만 활성화
- write permission 없음

### 원칙

> **우리 앱은 Source Provider의 권한 체계를 우회하지 않는다.**

IP Risk App의 `Source Manager`가 GitHub Organization admin 권한을 갖는다는 의미가 아니다.

---

# 8. Local Source Workspace

Local WS는 Desktop App에서 사용자가 Native Folder Picker로 directory를 직접 선택하여 생성한다.

```text
Desktop
  ↓
Folder Picker
  ↓
Selected Root
  ↓
Local Source Workspace
```

실제 접근권한은 OS 사용자 권한이 최종 경계다.

Canonical path / symlink 검증을 통해 선택 root 밖의 파일이 tracking 범위로 우회 진입하지 못하게 한다.

---

# 9. Raw Source 접근 정책

> **VWS Role은 Raw Source 접근권한을 부여하지 않는다.**

IP Risk App은 원본 Source viewer/proxy가 아니다.

### Drive

`Open Original` → 실제 Google Drive URL → Google이 권한 판정

### GitHub

`Open Original` → 실제 GitHub file/blob URL → GitHub가 권한 판정

### Local

Web Backend는 local raw source를 제공하지 않는다.

Desktop에서만 등록된 local mount를 이용해 원본을 연다.

```text
Risk UI
  ↓
openTrackedArtifact(artifact_id)
  ↓
Electron Main
  ↓
Local Registry
  ↓
Tracked-root validation
  ↓
OS / Editor
```

가능하면 Local absolute path는 서버에 저장하지 않는다.

---

## 9.1 Mount의 공유 의미

Source Workspace를 VWS에 Mount하는 것은 **원본 Source 접근권한을 VWS 멤버에게 넘기는 행위가 아니다.**

다만 분석으로 생성되는 Risk 상태·최소 Evidence·Review History는 VWS 권한에 따라 공유될 수 있다.

```text
Raw Source Authority
→ Provider / Local OS가 계속 소유

Derived Risk & Minimal Evidence
→ Risk Workspace의 승인된 멤버에게 공유
```

---

# 10. Risk Evidence와 Raw Source는 분리

Human-in-the-Loop review에는 근거가 필요하므로 VWS에는 원본 전체 대신 **최소 Risk Evidence**를 보관·표시한다.

예:

```text
Risk Evidence
- artifact: /backend/src/search.py
- revision: commit abc123
- excerpt: lines 121–128
- matched patent claim: Claim 4
- analysis explanation
```

하지만 전체 source가 필요하면 `Open Original`을 통해 Source Provider/Local OS로 이동한다.

```text
Risk Evidence ≠ Raw Source
```

---

# 11. VWS 보안은 2개 Layer로 분리

## Layer A — Source Workspace별 보안

### Drive

- `drive.file`
- Picker에서 명시한 파일

### GitHub

- GitHub App installation
- 선택 repository
- application-level branch/path tracking scope

### Local

- 사용자가 명시적으로 선택한 root directory
- OS filesystem permission

## Layer B — VWS 통합 보안 정책

이미 연결된 Source 중 **분석하면 안 되는 범위**를 VWS 전체에서 관리한다.

대표 기능은 논리적 `.ipriskignore`다.

```text
Risk Workspace
/
├─ .ipriskignore
├─ backend/
├─ design/
└─ prototype/
```

예:

```gitignore
/backend/**/.env*
/backend/**/secrets/**
/backend/**/*.pem
/prototype/customer-data/**
/design/private-hr/**
```

Local/GitHub source 내부 실제 `.ipriskignore`가 존재하면 추가 정책으로 적용할 수 있다.

**deny wins**를 기본 규칙으로 한다.

---

# 12. 공통 Security Gate

모든 Source는 Analyzer 전에 동일한 보안 단계를 통과한다.

```text
Provider Authorization
        ↓
Source Workspace Scope
        ↓
VWS .ipriskignore
        ↓
Optional Source .ipriskignore
        ↓
File type / size rules
        ↓
Secret / credential filtering
        ↓
Data minimization
        ↓
Analyzer
```

### 핵심 invariant

> **Effective tracked scope 밖의 Artifact는 Analyzer나 AI Provider에 도달해서는 안 된다.**

이 Gate의 VWS-level 판정은 **Platform & Control Plane**이 단독 소유한다.

---

# 13. 변경 감지 구조

| Source | Primary Change Signal | Safety / Reconcile |
|---|---|---|
| Local | Desktop filesystem watcher | local state rescan |
| GitHub | GitHub App webhook | current repository state fetch |
| Drive | Drive change notification + changes cursor | periodic reconcile |

모든 Source event는 공통 Source Contract로 normalize한다.

```text
Source-specific Event
        ↓
SourceChange
        ↓
Cloud Tasks / Processing
```

Connector는 Risk를 판단하지 않는다.

---

# 14. Cloud Tasks를 비동기 처리 경계로 사용

```text
Webhook / Local event
      ↓
Verify + Persist
      ↓
Cloud Tasks enqueue
      ↓
Immediate ACK

Worker
      ↓
Source fetch
      ↓
Security Gate
      ↓
Analysis
      ↓
Risk reconcile
```

이유:

- webhook 응답 지연 최소화
- retry
- concurrency 제어
- 외부 API rate 관리
- Source와 Analysis의 lifecycle 분리

---

# 15. 분석 구조 — Deterministic Workflow

핵심 Risk Detection은 명시적인 workflow가 제어한다.

```text
Change
 ↓
Source Snapshot / Changed Context
 ↓
Security Gate
 ↓
Analysis Artifact
 ↓
Patent Analyzer / License Analyzer
 ↓
Evidence validation
 ↓
Analysis Result
 ↓
Risk lifecycle reconciliation
```

AI 모델이 다음을 임의로 결정하지 않는다.

- provider 호출 성공/실패
- Risk identity
- lifecycle transition
- license policy severity
- evidence 존재 여부
- “분석 실패”와 “Risk 없음” 구분

> **Gemini는 분석 도구이며 시스템 truth의 소유자는 deterministic application code다.**

---

# 16. Core AI — Gemini 3.6 Flash

주요 용도:

- 기술적 핵심 요소 추출
- patent search query 생성
- source ↔ patent evidence grounded comparison
- Risk 설명
- license knowledge 근거 설명
- 향후 multimodal document 분석 확장

모델 출력은 typed schema로 받고 code에서 검증한다.

---

# 17. Patent Risk 분석

목표는 법적 침해 결론이 아니라 **검토해야 할 Patent 후보·근거·Review Priority 제공**이다.

```text
Changed technical content
        ↓
Gemini technical-element extraction
        ↓
Search query generation
        ↓
KIPRIS search
        ↓
Candidate dedup / ranking
        ↓
Claims + abstract fetch
        ↓
Evidence chunks
        ↓
Gemini grounded comparison
        ↓
Evidence validation
        ↓
Review Priority
```

### 실패 의미

```text
정상 검색 + 후보 0개
→ Successful / No candidate

KIPRIS timeout / auth / provider failure
→ Failed or Inconclusive
```

Provider 장애 때문에 기존 Risk를 자동 해소하지 않는다.

---

# 18. License Risk 분석

License는 가능한 한 deterministic하게 처리한다.

```text
Manifest / Lockfile
    ↓
Dependency extraction
    ↓
Resolved version
    ↓
Package metadata / SPDX
    ↓
Deterministic License Policy
    ↓
Risk Result
    ↓
RAG + Gemini explanation
```

원칙:

> **License decision = code/policy**  
> **Gemini/RAG = 설명과 근거 강화**

가능하면 version range보다 lockfile의 resolved version을 우선한다.

MVP에서는 Contract 안정성을 위해 versioned global deterministic policy를 사용하고, VWS별 license policy customization은 이후 확장 범위로 둔다.

---

# 19. RAG Engine — 채택 확정

RAG는 직접 vector pipeline을 구축하기보다 **Google Cloud RAG Engine**을 사용한다.

주요 목적:

- authoritative/reference knowledge ingestion
- chunking
- embedding orchestration
- corpus indexing
- retrieval

### Persistent RAG에 넣을 것

- SPDX reference
- OSS license text / obligations
- 검증된 License/IP 안내자료
- 내부 IP policy reference
- Copyright/IP 관련 curated reference

### Persistent RAG에 넣지 않을 것

- private GitHub repo 원문
- Local project source 전체
- Google Drive private project documents 전체

핵심 구분:

> **Source Workspace = 분석 대상**  
> **RAG Corpus = 분석을 돕는 참조 지식**

---

# 20. Hybrid Region Architecture — 의도적으로 채택

Application Plane은 **Seoul**에 두고 RAG Engine은 **external GA region**에 둔다.

```text
Seoul Application Plane
├─ Cloud Run API
├─ Cloud Run Worker
├─ Cloud Tasks
├─ Firestore
└─ Secret Manager
        │
        │ controlled cross-region retrieval
        ▼
External Knowledge Plane
├─ RAG Engine
└─ RagManagedDb
```

이 구조는 Preview 기능에 Core를 의존하지 않으면서 managed RAG를 활용하기 위한 **의도적인 architecture decision**이다.

### Seoul에 유지하는 이유

- 한국 사용자 interactive API latency
- KIPRIS proximity
- VWS/Risk/application state의 지역적 일관성
- Source/security state와 RAG knowledge plane 분리

### RAG를 외부 region으로 보내는 이유

- RAG Engine GA 사용
- ingestion/chunking/index/retrieval 직접 구현 감소
- 짧은 개발기간
- managed GCP AI 활용도 강화

### Data boundary

외부 RAG에는 private Workspace 원문을 persistent corpus로 넣지 않는다.

RAG region 자체를 data residency 보장으로 설명하지 않고 **전송 및 지속 저장 데이터 최소화**를 주된 방어선으로 둔다.

---

# 21. RAG Backend

초기 RAG는 **RAG Engine의 managed database (`RagManagedDb`) Basic tier**를 우선한다.

이유:

- 별도 vector infrastructure 구축 불필요
- 초기 corpus 규모에 적합
- managed operation
- 개발 기간 단축

대규모 enterprise vector-search architecture를 처음부터 만들지 않는다.

---

# 22. Risk Workspace Role — 확정

```text
Workspace Owner
      ↓
Source Manager
      ↓
Risk Reviewer
      ↓
Viewer
```

코드 enum:

```text
OWNER
SOURCE_MANAGER
RISK_REVIEWER
VIEWER
```

## Viewer

- VWS 조회
- Risk 조회
- Risk history / Workspace activity 조회
- 허용된 최소 Evidence 조회

## Risk Reviewer

Viewer +

- Risk disposition
- Review comment
- Monitoring / Accepted Risk / Excluded 등의 Human Review 관리

## Source Manager

Risk Reviewer +

- 새로운 Source Workspace Mount 생성
- **본인이 Mount한 WS의 custodian**
- 본인 Mount tracking scope / reconnect / disconnect / rename 관리

별도의 `Drive Picker Manager`, `GitHub Manager`, `Local Manager` 같은 Role은 만들지 않는다.

## Workspace Owner

- 모든 VWS 관리 기능
- Member / Role
- VWS global `.ipriskignore`
- security / retention 정책
- Audit 관리
- 다른 Mount의 administrative disable/remove
- VWS 삭제 / ownership transfer

단, Owner라도 타인의 Provider Credential을 사용할 수 없다.

> **Mount Administrative Authority ≠ Source Credential Authority**

---

# 23. 권한 구조의 실제 형태

```text
1. Application Identity
   Google Login
   "누구인가?"

2. VWS Authorization
   Owner / Source Manager / Risk Reviewer / Viewer
   "VWS에서 무엇을 할 수 있는가?"

3. Source Authority
   Drive OAuth / GitHub native permission / Local OS
   "실제 원본 Source에 접근할 수 있는가?"
```

상위 VWS Role이 Source Authority를 우회할 수 없다.

---

# 24. Mount Ownership / Custodianship

각 Mount에는 `mounted_by_user_id`를 기록한다.

Source Manager는 자신이 만든 Mount만 관리한다.

Provider credential이 필요한 scope 확대는 해당 credential의 사용자 권한도 필요하다.

```text
Drive 파일 추가
=
Source Manager 이상
AND Mount owner
AND 해당 Drive authorization owner
```

Source Manager가 VWS에서 제거될 경우 Mount를 바로 삭제하지 않고 `MANAGER_ACTION_REQUIRED`, `REAUTH_REQUIRED`, `SOURCE_OFFLINE` 등의 상태로 전환하여 Owner가 처리한다.

---

# 25. Risk Lifecycle와 Human Review는 분리

## Machine lifecycle

```text
NEW → EXISTING → RESOLVED
          ↑         │
          └─ REOPEN ┘
```

## Human Review disposition

```text
UNREVIEWED
MONITORING
ACCEPTED_RISK
EXCLUDED
```

`EXCLUDED`가 machine `RESOLVED`를 의미하지 않고, machine resolution도 과거 review history를 삭제하지 않는다.

---

# 26. Risk와 History 분리

## `Risk`

현재 상태 projection.

## `RiskEvent`

append-only history.

```text
08/14 DETECTED
08/14 PRIORITY_CHANGED MEDIUM → HIGH
08/14 REVIEWED BY ALICE: MONITORING
08/18 RESOLVED
08/23 REOPENED
```

과거 Event는 overwrite하지 않는다.

Risk state 변경과 Event 추가는 transaction으로 처리한다.

---

# 27. Audit / Activity

Risk 이외에 VWS 운영·보안 이력도 관리한다.

## AuditEvent

예:

```text
SOURCE_CONNECTED
SOURCE_DISCONNECTED
MOUNT_CREATED
MOUNT_SCOPE_CHANGED
SECURITY_POLICY_CHANGED
ANALYSIS_FAILED
MEMBER_INVITED
MEMBER_REMOVED
ROLE_CHANGED
```

## SourceAccessEvent

고빈도 source 접근은 별도 이력으로 저장한다.

```text
- timestamp
- mount
- artifact
- revision
- access_type: METADATA / DIFF / PARTIAL_CONTENT / FULL_CONTENT
- reason / analysis_job_id
- size
```

실제 source content 자체는 access log에 저장하지 않는다.

---

# 28. 사용자 관리 UI

## VWS Dashboard

```text
Needs Review       7
High Priority      3
Monitoring        12
Resolved This Week 8
Analysis Failed    1
```

## Risk Detail + Timeline

```text
Current Status
Evidence
Why This Risk?
Reviewer Decision
Timeline
Open Original
```

## Workspace Activity

```text
10:31 /backend scope changed
10:25 Patent Risk reopened
10:04 Drive file added
09:52 License Risk resolved
09:41 KIPRIS analysis failed
```

## Security & Data Access

```text
Connected Sources
/backend     GitHub / company/backend
/design      Drive / 8 selected files
/prototype   Local / Alice-MacBook

Global Protection
.ipriskignore       Enabled
Secret filtering    Enabled
Source retention    Minimal
External RAG        Reference knowledge only

Recent Source Access
10:41 /backend/src/search.py 23 changed lines
10:32 /design/architecture.docx revision 31
```

사용자가 다음 질문에 답을 얻을 수 있어야 한다.

- 현재 시스템은 내 어떤 자료를 볼 수 있는가?
- 실제로 어떤 자료를 분석했는가?
- 어떤 데이터가 장기 보존되는가?

---

# 29. Data Retention 원칙

- source 전체 persistent 저장 지양
- 변경 diff / relevant context 우선
- Evidence는 최소 excerpt
- source revision / hash 저장
- OAuth token 로그 금지
- full prompt / full model output 로그 금지
- Local absolute path server persistence 지양

기본 Evidence Retention은 **Balanced**로 본다.

재검토에 필요한 최소 evidence, source reference, revision/hash, analyzer/model/policy/corpus version을 보존한다.

---

# 30. Analysis Reproducibility

각 분석 Job에는 최소 다음 버전을 기록한다.

```text
model_id
prompt_version
analyzer_version
policy_version
rag_corpus_version
source_revision
```

목적은 과거와 현재 판단 차이를 설명할 수 있게 하는 것이다.

---

# 31. GCP Runtime 구조

```text
React Web / Electron Desktop
              │
              ▼
       Cloud Run API
          │       │
          │       └── Firestore Seoul
          │
          ▼
      Cloud Tasks
          │
          ▼
 Cloud Run Analysis Worker
    │       │       │
    │       │       └── External APIs
    │       └────────── Gemini
    └────────────────── External RAG Engine
```

Cloud Scheduler는 Drive watch renewal / reconciliation 등 정기 maintenance에 사용한다.

---

# 32. Web + Desktop

UI는 **React + TypeScript + Vite** 기반으로 최대한 공유한다.

Desktop은 **Electron shell**을 사용한다.

```text
Same React UI
├─ Browser
└─ Electron Renderer
       ↓
   Preload bridge
       ↓
   Electron Main
       ↓
   Local watcher / OS capability
```

Renderer에 filesystem 전체 권한을 제공하지 않고 좁은 IPC capability만 노출한다.

예:

```text
openTrackedArtifact(artifactId)
chooseTrackedDirectory()
```

---

# 33. Backend / State

### Backend

- Python
- FastAPI
- Pydantic typed contracts/models
- Cloud Run

### Firestore

Application state database로 사용한다.

주요 collection 개념:

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

Canonical application/Risk state의 소유자는 **Platform & Control Plane**이다.

---

# 34. Credentials / Service Accounts

### External credentials

- Drive refresh token: secure credential storage
- GitHub App private key / webhook secret: Secret Manager
- GitHub API: short-lived installation token

### GCP workload identity

service-account JSON key 파일을 runtime에 배포하지 않는다.

초기 권장 identity:

```text
app-api-sa
analysis-worker-sa
scheduler-sa
deploy-sa
```

필요 시 RAG ingestion identity를 추가 분리한다.

### 감사

```text
User-facing
→ RiskEvent / AuditEvent / SourceAccessEvent

Infrastructure
→ Cloud Audit Logs
```

---

# 35. 핵심 기술 선택 요약

| 영역 | 채택 | 핵심 이유 |
|---|---|---|
| App Login | Google OIDC | 사용자 인증 단순화 |
| Drive | OAuth `drive.file` + Picker | 명시적 파일 선택 / 최소권한 |
| GitHub | GitHub App | private repo / selected repo / short-lived auth |
| Local | Electron native folder selection | OS authority 유지 |
| Frontend | React + TypeScript + Vite | Web/Desktop 공유 |
| Desktop | Electron | local FS 연동과 구현 속도 |
| API | FastAPI | Python 분석 자산과 typed API |
| Runtime | Cloud Run | GCP serverless application plane |
| Async | Cloud Tasks | retry/concurrency/rate control |
| State DB | Firestore | transactional application state |
| LLM | Gemini 3.6 Flash | structured AI analysis |
| Patent | KIPRIS | 특허 후보 source |
| License | SPDX + package metadata | deterministic identity/policy |
| RAG | RAG Engine | managed ingestion/retrieval |
| RAG storage | RagManagedDb Basic | 초기 규모와 관리 단순성 |
| App region | Seoul | application/source/user proximity |
| RAG region | External GA region | Preview core dependency 회피 |
| Core orchestration | Explicit workflow | auditability / deterministic failure handling |

---

# 36. 개발 구조 — 3개 Plane으로 분리

병렬 Coding Agent 개발의 기준은 **기능 종류가 아니라 독립 개발 가능성과 통합 접점 최소화**다.

따라서 전체 구현을 다음 3개 개발축으로 분리한다.

```text
                  PLATFORM & CONTROL PLANE
               ┌─────────────────────────────┐
               │ Identity / VWS / Roles      │
               │ Mount Registry              │
               │ VWS Security Gate           │
               │ Risk Lifecycle / History    │
               │ Firestore / Product UI      │
               └──────────────┬──────────────┘
                              │
                ┌─────────────┴─────────────┐
                │                           │
                ▼                           ▼
   SOURCE INTEGRATION PLANE        RISK INTELLIGENCE PLANE
   ┌──────────────────────┐        ┌──────────────────────┐
   │ Drive / GitHub       │        │ Patent / License     │
   │ Local / Electron     │        │ Gemini / KIPRIS      │
   │ OAuth / Webhook      │        │ RAG Engine / SPDX    │
   │ Watch / Fetch        │        │ Evidence validation  │
   └──────────────────────┘        └──────────────────────┘
```

---

## 36.1 개발축 1 — Platform & Control Plane

한 문장 정의:

> **누가 어떤 Risk Workspace에서 무엇을 관리할 수 있고, Source와 AI 결과를 어떻게 신뢰 가능한 Risk state와 사용자 경험으로 만드는가.**

주요 책임:

- Google App Login
- Risk Workspace / Membership / Role
- Mount canonical metadata
- VWS global `.ipriskignore`
- Security Gate
- Firestore canonical application state
- ChangeEvent / AnalysisJob orchestration state
- Risk lifecycle / RiskEvidence / RiskEvent
- Review / Audit / SourceAccessEvent / Notification
- Dashboard / Risk / History / Security 중심 Web Product UI

이 축은 Drive/GitHub API, filesystem watcher, Gemini/KIPRIS/RAG 내부 구현을 알지 않는다.

---

## 36.2 개발축 2 — Source Integration & Desktop

한 문장 정의:

> **실제 Drive/GitHub/Local Source를 최소권한으로 연결하고, 변경을 안전하게 탐지해 표준 Source Event/Snapshot으로 전달한다.**

주요 책임:

- Google Drive OAuth / 다중 계정 / Picker
- Drive watch / changes cursor / reconcile
- GitHub App / private repo / webhook
- GitHub tracked branch/path
- Electron main/preload
- Local folder picker / watcher / debounce / staging
- provider-specific original locator
- Source-level tracking scope
- 각 Provider의 `SourceAdapter` 구현

이 축은 Patent/License 판단, Risk lifecycle, VWS Role truth를 직접 소유하지 않는다.

---

## 36.3 개발축 3 — Risk Intelligence & RAG

한 문장 정의:

> **Security Gate를 통과한 최소 Artifact를 Patent/License 관점에서 분석하여 근거와 재현 정보가 포함된 AnalysisResult를 만든다.**

주요 책임:

- Analyzer abstraction
- Patent Analyzer
- KIPRIS provider
- Patent candidate dedup/ranking/grounding
- License parser / lockfile / SPDX / deterministic policy
- Gemini typed analysis
- RAG Engine / RagManagedDb / corpus ingestion/retrieval
- Evidence validation
- model/prompt/policy/corpus version reporting

이 축은 Source Provider API나 Firestore Risk state를 직접 다루지 않는다.

---

# 37. Shared Contract — 세 개발축 사이의 유일한 공식 접점

각 개발축은 다른 축의 내부 구현에 의존하지 않고 **Frozen Shared Contract**만 공유한다.

공유 Contract는 5개다.

```text
1. SourceAdapter
2. SourceChange
3. SourceSnapshot
4. AnalysisArtifact
5. AnalysisResult
```

이 Contract는 개발 시작 전에 동결하고 병렬 Agent가 임의로 수정하지 않는다.

---

## 37.1 `SourceAdapter`

**행동 계약**이다.

Source Plane이 구현하고 Control/Integration이 사용한다.

주요 의미:

```text
health(mount)
fetch_snapshot(change) -> SourceSnapshot
resolve_original(artifact) -> OriginalSourceLocator
reconcile(mount, cursor) -> ReconcileResult
```

실제 구현체:

```text
GoogleDriveAdapter
GitHubAdapter
LocalAdapter
```

Control은 Provider별 내부 동작을 몰라도 된다.

---

## 37.2 `SourceChange`

**“어떤 Source Artifact가 어떤 revision에서 변했다”**를 표현하는 content-free event다.

Producer: Source Plane  
Consumer: Control Plane

포함:

- event / fingerprint
- VWS / Mount / Source Workspace ref
- Source type
- Artifact stable/provider identity
- change type: CREATE / UPDATE / DELETE / MOVE
- revision / previous revision
- observed time
- 안전한 metadata

포함 금지:

- raw source
- OAuth / installation token
- Local absolute path
- secret

Duplicate event 처리를 위해 idempotency fingerprint를 가진다.

---

## 37.3 `SourceSnapshot`

SourceAdapter가 실제 Source에서 확보한 **Security Gate 이전의 transient input**이다.

Producer: Source Plane  
Consumer: Control Plane

예:

```text
revision
logical path hint
mime/artifact kind
content scope
text segments
checksum
byte size
source access receipt
```

핵심 원칙:

> **SourceSnapshot은 장기 application state가 아니다.**

Risk DB에 원문 그대로 저장하지 않는다.

Local은 서버가 나중에 원본 PC를 직접 읽을 수 없으므로 short-lived staging을 이용할 수 있다.

---

## 37.4 `AnalysisArtifact`

**Security Gate를 통과한 AI/Analyzer 허용 입력**이다.

Producer: Control Plane  
Consumer: Risk Intelligence Plane

```text
SourceSnapshot
      ↓
VWS Security Gate
      ↓
AnalysisArtifact
```

포함 개념:

- analysis job / artifact / revision
- logical path
- requested analyzer types
- 최소화된 text segments
- security policy version
- redaction count
- input checksum
- `approved = true`

Risk Intelligence는 승인되지 않은 Artifact를 처리해서는 안 된다.

또한 Intelligence가 Drive/GitHub/Local에서 원문을 다시 가져오는 것은 금지한다.

---

## 37.5 `AnalysisResult`

Risk Intelligence가 반환하는 **분석 결과이지 Risk state 자체가 아니다.**

Producer: Risk Intelligence Plane  
Consumer: Control Plane

주요 상태:

```text
SUCCEEDED
FAILED
INCONCLUSIVE
SKIPPED
```

coverage:

```text
COMPLETE
PARTIAL
NONE
```

포함:

- analysis type
- candidates
- minimal evidence
- provider failures
- analyzer/model/prompt/policy/RAG corpus versions
- started/completed timestamps

### 핵심 Risk invariant

기존 Risk를 analysis 결과로 해소할 수 있는 조건은 원칙적으로:

```text
status == SUCCEEDED
AND
coverage == COMPLETE
```

이다.

따라서 `FAILED`, `INCONCLUSIVE`, `PARTIAL`은 기존 active Risk를 자동 해소할 수 없다.

---

# 38. Contract 전체 데이터 흐름

```text
              SOURCE PLANE

Drive / GitHub / Local
        │
        ▼
   SourceAdapter
        │
        ├── SourceChange
        │
        ▼
   SourceSnapshot

────────────────────────────────
             CONTROL PLANE
────────────────────────────────

     VWS Security Gate
        │
        ▼
   AnalysisArtifact

────────────────────────────────
       INTELLIGENCE PLANE
────────────────────────────────

 Patent / License / RAG
        │
        ▼
   AnalysisResult

────────────────────────────────
             CONTROL PLANE
────────────────────────────────

   Risk Reconciliation
        │
    ┌───┴────────────┐
    ▼                ▼
   Risk           RiskEvent
```

### Producer / Consumer 정리

| Contract | Producer | Consumer |
|---|---|---|
| `SourceAdapter` 구현 | Source | Integration / Control |
| `SourceChange` | Source | Control |
| `SourceSnapshot` | Source | Control |
| `AnalysisArtifact` | Control | Intelligence |
| `AnalysisResult` | Intelligence | Control |

> **Source Plane과 Intelligence Plane 사이에는 직접 Contract나 직접 호출 경로가 없다.**

---

# 39. 개발축 간 Dependency 규칙

세 Coding Agent의 독립성을 위해 다음을 강제한다.

```text
Control → contracts                 allowed
Source → contracts                  allowed
Intelligence → contracts            allowed
Integration → all planes            allowed
```

금지:

```text
Control → connectors 내부 import       금지
Control → intelligence 내부 import     금지

Source → core/application 내부 import  금지
Source → intelligence 내부 import      금지

Intelligence → core 내부 import        금지
Intelligence → connectors 내부 import  금지
```

요약:

> **Source Plane은 Risk를 모른다.**  
> **Intelligence Plane은 Source Provider를 모른다.**  
> **Control Plane은 Provider와 Analyzer 내부 구현을 모른다.**  
> **Integration Layer만 세 Plane의 실제 구현체를 알고 조립한다.**

---

# 40. 파일 Ownership — 회의 수준 확정

상세 파일 목록은 Coding Agent Master/개별 명세에 따르되, 팀 차원에서는 다음 exclusive ownership을 고정한다.

## Agent 1 — Platform & Control

```text
backend/src/ip_risk_agent/core/**
backend/src/ip_risk_agent/application/**
backend/src/ip_risk_agent/persistence/core_firestore/**
backend/src/ip_risk_agent/api/{auth,workspace,risk,history,security}/**

apps/web/**
packages/product-ui/**
```

## Agent 2 — Source Integration & Desktop

```text
backend/src/ip_risk_agent/connectors/**
apps/desktop/**
packages/source-ui/**
```

## Agent 3 — Risk Intelligence & RAG

```text
backend/src/ip_risk_agent/intelligence/**
rag-corpus/**
```

다른 Agent ownership directory를 직접 수정하지 않는다.

---

# 41. Shared / Integration-only 영역

병렬 개발 중 세 Agent 모두가 임의 수정해서는 안 되는 영역을 별도로 둔다.

## Frozen Shared Contract

```text
shared/contracts/**
```

Contract 변경이 필요하면 구현체에서 임의 확장하지 않고 변경 요청을 남기며 최종 Integration 단계에서 판단한다.

## Integration-only

```text
backend/src/ip_risk_agent/composition/**
backend/src/ip_risk_agent/main.py
backend/src/ip_risk_agent/worker.py

deploy/**
root package/toolchain/lock/config

tests/integration/**
tests/e2e/**
```

최종 Integration Agent가 세 Plane을 조립하고 root dependency/deployment configuration을 병합한다.

---

# 42. Integration Layer의 역할

Integration Agent의 목적은 세 개발축을 다시 구현하는 것이 아니라 **이미 구현된 public surface를 연결하는 것**이다.

핵심 wiring은 다음 다섯 단계다.

```text
1. Source event
   ↓
2. SourceChange + SourceAdapter.fetch_snapshot()
   ↓
3. SourceSnapshot -> SecurityGate -> AnalysisArtifact
   ↓
4. Analyzer -> AnalysisResult
   ↓
5. RiskLifecycle.reconcile()
```

Integration Layer가 주로 담당하는 것:

- SourceAdapter registry
- Analyzer registry
- API router composition
- Worker composition
- repository/provider dependency injection
- root dependencies
- deploy configuration
- integration/e2e tests

---

# 43. 왜 이 3분할을 채택했는가

다른 후보도 검토했다.

## Frontend / Backend / AI 분리

단점:

- Drive/GitHub 연결 기능이 UI와 Backend를 계속 넘나듦
- Local Electron과 Web 경계가 복잡
- Backend 담당자에게 Auth/VWS/Connector/Risk/Tasks가 집중
- 병렬 개발 시 기능 하나를 여러 사람이 동시에 수정

## Drive / GitHub / Local 분리

단점:

- 각 Source 팀이 Risk/security/analysis flow를 중복 구현하기 쉬움
- 마지막 통합 비용이 매우 큼
- “Source가 달라도 Change 이후는 공통”이라는 도메인 구조에 반함

## Plane 분리

장점:

- Source별 외부 API 복잡성은 Source Plane 안에서 완결
- AI/RAG 복잡성은 Intelligence Plane 안에서 완결
- Risk truth와 보안 policy는 Control Plane 한 곳에서 유지
- 통합 접점이 5개 Contract로 제한됨
- Coding Agent별 directory ownership 충돌 최소화
- 각 축을 fake contract input으로 독립 테스트 가능

따라서 현재 프로젝트에는 **Platform & Control / Source Integration & Desktop / Risk Intelligence & RAG** 분할이 가장 적합하다고 판단한다.

---

# 44. 테스트 책임 경계

상세 테스트 명세는 개발 문서에 따르지만 기본 ownership은 다음과 같다.

## Control

- VWS Role / Mount ownership
- duplicate SourceChange idempotency
- `.ipriskignore` / Security Gate
- SourceSnapshot transient policy
- AnalysisResult 실패 시 Risk 보존
- RiskEvent append-only

## Source

- Drive/GitHub/Local이 동일 Contract semantic을 생성하는지
- provider credential이 Contract/log에 노출되지 않는지
- Local root escape 방어
- webhook/watch/reconcile 동작

## Intelligence

- unapproved AnalysisArtifact 거부
- Patent/License golden tests
- malformed Gemini output
- KIPRIS/RAG/provider failure semantics
- Evidence validation
- strict AnalysisResult contract

## Integration

```text
SourceChange
→ SourceSnapshot
→ AnalysisArtifact
→ AnalysisResult
→ Risk
```

전체 흐름과 실제 DI/wiring을 검증한다.

---

# 45. 기존 세 프로젝트에서 얻은 핵심 교훈

특정 repo를 base로 삼지 않는다.

### Local/License prototype에서 유지

- filesystem watcher / debounce
- deterministic license 판단
- LLM은 explanation 역할
- scan coverage
- patent query/evidence validation

### GitHub/Agent prototype에서 유지

- GitHub webhook
- actual tool/API result를 LLM final narrative보다 authoritative하게 취급
- provider failure를 low-risk로 오해하지 않는 postcondition

### Product형 Drive/Risk prototype에서 유지

- Workspace/Risk domain
- Drive `drive.file`
- Risk lifecycle와 Human disposition 분리
- stable Risk identity
- transactional reconcile
- failure-safe resolution
- Firestore / Secret Manager / Cloud Run
- React SPA

### 버릴 것

- PAT 기반 GitHub 기본 인증
- polling-only를 실시간이라고 보는 구조
- 여러 UI framework 동시 유지
- LLM이 lifecycle/provider truth를 결정하는 구조
- raw source 장기 저장

---

# 46. MVP 범위와 확장 방향

## MVP Core

- Risk Workspace / Source Workspace / Mount
- Google Login + VWS Role
- Drive / GitHub / Local connector
- 변경 감지 + Cloud Tasks
- Patent Risk + License Risk
- Gemini + RAG Engine
- Risk Dashboard / Detail / Review / Timeline
- `.ipriskignore` + Security & Data Access
- Audit / Source access history
- 3 Plane + 5 Shared Contract 기반 병렬 개발 구조

## 후속 확장

- Copyright 및 기타 IP analyzer
- PDF/image 등 multimodal artifact 확대
- 조직별 세분화 license/IP policy
- 추가 notification channel
- 고급 분석 비교/통계/보고서

Connector / Analyzer / Risk contract를 분리해 새로운 Source나 IP Risk 유형이 추가되어도 전체를 재작성하지 않는 구조를 목표로 한다.

---

# 47. 프로젝트의 핵심 보안 메시지

> **사용자가 명시적으로 연결한 Source 범위만 추적하고, VWS 통합 정책으로 분석 범위를 다시 제한하며, 변경된 최소 데이터만 AI 분석에 사용하고, 원본 접근권한은 각 Source Provider/OS가 끝까지 소유하도록 설계한다.**

```text
Least Privilege
+ Explicit Mounting
+ Provider-native Authorization
+ VWS-wide Ignore Policy
+ Data Minimization
+ Raw Source Non-proxy
+ Minimal Evidence Retention
+ Append-only Risk History
+ Infrastructure Audit
```

개발 구조에서도 동일한 철학을 적용한다.

```text
Provider security  → Source Plane
VWS security       → Control Plane
AI input security  → Intelligence boundary
```

---

# 48. 프로젝트의 핵심 제품 메시지

> **여러 협업 Source를 하나의 Risk Workspace로 구성하고, 실제 변경을 지속적으로 추적하며, AI가 근거 기반 Risk를 제안하고 사람이 장기적으로 검토·관리하는 Secure Human-in-the-Loop IP Risk Workspace.**

---

# 49. 회의에서 최종 확인할 항목

팀 전체가 다음을 동일하게 이해해야 한다.

1. VWS는 실제 filesystem이 아니라 logical risk/security boundary다.
2. Mount alias/path는 Artifact identity가 아니다.
3. Drive는 filesystem mirror가 아니라 selected-artifact collection이다.
4. App login과 Source authorization은 별개다.
5. Source Provider authority는 VWS Role로 우회할 수 없다.
6. Source Manager는 모든 Source 관리자가 아니라 자신이 Mount한 WS의 custodian이다.
7. Raw Source는 App이 proxy하지 않는다.
8. VWS에는 최소 Risk Evidence만 보존한다.
9. RAG corpus와 private Workspace source를 분리한다.
10. External GA RAG는 의도적인 Hybrid Region 결정이다.
11. AI는 분석 도구이며 Risk lifecycle/system truth는 deterministic code가 관리한다.
12. Risk history와 보안/접근 history는 제품 기능으로 제공한다.
13. 구현은 3개 Plane으로 나누고 개발축 간 직접 내부 import를 금지한다.
14. `SourceAdapter`, `SourceChange`, `SourceSnapshot`, `AnalysisArtifact`, `AnalysisResult`가 공식 공유 Contract다.
15. `SourceSnapshot -> AnalysisArtifact`가 핵심 보안 경계다.
16. `AnalysisResult`는 Risk state가 아니며 Control만 Risk lifecycle을 변경한다.
17. `shared/contracts/**`는 Frozen 영역이다.
18. `composition/**`, root wiring, deploy, integration/e2e는 Integration Agent 전용이다.
19. 각 Coding Agent는 자신의 directory ownership 안에서 독립 완결성을 가져야 한다.
20. 최종 통합은 내부 구현 재작성보다 Contract wiring을 중심으로 수행한다.

---

# 50. 이 문서와 Coding Agent 개발 명세의 차이

이 문서는 **회의/청사진 문서**다.

팀원이 빠르게 다음을 공유하는 것이 목적이다.

- 무엇을 만드는가
- 왜 이 architecture인가
- 보안 경계는 어디인가
- Source/Risk/AI가 어떻게 연결되는가
- 세 개발축을 왜 이렇게 나눴는가
- 어떤 Contract에서 만나게 되는가

반면 실제 개발에는 별도의 다음 문서를 사용한다.

```text
CODING_AGENT_MASTER_SPEC.md
CODING_AGENT_SPEC_1_PLATFORM_CONTROL.md
CODING_AGENT_SPEC_2_SOURCE_DESKTOP.md
CODING_AGENT_SPEC_3_RISK_INTELLIGENCE_RAG.md
```

개발 명세에서는 Blueprint보다 더 상세하게 다음을 고정한다.

- 정확한 class / protocol / Pydantic schema
- API namespace와 route
- Firestore field/index
- transition guard
- provider exception semantics
- retry / timeout / staging lifetime
- public facade/factory
- test fixture / acceptance criteria
- Agent delivery format
- Integration wiring point

따라서 **Blueprint는 Why/What/Boundary**, Coding Agent 명세는 **How/Contract/Ownership/Acceptance Criteria**를 담당한다.

---

# Appendix A. 최종 개발 구조 요약

```text
                            shared/contracts
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
              ▼                   ▼                   ▼
     Platform & Control     Source Integration     Risk Intelligence
              │              & Desktop              & RAG
              │                   │                   │
              └───────────────────┼───────────────────┘
                                  │
                                  ▼
                          Integration Layer
```

```text
Source Plane
    │ SourceChange / SourceSnapshot
    ▼
Control Plane
    │ Security Gate
    │ AnalysisArtifact
    ▼
Intelligence Plane
    │ AnalysisResult
    ▼
Control Plane
    │
    ▼
Risk / Evidence / History / UI
```

---

# Appendix B. 현재 범위 밖의 사항

현재 구현/문서의 기본 구조에는 다음을 포함하지 않는다.

- user PAT 기반 GitHub authentication
- raw source proxy/viewer
- Preview RAG Engine region을 Core dependency로 사용
- Source별 세분화된 Picker/Connector 관리자 Role
- VWS별 custom license policy payload
- 다중 tracked branch를 기본 Source Workspace 모델로 사용
- arbitrary binary를 Shared Contract v1의 기본 payload로 사용

필요성이 실제로 확인될 때 Contract/API versioning과 함께 별도 설계한다.
