# IP Risk Agent Environment Setup

## 1. Repository structure

이 저장소는 IP Risk Agent 병렬 개발의 공통 기준 환경이다.

- `shared/contracts/python/iprisk_contracts`: Pydantic v2 기반 canonical Contract v1
- `shared/contracts/schemas`: 결정론적으로 생성되는 JSON Schema
- `shared/contracts/typescript`: 실제 workspace package `@iprisk/contracts`
- `shared/contracts/fixtures`, `shared/contracts/tests`: synthetic fixture와 frozen contract test
- `backend/src/ip_risk_agent`: 세 Plane 및 Integration-only Python namespace skeleton
- `frontend`: Agent 1/2가 사용할 최소 TypeScript workspace
- `apps/desktop`: Agent 2가 사용할 최소 TypeScript desktop workspace
- `rag-corpus`: Agent 3 전용 영역
- `tests/{control,connectors,intelligence}`: Agent 1/2/3 전용 test 영역
- `tests/{integration,e2e}`, `deploy`: Integration-only 영역

## 2. Toolchain

검증 기준 버전은 Python 3.14.7, Node.js 24.19.0, pnpm 11.19.0, TypeScript 5.9.3, Pydantic 2.13.4, pytest 9.1.1이다. Python package는 `pyproject.toml`, JavaScript package는 pnpm workspace와 `pnpm-lock.yaml`로 관리한다.

