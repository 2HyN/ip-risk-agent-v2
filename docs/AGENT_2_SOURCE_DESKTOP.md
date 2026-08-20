# Agent 2 — Source Integration & Desktop 통합 참조

> 문서 상태: Agent 2 분산 문서 통합본
> 코드 기준: `source-integration-desktop` merge 결과 (`ee861b730d161caf876d2a300b476783d03bbaf6`)
> 적용 branch: `integration-v2`
> 최종 dependency 결정: [`../INTEGRATION_V2_DEPENDENCY_BASELINE.md`](../INTEGRATION_V2_DEPENDENCY_BASELINE.md)
> 전체 조립 계획: [`../INTEGRATION_V2_EXECUTION_PLAN.md`](../INTEGRATION_V2_EXECUTION_PLAN.md)

이 문서는 Agent 2의 delivery와 dependency 요청을 하나로 정리한 유지 문서다. Agent 2 독립 test에서 “완료”였던 경로라도 Control 인증, canonical persistence와 production GCP port를 붙였을 때 추가 작업이 필요한 항목은 분리해 기록한다.

## 1. 통합한 원본

| 원본 | 이 문서에 흡수한 내용 |
|---|---|
| `AGENT_2_DELIVERY.md` | 구현 범위, 파일, route/port, 실행/test, 보안 체크, 제약 |
| `agent-deliverables/agent-2-dependencies.md` | provider/Electron dependency 선택과 검증 이력 |

원본은 전체 통합 검증 후 Phase 8에서만 삭제한다.

## 2. 역할과 경계

Agent 2는 다음을 제공한다.

- Google Drive OAuth, Picker/mount route와 SourceAdapter
- Google Drive change reconciliation과 webhook route
- GitHub App install, repository/mount route와 SourceAdapter
- GitHub webhook HMAC 검증과 change normalization
- Local staging/event route와 SourceAdapter
- Electron local registry, path guard, watcher, preload IPC와 main process
- Source frontend chooser와 platform adapter
- credential/runtime/tracking/state/lookup protocol과 in-memory fake
- provider error normalization, retry, fingerprint, `.ipriskignore`

Agent 2가 소유하지 않는 것:

- canonical user/VWS/membership/mount/Risk persistence
- 최종 Source route authorization 정책
- production Secret Manager/Firestore/GCS adapter
- Cloud Tasks/worker/analyzer
- final Product app shell과 runtime composition

### 핵심 불변식

- 사용자가 선택한 Drive file/GitHub repository·branch/local root 밖을 읽지 않는다.
- credential/token/private key/webhook secret을 contract/log에 노출하지 않는다.
- local absolute path를 cloud request/canonical metadata에 넣지 않는다.
- provider event를 frozen `SourceChange`로 정규화한다.
- raw content는 `SourceSnapshot`에서만 transient하게 다룬다.
- Source plane은 Risk 상태를 만들거나 해소하지 않는다.
- provider failure를 empty success로 바꾸지 않는다.

## 3. 코드 지도

```text
backend/src/ip_risk_agent/connectors/
  common/
    errors.py fingerprint.py credential_vault.py runtime_store.py
    adapter_support.py change_sink.py ipriskignore.py oauth_state.py
    authz.py retry.py
  google_drive/
    models.py client.py oauth.py oauth_routes.py mounts_routes.py
    tracking_scope.py connection_lookup.py mount_resolver.py
    adapter.py routes.py error_mapping.py
  github/
    models.py client.py oauth.py install_routes.py mounts_routes.py
    identity.py tracking_scope.py connection_lookup.py mount_resolver.py
    adapter.py webhook.py webhook_processor.py routes.py error_mapping.py
  local/
    identity.py staging_store.py device_lookup.py adapter.py routes.py

apps/desktop/
  core/ local-registry/ main/ preload/ security/ watcher/

frontend/src/sources/
  AddSourceChooser.tsx
  ConnectLocalSource.tsx
  api/connectionClient.ts
  platform/PlatformAdapter.ts
  dev/preview.tsx

tests/connectors/
```

## 4. 공통 public ports

### Authorization

