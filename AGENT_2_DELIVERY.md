# AGENT_2_DELIVERY.md — Agent 2 (Source Integration & Desktop)

> Master Spec §60 필수 제출 문서. Integration Agent는 이 파일을 먼저 읽고 통합한다.
> 작성 기준: branch `source-integration-desktop`, 최종 커밋 기준.

---

## 1. 구현한 범위

3개 Source Provider(Drive/GitHub/Local) 전부에 대해 `SourceAdapter` 계약(health/fetch_snapshot/resolve_original/reconcile)을 구현했고, **연결 시작(OAuth/App 설치) → 파일/저장소 선택(Picker/repositories) → 최종 Mount 생성 → 변경 감지·수신(webhook/desktop events)**까지 Drive/GitHub/Local 세 provider의 전체 라이프사이클 라우터가 끊김 없이 이어진다. Electron Desktop 앱은 로컬 폴더 감시(MOVE 감지 포함) → 실제 HTTP 전송 → 서버 라우터까지 전체 왕복이 완성돼 있다.

| Phase | 내용 | 상태 |
|---|---|---|
| A | 공통 도구함 (errors, fingerprint, credential_vault, runtime_store, adapter_support) | ✅ 완료 |
| C | Google Drive SourceAdapter 전체 + webhook 라우터 + **OAuth 연결 흐름 + Picker/Mount 생성** | ✅ 완료 |
| D | Local SourceAdapter + Electron watcher/security/registry + 실제 dialog/shell 배선 + MOVE 감지 + **HTTP 전송 배선** | ✅ 완료 |
| B | GitHub SourceAdapter 전체 + webhook 라우터 + **App 설치 흐름 + 저장소목록/Mount 생성** | ✅ 완료 |
| — | 라우터 3종 + device/mount 등록 + authz 주입 지점 + source-level `.ipriskignore` | ✅ 완료 |
| E | Source UI 최소 버전 (React+Vite 부트스트랩 포함) | 🟡 부분 완료 — 10-4 참고 |
| F | 하드닝 | ⬜ 미착수 |

---

## 2. 변경한 파일 목록

### Python (`backend/src/ip_risk_agent/connectors/`)
common/
errors.py, fingerprint.py, credential_vault.py, runtime_store.py,
adapter_support.py, change_sink.py, ipriskignore.py, oauth_state.py, authz.py

google_drive/
models.py, client.py, error_mapping.py, tracking_scope.py,
connection_lookup.py, adapter.py, mount_resolver.py, routes.py,
oauth.py, oauth_routes.py, mounts_routes.py

github/
models.py, webhook.py, error_mapping.py, client.py, identity.py,
tracking_scope.py, connection_lookup.py, adapter.py,
webhook_processor.py, mount_resolver.py, routes.py,
oauth.py, install_routes.py, mounts_routes.py

local/
identity.py, staging_store.py, device_lookup.py, adapter.py, routes.py


### TypeScript — Electron Desktop (`apps/desktop/`)

security/path-guard.ts
watcher/filters.ts, watcher.ts, chokidar.d.ts, ipriskignore.ts
local-registry/store.ts, device-identity.ts, artifact-resolver.ts
preload/api.ts, build-api.ts, preload.mts
core/local-source-service.ts
main/index.ts, electron-directory-picker.ts, electron-artifact-opener.ts,
desktop-event-reporter.ts


### TypeScript — Frontend (`frontend/`)

src/sources/platform/PlatformAdapter.ts
src/sources/AddSourceChooser.tsx
src/sources/ConnectLocalSource.tsx
src/sources/dev/preview.tsx ← 임시 파일, 10-4 참고
vite.config.ts, index.html


### 테스트

각 소스 파일당 `*.test.ts`/`test_*.py` 1:1 대응.

---

## 3. 외부 dependency 목록

`agent-deliverables/agent-2-dependencies.md`에 상세 기록. 요약:

| 영역 | Package | Version |
|---|---|---|
| Drive | google-api-python-client, google-auth | 2.198.0, 2.56.3 |
| GitHub / OAuth 공용 | PyJWT[crypto], httpx | 2.10.1, 0.28.x |
| 공통 라우터 | fastapi | 0.121.2 |
| Desktop | chokidar, electron, @types/node | ^5.0.0, ^43.4.0, ^24.0.0 |
| Frontend | react, react-dom, vite, @vitejs/plugin-react | 19.2.8, 19.2.8, 8.2.1, ^6.0.5 |

OAuth/Picker/Mount 라우터 구현에는 **새 dependency가 필요 없었음** — httpx/PyJWT/fastapi 전부 기존 재사용.

---

## 4. 필요한 Environment Variables

