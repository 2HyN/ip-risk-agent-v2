# IP Risk Agent

Secure Human-in-the-Loop IP Risk Management System for Local Directory, GitHub Repository, and Google Drive workspaces.

이 저장소는 하나의 공용 Git repository에서 개발축별 branch를 분리하여 병렬 개발한다. 모든 개발자는 동일한 `main` 기준점에서 자신의 branch를 시작하며, 각 개발축의 파일 ownership과 Frozen Shared Contract 경계를 유지한다.

## 1. 공통 개발 환경

프로젝트 개발자는 각자 자신의 PC에 아래 환경을 구성한다.

### 필수 버전

- **Python**: CPython `3.14.7` 고정
- **Python compatibility**: `>=3.14,<3.15`
- **Pydantic**: `2.13.4` 고정
- **pytest**: `9.1.1` 고정
- **Node.js**: `24.19.0`
- **pnpm**: `11.19.0`

Node.js 24.19.0은 아래 공식 다운로드 페이지에서 설치한다.

```text
https://nodejs.org/en/download
```

Node.js 설치 후 새 터미널을 열고 확인한다.

```bash
node --version
npm --version
```

`node --version` 결과가 다음이어야 한다.

```text
v24.19.0
```

pnpm을 설치한다.

```bash
npm install -g pnpm@11.19.0
```

확인:

```bash
pnpm --version
```

예상 결과:

```text
11.19.0
```

## 2. 저장소 문서

개발 전에 다음 6개 문서를 읽는다.

```text
IP_RISK_AGENT_MEETING_BLUEPRINT.md
CODING_AGENT_MASTER_SPEC.md
CODING_AGENT_SPEC_1_PLATFORM_CONTROL.md
CODING_AGENT_SPEC_2_SOURCE_DESKTOP.md
CODING_AGENT_SPEC_3_RISK_INTELLIGENCE_RAG.md
ENVIRONMENT_SETUP.md
```

문서 역할은 다음과 같다.

- `IP_RISK_AGENT_MEETING_BLUEPRINT.md`: 전체 제품/아키텍처/보안/개발축 청사진
- `CODING_AGENT_MASTER_SPEC.md`: 모든 개발축이 따라야 할 최상위 개발 규약
- `CODING_AGENT_SPEC_1_PLATFORM_CONTROL.md`: Agent 1 상세 구현 명세
- `CODING_AGENT_SPEC_2_SOURCE_DESKTOP.md`: Agent 2 상세 구현 명세
- `CODING_AGENT_SPEC_3_RISK_INTELLIGENCE_RAG.md`: Agent 3 상세 구현 명세
- `ENVIRONMENT_SETUP.md`: 공통 사전환경 구조와 실행/검증 방법

충돌 시 `CODING_AGENT_MASTER_SPEC.md`의 규칙을 우선한다.

## 3. Branch 구조

공용 저장소는 아래 branch 구조를 사용한다.

```text
main
├─ platform-control
├─ source-integration-desktop
├─ risk-intelligence-rag
└─ integration
```

### `main`

확정된 공통 기준점이다.

포함:

- 청사진 및 개발 명세
- 공통 개발 환경
- Frozen `shared/contracts/**`
- 초기 repository skeleton

병렬 개발 도중 각 Agent가 자신의 기능 구현을 직접 `main`에 push하지 않는다.

### `platform-control`

Platform & Control Plane 전용 branch.

주요 ownership:

```text
backend/src/ip_risk_agent/core/**
backend/src/ip_risk_agent/application/**
backend/src/ip_risk_agent/persistence/core_firestore/**
Agent 1 소유 API 영역
frontend/src/app/**
frontend/src/auth/**
frontend/src/workspace/**
frontend/src/risk/**
frontend/src/history/**
frontend/src/security/**
frontend/src/shared/**
tests/control/**
```

### `source-integration-desktop`

Source Integration & Desktop 전용 branch.

주요 ownership:

```text
backend/src/ip_risk_agent/connectors/**
Agent 2 소유 source API 영역
frontend/src/sources/**
apps/desktop/**
tests/connectors/**
```

### `risk-intelligence-rag`

Risk Intelligence & RAG 전용 branch.

주요 ownership:

```text
backend/src/ip_risk_agent/intelligence/**
rag-corpus/**
tests/intelligence/**
```

### `integration`

최종 통합 전용 branch.

주요 ownership:

```text
backend/src/ip_risk_agent/composition/**
backend/src/ip_risk_agent/main.py
backend/src/ip_risk_agent/worker.py
deploy/**
root dependency/toolchain/lock/config files
tests/integration/**
tests/e2e/**
```

## 4. 절대 개발 경계

### Frozen Shared Contracts

```text
shared/contracts/**
```

병렬 개발 중 Agent 1/2/3는 이 영역을 임의 수정하지 않는다.

Contract 변경이 필요하면 코드를 직접 고치지 말고 Master Spec의 contract-change request 규칙을 따른다.

### 다른 개발축 내부 구현 직접 import 금지

허용:

