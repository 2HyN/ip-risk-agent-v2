# Development

환경 구축부터 실행·테스트까지의 절차다. 병렬 개발 시기의 `ENVIRONMENT_SETUP.md` 와
`LOCAL_RUN_AND_TEST_GUIDE.md` 를 통합했고, 통합 완료 상태를 기준으로 갱신했다.

---

## 1. 저장소 구조

```
shared/contracts/
  python/iprisk_contracts   Pydantic v2 canonical Contract v1  (source of truth)
  schemas/                  결정론적으로 생성되는 JSON Schema
  typescript/               workspace package @iprisk/contracts
  fixtures/  tests/         synthetic fixture 와 frozen contract test
backend/src/ip_risk_agent/
  core/ application/ persistence/  api/      Control Plane
  connectors/                                Source Plane
  intelligence/                              Risk Intelligence Plane
  composition/  main.py  worker.py           Integration
frontend/                   React + Vite Web UI
apps/desktop/               Electron Desktop
rag-corpus/                 RAG 참조 지식
tests/{control,connectors,intelligence,integration,e2e}
deploy/                     배포 설정 (미작성)
docs/                       이 문서들
```

### Ownership

| 영역 | 소유 |
|---|---|
| `core`, `application`, `persistence/core_firestore`, control `api`, `frontend/src/{app,auth,workspace,risk,history,security,shared}`, `tests/control` | Platform & Control |
| `connectors`, `api/sources`, `frontend/src/sources`, `apps/desktop`, `tests/connectors` | Source Integration & Desktop |
| `intelligence`, `rag-corpus`, `tests/intelligence` | Risk Intelligence & RAG |
| `shared/contracts`, `composition`, `main.py`, `worker.py`, root manifest/lockfile, `scripts`, `deploy`, `tests/{integration,e2e}` | Integration |

`shared/contracts/**` 의 Contract v1 은 **Frozen** 이다. 변경이 필요하면 코드를 고치지 말고
`contract-change-requests/` 에 요청한다.

---

## 2. 툴체인

| 항목 | 버전 |
|---|---|
| CPython | 3.14.7 |
| Node.js | 24.19.0 |
| pnpm | 11.19.0 |
| TypeScript | 5.9.3 |

버전 목록 전체는 [DEPENDENCIES.md](DEPENDENCIES.md) 참조.

### Bootstrap

Git Bash:

```bash
py -3.14 -m venv .venv
source .venv/Scripts/activate
python -m pip install -e ".[dev]"
pnpm install --frozen-lockfile
```

PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pnpm install --frozen-lockfile
```

확인:

```bash
python --version          # Python 3.14.7
node --version            # v24.19.0
pnpm --version            # 11.19.0
python -m pip check       # No broken requirements found.
```

> `.venv`, `node_modules`, `.pnpm-store`, `dist` 는 공유하지 않는다.
> 각 PC 에서 manifest/lockfile 로 재생성한다.

---

## 3. 실행

```bash
cp .env.example .env       # 값을 채운다. 실제 secret 은 저장소에 넣지 않는다
```

### API

```bash
uvicorn ip_risk_agent.main:app --host 127.0.0.1 --port 8000
```

### 분석 워커

```bash
uvicorn ip_risk_agent.worker:app --host 127.0.0.1 --port 8001
```

### Web UI

```bash
pnpm --filter @iprisk/frontend run dev
```

Vite dev server 가 `/api` 를 `http://127.0.0.1:8000` 으로 proxy 한다.
production bundle 은 same-origin `/api/v1` 을 쓴다.

### Electron Desktop

```bash
pnpm --filter @iprisk/desktop run build
pnpm --filter @iprisk/desktop run start
```

### 자격증명 없이 실행할 때의 경계

GCP 자원이나 provider 자격증명이 없어도 앱은 뜬다. 무엇이 실제로 연결됐는지는
`/health` 가 알려준다.

| 없는 것 | 동작 |
|---|---|
| `GCP_PROJECT_ID` + `FIRESTORE_DATABASE` | in-memory 저장소. **프로세스 재시작 시 데이터 소멸** |
| Google OIDC 자격증명 | 로그인 경로가 502 로 fail closed. 우회 로그인은 없다 |
| Drive/GitHub 자격증명 | 해당 provider 라우터를 아예 마운트하지 않는다 |
| `GEMINI_MODEL_ID` | 분석 경로 비활성화 (`intelligence: "disabled"`) |

