# Dependencies

세 Plane 이 각자 선택·검증한 dependency 를 Integration 이 하나의 manifest 로 확정한 결과다.
병렬 개발 동안 각 Plane 은 root manifest 를 수정하지 않고 자기 문서에 후보를 기록했고,
통합 단계에서 충돌을 조율해 `pyproject.toml` 과 `pnpm-lock.yaml` 에 반영했다.

**최종 검증 환경** — CPython 3.14.7 / Node.js 24.19.0 / pnpm 11.19.0 / TypeScript 5.9.3
전이 의존성 포함 **70개 패키지**, `pip check` 통과.

---

## 1. 기준 런타임

| 항목 | 버전 | 고정 위치 |
|---|---|---|
| CPython | **3.14.7** (`>=3.14,<3.15`) | `pyproject.toml` |
| Node.js | **24.19.0** | `package.json` `engines` |
| pnpm | **11.19.0** | `package.json` `packageManager` |
| TypeScript | **5.9.3** | root `devDependencies` |
| Pydantic | **2.13.4** | `pyproject.toml` |
| pytest | **9.1.1** | `pyproject.toml` `[dev]` |

---

## 2. Python — 확정 목록

`pyproject.toml` 에 반영된 최종 상태다.

### Runtime

| 패키지 | 버전 | 소유 Plane | 용도 |
|---|---|---|---|
| `pydantic` | `2.13.4` | 공통 | Frozen Contract 및 모델 스키마 |
| `fastapi` | `0.141.1` | Control | Control API, dependency injection |
| `google-cloud-firestore` | `2.28.1` | Control | canonical Firestore repository/transaction |
| `authlib` | `1.7.2` | Control | Google OIDC authorization-code flow, state/nonce/PKCE |
| `httpx` | `0.28.1` | Control · Source · Intelligence | async HTTP (OIDC, GitHub, deps.dev, KIPRIS, RAG) |
| `itsdangerous` | `2.2.0` | Control | signed session/cursor |
| `google-api-python-client` | `>=2.180,<3.0` → 2.198.0 | Source | Google Drive API v3 |
| `google-auth` | `>=2.40,<3.0` → 2.56.3 | Source · Intelligence | OAuth credential, ADC |
| `PyJWT[crypto]` | `2.10.1` | Source | GitHub App JWT (RS256) |
| `defusedxml` | `0.7.1` | Intelligence | KIPRIS XML 파싱 (엔티티 확장 공격 방어) |
| `PyYAML` | `6.0.3` | Intelligence | RAG corpus 매니페스트 (`safe_load` 전용) |
| `google-genai` | `2.17.0` | Intelligence | Gemini 구조화 출력 |
| `uvicorn[standard]` | `0.52.4` | Integration | ASGI 런타임 |
| `google-cloud-secret-manager` | `2.30.0` | Integration | provider 자격증명 보관 |
| `google-cloud-tasks` | `2.24.0` | Integration | 분석 작업 큐 |
| `google-cloud-storage` | `3.13.1` | Integration | 로컬 스냅샷 staging |

전이 의존성 중 눈여겨볼 것: `starlette 1.6.0` (fastapi 가 선택), `grpcio 1.83.0`
(CPython 3.14 Windows wheel `cp314` 확인), `cryptography 50.0.0`, `protobuf 7.35.1`.

### Dev

| 패키지 | 버전 | 용도 |
|---|---|---|
| `pytest` | `9.1.1` | 전체 Python 테스트 |
| `httpx2` | `2.10.0` | Starlette `TestClient` transport. `httpx` 와 역할이 달라 공존한다 |
| `pytest-asyncio` | `1.4.0` | Intelligence 의 async provider 테스트. `asyncio_mode = "strict"` |

### 채택하지 않은 것

| 패키지 | 사유 |
|---|---|
| `google-cloud-aiplatform` | RAG Engine SDK. 설치 용량 100MB 초과인데 쓰는 기능은 `retrieveContexts` 하나뿐이다. `google-auth` 로 토큰만 얻고 REST 를 httpx 로 호출한다 |
| `requests` | `httpx` 와 역할이 겹친다. 하나만 쓴다 |


---

## 3. Node — 확정 목록

### `frontend`

| 패키지 | 버전 |
|---|---|
| `react`, `react-dom` | `19.2.8` |
| `react-router-dom` | `7.18.2` |
| `vite` | `8.2.1` |
| `@vitejs/plugin-react` | `6.0.5` |
| `vitest` | `4.1.10` |
| `jsdom` | `30.0.1` |
| `@testing-library/react` · `dom` · `user-event` · `jest-dom` | `16.3.2` · `10.4.1` · `14.6.4` · `7.0.1` |
| `@types/react` · `@types/react-dom` · `@types/node` | `19.2.18` · `19.2.4` · `26.2.0` |
| `typescript` | `5.9.3` |

### `apps/desktop`

| 패키지 | 버전 |
|---|---|
| `chokidar` | `^5.0.0` |
| `electron` | `^43.4.0` |
| `@types/node` | `^24.0.0` |
| `typescript` | `5.9.3` |

