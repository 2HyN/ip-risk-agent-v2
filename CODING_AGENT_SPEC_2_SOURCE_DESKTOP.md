# IP Risk Agent — Agent 2 Development Specification
## Source Integration & Desktop

> **이 문서는 `CODING_AGENT_MASTER_SPEC.md`와 함께 Agent 2에게 전달한다.**  
> Master Spec이 상위 규약이며, 충돌 시 Master Spec을 우선한다.  
> Agent 2는 Google Drive / GitHub / Local Source를 연결·감시·조회하는 Plane만 소유한다.

---

# 0. Agent 2 임무

> **외부 Source Workspace를 provider-native 최소권한으로 연결하고, 변경을 안전하게 감지하며, Frozen `SourceChange`/`SourceSnapshot`/`SourceAdapter` 계약으로 정규화한다.**

Agent 2의 끝은 Risk가 아니라 `SourceSnapshot`이다.

Agent 2는 Patent/License/AI/Risk lifecycle을 모른다.

---

# 1. 절대 경계

## MUST

- Drive/GitHub/Local 각각에 `SourceAdapter` 구현을 제공한다.
- Provider credential을 Connector 내부에 격리한다.
- 변경을 `SourceChange`로 normalize한다.
- source fetch를 `SourceSnapshot`으로 normalize한다.
- raw source original locator를 Provider/OS semantics로 제공한다.
- source-level tracking scope를 강제한다.
- Local root escape/symlink escape를 방지한다.
- transient Local staging을 구현한다.

## MUST NOT

- Risk/RiskEvent/Review lifecycle을 구현하지 않는다.
- Gemini/KIPRIS/RAG/SPDX를 호출하지 않는다.
- VWS role policy를 자체 정의하지 않는다.
- canonical Firestore Risk collections를 직접 수정하지 않는다.
- frozen contracts를 변경하지 않는다.
- Agent 1/3 내부 module을 import하지 않는다.

---

# 2. 소유 파일

```text
backend/src/ip_risk_agent/connectors/
├─ common/
├─ google_drive/
├─ github/
└─ local/

backend/src/ip_risk_agent/api/
└─ source-owned isolated routers only

frontend/src/sources/
├─ common/
├─ drive/
├─ github/
└─ local/

apps/desktop/
├─ main/
├─ preload/
├─ watcher/
├─ local-registry/
└─ security/

tests/connectors/**
```

`frontend/src/shared/**`는 Agent 1 소유다. 필요 component가 있으면 own feature 내부에 국소 구현하거나 delivery에 요청한다.

---

# 3. Public Integration Surface

Agent 2는 Integration Layer가 구현체를 등록할 수 있게 단순 factory/export를 제공한다.

예:

```text
connectors/google_drive/public.py
connectors/github/public.py
connectors/local/public.py
```

최소:

```python
def create_google_drive_adapter(config, credential_port, runtime_store) -> SourceAdapter: ...
def create_github_adapter(config, credential_port, runtime_store) -> SourceAdapter: ...
def create_local_adapter(config, staging_store, runtime_store) -> SourceAdapter: ...
```

그리고 source-owned routers factory:

```python
def create_source_router(authz_dependency, control_callbacks, ...): ...
```

Agent 2가 Agent 1을 import하지 않도록 auth/control dependency는 injection한다.

---

# 4. 공통 Connector 내부 구조

각 provider는 가능하면 다음 계층을 가진다.

```text
provider/
├─ client.py          # provider HTTP/SDK wrapper
├─ auth.py            # credential/token handling
├─ models.py          # provider-private models
├─ scope.py           # tracking scope enforcement
├─ events.py          # source event parsing/normalization
├─ adapter.py         # Frozen SourceAdapter implementation
├─ runtime_store.py   # provider operational state
└─ routes.py          # isolated routes/webhooks
```

Provider SDK model을 shared contract로 노출하지 않는다.

---

# 5. Source Operational Store

