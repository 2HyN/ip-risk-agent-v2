# IP Risk Agent

Local Directory, GitHub Repository, Google Drive 등 여러 실제 협업 Source Workspace 를
하나의 Risk Workspace 에 연결하고, 변경을 지속적으로 감지하여 Patent·License 중심의 잠재적
IP Risk 를 근거 기반으로 분석하고, 사용자가 장기적으로 검토·추적·감사할 수 있게 하는
**Secure Human-in-the-Loop AI Risk Management System**.

---

## 현재 상태

세 개발축의 병렬 개발과 통합이 끝났고 애플리케이션이 기동한다. GCP 자원 연동이 남았다.

| 항목 | 상태 |
|---|---|
| Platform & Control Plane | ✅ 완료 |
| Source Integration & Desktop Plane | ✅ 완료 |
| Risk Intelligence & RAG Plane | ✅ 완료 |
| branch 통합 · dependency 확정 | ✅ 완료 |
| 애플리케이션 배선 | ✅ 완료 |
| GCP 배포 | 🔴 미착수 |

**검증 — 656 tests / 654 passed / 9 skipped / 0 failed**
(Python 593, frontend 23, desktop 65 · skip 은 전부 환경 제약)

```bash
uvicorn ip_risk_agent.main:app       # API
uvicorn ip_risk_agent.worker:app     # 분석 워커
```

GCP 자원이나 provider 자격증명이 없어도 뜬다. 무엇이 실제로 연결됐는지는 `/health` 가 알려준다.

---

## 빠른 시작

```bash
py -3.14 -m venv .venv
source .venv/Scripts/activate        # PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pnpm install --frozen-lockfile
cp .env.example .env
```

검증:

```bash
pnpm run generate && pnpm run typecheck && pnpm run build && pnpm run verify:resolution
pytest
```

> `verify:resolution` 은 `build` **이후**에 실행한다. 자세한 절차와 문제 판정은
> [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) 를 따른다.

**기준 버전** — CPython 3.14.7 / Node.js 24.19.0 / pnpm 11.19.0 / TypeScript 5.9.3

---

## 문서

### 설계 (Frozen)

| 문서 | 내용 |
|---|---|
| [IP_RISK_AGENT_MEETING_BLUEPRINT.md](IP_RISK_AGENT_MEETING_BLUEPRINT.md) | 제품·아키텍처·보안·개발축 청사진 |
| [CODING_AGENT_MASTER_SPEC.md](CODING_AGENT_MASTER_SPEC.md) | 최상위 개발 규약. **충돌 시 이 문서를 우선한다** |
| [CODING_AGENT_SPEC_1_PLATFORM_CONTROL.md](CODING_AGENT_SPEC_1_PLATFORM_CONTROL.md) | Platform & Control Plane 상세 명세 |
| [CODING_AGENT_SPEC_2_SOURCE_DESKTOP.md](CODING_AGENT_SPEC_2_SOURCE_DESKTOP.md) | Source Integration & Desktop 상세 명세 |
| [CODING_AGENT_SPEC_3_RISK_INTELLIGENCE_RAG.md](CODING_AGENT_SPEC_3_RISK_INTELLIGENCE_RAG.md) | Risk Intelligence & RAG 상세 명세 |

### 현황·운영

| 문서 | 내용 |
|---|---|
| [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) | 세 Plane 구현 범위·검증 실적·알려진 제약 |
| [docs/INTEGRATION.md](docs/INTEGRATION.md) | 병합 기록, 조립 구조, authz 어댑터, 확장 지점, 계약 공백 |
| [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) | 확정 의존성, 해결한 충돌, 환경 변수 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 환경 구축, 실행, 검증, 시나리오별 테스트 |
| [docs/REPORT.md](docs/REPORT.md) | 2차 PBL 제출 보고서 작성 자료 (SECTION 00~17) |

---

## 구조