---

## 4. 통합 시 해결한 충돌

### 4.1 FastAPI — `0.141.1` vs `0.121.2` 🔴 해결

Control 은 `0.141.1`, Source 는 `0.121.2` 를 각자 검증했다. 두 Plane 의 라우터가 하나의 앱에
등록되므로 하나만 설치된다.

**결정: `0.141.1` 채택.** 상위 버전이고 Control 쪽 검증 범위가 훨씬 넓다.
`0.141.1` 환경에서 **Source 의 224건이 전부 통과**함을 실측으로 확인했다.
Starlette 은 `1.6.0` 이 동반된다.

### 4.2 `@types/node` — `26.2.0` vs `^24.0.0` ✅ 충돌 아님

패키지별로 다른 버전을 유지한다. 근거:

- pnpm workspace 는 패키지별 버전을 지원한다.
- `frontend/tsconfig.json` 이 `types: ["vite/client", "vitest/globals", "node"]` 로 제한하고,
  `frontend/src` 에는 `node:` import 가 테스트 2개 파일 외에 없다.
- npm dist-tag 기준 `ts5.9 → 26.2.0` 이라 TypeScript 5.9.3 에는 26.2.0 이 정본이다.
- `apps/desktop` 은 `node:fs/path/os/crypto` 를 무겁게 쓰므로 런타임 24.19.0 과 맞춘 24.x 가 옳다.

### 4.3 `pytest-asyncio` 도입 🟡 영향 없음 확인

Intelligence 는 `1.4.0` strict 모드를 요구하고, Control·Source 는 불필요하다고 기록했다.
strict 모드에서 marker 없는 async 테스트가 조용히 skip 되는 위험이 있어 실측했다.

- Control·Source 의 `async def test_` **0건** — 영향 없음
- 플러그인 유/무 모두 Control `259 passed` 동일

`live` marker 는 `pyproject.toml` 의 `markers` 에 등록했다. root `addopts` 에
`--strict-markers` 가 있어 등록하지 않으면 `-m live` 실행이 실패한다.

### 4.4 Python 버전 문서 불일치 🔴 해결

`pyproject.toml`(3.14) / `README`(3.14.7) / `ENVIRONMENT_SETUP`(3.12.13) /
Intelligence 개발 환경(3.13) 이 서로 달랐다. **3.14.7 로 통일**하고 문서를 수정했으며,
Intelligence 의 58건을 3.14.7 에서 재검증해 전부 통과함을 확인했다.

### 4.5 `pnpm-lock.yaml` 🔴 재생성 완료

Control 이 frontend 의존성 14개를 `package.json` 에 추가했으나 lockfile 은 Integration
소유라 건드리지 않았다. 그 결과 `pnpm install --frozen-lockfile` 이 실패했다.
통합 시 `pnpm install` 로 재생성했고 현재는 `--frozen-lockfile` 이 통과한다.

### 4.6 프론트엔드 툴체인 🔴 해결

Control 은 vitest + `moduleResolution: Bundler` + `noEmit`, Source 는 `node --test` +
`NodeNext` + emit 을 썼다. 병합 충돌 4건이 전부 여기서 나왔다.

**결정: Control 기준 채택.** `/api` → `127.0.0.1:8000` proxy 가 백엔드 연동에 필수이고,
Control 이 라우터·Testing Library·jsdom 하네스를 모두 보유한다. Source 의 테스트 2개 파일
8건은 vitest 로 포팅했다 (`// @vitest-environment node` 도크블록 필수 — 자세한 이유는
[INTEGRATION.md](INTEGRATION.md) 참조). `apps/desktop` 은 `node --test` 를 유지한다.

---

## 5. 환경 변수

값은 어디에도 기록하지 않는다. 각 Plane 은 환경변수를 직접 읽지 않고
`composition/settings.py` 가 유일하게 읽어 생성자 인자로 주입한다.
예외는 Intelligence 의 `IntelligenceConfig.from_env(env)` 와
Electron main 의 `process.env.IPRISK_SERVER_BASE_URL` 이다.