Agent 2는 canonical product state와 분리된 operational state만 저장한다.

가능한 namespace:

```text
connector_runtime/
```

개념:

```text
DriveRuntime
- connection_id
- change_cursor
- watch_channel_id
- watch_resource_id
- watch_expiry
- reconciliation_lease

GitHubRuntime
- connection_id
- installation_id
- repository_id
- tracked_branch
- webhook_status
- last_seen_delivery_id

LocalRuntime
- device_id
- mount_handle
- status
- last_heartbeat
- staging_metadata
```

실제 storage backend는 Firestore isolated collection 또는 다른 simple store 가능.

단 `risks`, `memberships`, `workspace_mounts` 등의 canonical schema를 재정의하지 않는다.

---

# 6. Credential Storage Port

Agent 2는 credential 원문을 application DB에 저장하지 않는다.

권장 abstraction:

```python
class SourceCredentialVault(Protocol):
    async def put(...): ...
    async def get(...): ...
    async def delete(...): ...
```

Production implementation은 Secret Manager-compatible하게 설계.

Root wiring은 Integration Agent가 한다.

Google refresh token, GitHub App private key/webhook secret 등은 logs/contract에 노출하지 않는다.

---

# 7. Google Drive — Identity & Authorization Flow

App login과 Drive authorization은 별개다.

한 App User가 여러 Google Drive 계정을 연결할 수 있어야 한다.

권장 flow:

```text
User logged into IP Risk App
  ↓
Connect Google Drive
  ↓
Drive OAuth authorization
  ↓
account selection
  ↓
drive.file scope authorization
  ↓
provider identity + refresh token secured
  ↓
SourceConnection canonical creation callback
  ↓
Picker session
  ↓
selected file IDs
  ↓
Drive SourceWorkspace + Mount creation callback
```

Agent 2가 App login session을 새 Google identity로 바꾸면 안 된다.

OAuth callback은 pending connection context를 복구해야 한다.

CSRF/state validation 필수.

---

# 8. Drive OAuth Credential Model

Provider-private metadata:

```text
GoogleDriveCredential
- provider_subject
- provider_email
- refresh_token_secret_ref
- granted_scopes
- created_at
- last_refresh_at
- status
```

App-facing metadata만 canonical callback으로 전달:

```text
provider_subject
provider_account_label
credential_ref opaque
status
```

---

# 9. Google Picker

Picker는 해당 Drive SourceConnection의 access token을 사용한다.

App login account의 token을 사용하지 않는다.

MVP:

- files selectable
- My Drive/Shared Drive 항목 허용 가능한 범위
- multiple selection 허용
- selected file IDs만 tracking

Picker에서 파일 선택이 바뀌면 Source Manager 본인 Mount + provider authority 검증이 필요하다.

이 authorization decision은 Integration이 제공하는 authz callback과 provider credential owner check를 함께 적용한다.

---

# 10. Drive SourceWorkspace Model

Drive SourceWorkspace는 directory mirror가 아니다.

Provider-private tracking config:

```text
DriveTrackingScope
- selected_file_ids[]
- display_metadata_by_file
```

VWS logical view는 collection-oriented.

Drive file identity:

```text
source_artifact_id = Drive file ID
```

`path_hint`는 optional display hint.

Parent hierarchy를 identity에 사용하지 않는다.

---

# 11. Drive Change Monitoring

목표:

```text
push wake-up + changes cursor + reconcile
```

권장 flow:

1. connection/source workspace가 활성화될 때 change cursor/start token 확보.
2. watch channel 생성.
3. webhook은 payload만으로 최종 change truth를 결정하지 않는다.
4. webhook 수신 시 sync/reconcile 작업 trigger.
5. `changes.list` equivalent로 cursor 이후 변경 조회.
6. selected file IDs와 intersect.
7. tracked 변경만 `SourceChange` 생성.
8. cursor CAS/update.
9. watch expiry 전 scheduler renewal hook 제공.
10. periodic reconcile safety net.