---

## 4. 검증

### 정식 순서

`verify:resolution` 은 반드시 `build` **이후**에 실행한다. contracts `dist` 가 없으면
`Cannot find module '@iprisk/contracts/dist/index.js'` 로 실패한다.

```bash
pnpm install --frozen-lockfile
pnpm run generate                    # 계약 재생성
pnpm run typecheck
pnpm run build
pnpm run verify:resolution
pytest
python -m compileall -q backend/src shared/contracts/python scripts
python -m pip check
pnpm --filter @iprisk/frontend test
pnpm --filter @iprisk/desktop test
```

Windows 에서 contract test 를 돌릴 때는 `PNPM_EXECUTABLE` 에 `pnpm.cmd` 경로를 지정한다.

```bash
export PNPM_EXECUTABLE="$(which pnpm.cmd)"      # PowerShell: $env:PNPM_EXECUTABLE = (Get-Command pnpm.cmd).Source
```

### 기대 결과

| 명령 | 결과 |
|---|---|
| `pytest` | `593 passed, 7 skipped` |
| `pnpm --filter @iprisk/frontend test` | `23 passed (6 files)` |
| `pnpm --filter @iprisk/desktop test` | `65 tests — 63 pass, 2 skipped` |
| 나머지 | exit code 0 |

skip 사유가 이 7 + 2건과 다르면 원인을 확인한다.

- Firestore emulator 미설정 1건
- provider 자격증명 없음 6건 (KIPRIS 4, Gemini 2)
- symlink 생성 권한 없음 2건 (Windows 관리자 권한 필요)

### 부분 실행

```bash
pytest shared/contracts/tests          # Frozen Contract 27
pytest tests/control                   # Control 259
pytest tests/connectors                # Source 224
pytest tests/intelligence -m "not live"  # Intelligence 58
pytest tests/integration               # Integration 21
```

---

## 5. 시나리오별 검증

무엇이 깨졌는지 좁힐 때 쓴다.

### A. Control 파이프라인과 동시성

```bash
pytest tests/control/test_phase12_stress_and_e2e.py -q
```

- 동일 SourceChange 32개 동시 전달에서 canonical ChangeEvent/Artifact/AnalysisJob 이 하나만 생성
- AnalysisJob 32개 동시 claim 에서 하나만 RUNNING 획득
- 동일 AnalysisResult 32개 동시 전달에서 하나만 ACCEPTED, 나머지 DUPLICATE
- 동일 review version 32개 동시 변경 시 하나만 적용되고 RiskEvent 도 하나만 추가
- SourceChange → Gate → 승인 Artifact → Result → Risk → human review 전 흐름 완주

### B. 역할과 API/UI 권한 일치

```bash
pytest tests/control/test_authorization.py tests/control/test_phase12_permission_matrix.py -q
pnpm --filter @iprisk/frontend test
```

- `VIEWER` 는 조회만, review/admin/audit 거부
- `RISK_REVIEWER` 는 risk review 가능, member/security/audit 관리 거부
- `SOURCE_MANAGER` 는 본인 source 관리까지, owner admin 없음
- `OWNER` 만 member 관리·security 변경·audit/export
- 권한 없는 audit URL 직접 접근은 backend 요청 없이 dashboard 로 되돌림
- frontend 가 숨기는 action 과 backend 403 판정이 같은 역할 표를 따름

### C. 로그 deny-list 와 safe error

```bash
pytest tests/control/test_phase12_observability.py -q
```

- correlation ID(request/event/job/workspace/mount/artifact)가 구조화 record 에 남음
- source full text·Evidence 전체·token·절대경로·full prompt·raw model response 는 기록 안 됨
- 사용자 응답에는 safe code/message 만, 내부 로그에는 category·diagnostic code·exception type 만
- 허용 안 된 Host/CORS origin 거부, rate limit 은 429 + `Retry-After`
- 유효한 `X-Request-ID` 는 반영, path/content 형태 값은 새 opaque ID 로 교체

### D. Control API 기능 회귀

```bash
pytest tests/control/test_control_api.py -q
```