```python
class AuthzDependency(Protocol):
    async def __call__(self, request: Request, resource_id: str) -> None: ...
```

기본 `allow_all_authz`는 test/local fake일 뿐 production에서 사용하면 안 된다. Integration은 session+CSRF, device bearer, webhook/internal identity를 route 성격에 맞게 분리한다.

### Change sink

```python
class SourceChangeSink(Protocol):
    async def persist(self, change: SourceChange) -> None: ...
```

Production binding은 Control facade의 `register_source_change()`다.

### Credential vault

```python
put(scope, secret) -> CredentialRef
get(ref) -> str
update(ref, secret) -> None
delete(ref) -> None
```

`InMemoryCredentialVault`는 production 불가다. Secret Manager adapter가 필요하다.

### Operational state

- `OAuthStateStore`: multi-instance shared, single-use TTL 필요
- `RuntimeStore[T]`: Drive/GitHub/Local operational record
- Drive/GitHub tracking scope store
- connection/install/credential lookup
- Drive channel mount resolver
- GitHub repository mount resolver
- Local device lookup
- `LocalStagingStore`: production GCS 필요

이 state에는 Risk/Membership/Review를 저장하지 않는다.

## 5. Google Drive

### Route factory

| Factory | Route |
|---|---|
| `create_drive_oauth_router` | `POST /api/v1/source-connections/google-drive/start` |
|  | `GET /api/v1/source-connections/google-drive/callback` |
| `create_drive_mounts_router` | `POST /api/v1/source-connections/{connection_id}/drive/picker-session` |
|  | `POST /api/v1/source-connections/{connection_id}/drive/mounts` |
| `create_drive_webhook_router` | `POST /webhooks/google-drive` |

### Callback

```python
create_drive_connection(
    request,
    *, risk_workspace_id, provider_subject, provider_email, credential_ref
) -> str

create_drive_mount(
    request,
    *, connection_id, risk_workspace_id, selected_file_ids
) -> DriveMountCreationResponse
```

OAuth callback은 token JSON을 vault에 저장하고 opaque `CredentialRef`만 callback에 전달한다. Picker session은 선택한 connection의 token을 가져오고 refresh 결과를 vault에 update한다.

### Adapter

`GoogleDriveAdapter` constructor:

```text
provider_factory
credential_vault
connection_lookup
tracking_scope_store
runtime_store
```

주요 메서드:

- `health(mount)`
- `fetch_snapshot(change)`
- `resolve_original(mount, artifact)`
- `reconcile(mount, cursor)`

선택 file ID가 tracking scope에 없으면 fetch를 거부한다. 지원 MIME만 text snapshot으로 만들고 access receipt를 포함한다. change cursor는 runtime store에 유지한다.

### Integration 의무

- pending OAuth connection과 canonical mount 연결
- production credential/binding/tracking/runtime stores
- watch channel 생성, resource/channel binding과 만료 갱신
- webhook channel token/resource 검증
- periodic reconciliation
- callback 후 Product UI 복귀와 Picker UI
- id_token/provider identity 검증 hardening

## 6. GitHub

### Route factory

| Factory | Route |
|---|---|
| `create_github_install_router` | `POST /api/v1/source-connections/github/install/start` |
|  | `GET /api/v1/source-connections/github/install/callback` |
| `create_github_mounts_router` | `GET /api/v1/source-connections/{connection_id}/github/repositories` |
|  | `POST /api/v1/source-connections/{connection_id}/github/mounts` |
| `create_github_webhook_router` | `POST /webhooks/github` |

### Callback

```python
create_github_connection(
    request, *, risk_workspace_id, installation_id
) -> str

create_github_mount(
    request,
    *, connection_id, risk_workspace_id, owner, repo, tracked_branch
) -> GitHubMountCreationResponse
```

installation ID는 secret이 아니며 GitHub App private key는 app-level provider factory가 관리한다.

### Adapter/webhook

`GitHubAdapter`는 provider factory, connection lookup, tracking scope store를 받는다.