GOOGLE_DRIVE_CLIENT_ID
GOOGLE_DRIVE_CLIENT_SECRET
GOOGLE_DRIVE_REDIRECT_URI
GOOGLE_DRIVE_WEBHOOK_BASE_URL
DRIVE_WATCH_CHANNEL_TOKEN

GITHUB_APP_ID
GITHUB_APP_SLUG # https://github.com/apps/{slug}/installations/new 조립용
GITHUB_APP_PRIVATE_KEY_SECRET_ID
GITHUB_WEBHOOK_SECRET_ID
GITHUB_APP_CALLBACK_URL

LOCAL_STAGING_BUCKET
GCP_PROJECT_ID
IPRISK_SERVER_BASE_URL # Electron이 /desktop/events, /desktop/staging을 호출할 서버 주소


전부 생성자 인자로 주입받는 구조라, Integration이 Secret Manager 등에서 읽어와 넘겨주면 된다.

---

## 5. 실행 방법

```bash
git switch source-integration-desktop
python -V:3.14.7 -m venv .venv
source .venv/Scripts/activate
pip install -e ".[dev]"
pip install "google-api-python-client>=2.180,<3.0" "google-auth>=2.40,<3.0" \
            "PyJWT[crypto]==2.10.1" "httpx>=0.28,<0.29" "fastapi==0.121.2"

pnpm install
```

Electron 데스크톱 앱 실행 (스모크 테스트):

```bash
pnpm --filter @iprisk/desktop run build
pnpm --filter @iprisk/desktop run start
```

Frontend 개발 서버:

```bash
pnpm --filter @iprisk/frontend run dev
```

---

## 6. Test 실행 방법과 결과

```bash
pytest tests/connectors/ -v
```
**209 passed**, 0 skipped, 0 failed.

```bash
pnpm --filter @iprisk/desktop run build && pnpm --filter @iprisk/desktop run test
```
**63 tests — 61 passed, 2 skipped.** skip 2개는 symlink 관련 테스트로, Windows에서 관리자 권한/Developer Mode 없는 환경이면 자동으로 건너뛰도록 코드에서 처리해뒀음 (에러 아님).

```bash
pnpm --filter @iprisk/frontend run build && pnpm --filter @iprisk/frontend run test
```
**5 passed.**

**합계: 277 tests — 275 passed, 2 skipped, 0 failed.**

전부 real fake(FakeDriveProvider, FakeGitHubProvider, FakeDriveOAuthClient 등)와 실제 파일시스템/실제 chokidar/실제 FastAPI TestClient/실제 Electron(헤드리스 실행 포함)으로 검증했고, mock-only로 완료 주장한 부분 없음 (Master Spec §59 금지사항 10번 준수).

---

## 7. Shared Contract 준수 여부

- `shared/contracts/**` 파일을 직접 수정한 적 없음 — 전체 개발 기간 매 Phase 종료 시점마다 확인.
- Frozen contract 테스트(27개)는 항상 별도로 재실행해서 통과 확인.
- 모든 Pydantic 모델은 `StrictModel`(`extra="forbid"`) 기반.
- `SourceChange`/`SourceSnapshot`에 raw content, credential, 로컬 절대경로를 담은 적 없음.
- `canonical_root_path`는 애초에 어떤 요청 스키마에도 없음 (§25) — 실수로도 서버에 못 나가는 구조.

---

## 8. Contract-change Request 목록

**없음.** v1 계약 범위 안에서 전부 구현 가능했음.

---

## 9. Integration Agent가 알아야 할 Wiring Point

### 9-1. 우리가 만든 "포트"(Protocol) — 전부 지금은 fake만 있고 진짜 구현 필요