```
shared/contracts/     Frozen Contract v1 (Pydantic → JSON Schema → TypeScript)
backend/src/ip_risk_agent/
  core/ application/ persistence/ api/   Control Plane
  connectors/                            Source Plane
  intelligence/                          Risk Intelligence Plane
  composition/ main.py worker.py         Integration
frontend/             React + Vite Web UI
apps/desktop/         Electron Desktop
rag-corpus/           RAG 참조 지식
tests/{control,connectors,intelligence,integration,e2e}
deploy/               배포 설정 (미작성)
```

### 3-Plane 분리

```
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
                ▼                           ▼
   SOURCE INTEGRATION PLANE        RISK INTELLIGENCE PLANE
   ┌──────────────────────┐        ┌──────────────────────┐
   │ Drive / GitHub       │        │ Patent / License     │
   │ Local / Electron     │        │ Gemini / KIPRIS      │
   │ OAuth / Webhook      │        │ RAG Engine / SPDX    │
   │ Watch / Fetch        │        │ Evidence validation  │
   └──────────────────────┘        └──────────────────────┘
```

Source Plane 과 Intelligence Plane 사이에 **직접 호출 경로가 없다.**
모든 교차 통신은 Frozen Contract 와 Control Plane 을 경유한다.

### 처리 파이프라인 (Master Spec 21 — 고정)

```
Source event → SourceChange → Control persist + idempotency → Cloud Tasks
  → fetch_snapshot() → SourceSnapshot → SourceAccessEvent
  → Security Gate → AnalysisArtifact → Analyzer Registry
  → AnalysisResult → Control validates → Risk reconcile
  → Risk / RiskEvidence / RiskEvent → Notification / UI
```

---

## 개발 경계

### Frozen Shared Contract

`shared/contracts/**` 는 Frozen 이다. 변경이 필요하면 코드를 고치지 말고
`contract-change-requests/` 에 요청한다.

### Ownership

| 영역 | 소유 |
|---|---|
| `core`, `application`, `persistence/core_firestore`, control `api`, `frontend/src/{app,auth,workspace,risk,history,security,shared}`, `tests/control` | Platform & Control |
| `connectors`, `api/sources`, `frontend/src/sources`, `apps/desktop`, `tests/connectors` | Source Integration & Desktop |
| `intelligence`, `rag-corpus`, `tests/intelligence` | Risk Intelligence & RAG |
| `shared/contracts`, `composition`, `main.py`, `worker.py`, root manifest/lockfile, `scripts`, `deploy`, `tests/{integration,e2e}` | Integration |

### 의존성 규칙

```
허용:  Control / Source / Intelligence  ->  shared contracts
       Integration                      ->  all public plane surfaces
금지:  Plane 간 내부 구현 직접 import
```

---

## 지켜야 할 불변조건

| 불변조건 | 의미 |
|---|---|
| **Raw source 비영속** | `SourceSnapshot` 은 transient. 승인된 최소 Artifact 와 content-free 이벤트만 남긴다 |
| **Provider authority 이중 검증** | Control RBAC 통과가 provider 접근 권한을 뜻하지 않는다 |
| **Gate-only boundary** | Intelligence 는 Gate 가 승인한 artifact 뒤에서만 동작한다 |
| **Failure preserves risk** | 실패를 성공이나 "Risk 없음" 으로 바꾸지 않는다 |
| **Backend-authoritative RBAC** | 권한 판단은 항상 backend. UI 는 표시만 한다 |
| **Credential/raw 로그 금지** | raw source·credential 을 로그나 Contract 에 넣지 않는다 |

---

## Branch

```
main
├─ platform-control
├─ source-integration-desktop
├─ risk-intelligence-rag
└─ integration          ← 세 branch 병합 + 조립 완료
```

각 개발자는 자신의 branch 에만 push 한다. 통합 검증 완료 후에만 `main` 으로 반영한다.