Webhook endpoint는 빠르게 ACK한다.

---

# 12. Drive SourceChange

필수 deterministic fingerprint:

```text
file_id + resolved_revision/version
```

변경 종류는 provider metadata를 바탕으로 CREATE/UPDATE/DELETE/MOVE로 normalize.

Drive stable file ID가 유지되면 MOVE에도 동일 artifact identity.

`SourceChange`에는 raw content 없음.

---

# 13. Drive fetch_snapshot()

Input:

```text
SourceChange
```

처리:

1. credential resolve.
2. mount/source tracking scope check.
3. current authoritative file metadata fetch.
4. unsupported/removed 처리.
5. file content text extraction/export.
6. checksum 계산.
7. SourceAccessReceipt 생성.
8. SourceSnapshot 반환.

MVP 지원 권장:

- Google Docs text export
- plain text/code-like Drive files
- text-extractable formats

PDF는 텍스트 추출 경로가 안정적으로 제공되는 범위만 지원하고, 그렇지 않으면 `UNSUPPORTED`/metadata-only로 반환 가능.

Analyzer를 직접 호출하지 않는다.

---

# 14. Drive resolve_original()

반환:

```text
OriginalSourceType.PROVIDER_URL
```

Google Drive file URL을 제공한다.

앱 backend가 원본 content를 proxy하지 않는다.

최종 access는 Google permission이 판단한다.

---

# 15. GitHub — GitHub App

PAT 방식 금지.

MVP 목표:

- personal/organization installation
- selected repository
- private repository 지원
- metadata/contents read-only 중심
- webhook
- short-lived installation token

GitHub App private key와 webhook secret은 Secret Manager/credential vault.

---

# 16. GitHub Installation Flow

```text
Source Manager
  ↓
Connect GitHub
  ↓
GitHub App install/authorize URL
  ↓
Account/Organization 선택
  ↓
Selected repositories
  ↓
GitHub native approval
  ↓
installation callback
  ↓
installation metadata
  ↓
repository choose / tracked branch / path scope
  ↓
SourceWorkspace + Mount canonical callback
```

조직 owner approval이 필요한 경우 GitHub flow를 그대로 따른다.

앱 내부 Source Manager role은 GitHub 권한을 만들어내지 않는다.

---

# 17. GitHub Runtime Identity

```text
GitHubSourceRuntime
- installation_id
- repository_id
- owner/name
- default_branch
- tracked_branch
- include_patterns[]
- exclude_patterns[]
```

MVP에서는 tracked branch 1개.

기본값은 default branch.

---

# 18. GitHub Tracking Scope

Application-level path filter를 제공한다.

예:

```text
include:
  src/**
  docs/**
  package*.json

exclude:
  customer-data/**
  generated/**
```

Source-level `.ipriskignore`가 repo에 존재한다면 optional deny source로 읽을 수 있다.

Provider repo permission보다 좁은 scope만 허용한다.

---

# 19. GitHub Webhook

MUST:

- HMAC signature 검증
- delivery/event ID 추적
- 필요한 event만 처리
- push event 중심 MVP
- tracked branch 아닌 이벤트 무시
- changed paths만 추출
- scope intersect 후 SourceChange 생성
- raw diff/source를 SourceChange에 넣지 않음

Webhook failure를 성공으로 숨기지 않는다.

---

# 20. GitHub SourceChange Identity

권장 fingerprint:

```text
repository_id + tracked_branch + commit_sha + changed_path
```

Artifact ref:

```text
source_artifact_id = stable logical key(repo_id + branch + path)
path_hint = repo-relative path
```

MOVE/rename이 감지되면 `previous_artifact` 제공.

---

# 21. GitHub fetch_snapshot()

전체 repo clone을 기본 방식으로 사용하지 않는다.

처리:

1. installation token 발급.
2. repository/tracked branch 검증.
3. tracked path 검증.
4. change type 확인.
5. current content fetch.
6. 가능하면 commit diff/changed lines + context 구성.
7. file size/type guard.
8. checksum.
9. SourceAccessReceipt.
10. SourceSnapshot.

`CHANGESET_WITH_CONTEXT`를 우선.

manifest/lockfile 등 작은 파일은 FULL_TEXT 가능.

---

# 22. GitHub resolve_original()

현재 revision에 해당하는 blob/file URL을 우선 제공한다.

```text
PROVIDER_URL
```

Private repo이면 사용자가 GitHub 권한을 가져야 열린다.

App이 raw source를 proxy하지 않는다.

---

# 23. Local Desktop Architecture

```text
React/Electron Renderer
        ↓ safe IPC
Preload
        ↓
Electron Main
        ↓
Local Registry + Watcher + OS
        ↓
Transient Cloud Staging
```

Renderer에는 Node arbitrary fs 권한을 주지 않는다.

---

# 24. Local Source Creation

Flow:

```text
Source Manager in Desktop
 ↓
Native folder picker
 ↓
canonical root resolution
 ↓
local mount handle 생성
 ↓
server-side SourceWorkspace/Mount callback
 ↓
watcher start
```

Local actual path는 device local registry에만 저장하는 것이 기본.

서버에는 opaque mount/device ID + relative path만 전송.

---

# 25. Local Registry

Desktop local storage:

```text
LocalMountRecord
- local_mount_handle
- server_mount_id
- canonical_root_path
- device_id
- include_patterns
- exclude_patterns
- status
```

이 storage는 OS user profile/private app data 영역 사용.

절대 Cloud Contract로 `canonical_root_path`를 내보내지 않는다.

---

# 26. Local Watcher

기존 prototype의 watchdog-style semantics를 참고하되 Electron/Node 환경에 맞는 안정적인 watcher library 선택 가능.

MUST:

- recursive watch
- debounce
- temp/swap/build output filter
- file size/type guard
- CREATE/UPDATE/DELETE/MOVE normalization
- ignored path skip
- symlink escape defense

watcher event는 path만 믿지 말고 root validation을 다시 수행한다.

---

# 27. Local Path Security

매 access 시:

```text
relative path
  ↓
join with registered canonical root
  ↓
realpath/canonicalize
  ↓
is descendant of root?
  ↓
YES continue / NO deny
```

symlink가 root 밖을 가리키면 deny.

Renderer가 arbitrary path를 main에 넘겨 열게 하지 않는다.

---

# 28. Local `.ipriskignore`

Source-level `.ipriskignore`를 root에서 optional 로드.

Agent 2는 source-level deny result를 적용해 untracked source를 cloud로 보내지 않는 것을 우선한다.

VWS global `.ipriskignore`는 Agent 1 SecurityGate 책임이므로 Agent 2가 재구현하지 않는다.

즉 source-level ignore와 VWS ignore가 중첩된다.

---

# 29. Local Change Data Minimization

Desktop에서 가능하면 full file보다:

```text
changed lines + surrounding context
```

을 우선 계산한다.

작은 manifest/lockfile은 full text 허용.

소스 전체가 필요한 경우라도 short-lived staging을 이용한다.

---

# 30. Local Transient Staging

Cloud worker가 local filesystem에 직접 접근할 수 없기 때문에 필요.

권장 abstraction:

```python
class LocalStagingStore(Protocol):
    async def put(payload, metadata_safe) -> StagingRef: ...
    async def get(ref) -> bytes/text: ...
    async def delete(ref) -> None: ...
```

Production target:

- Seoul region private Cloud Storage bucket
- uniform access
- public URL 없음
- opaque object name
- short TTL lifecycle rule
- analysis 후 best-effort delete

Cloud Tasks payload에는 staging ref만 전달.

---

# 31. Local SourceChange

`SourceChange`에:

- device ID를 safe metadata에 넣을 수 있음
- local absolute path 금지
- artifact path는 mount-relative path
- event fingerprint deterministic