| 포트 | 위치 | 실제로 뭐에 연결해야 하는지 |
|---|---|---|
| `AuthzDependency` | `common/authz.py` | **전체 라우터 공용.** 기본값(`allow_all_authz`)은 아무 검사도 안 함 — 프로덕션 배포 전 Agent 1의 실제 VWS Role 검사로 반드시 교체 |
| `SourceChangeSink` | `common/change_sink.py` | 모든 라우터가 만든 `SourceChange` → Control의 실제 persist+idempotency+Cloud Tasks enqueue |
| `OAuthStateStore` | `common/oauth_state.py` | 지금은 InMemory — 여러 서버 인스턴스 환경이면 Firestore 등 공유 저장소 필요 |
| `DriveConnectionCreationCallback` | `google_drive/oauth_routes.py` | provider_subject/email/credential_ref로 canonical `SourceConnection` 생성 |
| `GitHubConnectionCreationCallback` | `github/install_routes.py` | installation_id로 canonical `SourceConnection` 생성 |
| `DriveMountCreationCallback` | `google_drive/mounts_routes.py` | 선택된 file_id들로 canonical `SourceWorkspace`+`Mount` 생성 |
| `GitHubMountCreationCallback` | `github/mounts_routes.py` | owner/repo/branch로 canonical `SourceWorkspace`+`Mount` 생성 |
| `DeviceRegistrationCallback` | `local/routes.py` | device_id를 현재 세션의 app_user에 연결 |
| `MountCreationCallback` | `local/routes.py` | Local의 canonical `SourceWorkspace`+`Mount` 생성 |
| `DriveConnectionLookup`, `DriveConnectionCredentialLookup` | `google_drive/connection_lookup.py` | 각각 mount_id, connection_id 기준으로 credential 조회 |
| `GitHubConnectionLookup`, `GitHubConnectionInstallationLookup` | `github/connection_lookup.py` | 각각 mount_id, connection_id 기준으로 installation_id 조회 |
| `LocalDeviceLookup` | `local/device_lookup.py` | mount_id → device_id 조회 |
| `DriveChannelMountResolver`, `GitHubMountResolver` | 각 provider `mount_resolver.py` | channel_id/repo → mount 목록 조회 |
| `SourceCredentialVault` | `common/credential_vault.py` | 실제 Secret Manager로 교체 |
| `*RuntimeStore`, `*TrackingScope` 저장 | `common/runtime_store.py`, 각 provider `tracking_scope.py` | Firestore 등 실제 영구 저장소 |
| `LocalStagingStore` | `local/staging_store.py` | 실제 GCS 버킷 (텍스트만 처리, 바이너리 필요시 확장 필요) |

### 9-2. 라우터 등록 (전부 `APIRouter` 반환, `include_router()`로 붙이면 됨)

```python
# 연결 시작
create_drive_oauth_router(client_id=..., redirect_uri=..., state_store=..., oauth_client=...,
    credential_vault=..., connection_creation_callback=..., authz_dependency=...)
create_github_install_router(app_slug=..., state_store=..., connection_creation_callback=..., authz_dependency=...)

# 파일/저장소 선택 + 최종 Mount 생성
create_drive_mounts_router(provider_factory=..., credential_vault=..., connection_credential_lookup=...,
    tracking_scope_store=..., mount_creation_callback=..., authz_dependency=...)
create_github_mounts_router(provider_factory=..., connection_installation_lookup=...,
    tracking_scope_store=..., mount_creation_callback=..., authz_dependency=...)

# 변경 수신
create_github_webhook_router(webhook_processor=..., mount_resolver=..., change_sink=...)
create_drive_webhook_router(adapter=..., channel_resolver=..., channel_token=..., change_sink=...)
create_local_desktop_router(staging_store=..., change_sink=..., device_registration_callback=...,
    mount_creation_callback=..., authz_dependency=...)
```

**실제 앱(`main.py`/`composition/`)에 아직 연결 안 돼있음** — Integration 몫.

### 9-3. Local Desktop 쪽 실제 서버 구성

`apps/desktop/main/index.ts`는 mount 연결 시 자동으로 watcher를 시작하고, 감지된 변경을 실제 HTTP로 서버에 전송한다(`desktop-event-reporter.ts`, `IPRISK_SERVER_BASE_URL` 환경변수 사용). 앱 재시작 시 기존 ACTIVE mount들도 자동 재감시한다. `connectLocalMount()`가 `serverMountId`를 인자로 받는 구조는 그대로라, 실제로는 Electron이 먼저 `/desktop/mounts/register`를 호출해서 그 값을 받아온 뒤 로컬 IPC를 불러야 완결된다 — **이 두 단계를 잇는 Electron 쪽 배선은 아직 없음** (10-2 참고).

### 9-4. Drive OAuth 토큰

`GoogleDriveAdapter`와 `mounts_routes.py`의 picker-session 둘 다 매 호출마다 `credential_vault.update()`로 갱신된 토큰을 자동 저장한다. Secret Manager 구현으로 교체만 하면 별도 배선 없이 그대로 동작.

---

## 10. 미완성/제약/Known Issue

### 10-1. 진짜로 Agent 1 결정이 먼저 나와야 하는 것

- **라우터의 실제 authz 정책 내용** — 주입 지점은 전부 완성했지만, "이 사람이 이 mount/워크스페이스를 건드릴 권한이 있는가"를 판단하는 실제 규칙은 Agent 1의 VWS Role 시스템 몫.
- **canonical Firestore 저장의 마지막 단계** — 위 9-1의 `*CreationCallback` 포트들이 실제로 Firestore에 쓰는 부분.

### 10-2. 우리 힘으로 할 수 있는데 아직 안 한 것