| 변수 | 사용처 | 없으면 |
|---|---|---|
| `SESSION_SECRET` | Control 세션·cursor 서명 (최소 32자) | 프로세스마다 임시 생성 — 재시작 시 세션 무효 |
| `APP_PUBLIC_BASE_URL` | 로그인 후 이동, exact CORS origin, 쿠키 `https_only` 판정 | `http://127.0.0.1:8000` |
| `GOOGLE_LOGIN_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` | Google OIDC | 로그인 경로가 502 로 fail closed |
| `GCP_PROJECT_ID` + `FIRESTORE_DATABASE` | Firestore 저장소·Secret Manager vault·OAuth state·change relay·provider binding | 전부 in-memory 로 하강 |
| `CLOUD_TASKS_LOCATION` · `_QUEUE` · `ANALYSIS_WORKER_URL` · `CLOUD_TASKS_SERVICE_ACCOUNT` | Cloud Tasks. **넷을 모두 채워야 붙는다** | in-memory 큐 — 별도 워커가 작업을 받지 못한다 |
| `FIRESTORE_EMULATOR_HOST` | emulator 테스트 전용 | 해당 테스트 1건 skip. **production 에 설정 금지** |
| `GOOGLE_DRIVE_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` | Drive OAuth | Drive 라우터를 마운트하지 않음 |
| `GOOGLE_DRIVE_WEBHOOK_BASE_URL`, `DRIVE_WATCH_CHANNEL_TOKEN` | Drive push notification | 〃 |
| `GITHUB_APP_ID`, `GITHUB_APP_SLUG` | GitHub App 설치 흐름 | GitHub 라우터를 마운트하지 않음 |
| `GITHUB_APP_CALLBACK_URL` | GitHub 설치 콜백 | 〃 |
| `GITHUB_APP_PRIVATE_KEY` | GitHub App 인증 (PEM 전문) | mounts 라우터 미마운트 |
| `GITHUB_WEBHOOK_SECRET` | webhook HMAC 검증 | **webhook 라우터를 아예 붙이지 않는다** — 검증 없이 받으면 위조를 신뢰하게 된다 |
| `GITHUB_APP_PRIVATE_KEY_SECRET_ID`, `GITHUB_WEBHOOK_SECRET_ID` | 위 두 값의 Secret Manager 참조 ID | — |
| `LOCAL_STAGING_BUCKET` | 로컬 스냅샷 staging | in-memory staging |
| `IPRISK_SERVER_BASE_URL` | Electron 이 서버를 찾는 주소 | 데스크톱이 서버에 붙지 못함 |
| `GEMINI_MODEL_ID` | 모델 식별자. 결과의 `versions.model_id` 에 기록 | **분석 경로 전체 비활성화** |
| `GEMINI_API_KEY` | AI Studio 사용 시 | Gemini 호출 불가 |
| `VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG` | Vertex 사용 시 | — |
| `KIPRIS_ACCESS_KEY` | 특허 검색 | 특허 경로만 비활성화 |
| `KIPRIS_API_KEY_SECRET_ID` | Secret Manager 참조 ID. Integration 이 읽어 `KIPRIS_ACCESS_KEY` 로 주입 | — |
| `RAG_REGION`, `RAG_CORPUS_ID` | RAG Engine | RAG 검색 비활성화 (정책 판정은 동작) |
| `RAG_CORPUS_VERSION` | 결과에 기록 | `unversioned` |
| `RAG_DISTANCE_THRESHOLD` | 관련도 거리 임계값. 이보다 먼 조각은 근거로 쓰지 않는다 | 기본 `0.6`. 끄려면 `none` 명시 |
| `PACKAGE_METADATA_BASE_URL` | 패키지 메타데이터 기본 URL 재정의 | 기본값 사용 |

> **`GEMINI_MODEL_ID` 값 미확정.** Master Spec 16/35 와 Blueprint 35 의 "Gemini 3.6 Flash"
> 는 실재하지 않는 식별자다. 검증에는 `gemini-3-flash-preview` 를 썼다. 배포 전에 값을
> 정해야 하며, 재현성 기록에 남으므로 임의로 바꾸면 과거 판정을 설명할 수 없게 된다.

---

## 6. 각 Plane 의 선택 근거 (원 기록 요약)

**Control** — package 가 처음 필요한 Phase 에서 최신 안정 release 를 검토하고 Python/Node
기준 버전과 기존 Pydantic/pytest/TypeScript, 직접 및 전체 회귀 테스트로 호환성을 확인했다.
Uvicorn 은 직접 import 하지 않으므로 Integration 이 선택하도록 남겼다.

**Source** — `google-api-python-client`/`google-auth` 는 팀 공개 저장소
`2HyN/ip-risk-agent` 에서 검증된 버전대를 채택했다. `httpx` 기반 GitHub 클라이언트는
`dsdr-re/AI_develop_5` 의 운영 검증 패턴을 참고했다. 재시도·연결배선 구현에는 신규
dependency 가 필요하지 않았다.

**Intelligence** — 의존성 수만큼 조회를 반복하므로 진짜 async 와 연결 재사용이 필요해
`httpx` 를 골랐다. KIPRIS 는 외부 XML 이라 표준 `xml.etree` 대신 `defusedxml` 을 쓴다.
corpus 매니페스트는 명세가 YAML 이라 `PyYAML` 을 도입하고 `safe_load` 만 사용한다.

### 설치 중 알려진 현상

`cryptography` 설치가 `Operation cancelled by user` 로 중단되는 경우가 있었다.
패키지 문제가 아니라 터미널 조작 중 취소된 것으로, 같은 명령을 재실행하면 정상 완료된다.

---

## 7. 재현

```bash
py -3.14 -m venv .venv
source .venv/Scripts/activate          # PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pip check

pnpm install --frozen-lockfile
```

자세한 절차와 검증 명령은 [DEVELOPMENT.md](DEVELOPMENT.md) 를 따른다.