Windows PowerShell 기준 bootstrap:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
pnpm install --frozen-lockfile
```

Node와 pnpm이 PATH에 없다면 Node.js 24와 pnpm 11.19를 설치하거나 동일 버전 executable 경로를 PATH에 추가한다.

## 3. Python shared contracts

Canonical package 위치는 `shared/contracts/python/iprisk_contracts`이며 editable install 후 다음처럼 import한다.

```python
from iprisk_contracts import (
    SourceAdapter,
    SourceChange,
    SourceSnapshot,
    AnalysisArtifact,
    AnalysisResult,
)
```

Import 확인:

```powershell
.\.venv\Scripts\python.exe -c "from iprisk_contracts import SourceAdapter, SourceChange, SourceSnapshot, AnalysisArtifact, AnalysisResult; print('OK')"
```

## 4. TypeScript contracts

Package 위치는 `shared/contracts/typescript`이고 workspace package 이름은 `@iprisk/contracts`다. frontend와 desktop은 상대경로가 아니라 다음 package import를 사용한다.

```ts
import type {
  SourceChange,
  SourceSnapshot,
  AnalysisArtifact,
  AnalysisResult,
} from "@iprisk/contracts";
```

실제 resolution 확인:

```powershell
pnpm run verify:resolution
```

## 5. Schema and TypeScript generation

Pydantic model이 source of truth다. 다음 명령은 네 JSON Schema와 `generated/contracts.ts`를 결정론적으로 다시 생성한다.

```powershell
.\.venv\Scripts\python.exe scripts/generate_contracts.py
```

생성 대상:

- `source-change.v1.json`
- `source-snapshot.v1.json`
- `analysis-artifact.v1.json`
- `analysis-result.v1.json`
- `shared/contracts/typescript/generated/contracts.ts`

## 6. Contract tests

```powershell
$env:PNPM_EXECUTABLE = (Get-Command pnpm).Source
.\.venv\Scripts\python.exe -m pytest
```

이 suite는 strict field validation, enum/version, timezone-aware datetime, content/credential extra rejection, recursive JSON metadata, Security Gate approval guard, status/coverage, Evidence reference, fixture round trip, deterministic generation, frontend/desktop package type resolution을 검사한다.

## 7. Frontend and desktop baseline

```powershell
pnpm run build
pnpm run typecheck
pnpm run verify:resolution
```

개별 명령:

```powershell
pnpm --filter @iprisk/contracts build
pnpm --filter @iprisk/frontend typecheck
pnpm --filter @iprisk/frontend build
pnpm --filter @iprisk/desktop typecheck
pnpm --filter @iprisk/desktop build
```

## 8. Backend baseline

```powershell
.\.venv\Scripts\python.exe -m compileall -q backend/src shared/contracts/python
.\.venv\Scripts\python.exe -c "import ip_risk_agent; import ip_risk_agent.main; import ip_risk_agent.worker; print('OK')"
```

## 9. Frozen Shared Contract

`shared/contracts/**`의 Contract v1은 병렬 Agent 시작 전에 Frozen 상태다. Agent 1/2/3은 이 영역을 직접 수정하지 않는다. 변경 필요성은 `contract-change-requests/`에 요청하고 Integration 단계에서 판단한다.

모든 최상위 data Contract는 `contract_version: "1"`, strict unknown-field rejection, timezone-aware datetime, JSON-safe metadata를 사용한다. Provider SDK object, credential/token/private key, Local absolute path 전용 field는 Contract에 허용하지 않는다.

## 10. Ownership boundaries

- Agent 1: `backend/src/ip_risk_agent/{core,application,persistence/core_firestore}`, control-owned `api` namespace, `frontend/src/{app,auth,workspace,risk,history,security,shared}`, `tests/control`
- Agent 2: `backend/src/ip_risk_agent/connectors`, `backend/src/ip_risk_agent/api/sources`, `frontend/src/sources`, `apps/desktop`, `tests/connectors`
- Agent 3: `backend/src/ip_risk_agent/intelligence`, `rag-corpus`, `tests/intelligence`
- Integration only: `shared/contracts`, `backend/src/ip_risk_agent/composition`, `main.py`, `worker.py`, root manifests/lockfiles, `scripts`, `deploy`, `tests/integration`, `tests/e2e`

## 11. Environment variables

`.env.example`은 값 없이 이름만 제공한다.

- App/Control: `GOOGLE_LOGIN_CLIENT_ID`, `GOOGLE_LOGIN_CLIENT_SECRET`, `GOOGLE_LOGIN_REDIRECT_URI`, `SESSION_SECRET`, `APP_PUBLIC_BASE_URL`, `FIRESTORE_DATABASE`
- Shared GCP: `GCP_PROJECT_ID`
- Drive: `GOOGLE_DRIVE_CLIENT_ID`, `GOOGLE_DRIVE_CLIENT_SECRET`, `GOOGLE_DRIVE_REDIRECT_URI`, `GOOGLE_DRIVE_WEBHOOK_BASE_URL`
- GitHub: `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_SECRET_ID`, `GITHUB_WEBHOOK_SECRET_ID`, `GITHUB_APP_CALLBACK_URL`
- Local staging: `LOCAL_STAGING_BUCKET`
- Intelligence: `VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG`, `GEMINI_MODEL_ID`, `KIPRIS_API_KEY_SECRET_ID`, `RAG_REGION`, `RAG_CORPUS_ID`, `RAG_MANAGED_DB_CONFIG`, `PACKAGE_METADATA_BASE_URL`

실제 secret은 `.env.example`, source, fixture, log에 기록하지 않는다.

## 12. Intentionally unimplemented

현재 skeleton에는 Google login/Firestore/Risk lifecycle/Security Gate business logic, Drive OAuth/Picker/watch, GitHub App/webhook, Electron watcher/staging, Gemini/KIPRIS/SPDX analyzer, RAG integration, product UI, Cloud Run/Tasks deployment가 구현되어 있지 않다. `main.py`, `worker.py`, `composition/**`도 import 가능한 placeholder뿐이다.

## 13. Required baseline before parallel development

아래 순서가 모두 성공한 뒤에만 Agent 1/2/3 개발을 시작한다.

```powershell
.\.venv\Scripts\python.exe scripts/generate_contracts.py
pnpm run build
pnpm run typecheck
pnpm run verify:resolution
$env:PNPM_EXECUTABLE = (Get-Command pnpm).Source
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall -q backend/src shared/contracts/python
.\.venv\Scripts\python.exe -c "from iprisk_contracts import SourceChange, SourceSnapshot, AnalysisArtifact, AnalysisResult; import ip_risk_agent.main; import ip_risk_agent.worker; print('BASELINE_OK')"
```