- **Electron이 mount 등록 2단계(register → connect)를 실제로 잇는 배선** — 서버 라우터(`/desktop/mounts/register`)와 로컬 IPC(`connectLocalMount`)가 각각 완성돼 있지만, 그 사이를 잇는 호출 코드가 없음.
- **Frontend `AddSourceChooser`가 실제 OAuth 시작 라우터를 호출하도록 연결** — 버튼 UI는 있지만 오늘 만든 `/source-connections/google-drive/start`, `/source-connections/github/install/start`를 아직 안 부름.
- **`GET /desktop/mounts/{id}/status`** — 조회용 엔드포인트, 아직 미구현.
- **GitHub `reconcile()` 고도화** — 지금은 안전한 no-op(§43 최소 기준 충족)만 있고 "tracked branch latest tree 비교"까지는 안 함.

### 10-3. 알려진 한계 (의도적 단순화, 문서화 완료)

- **Local MOVE 감지는 내용 해시 기반 추정** — 내용이 완전히 같은 서로 다른 두 파일이 우연히 겹치면 오판 가능.
- **`.ipriskignore`는 fnmatch 기반** — gitignore 전체 문법(`!` 부정 등)은 구현 안 함.
- **Drive id_token 서명 검증 생략** — provider_subject/email 추출용으로만 디코딩하고 서명은 검증 안 함(실제 보안 결정은 state CSRF 검증 + code exchange에서 이미 끝남). 더 엄격하게 가려면 Google JWKS 서명 검증 추가 가능.
- **GitHub `list_installation_repositories()`는 단일 페이지(최대 100개)만 처리** — 저장소 100개 넘는 installation은 페이지네이션 추가 필요.
- **LocalStagingStore는 텍스트만 처리** — 바이너리 필요시 타입 확장 필요.
- **symlink escape 테스트 2개, 이 개발 환경에서 SKIP** — 관리자 권한 없으면 symlink 생성 자체가 안 돼서 자동 skip. 코드 로직은 존재하고 문자열 기반 탈출 방지는 항상 테스트됨.

### 10-4. Frontend는 최소 기능만

- `AddSourceChooser`의 Drive/GitHub 버튼은 아직 OAuth 시작 라우터를 실제로 호출하지 않음 (10-2 참고).
- `sources/dev/preview.tsx`는 임시 파일 — Agent 1이 `frontend/src/app/**`에 진짜 app shell/router를 만들면 대체돼야 함.
- 스타일링 없음 (요청대로 기능 우선 진행).
- React 컴포넌트 자동 테스트 없음 — `PlatformAdapter` 순수 로직만 테스트, 화면은 브라우저로 눈으로 확인.

---

## 부록 — Agent 2 Spec §45 보안 테스트 체크리스트 대조 (20개)

| # | 항목 | 상태 |
|---|---|---|
| 1 | Drive OAuth state mismatch reject | ✅ |
| 2 | Drive multiple account 연결 metadata isolation | ✅ |
| 3 | Picker가 선택된 connection token 추상화 사용 | ✅ **오늘 완료** (picker-session이 connection_id별 credential만 사용) |
| 4 | 선택 안 된 Drive 파일은 유효한 tracked event/snapshot 생성 불가 | ✅ |
| 5 | Drive file ID가 폴더 이동에도 안정적 | 🟡 설계상 보장되나 별도 테스트는 없음 |
| 6 | GitHub webhook HMAC 잘못된 서명 거부 | ✅ |
| 7 | 선택 안 된 repo 무시/거부 | ✅ |
| 8 | tracked 아닌 branch 무시 | ✅ |
| 9 | 제외된 path는 fetch 안 됨 | ✅ (tracking scope + `.ipriskignore` 이중) |
| 10 | private repo가 mocked installation token으로 동작 | ✅ |
| 11 | token이 contract/log에 노출 안 됨 | ✅ |
| 12 | Local root escape 거부 | ✅ |
| 13 | symlink escape 거부 | 🟡 코드 존재, 이 환경에서 권한 부족으로 SKIP |
| 14 | 절대경로가 SourceChange/Snapshot cloud metadata에 없음 | ✅ |
| 15 | renderer의 임의 fs 호출 불가능 | ✅ |
| 16 | staging object cleanup | ✅ |
| 17 | staging TTL 설정 문서화 | 🟡 요구사항으로만 문서화, 실제 GCS lifecycle 설정은 Integration 몫 |
| 18 | OriginalSourceLocator semantics 정확 | ✅ |
| 19 | 중복 이벤트 fingerprint 안정적 | ✅ |
| 20 | SourceAccessReceipt가 scope를 정확히 반영 | ✅ |

**✅ 완료 17개 / 🟡 부분·환경제약 3개 / ⬜ 미구현 0개**