- encoded artifact identity를 검증한다.
- selected repository/branch/include/exclude scope를 적용한다.
- repository root `.ipriskignore` deny를 추가 적용한다.
- 최대 file size와 지원 확장자를 보수적으로 처리한다.
- webhook processor가 raw body HMAC, delivery, branch와 mount scope를 검증한다.
- owner/repo resolver는 같은 repository를 추적하는 여러 VWS mount를 반환할 수 있다.

### Integration 의무

- pending installation과 canonical mount mapping
- private key/webhook secret의 Secret Manager 주입
- installation/mount/repository binding persistence
- callback 후 repository/branch/mount UI
- repository list pagination
- no-op인 `reconcile()`의 운영상 의미와 health 보완

## 7. Local Desktop

### Server routes

| Route | 의미 |
|---|---|
| `POST /desktop/devices/register` | device를 authenticated app user에 연결 |
| `POST /desktop/mounts/register` | canonical Local mount 생성 |
| `POST /desktop/staging` | transient text를 staging store에 저장 |
| `POST /desktop/events` | metadata-only SourceChange 생성/전달 |

`GET /desktop/mounts/{id}/status`는 branch에 없다.

### Cloud request data

Mount registration에는 다음만 보낸다.

```text
risk_workspace_id, device_id, include_patterns, exclude_patterns
```

`canonical_root_path`는 보내지 않는다. event에는 relative path, device/mount/workspace ID, change type, revision과 opaque staging object name만 포함한다.

### Electron structure

- `FileDeviceIdentityStore`: device identity
- `FileLocalRegistryStore`: local root와 server mount mapping
- `path-guard`: root/path traversal/symlink 경계
- `watcher`: CREATE/UPDATE/DELETE/MOVE 감지
- `DesktopEventReporter`: staging 후 event 전송
- `HttpMountRegistrationClient`: device/mount 등록
- preload: allow-listed IPC만 renderer에 노출
- `LocalSourceService`: directory 선택, mount 연결, original open

### 현재 통합 공백

Agent 2 branch의 HTTP client는 cookie/CSRF/device credential 없이 호출한다. Source authz를 fail closed하면 background request가 401이 된다. Integration은 one-time enrollment, hashed server credential, Electron `safeStorage`, bearer 인증과 revoke/rotation을 구현한다.

현재 Electron main은 Product renderer가 아니라 `data:` smoke page를 연다. Source frontend의 Local component도 directory 선택 뒤 `connectLocalMount`를 호출하지 않는다. 두 항목은 Phase 5에서 완성한다.

## 8. Source frontend

제공 요소:

- `AddSourceChooser`
- `ConnectLocalSource`
- `HttpConnectionApiClient`
- Web/Electron `PlatformAdapter`

현재 Drive/GitHub 버튼은 connection start endpoint까지 호출한다. Product integration에서 추가할 것:

- current VWS 사용, `dev-workspace` 제거
- Control session의 CSRF-aware client 사용
- OAuth/install callback completion route
- Drive Picker와 mount create
- GitHub repository/branch와 mount create
- connected source/status/reconnect UI
- Local directory 선택 후 실제 IPC mount 연결
- `frontend/src/sources/dev/preview.tsx` 삭제

Control UI에는 `ControlPlaneApp.integration.sourcePanel/sourceNavigation`으로 주입한다.

## 9. Retry와 error 의미

공통 retry는 network failure, HTTP 429/5xx와 retryable connector error에 exponential backoff를 적용한다. auth, permission, not-found, invalid webhook과 scope violation을 무조건 retry하지 않는다.

Provider error는 safe category로 바꾸며 raw provider response/token을 외부에 노출하지 않는다. client 내부 retry가 소진되면 Worker/Cloud Tasks 정책으로 넘긴다.

## 10. Agent 검증 dependency 이력

| Package | Agent 2 검증/요청값 | 용도 |
|---|---:|---|
| google-api-python-client | 2.198.0 | Drive API |
| google-auth | 2.56.3 | Drive OAuth credential refresh |
| PyJWT[crypto] | 2.10.1 | GitHub App JWT |
| httpx | 0.28.x | GitHub/OAuth HTTP |
| fastapi | 0.121.2 | isolated Source router 검증 |
| chokidar | 5.0.0 | local watcher |
| electron | 43.4.0 | desktop shell |
| @types/node | 24.x | desktop TypeScript |
| React/React DOM | 19.2.8 | Source UI |
| TypeScript | 5.9.3 | frontend/desktop |
| Vite | 8.2.1 | Source UI build |