예:

```text
device_id + mount_id + relative_path + revision/content fingerprint
```

---

# 32. Local fetch_snapshot()

Cloud-side LocalAdapter는 SourceChange safe metadata/staging ref를 바탕으로 snapshot을 복구한다.

반환:

- source_type LOCAL
- relative logical path hint
- text segments
- checksum
- bytes
- access receipt

snapshot fetch 완료 후 staging delete 시도.

분석 성공 여부와 무관하게 TTL safety net 존재.

---

# 33. Local resolve_original()

반환:

```text
OriginalSourceType.LOCAL_DEVICE
- device_id
- artifact opaque id
```

absolute path는 반환하지 않는다.

Web에서는 raw source 제공 안 함.

Desktop에서만 `Open Original` 구현.

---

# 34. Electron IPC — 허용 API

Renderer에 최소 capability만 노출.

예:

```text
chooseTrackedDirectory()
connectLocalMount(serverMountContext)
openTrackedArtifact(artifactId)
showTrackedArtifactInFolder(artifactId)
getDesktopConnectionStatus()
```

금지:

```text
readFile(path)
writeFile(path)
openPath(path)
listDirectory(path)
executeShell(command)
```

Preload bridge에서 input validation 필수.

---

# 35. Open Local Original

Flow:

```text
User clicks Open Original in Desktop
 ↓
artifact_id
 ↓
local registry resolves mount + relative path
 ↓
canonical root check
 ↓
file exists?
 ↓
OS open / show in folder
```

Web deep-link는 MVP 필수 아님.

---

# 36. Device Identity

Local connector에는 최소 device identity가 필요하다.

```text
DesktopDevice
- device_id random stable UUID
- app_user linkage server-side callback
- device_label
- last_seen
```

인증 자체는 App login session/desktop session을 재사용하되, device ID가 권한을 대신하지 않는다.

---

# 37. Source Route Namespace

Agent 2 소유:

```text
/api/v1/source-connections/**
/api/v1/source-workspaces/**
/api/v1/mounts/{mount_id}/source-operations/**
/webhooks/google-drive/**
/webhooks/github/**
/desktop/**
```

단 VWS membership/role 결정은 주입된 `authz_dependency`를 사용한다.

Agent 2가 Membership DB를 직접 읽는 구현을 만들지 않는다.

---

# 38. 권장 Source APIs

## Drive

```text
POST /api/v1/source-connections/google-drive/start
GET  /api/v1/source-connections/google-drive/callback
POST /api/v1/source-connections/{id}/drive/picker-session
POST /api/v1/source-connections/{id}/drive/mounts
POST /api/v1/mounts/{id}/source-operations/drive/manage-files
POST /api/v1/mounts/{id}/source-operations/reconnect
```

## GitHub

```text
GET/POST /api/v1/source-connections/github/install/start
GET      /api/v1/source-connections/github/install/callback
GET      /api/v1/source-connections/{id}/github/repositories
POST     /api/v1/source-connections/{id}/github/mounts
PATCH    /api/v1/mounts/{id}/source-operations/github/scope
```

## Local

```text
POST /desktop/devices/register
POST /desktop/mounts/register
POST /desktop/events
POST /desktop/staging
GET  /desktop/mounts/{id}/status
```

정확한 canonical Mount creation은 Control callback과 Integration에서 묶는다.

---

# 39. Source UI

Agent 2는 `frontend/src/sources/**`만 소유한다.

필수 UI:

### Add Source chooser

- Google Drive
- GitHub Repository
- Local Folder (Desktop only)

### Drive

- connected account label
- select/manage files
- selected file count/list summary
- reconnect/disconnect

### GitHub

- installation/account
- repository
- private/public badge
- tracked branch
- path include/exclude
- webhook status

### Local

- device label
- root display label (민감 path 전체 노출 최소화)
- include/exclude
- watcher status
- open-on-desktop semantics

