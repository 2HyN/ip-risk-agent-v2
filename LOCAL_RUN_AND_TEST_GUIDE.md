# Phase 13 전 로컬 실행 및 테스트 가이드

> 이 파일은 개발자 로컬 검증을 위한 임시 문서다. Phase 13 인계 문서의 정식 구성요소가 아니며, 검증을 마친 뒤 삭제해도 프로젝트 코드·계약·빌드 완결성에 영향이 없다.

## 1. 현재 로컬 실행 경계

이 브랜치에서 Agent 1의 Control Plane은 fake/in-memory port, FastAPI `TestClient`, React/Vitest 및 production build로 독립 실행 검증할 수 있다. 최종 ASGI app인 `backend/src/ip_risk_agent/main.py`와 실제 Google OIDC, Agent 2 Source adapter, Agent 3 Analyzer, Cloud Tasks wiring은 Integration 소유이므로 이 브랜치만으로 실제 provider를 연결한 제품 서버를 실행하지 않는다.

따라서 Phase 13 전 로컬 승인 기준은 다음 세 가지다.

1. Python 3.14.7에서 계약·Control test와 compile이 통과한다.
2. Node.js 24.19.0/pnpm 11.19.0에서 frontend test, typecheck와 production build가 통과한다.
3. 공식 계약 생성 후 Frozen generated file에 tracked diff가 없다.

## 2. Windows PowerShell 환경 준비

프로젝트 루트에서 실행한다.

```powershell
py -V:3.14.7 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
node --version
pnpm --version
```

예상 버전:

```text
Python 3.14.7
Node.js v24.19.0
pnpm 11.19.0
```

Python 기본 package와 Agent 1이 검증한 runtime/test package를 설치한다. 실제 secret이나 production credential은 필요하지 않다.

```powershell
python -m pip install -e ".[dev]"
python -m pip install google-cloud-firestore==2.28.1 fastapi==0.141.1 authlib==1.7.2 httpx==0.28.1 itsdangerous==2.2.0 httpx2==2.10.0
python -m pip check
```

Agent 1 frontend manifest는 Integration 소유 root lockfile에 아직 병합되지 않았다. 이 브랜치의 로컬 검증에서는 root lockfile을 수정하지 않는 아래 명령을 사용한다.

```powershell
pnpm install --filter @iprisk/frontend --lockfile=false
$env:PNPM_EXECUTABLE = (Get-Command pnpm.cmd).Source
```

## 3. 빠른 승인 테스트

```powershell
python -m pytest shared/contracts/tests tests/control -q
pnpm --filter @iprisk/frontend test
pnpm run typecheck
pnpm run build
pnpm run verify:resolution
python -m compileall backend/src shared/contracts/python scripts
python -m pip check
```

Phase 12 완료 시점 기준 예상 결과:

- Python: `282 passed, 1 skipped`
- skip 1건: `FIRESTORE_EMULATOR_HOST`가 없을 때의 실제 emulator transaction test
- Frontend: `15 passed`
- typecheck, build, resolution, compileall, pip check: exit code 0

## 4. 테스트 시나리오

### 시나리오 A — 전체 in-memory Control pipeline과 동시성

```powershell
python -m pytest tests/control/test_phase12_stress_and_e2e.py -q
```

검증 내용:

- 동일 SourceChange 32개 동시 전달에서 canonical ChangeEvent/Artifact/AnalysisJob이 하나만 생성된다.
- AnalysisJob 32개 동시 claim에서 하나만 RUNNING 전환을 획득한다.
- 동일 AnalysisResult 32개 동시 전달에서 하나만 ACCEPTED이고 나머지는 DUPLICATE다.
- 동일 review version으로 32개 동시 변경 시 하나만 적용되고 RiskEvent도 하나만 추가된다.
- SourceChange → Security Gate → 승인 AnalysisArtifact → AnalysisResult → Risk → human review 흐름이 fake port만으로 끝까지 실행된다.

### 시나리오 B — 역할 및 API/UI 권한 일치

```powershell
python -m pytest tests/control/test_authorization.py tests/control/test_phase12_permission_matrix.py -q
pnpm --filter @iprisk/frontend test -- workspace-capabilities.test.ts control-plane-app.test.tsx
```

확인 사항:

- VIEWER는 조회만 가능하고 review/admin/audit action은 거부된다.
- RISK_REVIEWER는 risk review가 가능하지만 member/security/audit 관리는 거부된다.
- SOURCE_MANAGER는 review와 본인 source 관리 권한을 가지지만 owner admin 권한은 없다.
- OWNER만 member 관리, security 변경, audit/export를 수행한다.
- 권한 없는 direct audit URL은 workspace dashboard로 되돌아가며 backend 요청을 보내지 않는다.
- frontend에서 숨기거나 비활성화한 action과 backend의 최종 403 판정이 같은 역할 표를 따른다.