```text
Control      -> shared contracts
Source       -> shared contracts
Intelligence -> shared contracts
Integration  -> all public plane surfaces
```

금지:

```text
Control      -> connectors internals
Control      -> intelligence internals
Source       -> Control internals
Source       -> Intelligence internals
Intelligence -> Control internals
Intelligence -> connectors internals
```

## 5. 처음 저장소를 Clone한 뒤 환경 구성

각 개발자는 자신의 PC에서 공용 repository를 clone한다.

```bash
git clone <REMOTE_REPOSITORY_URL>
cd ip-risk-agent-v2
```

### Python 버전 확인

프로젝트 가상환경을 만들기 전에 Python 3.14.7이 설치되어 있는지 확인한다.

```bash
py -V:3.14.7 --version
```

설치되어 있지 않다면:

```bash
py install 3.14.7
```

### Python 가상환경

Git Bash:

```bash
py -V:3.14.7 -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

설치된 버전을 확인한다.

```bash
python --version
python -c "import pydantic; print(pydantic.__version__)"
pytest --version
```

다음 버전이어야 한다.

```text
Python 3.14.7
Pydantic 2.13.4
pytest 9.1.1
```

### Node / TypeScript dependency

Node.js 24.19.0과 pnpm 11.19.0을 설치한 뒤 프로젝트 root에서 실행한다.

```bash
pnpm install --frozen-lockfile
```

`.venv/`, `node_modules/`, `.pnpm-store/`, `dist/` 등은 Git으로 공유하지 않는다. 각 PC에서 위 manifest/lockfile을 기준으로 재생성한다.

## 6. 초기 환경 검증

프로젝트 root에서 실행한다.

```bash
pnpm run typecheck
pnpm run generate
pnpm run build
pnpm run verify:resolution
pytest
python -m compileall backend/src shared/contracts/python scripts
```

모든 명령이 성공한 상태에서 개발을 시작한다.

특히 `shared/contracts/typescript/dist`가 없는 clean 상태에서도 TypeScript typecheck가 성공해야 한다.

## 7. 각 개발자의 Branch 시작 방법

모든 개발자는 자신의 담당 branch만 checkout하여 작업한다.

### Agent 1

```bash
git fetch origin
git switch platform-control
git pull --ff-only origin platform-control
```

### Agent 2

```bash
git fetch origin
git switch source-integration-desktop
git pull --ff-only origin source-integration-desktop
```

### Agent 3

```bash
git fetch origin
git switch risk-intelligence-rag
git pull --ff-only origin risk-intelligence-rag
```

### Integration 담당

```bash
git fetch origin
git switch integration
git pull --ff-only origin integration
```

## 8. 일상 작업 흐름

작업 시작 전:

```bash
git status
git fetch origin
git pull --ff-only
```

구현 후 담당 테스트를 실행한다.

예:

```bash
pytest
pnpm run typecheck
```

변경 사항 확인:

```bash
git status
git diff
```

Commit:

```bash
git add <OWNED_FILES>
git commit -m "<type>: <summary>"
```

Push:

```bash
git push origin HEAD
```

각 개발자는 자신의 branch에만 push한다.

## 9. `main` 변경을 자신의 Branch에 반영

병렬 개발 중 공통 기준점에 필요한 수정이 `main`에 반영된 경우 자신의 branch에서 다음과 같이 동기화한다.

```bash
git fetch origin
git switch <YOUR_BRANCH>
git merge origin/main
```

충돌이 발생하면 자신의 ownership 범위와 Master Spec을 기준으로 해결한다.

Frozen Contract 또는 타 Agent 소유 영역에서 의미 있는 충돌이 발생했다면 임의로 해결하지 말고 팀에서 먼저 합의한다.

## 10. 개발 완료 시

각 Agent는 자신의 상세 개발 명세에 정의된 테스트와 Acceptance Criteria를 통과시킨다.

최종적으로 코드와 함께 해당 Agent 명세에서 요구하는 `AGENT_DELIVERY.md`를 작성한다.

Integration 단계에서는 세 Agent branch의 결과를 `integration` branch로 병합한 뒤 다음을 수행한다.

```text
SourceAdapter wiring
Analyzer Registry wiring
Control/Source/Intelligence composition
root dependency merge
Cloud worker/API composition
integration tests
e2e tests
```

통합 검증 완료 후에만 `main`으로 반영한다.

## 11. 중요 원칙

- 하나의 공용 repository를 사용한다.
- 개인별 별도 repository를 만들지 않는다.
- 모든 작업 branch는 동일한 `main` 기준점에서 시작한다.
- `.venv`, `node_modules`, `.pnpm-store`, `dist`는 공유하지 않는다.
- dependency와 환경은 manifest/lockfile/`ENVIRONMENT_SETUP.md`를 통해 재현한다.
- `shared/contracts/**`는 병렬 개발 동안 Frozen이다.
- 자신의 ownership 밖의 기능을 대신 구현하지 않는다.
- provider/system failure를 성공 또는 “Risk 없음”으로 변환하지 않는다.
- raw source/credential을 로그나 Shared Contract에 추가하지 않는다.