Agent 1 shared UI primitive를 import할 수 없다는 dependency rule이 frontend에도 엄격히 적용되는 것은 현실적으로 어려울 수 있다. 따라서 Integration 단계에서 composition하기 쉽게 public props/API boundary를 유지하고, shared primitive 요청은 delivery에 남긴다.

---

# 40. Original Source UI Contract

Source UI/Integration이 제공해야 할 사용자-facing semantics:

```text
Drive -> Open in Google Drive
GitHub -> Open on GitHub
Local -> Open on this Desktop
```

raw content preview component를 만들지 않는다.

---

# 41. SourceAccessReceipt

모든 `fetch_snapshot()`은 access receipt를 정확히 채운다.

Drive/GitHub/Local 각각:

```text
METADATA
DIFF
PARTIAL_CONTENT
FULL_CONTENT
```

중 실제 동작을 반영.

`content_bytes`는 가능한 정확하게 측정.

Control이 SourceAccessEvent를 생성할 수 있어야 한다.

---

# 42. Error Semantics

Provider-private exception을 외부에 누출하지 않고 safe category로 변환.

예:

```text
AUTH_REQUIRED
PERMISSION_DENIED
NOT_FOUND
RATE_LIMITED
TEMPORARY_UNAVAILABLE
UNSUPPORTED_CONTENT
INVALID_WEBHOOK
SOURCE_OFFLINE
```

Adapter `fetch_snapshot()` 실패는 Integration/worker가 Analysis pipeline failure로 처리할 수 있도록 명확한 typed exception 또는 result policy를 제공한다.

빈 content를 성공으로 위장하지 않는다.

---

# 43. Reconciliation

`SourceAdapter.reconcile()` 구현:

### Drive

실제 cursor sync/reconcile 기능 제공.

### GitHub

MVP에서는 tracked branch latest tree/checkpoint와 비교하는 lightweight reconcile 가능. 최소한 method가 안전하게 no-op/unsupported capability를 표현해야 한다.

### Local

Desktop offline이면 cloud reconcile 불가. capability flag/no-op semantics.

Protocol이 optional behavior를 명확히 하도록 adapter 내부에서 safe result를 반환.

---

# 44. Source Health

`health(mount)`는 사용자 UI와 scheduler에 사용할 최소 상태를 제공.

권장 safe status:

```text
HEALTHY
REAUTH_REQUIRED
PERMISSION_DENIED
OFFLINE
DEGRADED
DISABLED
```

credential detail은 노출하지 않는다.

---

# 45. Security Tests

`tests/connectors/**` MUST:

1. Drive OAuth state mismatch reject
2. Drive multiple account connection metadata isolation
3. Picker uses selected connection token abstraction
4. unselected Drive file cannot produce valid tracked event/snapshot
5. Drive file ID stable across folder move
6. GitHub webhook HMAC reject invalid signature
7. non-selected repo ignored/rejected
8. non-tracked branch ignored
9. excluded path not fetched
10. private repo adapter works with mocked installation token
11. token never appears in contracts/logs
12. Local root escape rejected
13. symlink escape rejected
14. absolute path absent from SourceChange/Snapshot cloud metadata
15. renderer arbitrary fs call unavailable
16. staging object cleanup
17. staging TTL config documented
18. OriginalSourceLocator semantics correct
19. duplicate event fingerprint stable
20. SourceAccessReceipt accurately reports scope

---

# 46. Contract Tests

각 provider fixture에 대해:

```text
provider event
 -> valid SourceChange
 -> adapter.fetch_snapshot()
 -> valid SourceSnapshot
```

shared contract strict validation 통과.

unknown extra field를 넣지 않는다.

---

# 47. Provider Mocks/Fakes

실제 external integration과 별개로 testable fake client 제공.

- FakeDriveClient
- FakeGitHubClient
- FakeLocalStagingStore

하지만 production client implementation/skeleton이 반드시 존재해야 한다.