### 시나리오 C — 로그 deny-list와 safe error

```powershell
python -m pytest tests/control/test_phase12_observability.py -q
```

확인 사항:

- request/event/job/workspace/mount/artifact correlation ID가 구조화 record에 남는다.
- source full text, Evidence 전체, token, Windows/Unix absolute path, full prompt와 raw model response는 기록되지 않는다.
- 사용자 응답에는 safe code/message만 포함되고 내부 로그에는 분류 category, diagnostic code와 exception type만 남는다.
- 허용하지 않은 Host/CORS origin은 거부되고, 구성한 local rate limit은 429와 `Retry-After`를 반환한다.
- 유효한 `X-Request-ID`는 응답에 반영되지만 path/content 형태의 값은 새 opaque ID로 교체된다.

### 시나리오 D — Control API 기능 회귀

```powershell
python -m pytest tests/control/test_control_api.py -q
```

로그인 session/CSRF, workspace/invitation, dashboard, risk/review/timeline, history/audit export, security/data access, notification, signed cursor 및 safe provider error를 검증한다. 테스트는 fake Google identity를 사용하며 외부 네트워크를 호출하지 않는다.

### 시나리오 E — Frontend pagination과 제품 경계

```powershell
pnpm --filter @iprisk/frontend test
pnpm --filter @iprisk/frontend build
```

확인 사항:

- signed `next_cursor`가 변경 없이 다음 요청에 전달되고 페이지 항목이 누적된다.
- 현재 사용자 membership은 전체 member list 첫 페이지에 의존하지 않고 전용 endpoint로 조회한다.
- Agent 2 source panel slot은 유지되고 Control UI가 raw source preview를 만들지 않는다.
- `Open Original`은 opaque callback만 호출하며 callback 미주입 시 fail closed한다.
- Web production bundle이 생성된다.

### 시나리오 F — Firestore emulator 선택 검증

Firestore emulator가 이미 설치된 경우 별도 터미널에서 emulator를 시작한 뒤 실행한다.

```powershell
$env:FIRESTORE_EMULATOR_HOST = "127.0.0.1:8080"
python -m pytest tests/control/test_firestore_emulator.py -q
```

예상 결과는 `1 passed`다. 테스트는 무작위 project/user ID와 anonymous emulator credential을 사용하고 생성한 document를 종료 전에 삭제한다. production credential을 설정하지 않는다.

## 5. Frozen 계약 결정성 확인

공식 생성 명령만 사용한다.

```powershell
pnpm run generate
git diff --exit-code -- shared/contracts/schemas shared/contracts/typescript/generated/contracts.ts
```

두 번째 명령의 출력이 없고 exit code가 0이어야 한다. diff가 있으면 generated file을 수동 수정하지 말고 Pydantic source 변경 여부와 Python/pnpm 실행 버전을 먼저 확인한다.

## 6. 최종 수동 체크리스트

- [ ] Python/Node/pnpm 버전이 README와 일치한다.
- [ ] 전체 Python test가 통과하고 emulator 미사용 시 skip 사유가 정확히 1건이다.
- [ ] frontend 15개 test와 production build가 통과한다.
- [ ] contract 재생성 후 Frozen tracked diff가 없다.
- [ ] 로그/응답에 실제 credential, source content 또는 local absolute path를 입력하지 않았다.
- [ ] root `package.json`, `pnpm-lock.yaml`, `pyproject.toml`을 수정하지 않았다.
- [ ] 전체 검증 결과를 확인한 뒤에만 Phase 13을 요청한다.

## 7. 문제 발생 시 판정

- emulator 1건만 skip: 허용. 시나리오 F 실행 전까지 외부 환경 미설정 상태다.
- Google login/provider roundtrip 실패: 이 브랜치의 로컬 승인 대상이 아니다. Integration staging에서 검증한다.
- Vite만 실행했을 때 `/api` 연결 실패: 최종 ASGI composition이 없는 Agent 1 브랜치의 정상 경계다. UI 검증은 Vitest와 production build 결과를 사용한다.
- generated contract diff 발생: Phase 13 진행을 중단하고 생성 환경과 source diff를 확인한다.
- 그 외 test/typecheck/build 실패: Phase 13 진행을 중단하고 실패한 focused scenario부터 수정한다.