로그인 session/CSRF, workspace/invitation, dashboard, risk/review/timeline,
history/audit export, security/data access, notification, signed cursor, safe provider error.
fake Google identity 를 쓰며 외부 네트워크를 호출하지 않는다.

### E. Source 보안 경계

```bash
pytest tests/connectors -q
```

Drive OAuth state mismatch 거부, GitHub webhook HMAC 검증, 미선택 repo/branch 무시,
Local root escape 거부, renderer 임의 fs 호출 차단, staging cleanup, fingerprint 안정성.

### F. Intelligence 근거 무결성

```bash
pytest tests/intelligence -m "not live" -q
```

라이선스 파서·SPDX·정책·provider 실패·환각 인용, 특허 0건과 실패 구분·중복 제거·순위·
근거 검증·우선순위, RAG 버전·검색·매니페스트·적재·경로 이탈 방지.

### G. Integration 경계

```bash
pytest tests/integration -q
```

무인증 Source 접근 거부, VWS 멤버십 없는 Mount 등록 거부, 실패를 성공으로 위장하지 않음,
같은 변경이 하나의 `ChangeEvent` 로 수렴, Electron 이벤트가 Control 까지 도달.

### H. 실제 provider 호출 (선택)

```bash
export GEMINI_MODEL_ID=... GEMINI_API_KEY=... KIPRIS_ACCESS_KEY=...
pytest tests/intelligence -m live -q
```

deps.dev·PyPI·npm 은 자격증명 없이도 통과한다. KIPRIS·Gemini 는 키가 없으면 skip 된다.

### I. Firestore emulator (선택)

emulator 를 별도 터미널에서 시작한 뒤:

```bash
export FIRESTORE_EMULATOR_HOST="127.0.0.1:8080"
pytest tests/control/test_firestore_emulator.py -q
```

무작위 project/user ID 와 anonymous credential 을 쓰고 생성한 document 를 종료 전에 삭제한다.
**production credential 을 설정하지 않는다.**

---

## 6. Frozen 계약 결정성

Pydantic model 이 source of truth 다. 생성 대상은 JSON Schema 4종과
`shared/contracts/typescript/generated/contracts.ts` 다.

```bash
pnpm run generate
git diff --exit-code -- shared/contracts/schemas shared/contracts/typescript/generated
```

출력이 없고 exit code 가 0 이어야 한다. diff 가 있으면 generated file 을 손으로 고치지 말고
Pydantic source 변경 여부와 Python/pnpm 실행 버전을 먼저 확인한다.

> Windows `core.autocrlf=true` 때문에 생성물이 CRLF 로 기록되어 modified 로 보이던 문제는
> `.gitattributes` 로 해결했다. 내용 diff 는 0 이었다.

---

## 7. 문제 판정

| 증상 | 판정 |
|---|---|
| emulator 1건만 skip | 정상. 시나리오 I 를 실행하지 않은 상태 |
| `live` 6건 skip | 정상. provider 자격증명 미설정 |
| symlink 2건 skip | 정상. Windows 관리자 권한 없음 |
| `verify:resolution` 이 `Cannot find module` 로 실패 | `pnpm run build` 를 먼저 실행 |
| `--frozen-lockfile` 실패 | `package.json` 과 lockfile 불일치. `pnpm install` 로 재생성 후 커밋 |
| Vite 만 띄웠을 때 `/api` 실패 | API 서버(`uvicorn ip_risk_agent.main:app`)를 함께 띄운다 |
| 로그인이 502 | Google OIDC 자격증명 미설정. 의도된 fail closed 다 |
| generated contract diff 발생 | 진행 중단. 생성 환경과 source diff 확인 |

---

## 8. 커밋 전 체크리스트

- [ ] Python/Node/pnpm 버전이 2절과 일치한다
- [ ] `pytest` 결과가 기대 skip 건수와 같다
- [ ] frontend 23건, desktop 65건이 통과한다
- [ ] contract 재생성 후 tracked diff 가 없다
- [ ] 로그·응답·문서에 실제 credential, source content, 절대경로가 없다
- [ ] 자신의 ownership 밖 파일을 수정하지 않았다
- [ ] `shared/contracts/**` 를 수정하지 않았다