mock-only 완료 금지.

---

# 48. Observability

Structured log:

```text
provider
connection_id
source_workspace_id
mount_id
operation
provider_request_id safe
status
latency_ms
```

금지:

- access token
- refresh token
- raw source
- absolute local path
- GitHub App private key

---

# 49. Environment/Dependency Requests

예상 env:

```text
GOOGLE_DRIVE_CLIENT_ID
GOOGLE_DRIVE_CLIENT_SECRET
GOOGLE_DRIVE_REDIRECT_URI
GOOGLE_DRIVE_WEBHOOK_BASE_URL

GITHUB_APP_ID
GITHUB_APP_PRIVATE_KEY_SECRET_ID
GITHUB_WEBHOOK_SECRET_ID
GITHUB_APP_CALLBACK_URL

LOCAL_STAGING_BUCKET
GCP_PROJECT_ID
```

Root config 수정 대신 dependency/delivery 문서에 기록.

---

# 50. 구현 순서

## Phase A — Common Connector Framework

- provider clients abstraction
- credential vault port
- runtime store
- source adapter base helpers
- fingerprint helpers

## Phase B — GitHub

- App auth/install
- repository scope
- webhook
- snapshot
- original locator

## Phase C — Drive

- OAuth multi-account
- Picker
- selected files
- cursor/watch/reconcile
- snapshot

## Phase D — Local Desktop

- Electron main/preload
- local registry
- watcher
- staging
- snapshot adapter
- open original

## Phase E — Source UI

- add source
- provider management
- statuses

## Phase F — Hardening

- security tests
- retries
- cleanup
- delivery docs

순서는 기존 자산/팀 상황에 따라 Drive와 GitHub를 바꿔도 된다.

---

# 51. Integration Wiring Points

`AGENT_DELIVERY.md`에 최소:

1. provider adapter factory import paths
2. source router factory import path
3. required authz callback signature
4. canonical SourceConnection/SourceWorkspace/Mount creation callback needs
5. webhook router registration paths
6. scheduler hooks for Drive watch renewal/reconcile
7. Local staging store constructor
8. Desktop server endpoints
9. Source UI exported components/routes
10. env/dependency list

---

# 52. Acceptance Criteria

### Drive

- App login과 별개 Drive 계정 연결 가능 구조.
- multiple Drive connections isolated.
- `drive.file`/Picker selected file scope.
- change monitoring + cursor/reconcile.
- provider URL original locator.

### GitHub

- GitHub App selected repo/private repo 구조.
- webhook signature.
- tracked branch/path.
- no full clone default.
- provider URL original locator.

### Local

- explicit folder picker.
- root/symlink security.
- debounce/watch.
- no absolute path cloud contract.
- short-lived staging.
- Desktop-only raw open.

### Contracts

- 세 provider가 동일 SourceChange/SourceSnapshot semantics 준수.
- credential/raw content leak 없음.

### Testing

- shared contract tests 통과.
- connector security tests 통과.

### Delivery

- production adapter/client paths 존재.
- `AGENT_DELIVERY.md`, dependency request, known issues 작성.

---

# 53. Agent 2가 결정하지 말아야 할 사항

- Risk state/lifecycle
- Review disposition
- VWS role mapping
- global `.ipriskignore` semantics 변경
- SecurityGate AI-input policy
- Patent/License analysis
- Gemini/RAG behavior
- canonical Firestore schema
- shared contract fields
- deployment root config

---

# 54. 최종 성공 정의

Agent 2 구현만 단독으로 놓았을 때 fake Control callbacks를 사용해 다음이 가능해야 한다.

```text
Connect mocked Drive/GitHub or Local Desktop
 -> establish provider/source runtime
 -> detect simulated change
 -> emit valid SourceChange
 -> fetch valid SourceSnapshot
 -> resolve original locator
```

이 흐름에 Risk/AI 코드가 단 한 줄도 필요하지 않아야 한다.