FastAPI와 frontend toolchain은 merge conflict 해결 시 Control 기준을 채택했다. 최종 exact set은 dependency baseline을 따른다. `google-cloud-secret-manager`, Firestore, GCS는 Agent 2가 검증한 dependency가 아니라 Integration production adapter용이다.

## 11. 환경 변수

```text
GOOGLE_DRIVE_CLIENT_ID
GOOGLE_DRIVE_CLIENT_SECRET
GOOGLE_DRIVE_REDIRECT_URI
GOOGLE_DRIVE_WEBHOOK_BASE_URL
DRIVE_WATCH_CHANNEL_TOKEN

GITHUB_APP_ID
GITHUB_APP_SLUG
GITHUB_APP_PRIVATE_KEY_SECRET_ID
GITHUB_WEBHOOK_SECRET_ID
GITHUB_APP_CALLBACK_URL

LOCAL_STAGING_BUCKET
GCP_PROJECT_ID
IPRISK_SERVER_BASE_URL
```

실제 secret은 source나 `.env.example`에 넣지 않는다. 최종 설정 group과 Secret Manager reference 규칙은 통합 기준 문서를 따른다.

## 12. 검증 증거와 재실행

Agent 2 인계 시점:

- Python connector: 224 passed
- Desktop TypeScript: 65 tests, 63 passed/2 Windows symlink skip
- Source frontend: 8 passed
- 총 297 tests, 295 passed/2 skipped
- frozen contract 수정 없음

통합 후 재실행:

```powershell
python -m pytest tests/connectors -q
pnpm --filter @iprisk/desktop run build
pnpm --filter @iprisk/desktop run test
pnpm --filter @iprisk/frontend run test
pnpm --filter @iprisk/frontend run build
```

Source frontend tests는 merge 후 Vitest 체계로 포팅해야 한다. Windows symlink test는 권한 가능한 CI runner에서 별도 실행한다.

## 13. 보안 검증 coverage

독립 branch에서 확인한 주요 항목:

- OAuth state mismatch 거부
- Drive account/token isolation
- selected Drive file 외 fetch 거부
- GitHub HMAC invalid 거부
- unselected repo/untracked branch/ignored path 거부
- private repo fake installation path
- token contract/log 비노출
- Local root escape 거부
- renderer arbitrary filesystem 호출 불가
- staging cleanup
- OriginalSourceLocator semantics
- stable duplicate fingerprint
- SourceAccessReceipt scope

부분/환경 의존:

- Drive file ID 이동 안정성은 설계상 보장이나 별도 test 없음
- symlink test 2건 Windows 권한으로 skip
- staging TTL은 문서화만 됐고 실제 bucket lifecycle은 Integration 책임

## 14. Known issues와 우선순위

### Phase 3~5 blocker

- production authz/CSRF와 desktop device auth
- pending connection/canonical mount persistence
- production vault/runtime/tracking/lookup/staging
- Drive watch 생성/갱신
- OAuth callback 이후 mount completion UI
- desktop mount status와 Product renderer

### 후속/제한

- GitHub reconcile는 safe no-op
- repository list는 최대 100개 단일 page
- Drive id_token signature 검증 보강 필요
- Drive sync file API 일부는 공통 retry 미적용
- Local staging은 text only
- `.ipriskignore`는 fnmatch subset
- 동일 content file에서 MOVE 추정 오판 가능
- Source UI styling/component coverage 제한

제약을 success로 숨기지 않고 readiness, UI와 운영 문서에 드러낸다.

## 15. Phase 8 원본 삭제 확인표

| 원본 | 대체 section |
|---|---|
| delivery | §2~14 |
| dependency request | §10~12 |

삭제 전 build/test/운영 절차의 원본 파일명 참조를 이 문서 또는 최종 개발/운영 문서로 바꾼다. 보호 대상 명세·기준 문서와 provenance/history 구간의 과거 참조는 실행 경로가 아님을 확인한 뒤 보존할 수 있다.
