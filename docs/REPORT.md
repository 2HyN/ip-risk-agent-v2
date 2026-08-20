# 2차 PBL 제출 보고서 — 작성 자료

> **대상 양식**: `AJOU_PBL_2차_프로젝트_통합_제출양식_(배포).docx`
> (PROJECT BASED LEARNING 2차 Team 프로젝트 기획서 및 결과보고서 — 엔터프라이즈급 고도화 및 서비스 상용화 실증, SECTION 00~17)
> **성격**: 보고서 원고가 아니라, 각 SECTION 을 채우는 데 필요한 **확인된 사실 자료 + 미확보 항목 목록**.
> **기준**: branch `integration`. 세 Plane 병합과 애플리케이션 배선까지 완료한 상태.
> 모든 수치는 실제 실행 결과이며, 미확보 항목은 그렇다고 표시했다.

## 현재 상태 한눈에

| | 상태 |
|---|---|
| 세 Plane 구현 | ✅ 완료 |
| branch 통합 | ✅ 완료 (충돌 4건 해결) |
| dependency 확정 | ✅ 완료 (`pip check` 통과) |
| 애플리케이션 배선 | ✅ 완료 — `uvicorn ip_risk_agent.main:app` 로 기동 |
| 검증 | ✅ **656 tests / 654 passed / 9 skipped / 0 failed** |
| GCP 배포 | 🔴 미착수 — `deploy/` 비어 있음, 배포 URL 없음 |
| 사용자 테스트 | 🔴 미실시 |

---

## 0. 먼저 알아야 할 것 — 1차와 2차의 관계

| | 1차 (`ip-risk-agent`, v1) | 2차 (`ip-risk-agent-v2`) |
|---|---|---|
| 성격 | 단일 프로젝트 검사 MVP 프로토타입 | 엔터프라이즈 멀티테넌트 제품 |
| 소스 | 로컬 zip 업로드 중심 | Drive / GitHub / Local **3-provider 지속 감시** |
| 사용자 | 단일 사용자 | VWS + 멤버 + 4단계 Role |
| 아키텍처 | 단일 앱 | 3-Plane 분리 + Frozen Shared Contract 5종 |
| 보고서 | `docs/sections*.md` (SECTION 01~11) | 본 정보 팩 (SECTION 00~17) |

**2차 양식은 "엔터프라이즈급 고도화 및 서비스 상용화 실증"이 주제다.** 따라서 v1 → v2 전환 자체(단일 사용자 스캐너 → 멀티테넌트 보안 제품)가 SECTION 01.2(차별점), SECTION 10.1(주요 변경 결정), SECTION 15(고도화)의 핵심 소재가 된다.

⚠️ **가장 큰 리스크**: 2차 양식은 SECTION 11(클라우드 배포), 12(기능 검증·사용자 테스트), 13(품질 개선), 13.1/13.2(최종 화면·영상)를 요구하는데, **v2는 아직 통합조차 되지 않았고 배포 URL이 없으며 `deploy/`가 비어 있다.** 이 4개 SECTION은 통합·배포가 끝나야 채울 수 있다. §12에 대응 방안을 정리했다.

---

## SECTION 00 · 표지 / 작성 및 제출 안내

### 표지 항목

| 항목 | 확보된 값 | 상태 |
|---|---|---|
| 프로젝트명 | **IP Risk Agent** (제품 별칭: IP DeteDog — 1차 발표자료 기준) | 팀 확정 필요 |
| 팀명 | AI 부트캠프 **5조** | ✅ |
| 팀원 / 역할 | Agent 1 Platform&Control / Agent 2 Source&Desktop / Agent 3 Intelligence&RAG / Integration — **실명 매핑 필요** | 🔴 미확보 |
| 제출일 | — | 🔴 미확보 |
| GitHub 저장소 | `https://github.com/2HyN/ip-risk-agent-v2` | ✅ |
| 배포 서비스 | **미배포** | 🔴 미배포 사유 작성 필요 |

> 양식 SECTION 00 체크리스트: "구현하지 못한 기능은 삭제하지 말고 **미구현 사유와 다음 계획**을 적는다" — 미배포도 사유+계획으로 쓰면 감점 요소가 아니라 요구사항 충족이다.

---

## SECTION 01 · 프로젝트 개요

### 1.1 한 문장 서비스 소개 — 그대로 쓸 수 있는 원문

Blueprint §0 확정 문구:

> Local Directory, GitHub Repository, Google Drive 등 여러 실제 협업 Source Workspace를 하나의 Risk Workspace에 연결하고, 변경을 지속적으로 감지하여 Patent·License 중심의 잠재적 IP Risk를 근거 기반으로 분석하고, 사용자가 장기적으로 검토·추적·감사할 수 있게 하는 Secure Human-in-the-Loop AI Risk Management System.

### 요약 항목 표 채움 자료

| 요약 항목 | 확인된 내용 |
|---|---|
| **해결할 문제** | 협업 프로젝트의 IP Risk는 정적 검사 한 번으로 끝나지 않는다. ① 코드·문서가 지속 수정됨 ② dependency와 license가 변경됨 ③ 기술 아이디어가 문서화·구현되며 기존 patent와의 관련성이 달라짐 ④ 같은 Risk도 `신규 발견 → 검토 → 변화 → 해소 → 재발`을 겪음 ⑤ 원본 Source가 민감해 분석 편의보다 접근권한·최소수집·감사가능성이 중요 (Blueprint §1) |
| **핵심 사용자/고객** | Risk Workspace 멤버 4개 Role — `Viewer` / `Risk Reviewer` / `Source Manager` / `Workspace Owner` (Master Spec §24) |
| **사용할 공공·산업 데이터** | **KIPRIS**(한국특허정보원 특허검색 API — 특허 후보), **SPDX License List**(라이선스 식별자 표준), **deps.dev**(Google, 패키지 라이선스), **PyPI / npm 레지스트리**(패키지 메타데이터 폴백) |
| **인공지능의 역할** | Gemini 구조화 출력으로 ① 문서에서 기술 요소·검색어 추출(`patent_extract`) ② 문서와 선행 특허 대조(`patent_compare`) ③ 라이선스 의무 설명 생성(`license_explain`). **AI는 침해 여부·권리 범위·법적 결론을 판단하지 않는다** — 검토가 필요한 지점을 좁히는 데만 쓴다 |
| **RAG의 역할** | 라이선스 의무사항 참조 지식 검색. 규칙 엔진이 이미 결정한 분류에 대해 "왜 그런 의무가 생기는지"를 **근거 조각 ID와 함께** 설명. 근거 목록에 없는 ID를 만들면 설명 전체를 폐기 |
| **핵심 기능** | Blueprint §46 MVP Core 참조 — 아래 §SECTION 04 표 |
| **단위 테스트 개요** | 3-Plane 각각 소유 테스트. Control 137 / Connectors 211 / Intelligence 68 (`def test_` 기준). 실행 기록: Control 286 passed·1 skipped, Connectors 224 passed, Intelligence 58 passed(대역) + 10 passed(실호출) |
| **통합 테스트 개요** | 🔴 **`tests/integration`, `tests/e2e` 미작성.** Integration 단계 산출물 |

### 1.2 차별점 및 독창성 (3가지 이내) — 근거 자료

1. **Continuous Monitoring** — 일회성 스캐너가 아니라 실제 Workspace 변화(Drive webhook / GitHub webhook / Local chokidar watcher)에 반응. 같은 Risk의 생애(`NEW → EXISTING → RESOLVED → REOPEN`)를 추적.
2. **Security by Architecture** — 원본 소스를 **저장하지 않는다.** `SourceSnapshot`은 transient이고 persistence에는 Security Gate가 승인한 최소 `AnalysisArtifact` + content-free access event + bounded Evidence만 남는다. "무엇을 연결했고 무엇을 실제로 읽었는지"를 `SourceAccessEvent`로 구조적으로 통제.
3. **Evidence-grounded, Human-in-the-Loop** — AI가 법적 결론을 내리지 않고 근거(Evidence)와 검토 우선순위만 제공. Machine lifecycle(`RESOLVED`)과 Human disposition(`EXCLUDED`)을 **분리**해 사용자 판단 이력을 별도 보존.

---

## SECTION 02 · 문제 정의

### 2.1 문제 배경 및 현황 — 확보 자료

Blueprint §1 5개 항목(위 SECTION 01 표 참조) + Master Spec §68 설계 의도.

### 근거 ID 표 (E1~E3) — 🔴 대부분 미확보

| 근거 ID | 근거 유형 | 현재 확보 상태 |
|---|---|---|
| E1 | 실측/API | 🟢 **사용 가능** — Agent 3 실호출 결과: `PyMuPDF 1.24.0`은 deps.dev가 `non-standard`로 응답 → 레지스트리 원문에서 `AGPL-3.0-only` 복원 → `POLICY_CONFLICT` 판정. **공개 메타데이터만 믿으면 AGPL 의무를 놓친다는 실증** |
| E2 | 실측/API | 🟢 **사용 가능** — KIPRIS Plus는 **청구항을 제공하지 않고 초록만 제공.** 그래서 청구항 근거를 요구하는 규칙에서는 모든 후보가 `LOW`가 되어 우선순위가 정보를 주지 못했다 → 초록 근거 2개 이상이면 `MEDIUM`으로 조정. **공공 특허 API의 실제 한계 실증** |
| E3 | 통계/문헌/인터뷰 | 🔴 **미확보** — IP 분쟁 비용, 오픈소스 라이선스 위반 사례 통계, 개발팀 인터뷰 등이 필요. 1차 보고서 `sections-01-05.md` §2.1에 조사 내용이 있을 수 있으니 재활용 검토 |

> 양식이 요구하는 것은 "기술이나 기능에서 출발하지 말고 **실제 사용자가 겪는 문제와 크기·빈도·영향**". 위 E1/E2는 기술 실증이므로 SECTION 02보다 SECTION 07/08에 더 어울린다. **SECTION 02용 사용자 근거(E3)를 별도 확보해야 한다.**

### 2.2 핵심 문제 진술문 (Who / What / Why)

- **Who**: 여러 Source(로컬·GitHub·Drive)에 흩어져 협업하는 프로젝트 팀과 그 IP 리스크를 책임지는 관리자
- **What**: 코드·문서·의존성이 계속 바뀌는데 IP Risk 점검은 특정 시점 한 번에 그친다. 점검하려면 원본 전체를 어딘가에 올려야 해서 보안상 꺼려진다. 발견한 Risk를 누가 언제 어떻게 판단했는지 추적되지 않는다
- **Why**: 근거 확보 필요 (E3)

### 2.3 문제 원인과 기대효과

원인 분리 자료: 표면 현상(= 스캔 결과가 금방 낡음) vs 근본 원인(= 변경 감지·권한 경계·이력 관리가 제품 구조에 없음) vs 해결 대상 아님(= 법적 판단 자체, 특허청 API의 청구항 미제공).

---

## SECTION 03 · 사용자 시나리오 기반 요구사항 정의

### 이해관계자 표 — 코드로 확정된 Role 권한 (Master Spec §24)

| 이해관계자 | Role | 실제 구현된 권한 |
|---|---|---|
| 사용자 | `Viewer` | VWS 조회, Risk 조회, Risk history/activity 조회, 허용된 최소 Evidence 조회 |
| 사용자 | `Risk Reviewer` | Viewer + review disposition 변경, review comment, monitoring/accepted/excluded 판단 |
| 운영자 | `Source Manager` | Risk Reviewer + SourceWorkspace Mount 생성, 자신이 Mount한 Source의 custodian, 자신의 Mount scope/reconnect/disconnect/rename 관리. **다른 Source Manager의 Mount는 관리하지 않는다** |
| 고객/의사결정자 | `Workspace Owner` | VWS 최고 관리자, Member/Role 관리, VWS security·retention policy, global `.ipriskignore`, Audit 관리, Mount administrative disable/remove, VWS 삭제/소유권 이전 |
| 데이터 제공자 | KIPRIS / SPDX / deps.dev / PyPI / npm / Google Drive / GitHub | 외부 |

**Critical authority rule (양식의 "핵심 어려움"에 쓸 수 있는 설계 포인트)**

```
VWS Role  ≠  Source Provider Authority
```

Owner라도 **타인의 provider credential을 사용할 수 없다.** 권한 상승으로 남의 Drive를 읽는 경로가 구조적으로 없다.

### 3.2 서비스 플로우 — 확정된 흐름 (그대로 Draw.io로 옮기면 됨)

**A. 처리 파이프라인 (Master Spec §21 — 고정)**

```
Source event
  → Connector verify / normalize
  → SourceChange
  → Control persist + idempotency
  → Cloud Tasks
  → SourceAdapter.fetch_snapshot()
  → SourceSnapshot
  → SourceAccessEvent record
  → Control Security Gate            ← 여기서 조건부 분기
  → AnalysisArtifact
  → Analyzer Registry
  → Patent / License Analyzer
  → AnalysisResult
  → Control validates result
  → Risk Lifecycle reconcile transaction
  → Risk / RiskEvidence / RiskEvent
  → Notification / UI
```

**B. 조건부 분기·에러 처리 (양식이 명시적으로 요구하는 "시스템의 정책")**

| 분기점 | 조건 | 시스템 동작 |
|---|---|---|
| Security Gate | `gate.approved == False` | 분석 중단. Analyzer 호출 안 함 |
| Gate 진입 | `security_context.approved` 미승인 | Intelligence가 **provider 호출 전에** 거부 |
| snapshot 실패 | provider 예외 | `fail_analysis(failure_safe="PROVIDER_UNAVAILABLE")`. **empty success로 바꾸지 않음** |
| 분석 실패 | `FAILED` / `INCONCLUSIVE` | 기존 active Risk state **유지** (해소 금지) |
| 후보 미판정 | 상위 6건 초과 | `coverage = PARTIAL` → Control이 **자동 해소하지 않음** |
| Source 삭제 | `ChangeType.DELETE` | Risk 자동 `RESOLVED` **금지**. Source 연결 해제 ≠ IP Risk 해소 |
| Open Original | callback 미주입 | 버튼이 **fail closed**로 disabled (이유 표시) |
| RAG 근거 | 목록에 없는 chunk ID 생성 | 설명 전체 폐기 |
| Patent 대조 | 목록에 없는 segment/evidence ID 생성 | 결과 전체 폐기 |

**C. 사용자 흐름**: Google 로그인 → VWS 생성 → Source 연결(Drive OAuth / GitHub App 설치 / Local 폴더 선택) → Mount 생성 → 변경 발생 → 자동 분석 → Risk Dashboard 확인 → Risk Detail에서 Evidence 검토 → disposition 판단 → Timeline에 이력 기록

### 요구 ID 표 (UR-01~) — 🔴 팀이 작성해야 함

구현된 기능에서 역산할 수는 있으나, 양식은 "사용자 스토리 + 근거 + 수용 조건 + 우선순위"를 요구한다. §SECTION 04의 기능 목록을 사용자 관점으로 뒤집어 쓰면 된다.

### 3.3 핵심 가치 제안 — 수치화 가능한 것

| 관점 | 확보된 근거 |
|---|---|
| 보안 | 원본 소스 **0건 영구 저장**. 승인된 최소 Artifact와 content-free 접근 이벤트만 남음 |
| 접근성 | 3개 Source Provider(Drive/GitHub/Local)를 하나의 VWS로 통합 |
| 품질 | 근거 없는 답변 구조적 차단 — 존재하지 않는 ID를 만들면 결과 폐기 |
| 시간 | 🔴 미측정 (분석 소요시간, 응답시간) |

---

## SECTION 04 · 프로젝트 범위와 요구사항

### 4.1 기능 목록 (F-01~) — 구현 상태 실측

| 기능 ID | 기능명 | 우선순위 | 완료 조건 | **실제 상태** |
|---|---|---|---|---|
| F-01 | Google OIDC 로그인 / 세션 | Must | 로그인 후 `/api/v1/auth/me` 응답 | ✅ 구현·테스트 완료 / 🔴 실제 Google credential roundtrip 미검증 |
| F-02 | Risk Workspace(VWS) 생성·멤버·Role 관리 | Must | 4개 Role 권한 매트릭스 통과 | ✅ 완료 (`test_phase12_permission_matrix.py`) |
| F-03 | Google Drive 연결 (OAuth `drive.file` + Picker) | Must | 연결→선택→Mount 생성→webhook 수신 | ✅ 완료 |
| F-04 | GitHub 연결 (GitHub App) | Must | App 설치→repo 선택→Mount→webhook HMAC 검증 | ✅ 완료 |
| F-05 | Local 연결 (Electron 폴더 선택) | Must | 폴더 선택→서버 등록→watcher→변경 전송 왕복 | ✅ 완료 (실제 Electron 헤드리스 실행 검증) |
| F-06 | 변경 감지 → Cloud Tasks 비동기 처리 | Must | idempotency + de-dup | 🟡 Control 로직 완료 / **실제 Cloud Tasks adapter는 Integration 미구현** |
| F-07 | VWS Security Gate + `.ipriskignore` | Must | deny wins, 미승인 시 분석 차단 | ✅ 완료 (`test_security_gate.py` 625줄) |
| F-08 | License Risk 분석 (SPDX + 패키지 메타데이터) | Must | 매니페스트/잠금파일 파싱 → 정책 판정 | ✅ 완료 + **실호출 검증** |
| F-09 | Patent Risk 분석 (KIPRIS + Gemini) | Must | 추출→검색→순위→근거→대조 | ✅ 완료 + **실호출 검증** |
| F-10 | RAG 기반 라이선스 의무 설명 | Must | 근거 chunk ID 검증 | 🟡 로직 완료 / **RAG Engine 실호출 미검증** |
| F-11 | Risk Dashboard / Detail / Timeline / Review | Must | 목록·상세·이력·disposition 변경 | ✅ 완료 (React 33 파일) |
| F-12 | Audit / Source Access History | Must | `/audit`, `/audit/export`, `/source-access` | ✅ 완료 |
| F-13 | 알림 | Should | 목록·읽음 처리 | ✅ 완료 |
| F-14 | 3-Plane 통합 (`main.py` 배선) | Must | 앱 기동 | ✅ **완료** — `/health` 200, 미인증 401 실측 |
| F-15 | GCP 배포 (Cloud Run × 2) | Must | 배포 URL 접근 | 🔴 **미구현** — `deploy/` 비어 있음 |
| F-16 | Source 라우터 권한 검사 | Must | 무인증 접근 거부 | ✅ **완료** — 기본값이 무검사였던 것을 Control RBAC 로 교체 |

### 4.2 프로젝트 범위에서 제외 (Blueprint §46 후속 확장)

- Copyright 및 기타 IP analyzer (Patent·License만 구현)
- PDF/image 등 multimodal artifact (텍스트만 처리. `LocalStagingStore`도 텍스트 전용)
- 조직별 세분화 license/IP policy (전역 정책 `global-license-policy-2026-08-14.1` 하나만)
- 추가 notification channel
- 고급 분석 비교/통계/보고서

### 비기능 요구사항 표 — 확보 자료

| 구분 | 확인된 내용 | 상태 |
|---|---|---|
| 성능 | 🔴 응답시간·처리량 미측정 | 측정 필요 |
| 정확성 | 근거 무결성: 목록에 없는 ID 생성 시 결과 폐기. 라이선스 판정은 규칙 엔진(결정적), AI는 설명만 | ✅ 자료 있음 |
| 보안·개인정보 | 원본 비영속 / provider authority 이중 검증 / raw·credential 로그 금지 / Gate-only boundary / backend-authoritative RBAC. **보안 테스트 20개 항목 중 17 완료·3 부분** | ✅ 자료 충분 |
| 사용성·접근성 | Testing Library 접근성 role 기반 component test 15건. 🔴 **스타일링 없음** (Agent 2 명시) | 부분 |
| 운영성 | structured observability(`StructuredLogger`/`StructuredEventSink`), allow-list 로그 | ✅ 자료 있음 |

### 4.3 핵심 기능과 검증 방법

| 구분 | 방법 | 실측 결과 |
|---|---|---|
| 단위 테스트 | pytest / vitest / node:test | Control 286 passed·1 skipped, Connectors 224 passed, Intelligence 58 passed, Desktop 65(63 passed·2 skipped), Frontend 15 + 8 passed |
| 통합 테스트 | `pytest tests/integration` | **21 passed** — 무인증 거부, 실패 보존, idempotency, Electron→Control 도달 |
| 정량 평가 | Agent 3 실호출 파이프라인 1회 통과 (§SECTION 08 참조) | ✅ |
| 정성 평가 | 🔴 사용자 테스트 미실시 | — |

**총계(통합 트리 실측)**: Python **593 passed / 7 skipped**, TypeScript **88 (86 passed / 2 skipped)**.
합계 **656 tests — 654 passed, 9 skipped, 0 failed**. skip 은 전부 환경 제약(Firestore emulator 1, provider 자격증명 6, symlink 권한 2)이다.

---

## SECTION 05 · 상용화 아키텍처 설계

### 5.1 시스템 아키텍처 다이어그램 — 그대로 옮길 수 있는 원문

**A. 3-Plane 개발 구조 (Blueprint §36)**

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

**B. GCP 런타임 구조 (Blueprint §31)**

```
React Web / Electron Desktop
              │
              ▼
       Cloud Run API
          │       │
          │       └── Firestore (Seoul)
          │
          ▼
      Cloud Tasks
          │
          ▼
 Cloud Run Analysis Worker
    │       │       │
    │       │       └── External APIs (KIPRIS, deps.dev, PyPI, npm)
    │       └────────── Gemini
    └────────────────── External RAG Engine (외부 GA region)
```

Cloud Scheduler는 Drive watch renewal / reconciliation 등 정기 maintenance에 사용.

**C. Hybrid Region 전략 (Blueprint §20)** — "상용화 실증" 주제에 강한 소재

- Application / Source / Firestore: **Seoul** (사용자·소스 근접)
- RAG Engine: **외부 GA region** (Preview 상태 core dependency 회피)
- Data boundary를 명시적으로 설계

### 컴포넌트 표 채움 자료

| 컴포넌트 | 기술/서비스 | 책임 | 입력 | 출력 |
|---|---|---|---|---|
| Web UI | React 19.2.8 + TypeScript 5.9.3 + Vite 8.2.1 | 사용자 상호작용, VWS/Risk/Audit 화면 | 사용자 조작 | 화면 |
| Desktop | Electron 43.4.0 + chokidar 5 | 로컬 폴더 감시, OS 권한 유지 | 파일 변경 | `SourceChange` |
| Backend API | FastAPI (0.141.1 / 0.121.2 — **통합 시 확정 필요**) | 인증·검증·오케스트레이션 | HTTP 요청 | JSON 응답 |
| Analysis Worker | Cloud Run (Python) | 분석 파이프라인 실행 | Cloud Tasks 메시지 | `AnalysisResult` |
| Gemini | `GEMINI_MODEL_ID` (**값 미확정** — 검증에는 `gemini-3-flash-preview` 사용) | 구조화 추출·대조·설명 | 프롬프트 + 근거 | JSON 구조화 결과 |
| RAG | RAG Engine + RagManagedDb Basic | 라이선스 의무 근거 검색 | 질의 | `ReferenceChunk[]` (top_k=3) |
| Data/API | KIPRIS, deps.dev, PyPI, npm, SPDX | 원천 데이터 | 검색어/패키지명 | 특허·라이선스 메타데이터 |
| State DB | Firestore (Seoul) | canonical 상태 16 collection | 트랜잭션 | 문서 |
| Async | Cloud Tasks | retry / concurrency / rate control | `change_event_id` | 워커 호출 |
| Secret | Secret Manager | credential 보관 | — | 주입값 |

### API 명세 표 — 실제 구현된 엔드포인트 전체

**Control Plane (Agent 1)** — prefix `/api/v1`

| Method | Endpoint | 목적 |
|---|---|---|
| GET | `/health` | ✅ 구현. 상태 + 어떤 저장소·provider·분석 경로가 연결됐는지 반환 (비밀값 미포함) |
| GET | `/api/v1/auth/google/login` | Google OIDC 로그인 시작 |
| GET | `/api/v1/auth/google/callback` | OIDC 콜백 |
| GET | `/api/v1/auth/me` | 현재 세션 사용자 |
| POST | `/api/v1/auth/logout` | 로그아웃 |
| GET / POST | `/api/v1/workspaces` | VWS 목록 / 생성 |
| GET / PATCH / DELETE | `/api/v1/workspaces/{vws_id}` | VWS 조회 / 수정 / 삭제 |
| GET | `/api/v1/workspaces/{vws_id}/dashboard` | 대시보드 |
| GET | `/api/v1/workspaces/{vws_id}/members` | 멤버 목록 |
| PATCH / DELETE | `/api/v1/workspaces/{vws_id}/members/{user_id}` | Role 변경 / 제거 |
| GET | `/api/v1/workspaces/{vws_id}/membership` | 내 멤버십 |
| GET | `/api/v1/workspaces/{vws_id}/mounts`, `/mounts/{mount_id}` | Mount 목록 / 상세 |
| PATCH | `/api/v1/workspaces/{vws_id}/mounts/{mount_id}/alias` | Mount 별칭 |
| POST | `/api/v1/workspaces/{vws_id}/mounts/{mount_id}/disable` | Mount 비활성 |
| GET | `/api/v1/workspaces/{vws_id}/risks/{risk_id}` | Risk 상세 |
| GET | `/api/v1/workspaces/{vws_id}/risks/{risk_id}/timeline` | Risk 이력 |
| PATCH | `/api/v1/workspaces/{vws_id}/risks/{risk_id}/review` | disposition 변경 |
| GET | `/api/v1/workspaces/{vws_id}/activity` | 활동 로그 |
| GET | `/api/v1/workspaces/{vws_id}/audit`, `/audit/export` | 감사 로그 / 내보내기 |
| GET | `/api/v1/workspaces/{vws_id}/source-access` | 소스 접근 이력 |
| GET | `/api/v1/workspaces/{vws_id}/data-access-summary` | 데이터 접근 요약 |
| PUT | `/api/v1/workspaces/{vws_id}/ipriskignore` | 보안 정책 |
| GET / POST | `/api/v1/notifications`, `/{id}/read` | 알림 |

**Source Plane (Agent 2)**

| Method | Endpoint | 목적 |
|---|---|---|
| POST | `/api/v1/source-connections/google-drive/start` | Drive OAuth 시작 |
| POST | `/webhooks/google-drive` | Drive push notification |
| POST | `/webhooks/github` | GitHub webhook (HMAC 검증) |
| POST | `/desktop/devices/register` | Electron 기기 등록 |
| POST | `/desktop/mounts/register` | 로컬 Mount 등록 |
| POST | `/desktop/staging` | 로컬 스냅샷 스테이징 |
| POST | `/desktop/events` | 로컬 변경 이벤트 |

### 오류 처리

`SourceHealthStatus`: `HEALTHY` / `REAUTH_REQUIRED` / `PERMISSION_DENIED` / `OFFLINE` / `DEGRADED` / `DISABLED`
분석 실패 분류: `ProviderFailure` + `FailureCategory` (`UNAVAILABLE`, `NOT_FOUND`, `retryable` 플래그 등)

---

## SECTION 06 · 데이터 및 데이터 모델 설계

### 데이터/API 표 — 확인된 전체 목록

| 데이터/API | 제공기관 | 수집 방식·주기 | 핵심 필드 | 품질 이슈 (**실측**) | 이용 조건 |
|---|---|---|---|---|---|
| **KIPRIS Plus** | 한국특허정보원 | REST API, 분석 시점 온디맨드 | `applicationNo`, `inventionName`, `korAbstractInfo.korAbstract` | 🔴 **문서와 실제 필드명이 다름** (`applicationNumber`/`inventionTitle` ❌ → `applicationNo`/`inventionName` ✅). 🔴 **청구항 미제공 — 초록만.** 국문 초록이 별도 필드 | API 키 필요 (`KIPRIS_ACCESS_KEY`) |
| **deps.dev** | Google | REST API, 온디맨드 | 패키지 라이선스 | 🔴 비표준 라이선스를 `non-standard`로 반환 (예: PyMuPDF) | 공개 API |
| **PyPI 레지스트리** | PSF | REST, deps.dev 폴백 | 라이선스 원문 | 자유 서술 필드 → 추정 필요 | 공개 |
| **npm 레지스트리** | npm Inc. | REST, 온디맨드 | 라이선스 | — | 공개 |
| **SPDX License List** | Linux Foundation | 정적 식별자 | SPDX ID | — | CC-BY-3.0 |
| **Google Drive API v3** | Google | OAuth `drive.file` + Picker + push notification | 파일 메타데이터·내용 | — | Google API 약관 |
| **GitHub REST API** | GitHub | GitHub App(short-lived token) + webhook | repo·commit·파일 | 🔴 `list_installation_repositories()` 단일 페이지(최대 100개) | GitHub 약관 |
| **RAG corpus (자체)** | 팀 작성 | 정적 파일 3건 | 라이선스 의무사항 | 🔴 **초기 3건만** (AGPL-3.0 / LGPL-2.1 / 고지형) | 공개 자료만 포함 |

### 6.1 전처리·검증 규칙 — 구현된 것

| 규칙 | 구현 |
|---|---|
| 형식 통일 | SPDX 표준 식별자로 정규화. 실패 시 레지스트리 원문에서 추정하고 `LICENSE_INFERRED_FROM_FREE_TEXT` 표시 |
| 결측 처리 | 라이선스 미확인 → `LicensePolicyOutcome.UNKNOWN`. **"문제 없음"으로 바꾸지 않음** |
| 중복 제거 | `SourceChange` fingerprint 기반 idempotency. 특허 후보 중복 제거 |
| 파싱 안전성 | KIPRIS XML은 `defusedxml`로 파싱 (엔티티 확장 공격 방어) |
| 경로 이탈 방지 | RAG corpus는 매니페스트에 없는 경로를 **아예 읽지 않음**. `is_relative_to(root)` 검사 |
| 무결성 | corpus 자료마다 `sha256` checksum을 매니페스트와 대조. 불일치 시 적재 거부 |
| 스키마 엄격성 | 모든 Pydantic 모델이 `StrictModel` (`extra="forbid"`) |
| 버전 고정 | `RAG_CORPUS_VERSION`, `corpus_version: 2026-08-14.1`, `global-license-policy-2026-08-14.1` |

### 6.2 데이터 모델 / ERD — 확보 자료

**A. Frozen Shared Contract 5종** (`shared/contracts/python/iprisk_contracts/`)

| Contract | 역할 | Producer → Consumer |
|---|---|---|
| `SourceAdapter` | provider 추상화 | Source Plane 구현 |
| `SourceChange` | 변경 이벤트 (content-free) | Source → Control |
| `SourceSnapshot` | 원본 스냅샷 (**transient**) | Source → Control Gate |
| `AnalysisArtifact` | Gate 승인된 최소 분석 대상 | Control → Intelligence |
| `AnalysisResult` | 분석 결과 + Evidence | Intelligence → Control |

JSON Schema 4종이 `shared/contracts/schemas/*.v1.json`, TypeScript 타입이 `shared/contracts/typescript/generated/contracts.ts`에 생성되어 있고, fixture 9건이 `shared/contracts/fixtures/`에 있다. **보고서에 스키마를 붙일 자료가 이미 있다.**

**B. 확정 Enum 전체** (`common.py`)

```
SourceType            GOOGLE_DRIVE | GITHUB | LOCAL
ChangeType            CREATE | UPDATE | DELETE | MOVE
ArtifactKind          TEXT | SOURCE_CODE | MANIFEST | LOCKFILE | DOCUMENT_TEXT | UNKNOWN
ContentScope          FULL_TEXT | CHANGESET_WITH_CONTEXT | METADATA_ONLY | UNSUPPORTED
SegmentKind           FULL | CHANGED | CONTEXT
SourceAccessType      METADATA | DIFF | PARTIAL_CONTENT | FULL_CONTENT
AnalysisType          PATENT | LICENSE
AnalysisStatus        SUCCEEDED | FAILED | INCONCLUSIVE | SKIPPED
AnalysisCoverage      COMPLETE | PARTIAL | NONE
OriginalSourceType    PROVIDER_URL | LOCAL_DEVICE | UNAVAILABLE
SourceHealthStatus    HEALTHY | REAUTH_REQUIRED | PERMISSION_DENIED | OFFLINE | DEGRADED | DISABLED
EvidenceType          SOURCE_EXCERPT | PATENT_CLAIM | PATENT_ABSTRACT | LICENSE_REFERENCE | RAG_REFERENCE | PACKAGE_METADATA
ReviewPriority        LOW | MEDIUM | HIGH
LicensePolicyOutcome  NO_ACTION | NOTICE_REQUIRED | REVIEW_REQUIRED | POLICY_CONFLICT | UNKNOWN
```

**C. Firestore canonical collection 16개 + composite index 8개**

| Collection | Index fields |
|---|---|
| `memberships` | `record_kind`, `risk_workspace_id` |
| `memberships` | `record_kind`, `user_id`, `status` |
| `memberships` | `record_kind`, `email` |
| `workspace_mounts` | `record_kind`, `risk_workspace_id` |
| `workspace_mounts` | `record_kind`, `risk_workspace_id`, `mounted_by_user_id` |
| `risks` | `record_kind`, `artifact_id`, `analysis_type`, `lifecycle_state` |
| `risks` | `record_kind`, `risk_workspace_id` |
| `change_events` | `risk_workspace_id` |

**D. 핵심 도메인 관계 (ERD 소재)**

```
User ──< Membership >── RiskWorkspace (VWS)
                              │
                              ├──< WorkspaceMount >── SourceWorkspace ──< SourceConnection ── User(credential owner)
                              │
                              ├──< ChangeEvent ──< AnalysisJob ──< AnalysisResult
                              │
                              ├──< Risk ──< RiskEvidence
                              │      └──< RiskEvent (append-only)
                              │
                              ├──< AuditEvent
                              ├──< SourceAccessEvent
                              └──< Notification
```

**E. Risk 상태 모델 (2계층 — 독창성 포인트)**

```
Machine lifecycle:   NEW → EXISTING → RESOLVED
                            ↑            │
                            └── REOPEN ──┘

Human disposition:   UNREVIEWED | MONITORING | ACCEPTED_RISK | EXCLUDED

핵심:  EXCLUDED ≠ RESOLVED
       사용자 disposition 변경이 machine lifecycle을 바꾸지 않는다
       machine Risk가 RESOLVED되어도 review/history는 보존한다
```

### 6.3 데이터 검증 (보안 검토 표) — 채움 자료

| 위험 항목 | 해당 여부 | 대응 방법 |
|---|---|---|
| 개인정보/민감정보 포함 | **예** (원본 소스 코드·문서, Google 계정 이메일) | 원본 **비영속**(`SourceSnapshot` transient), 최소수집(Gate 승인 Artifact만), content-free 이벤트, `.ipriskignore` 제외, bounded Evidence, retention policy |
| 출처·라이선스 제한 | **예** (KIPRIS·SPDX·Drive·GitHub) | corpus는 **공개 자료만** 포함(`manifest.yaml` 명시). 비공개 작업공간 자료를 corpus에 넣는 기능을 아예 만들지 않음 |
| 편향 또는 대표성 부족 | **예** | RAG corpus 3건뿐 → 문서에 명시. 특허는 KIPRIS(한국) 중심 → 관할 `jurisdiction: KR` 명시 |
| 최신성·품질 불확실 | **예** | `corpus_version` / `policy version` / `model_id`를 결과에 기록해 재현성 확보. checksum 대조 |

---

## SECTION 07 · 인공지능 기능 및 프롬프트 설계

### AI 기능 표 — 실제 구현 3종

| AI 기능 | 모델/설정 | 입력 | 출력 형식 | **일반 로직과의 경계 (LLM이 하지 않는 것)** |
|---|---|---|---|---|
| `patent_extract` v1 | `GEMINI_MODEL_ID`, 구조화 출력 | 문서 segment 목록 | JSON: `is_technical`, `technical_elements[]`, `search_queries[]`, `source_segment_ids[]` | 특허 검색 자체는 KIPRIS가 수행. LLM은 검색어만 만든다 |
| `patent_compare` v1 | 동일 | 문서 segment + 특허 근거 | JSON: `matched_elements[]`, `distinct_elements[]`, `uncertainty_flags[]` | **침해 여부·권리 범위·법적 결론을 판단하지 않는다.** 후보 순위·우선순위 산정은 규칙이 담당 |
| `license_explain` v1 | 동일 | 패키지·라이선스 표현식·판정 결과·참조 자료 | JSON: `summary`, `obligations[]`, `reference_chunk_ids[]` | **분류는 규칙 엔진이 이미 결정.** LLM은 결과를 바꾸거나 반박하지 않고 설명만 |

**설계 원칙 (보고서 강조 포인트)**: 판정은 결정적 규칙 엔진, 설명·추출·대조만 LLM. AI가 최종 판단을 내리는 지점이 없다.

### 7.1 핵심 프롬프트 — 실제 파일 그대로 붙여 넣을 수 있음

위치: `backend/src/ip_risk_agent/intelligence/gemini/prompts/`

<details><summary><code>patent_extract_v1.md</code></summary>

```markdown
---
prompt_id: patent_extract
version: v1
---

문서에서 특허 검토에 필요한 기술 요소와 검색어를 뽑는다.

## 판단 기준
`is_technical` 은 다음을 모두 만족할 때만 참이다.
- 구체적인 처리 방식, 구조, 알고리즘, 장치 구성이 서술되어 있다
- 단순한 일정, 회의록, 사업 계획, 용어 정리가 아니다
기능 목록만 나열된 문서는 참이 아니다. 무엇을 어떻게 처리하는지가 있어야 한다.

## technical_elements
구성 요소를 한 줄씩 적는다. 문서에 실제로 서술된 것만 적는다.
일반적인 기술 상식을 보태지 않는다.

## search_queries
특허 검색에 넣을 영문 검색어다. 다음을 지킨다.
- 한 검색어는 **2~3 단어**로 만든다
- 검색 엔진이 모든 단어를 포함하는 문서만 찾으므로, 길면 결과가 0건이 된다
- 서로 다른 관점을 담아 2~5개를 만든다
- 제품명이나 회사명은 넣지 않는다

## source_segment_ids
각 판단의 근거가 된 입력 segment 의 ID 를 적는다. 입력에 없는 ID 를 만들지 않는다.

## 입력
{segments}
```
</details>

<details><summary><code>patent_compare_v1.md</code></summary>

```markdown
---
prompt_id: patent_compare
version: v1
---

문서와 선행 특허를 대조해 겹치는 기술 구성을 찾는다.

## 하지 않는 것
침해 여부, 권리 범위, 법적 결론을 판단하지 않는다.
그것은 사람이 판단할 영역이며, 이 결과는 검토가 필요한 지점을 좁히는 데만 쓴다.

## matched_elements
문서와 특허 양쪽에 같은 기술 구성이 나타날 때만 적는다.
- `source_segment_id` 는 입력 segment 목록에 있는 ID 여야 한다
- `patent_evidence_id` 는 제시된 특허 근거 목록에 있는 ID 여야 한다
- 목록에 없는 ID 를 만들면 결과 전체가 폐기된다
- `explanation` 은 어느 구성이 어떻게 겹치는지를 한두 문장으로 적는다
같은 분야라는 이유만으로 겹친다고 적지 않는다. 처리 방식이 같아야 한다.

## distinct_elements
문서에만 있고 특허에는 없는 구성을 적는다.
겹치는 부분만 보면 사람이 판단할 수 없다. 다른 점도 함께 있어야 한다.

## uncertainty_flags
판단이 어려웠던 이유를 적는다. 예: 초록만 제공되어 청구항을 확인할 수 없음.

## 입력
문서 segment  {segments}
특허 근거      {patent_evidence}
```
</details>

<details><summary><code>license_explain_v1.md</code></summary>

```markdown
---
prompt_id: license_explain
version: v1
---

이미 결정된 라이선스 검토 분류를 사람이 읽을 수 있게 설명한다.

## 전제
분류는 규칙 엔진이 이미 결정했다. 그 결과를 바꾸거나 반박하지 않는다.
제시된 참조 자료에 근거해 왜 그런 의무가 생기는지를 설명하는 것이 전부다.

## summary
두세 문장으로 적는다. 이 패키지를 그대로 배포하면 무엇을 해야 하는지가 드러나야 한다.

## obligations
배포 시 실제로 해야 하는 일을 항목으로 적는다.
참조 자료에 없는 의무를 추측해서 보태지 않는다.

## reference_chunk_ids
설명의 근거가 된 참조 조각의 ID 를 적는다.
제시된 목록에 없는 ID 를 만들면 설명 전체가 폐기된다.

## 입력
패키지          {package}
라이선스 표현식  {license_expression}
검토 분류        {outcome}
참조 자료        {references}
```
</details>

### 프롬프트 테스트 표 (P-01~P-03) — 실측 자료

| 테스트 ID | 대표 입력 | 기대 결과 | **실제 결과 (실호출 검증됨)** | 판정 |
|---|---|---|---|---|
| P-01 (정상) | 기술 문서 | 구조화 출력 수신 | 선언한 스키마대로 구조화 출력 수신 | 통과 |
| P-02 (정보 부족) | 비기술 문서 | 기술 문서 아님 판정 | `is_technical=False`로 판정 | 통과 |
| P-03 (오류/악의) | 존재하지 않는 근거 ID 생성 시도 | 안전 처리 | 목록에 없는 ID → **결과 전체 폐기** (코드 강제) | 통과 |
| P-04 (스키마 호환) | `extra="forbid"` Pydantic 스키마 | 정상 호출 | 🔴 **Gemini가 `additionalProperties`를 거부, 400 반환** → 내부 검증은 엄격 유지하고 API 전송 스키마에서만 해당 항목과 `$ref`를 정리하는 변환기 추가 | **수정 후 통과** |

> P-04는 "대역 테스트만으로는 발견되지 않고 실호출에서 드러난 문제"의 대표 사례다. SECTION 10(구현 기록)과 SECTION 15.3(레슨런)에도 재사용 가능.

### 7.2 환각·안전·오류 대응 — 구현된 방어 계층

| 상황 | 대응 |
|---|---|
| 근거 없는 답변 | `source_segment_id` / `patent_evidence_id` / `reference_chunk_ids`가 **입력 목록에 없으면 결과 전체 폐기**. `EvidenceLedger`가 등록·참조를 함께 관리해 참조 무결성 보장 |
| 법적 결론 생성 시도 | 프롬프트에서 명시적으로 금지 + 출력 스키마에 해당 필드 없음 |
| 라이선스 판정 번복 | 규칙 엔진 결과를 LLM이 바꿀 수 없는 구조 (설명 전용 프롬프트) |
| API 실패 | `ProviderFailureError(provider, FailureCategory, message)` + `retryable` 분류. 지수 백오프 재시도 (5xx/429/네트워크 단절) |
| 출력 파싱 실패 | `ResultBuilder`가 조립. **`SUCCEEDED`가 아니면 `COMPLETE`를 만들 수 없다** |
| provider 부분 실패 | 하나라도 실패하면 `COMPLETE` 미반환 → Control이 자동 해소하지 않음 |
| 미승인 Artifact | Analyzer 진입점에서 `security_context.approved` 확인, 미승인이면 **provider 호출 전에** 거부 |
| 추정 표시 | 라이선스를 자유 서술에서 추정한 경우 `LICENSE_INFERRED_FROM_FREE_TEXT` 플래그 부착 |

---

## SECTION 08 · RAG 설계와 검색 품질

### 설계 항목 표 — 실제 구현 값

| 설계 항목 | 팀의 선택 | 선택 이유 / 검증 방법 |
|---|---|---|
| 지식 문서 범위 | **라이선스 의무사항 참조 지식 3건** (AGPL-3.0, LGPL-2.1, 고지형 permissive). 총 **2,120 bytes / 60줄**. `jurisdiction: KR`, `source_type: OBLIGATION_GUIDE` | 라이선스 의무는 문헌 근거가 필요하고 자주 바뀌지 않아 persistent RAG에 적합. **원본 소스 코드는 넣지 않는다** (Blueprint §19) |
| 문서 정제 | 매니페스트(`rag-corpus/manifest.yaml`) 기반 화이트리스트. 매니페스트에 없는 경로는 **읽지 않음** | 비공개 작업공간 자료가 실수로도 corpus에 들어갈 수 없게 하는 구조적 차단 |
| 무결성 검사 | 자료마다 `sha256` checksum을 매니페스트와 대조 | 지문 불일치 시 적재 거부 — corpus 버전이 실제 내용을 설명하지 못하는 상황 방지 |
| Chunk 전략 | 🔴 **명시적 chunk size/overlap 설정 없음.** RAG Engine 관리형 ingestion에 위임 | 비교 실험 미수행 |
| Embedding / Vector Store | **RAG Engine + RagManagedDb Basic** | 관리형 ingestion/retrieval. 초기 규모와 관리 단순성 (Blueprint §35) |
| 적재(ingestion) | 🔴 **RAG Engine 업로더 미구현.** `CorpusUploader` Protocol의 구현체가 `InMemoryCorpusUploader` 하나뿐이라 코드로는 corpus를 RAG Engine에 올릴 수 없다 | Agent 3 Spec §36이 `upload/import RAG Engine`을 요구하나 미충족. 콘솔/`gcloud` 수동 업로드 필요 |
| 검색 방식 | `retrieveContexts` REST 호출, **`top_k = 3`**. 🔴 **`filters`는 시그니처에만 있고 payload에 반영되지 않아 운영 경로에서 무시된다** (`engine.py`). `license/analyzer.py`도 `filters`를 넘기지 않음 | `google-cloud-aiplatform` SDK(100MB+) 대신 `google-auth` + httpx REST 직접 호출 — 필요 기능이 `retrieveContexts` 하나뿐. `test_retrieval_honours_filters`는 `InMemoryReferenceRetriever`만 검증하므로 이 불일치를 잡지 못한다 |
| 관련성 임계값 | 🔴 **없음.** `threshold`/`vector_distance`/`similarity` 설정이 코드 전체에 부재. 관련도와 무관하게 항상 `top_k=3` 반환 | corpus에 없는 라이선스도 무조건 3건이 근거로 붙는다 (§검색 품질 위험 참조) |
| RAG 호출 조건 | `policy.needs_review(outcome)` — 심각도 ≥ `UNKNOWN`. 즉 **`POLICY_CONFLICT`·`REVIEW_REQUIRED`·`UNKNOWN`에서만** 검색. `NOTICE_REQUIRED`·`NO_ACTION`은 RAG 미사용 | 고지형은 고정 문구(`policy.describe()`)로 충분하다는 판단 |
| 재정렬/후처리 | 사용 안 함 | — |
| 출처 표시 | `reference_chunk_ids`를 결과에 포함. 목록에 없는 ID 생성 시 **설명 전체 폐기** | 사용자가 Risk Detail에서 근거 확인 |
| 버전 관리 | `corpus_version: 2026-08-14.1`, `RAG_CORPUS_VERSION` 환경변수, 없으면 `unversioned` | 결과의 `versions`에 기록되어 재현성 확보 |
| 교체 가능성 | Analyzer는 `ReferenceRetriever` 규약만 안다. `RagEngineRetriever`(운영) / `InMemoryReferenceRetriever`(테스트·오프라인) 교체 가능 | 관리형 서비스든 로컬 색인이든 갈아끼울 수 있음 |
| Region | Application=Seoul, **RAG Engine=외부 GA region** | Preview 상태 core dependency 회피 (Blueprint §20) |

### 8.1 RAG 처리 흐름

```
라이선스 판정 완료 (규칙 엔진, 결정적)
        ↓
질의 구성: 패키지 + 라이선스 표현식 + 판정 결과
        ↓
ReferenceRetriever.retrieve(query, filters, top_k=3)
        ↓
RAG Engine :retrieveContexts (REST, google-auth ADC)
        ↓
ReferenceChunk[] (chunk_id · source_id · text · metadata)
        ↓
license_explain 프롬프트에 근거로 주입
        ↓
Gemini 구조화 출력 (summary · obligations · reference_chunk_ids)
        ↓
reference_chunk_ids 검증 ── 목록 밖 ID → 설명 전체 폐기
        ↓
Evidence(EvidenceType.RAG_REFERENCE) 로 등록 → 사용자에게 출처 표시
```

**적재 흐름 (`ingestion.py`)**: 매니페스트 로드 → `approved_for_rag` 확인 → 경로가 corpus 밖을 가리키지 않는지 검사 → 파일 읽기 → sha256 대조 → 정규화 → 업로드. 건너뛴 항목은 `IngestionReport.skipped`에 기록되고 `is_clean`으로 판정.

### 🔴 검색 품질 위험 — corpus 커버리지 18%

정책 표(`license/policy.py`)의 식별자와 corpus 문서를 대조한 결과:

| 판정 | 식별자 수 | RAG 호출 | 대응 corpus 문서 |
|---|---:|:---:|---|
| `POLICY_CONFLICT` | 9 (AGPL×2, GPL-2.0×2, GPL-3.0×2, OSL-3.0, EUPL-1.2, SSPL-1.0) | ✅ | **AGPL-3.0 1건뿐** |
| `REVIEW_REQUIRED` | 13 (LGPL-2.1×2, LGPL-3.0×2, MPL×2, EPL×2, CDDL×2, CPL-1.0, MS-RL, OFL-1.1) | ✅ | **LGPL-2.1 1건뿐** |
| `UNKNOWN` | — | ✅ | **없음** |
| `NOTICE_REQUIRED` | 16 (Apache-2.0, MIT, BSD×2, ISC …) | ❌ | permissive-notice 1건 |
| `NO_ACTION` | 4 (0BSD, CC0-1.0, Unlicense, WTFPL) | ❌ | 없음 |

**RAG를 타는 22개 식별자 중 대응 문서가 있는 것은 4개(18%).** 나머지 18개는 근거 문서가 없는데도 임계값이 없어 `top_k=3`이 무조건 반환된다.

**구체적 실패 시나리오**: `GPL-3.0-only` 분석 시 corpus에 GPL 문서가 없어 AGPL 문서가 근거로 붙는다. 그 문서에는 "바이너리를 배포하지 않고 서비스 형태로만 제공하더라도 이 의무가 발생한다. **이 점이 GPL-3.0 과 다르다**"라고 적혀 있다. 근거 ID 검증도, "참조 자료에 없는 의무를 추측하지 않는다"는 프롬프트 제약도 모두 통과하므로 **환각 방어 장치가 전부 작동하는 채로 틀린 근거가 나간다.**

**부수 문제**: `permissive-notice.md`가 다루는 MIT/BSD/Apache-2.0/ISC는 전부 `NOTICE_REQUIRED`라 `needs_review`가 `False`다. 즉 corpus 3건 중 1건은 **자기 용도로는 검색되지 않고**, `UNKNOWN` 케이스에서 잘못 끌려 나올 수만 있다.

### 평가 질문 표 (Q1~Q5) — 🔴 **미수행**

RAG 검색 품질 평가는 아직 수행되지 않았다. **RAG Engine 실호출이 미검증일 뿐 아니라, 적재 경로 자체가 미구현**(위 설계 표 "적재" 행)이기 때문이다.

**대안 — 지금 채울 수 있는 방법**: `InMemoryReferenceRetriever`(어휘 겹침 순위)로 corpus 3건에 대해 평가 질문 5개를 돌리면 "검색된 근거 / 답변 품질 / 개선점" 표를 채울 수 있다. 이 경우 **검색기 종류를 반드시 명시**할 것. 평가 질문에 GPL-3.0이나 MPL-2.0처럼 **corpus에 없는 라이선스를 1개 이상 넣으면** 위 커버리지 문제가 그대로 "개선점" 칸의 근거가 된다.

**대신 지금 쓸 수 있는 실측 자료 — 전체 파이프라인 1회 실호출 결과**

```
LICENSE  SUCCEEDED / COMPLETE
  pymupdf   1.24.0  AGPL-3.0-only  POLICY_CONFLICT   [LICENSE_INFERRED_FROM_FREE_TEXT]
  requests  None    Apache-2.0     NOTICE_REQUIRED   [VERSION_RANGE_NOT_PINNED]

PATENT   SUCCEEDED / COMPLETE · 후보 3건 · 근거 4건
  1020080080388  보이스-피싱 검출을 위한 GMM 모델...
     "통화 음성의 복호화 과정에서 추출된 파라미터를 특징 벡터로 구성하는
      기술적 특징이 일치함"
```

**provider별 실호출 검증 결과 (10건)**

| 대상 | 확인 내용 |
|---|---|
| deps.dev | `requests 2.32.3` → `Apache-2.0` 표준 식별자 수신 |
| PyPI 폴백 | `PyMuPDF 1.24.0`은 deps.dev가 `non-standard`로 응답 → 레지스트리 원문에서 `AGPL-3.0-only` 복원 → `POLICY_CONFLICT` |
| npm | `express 4.19.2` → `MIT` |
| 미존재 패키지 | `NOT_FOUND` · `retryable=False`로 분류 |
| KIPRIS 검색 | 정규화된 출원번호 수신 |
| KIPRIS 0건 | 무의미한 검색어에 빈 결과 — **실패와 구분됨** |
| KIPRIS 상세 | 초록 수신 |
| KIPRIS 잘못된 키 | 오류 또는 0건으로 안전 처리 |
| Gemini | 선언한 스키마대로 구조화 출력 수신 |
| Gemini 비기술 문서 | `is_technical=False` 판정 |

### 8.2 RAG 고도화 전략 (Agentic AI 기반 Advanced RAG 로드맵) — 소재

| 우선 | 단계 | 내용 | 근거 |
|:---:|---|---|---|
| 🔴 1 | **RAG Engine 업로더 구현** | `CorpusUploader` Protocol에 RAG Engine 구현체를 붙인다. 현재 `InMemoryCorpusUploader`뿐이라 코드로는 적재가 불가능하다 | Agent 3 Spec §36 `upload/import RAG Engine` 미충족 |
| 🔴 2 | **`filters` 실제 반영** | `engine.py`의 `retrieve()`가 `filters`를 payload에 넣도록 수정하고, 실물 retriever 대상 테스트를 추가한다. 현재 대역만 필터를 지킨다 | `engine.py`에서 파라미터 미사용 확인 |
| 🔴 3 | **관련성 임계값 도입** | `vector_distance_threshold`를 설정해 관련 없는 근거가 붙지 않게 한다. 임계 미달이면 근거 없이 `policy.describe()` 고정 문구로 대체 | 코드에 threshold 부재 확인 |
| 🔴 4 | **corpus 커버리지 확대** | 최소한 RAG를 타는 22개 식별자를 덮는다 — GPL-2.0/3.0, OSL-3.0, EUPL-1.2, SSPL-1.0, LGPL-3.0, MPL, EPL, CDDL, CPL, MS-RL, OFL. 이후 84종으로 확대 | 현재 커버리지 18% |
| 🟡 5 | **Chunk 전략 비교 실험** | 현재 관리형 ingestion에 위임. 크기·overlap 실험 후 결정 | 미수행 항목 |
| 🟡 6 | **Hybrid 검색 / 재정렬 도입** | 현재 `top_k=3` 단순 검색 | 미도입 |
| 🟡 7 | **관할별 corpus 분리** | 현재 전부 `jurisdiction: KR`. 메타데이터는 이미 붙어 있으나 **위 2번이 선행되어야 실제로 필터링된다** | 확장 지점 존재 |
| 🟡 8 | **조직별 라이선스 정책** | 현재 전역 정책 1개. `AnalysisArtifact`에 자리가 없어 **Contract v2 또는 별도 정책 컨텍스트 필요** | Agent 3 문서 §8 명시 |
| 🟡 9 | **특허 청구항 확보 시 정확도 상승** | `PatentDocument.claims`는 이미 구현되어 있어 청구항을 얻을 수 있게 되면 그대로 동작하고 `HIGH` 판정이 가능해짐 | 코드 준비 완료 |

---

## SECTION 09 · 구현 계획과 팀 협업

### 작업 ID 표 (T-01~) — 실제 구조에 맞춘 매핑

| 작업 ID | 작업 | 담당 | 의존 작업 | 완료 조건 | **상태** |
|---|---|---|---|---|---|
| T-01 | 환경·저장소·Frozen Contract 확정 | 전원 | — | `pnpm run generate` diff 없음, contract test 27건 통과 | ✅ 완료 |
| T-02 | Platform & Control Plane | Agent 1 | T-01 | Phase 0~13, 286 passed | ✅ 완료 |
| T-03 | Source Integration & Desktop | Agent 2 | T-01 | Phase A~F, 297 tests | ✅ 완료 |
| T-04 | Risk Intelligence & RAG | Agent 3 | T-01 | 58 + 10 passed | ✅ 완료 |
| T-05 | Branch 통합 (`integration`) | Integration | T-02/03/04 | 충돌 해결 + 전체 테스트 통과 | ✅ **완료** |
| T-06 | 앱 배선 (`main.py`/`worker.py`/`composition/`) | Integration | T-05 | 앱 기동 | ✅ **완료** |
| T-07 | GCP 배포 (Cloud Run × 2, Tasks, Scheduler, Firestore index) | Integration | T-06 | 배포 URL 접근 | 🔴 미착수 |
| T-08 | 통합 테스트 | Integration | T-06 | `tests/integration` | ✅ **완료 21건**. `tests/e2e` 는 배포 후 |
| T-09 | 사용자 테스트 | 전원 | T-07 | 3인 이상 과업 수행 | 🔴 미착수 |

### 협업 기준 표 — 실제 확정된 규칙

| 구분 | 팀의 기준 |
|---|---|
| **저장소·브랜치** | 단일 공용 repository. `main`(공통 기준점) → `platform-control` / `source-integration-desktop` / `risk-intelligence-rag` / `integration`. **각 Agent는 자신의 branch에만 push.** main 직접 push 금지. 통합 검증 완료 후에만 main 반영. 커밋 메시지 `<type>: <summary>` |
| **파일 ownership** | branch별 디렉터리 소유권 명시(README §3). 자신의 ownership 밖 기능을 대신 구현하지 않는다. **결과: backend 파일 단위 충돌 0건** |
| **Frozen Shared Contract** | `shared/contracts/**`는 병렬 개발 동안 Frozen. 변경이 필요하면 코드를 고치지 말고 contract-change request 절차를 따른다. **실제 결과: 세 Agent 모두 request 0건** |
| **의존성 규칙** | 다른 Plane의 내부 구현 직접 import 금지. 허용: `Control/Source/Intelligence → shared contracts`, `Integration → all public plane surfaces` |
| **개발 환경** | CPython 3.14.7 / Node.js 24.19.0 / pnpm 11.19.0 / TypeScript 5.9.3 / Pydantic 2.13.4 / pytest 9.1.1. `.venv`·`node_modules`·`.pnpm-store`·`dist`는 공유하지 않고 manifest/lockfile로 재현 |
| **Dependency 추가** | root `pyproject.toml`을 직접 수정하지 않는다. 각자 venv에서 설치·검증한 뒤 Plane 별 dependency 문서에 **버전·용도·검증 결과·특이사항**을 기록. 최종 pin 은 Integration 이 병합해 [DEPENDENCIES.md](DEPENDENCIES.md) 와 `pyproject.toml` 로 확정 |
| **환경 변수** | `.env.example`에 이름만 선언. 실제 값은 소스·fixture·log·task payload 어디에도 기록 금지. 각 Plane은 환경변수를 직접 읽지 않고 **생성자 주입** |
| **코드 품질** | 각 Agent가 자신의 테스트 소유(`tests/control` / `tests/connectors` / `tests/intelligence`). **mock-only로 완료 주장 금지** (Master Spec §59) — real fake + 실제 파일시스템 + 실제 FastAPI TestClient + 실제 provider 호출로 검증 |
| **인계 문서** | 개발 완료 시 Master Spec §60 형식의 `AGENT_N_DELIVERY.md` 필수 작성 |
| **협업 도구** | 🔴 미확보 (GitHub 외) |

### 9.1 기술 위험과 대응 — 실제 발생한 것 + 예상되는 것

| 위험 | 실제 발생 여부 | 대응 |
|---|---|---|
| 외부 API 문서와 실제 응답 불일치 | 🔴 **발생** — KIPRIS 필드명이 `applicationNo`/`inventionName`이었음 | 실호출 검증 필수화. 대역 테스트만으로는 0건 응답과 구분 불가 |
| 외부 API 기능 부재 | 🔴 **발생** — KIPRIS가 청구항 미제공 | 초록 근거 2개 이상이면 `MEDIUM`으로 우선순위 규칙 조정 |
| LLM 스키마 호환성 | 🔴 **발생** — Gemini가 `additionalProperties` 거부 | API 전송용 스키마 변환기 추가. 내부 검증은 엄격 유지 |
| 모델 식별자 미확정 | 🔴 **미해결** — "Gemini 3.6 Flash"는 실재하지 않는 식별자 | 환경변수화로 코드 변경 없이 지정 가능. **배포 전 값 확정 필요** |
| Plane 간 dependency 충돌 | 🔴 **발생** — FastAPI `0.141.1` vs `0.121.2`, `@types/node` `26.2.0` vs `^24.0.0` | 상위 버전 채택 후 반대편 테스트 재검증 |
| 문서 간 런타임 버전 불일치 | 🔴 **발생** — pyproject 3.14 / README 3.14.7 / 환경 문서 3.12.13 / Intelligence 실제 3.13 | ✅ 3.14.7 로 통일하고 전 Plane 재검증 완료 |
| 프론트엔드 빌드 철학 충돌 | 🔴 **발생** — vitest+Bundler vs node:test+NodeNext | vitest로 통일, `PlatformAdapter.test.ts` 포팅 |
| 외부 서비스 미검증 | 🔴 **미해결** — Google OIDC roundtrip, Firestore production, Cloud Tasks, RAG Engine | 배포 환경 확보 후 검증 |
| 배포 미착수 | 🔴 **미해결** — `deploy/` 비어 있음 | T-07 |

---

## SECTION 10 · 구현 기록 · 코드 리뷰 · 변경 관리

### 진행 단계 표 — 채움 자료

| 진행 단계 | 완료한 내용 | 문제/막힘 | 결정·다음 행동 |
|---|---|---|---|
| 기획·설계 | Blueprint(49KB) + Master Spec(55KB) + Agent별 상세 명세 3종(85KB) 작성. Frozen Contract 5종·Enum 14종 확정. 3-Plane 경계와 파일 ownership 사전 확정 | 병렬 개발 시 충돌 우려 | **디렉터리 ownership 사전 분할 + Frozen Contract 채택** → 결과적으로 backend 충돌 0건 |
| 핵심 기능 구현 | Agent 1 Phase 0~13 / Agent 2 Phase A~F / Agent 3 전 영역 완료. 총 568 Python + 88 TS 테스트 | 대역 테스트로는 외부 API 실제 동작을 알 수 없었음 | **실호출 검증 의무화** → 5가지 결함 발견·수정 |
| 배포·검증 | 세 branch 병합(충돌 4건, 전부 프론트 설정), dependency 확정, `composition/` 8모듈 배선, 통합 테스트 21건 | ① dependency 충돌이 통합 시점에 한꺼번에 드러남 ② Source 라우터 authz 기본값이 무검사 ③ Cloud Tasks 가 content-free ID 만 넘기는데 이를 `SourceChange` 로 되짚는 공개 메서드가 없음 | ①은 상위 버전 채택 후 반대편 테스트 실측 재검증 ②는 경로별 스코프 어댑터로 교체 ③은 contract-change request 대상으로 기록하고 우회 조회하지 않음 |
| 시연·회고 | 🔴 미착수 | — | — |

### 코드 리뷰 표 — 채움 자료

| 리뷰 항목 | 발견 내용 | 조치 |
|---|---|---|
| 구조·책임 분리 | 3-Plane + Frozen Contract로 사전 분리. Plane 간 내부 구현 import 금지 규칙 | `test_delivery_contract.py`가 공개 surface 드리프트를 자동 탐지 (4 tests) |
| 오류·예외 처리 | provider 실패를 성공으로 바꾸는 경로가 없는지 점검 | `ResultBuilder`가 `SUCCEEDED`가 아니면 `COMPLETE`를 만들 수 없게 강제. `fail_analysis(failure_safe=...)` 경로 분리 |
| 키·개인정보·보안 | Agent 2 보안 체크리스트 20개 항목 대조 | ✅17 / 🟡3 (Drive file ID 안정성 — 설계상 보장·별도 테스트 없음 / symlink escape — 코드 존재·환경 제약 SKIP / staging TTL — 문서화만) |
| 프롬프트/RAG 품질 | 근거 ID 무결성, 추정 표시 누락 | 목록 밖 ID 시 결과 폐기. `normalize()`가 추정까지 수행해 `inferred_from_free_text`가 항상 `False`였던 버그 → 파싱과 추정 분리 |
| 재현성·문서화 | `corpus_version` / `policy version` / `model_id` 기록. Agent별 인계 문서 + dependency 문서 | ✅ |
| **미해결** | `AuthzDependency` 기본값이 **아무 검사도 하지 않음** | 🔴 프로덕션 전 Agent 1 VWS Role 검사로 교체 **필수** |
| **미해결** | `AddSourceChooser`의 `riskWorkspaceId`가 `"dev-workspace"` 하드코딩 | 🔴 Agent 1 app shell 연결 시 제거 |

### 10.1 주요 변경 결정 — 실제 기록된 것

| # | 초기 계획 | 변경 내용 | 변경 근거 | 영향 범위 |
|---|---|---|---|---|
| 1 | 단일 앱 프로토타입 (v1) | **3-Plane 병렬 개발 + Frozen Shared Contract** (v2) | 엔터프라이즈 멀티테넌트 요구. 기능 종류가 아니라 **독립 개발 가능성과 통합 접점 최소화**를 기준으로 분할 | 전체 아키텍처 |
| 2 | `google-cloud-aiplatform` SDK 사용 | **`google-auth` + httpx REST 직접 호출** | SDK 설치 용량 100MB 초과인데 필요 기능은 `retrieveContexts` 하나뿐. 이미 httpx를 쓰므로 새 의존성 증가 없음 | Intelligence Plane |
| 3 | 청구항 근거 기반 우선순위 | **초록 근거 2개 이상이면 `MEDIUM`** | KIPRIS Plus가 청구항을 제공하지 않아 실측에서 모든 후보가 `LOW`로 깔림 → 우선순위가 정보를 주지 못함 | Patent analyzer |
| 4 | 영문 초록 사용 | **국문 초록(`korAbstractInfo.korAbstract`) 우선** | 검사 대상 문서가 대개 한국어. 영문 초록과 한국어 문서를 대조하면 겹치는 표현을 찾기 어려움 | Patent analyzer |
| 5 | corpus 매니페스트를 TOML로 | **YAML(`PyYAML` `safe_load`)** | 명세 §34의 형식이 YAML. 이전에는 의존성을 늘릴 수 없어 우회했으나 정책 변경 후 명세대로 맞춤 | RAG |
| 6 | Pydantic 스키마를 그대로 Gemini에 전송 | **API 전송용 스키마 변환기 추가** | `extra="forbid"`가 넣는 `additionalProperties`를 Gemini가 400으로 거부 | Gemini client |
| 7 | `normalize()`가 파싱+추정 동시 수행 | **파싱과 추정 분리** | `inferred_from_free_text`가 항상 `False`가 되어 "라이선스를 추측했다"는 사실이 사용자에게 전달되지 않음 | License analyzer |
| 8 | 각 Agent가 root `pyproject.toml` 수정 | **dependency 문서에 기록 → Integration이 병합** | root manifest 동시 수정 시 충돌 불가피 | 협업 규칙 |

---

## SECTION 11 · 웹 연계와 클라우드 배포

🔴 **이 SECTION 전체가 미착수다.** `deploy/`에는 `.gitkeep`만 있고 배포 URL이 없다.

### 배포 항목 표 — 계획으로 채울 수 있는 자료

| 배포 항목 | 계획된 내용 | 상태 |
|---|---|---|
| 웹 인터페이스 | React 19 + Vite 8. `ControlPlaneApp` 진입점. `router="browser"`(Web) / `"hash"`(Electron renderer). 주요 화면: Login / Workspace List / Dashboard / Risk List / Risk Detail / Risk Timeline / History / Security & Data Access / Members / Notifications | 코드 ✅ / 배포 🔴 |
| 백엔드 서비스 | **Cloud Run** (asia-northeast3 Seoul) — API 1개 + Analysis Worker 1개 | 🔴 미배포 |
| 데이터/저장소 | **Firestore Native** (Seoul), canonical collection 16개 + composite index 8개. Local staging은 GCS 버킷(`LOCAL_STAGING_BUCKET`), TTL 설정 필요 | 🔴 미배포 |
| 환경 변수/Secret | **Secret Manager**. 각 Plane은 환경변수를 직접 읽지 않고 생성자 주입. 필요 변수 전체 목록은 [DEPENDENCIES.md](DEPENDENCIES.md) 5절 | 🔴 미구성 |
| 빌드·배포 명령 | `pnpm run generate` → `pnpm run typecheck` → `pnpm run build` → `pytest` → 컨테이너 빌드 → Cloud Run 배포. **CI/CD 미구성** | 🔴 |
| 헬스 체크 | ✅ `GET /health` — `status`, `control_backend`, `google_login`, `intelligence`, `sources.{mounted,skipped}` 반환. 비밀값 미포함 | ✅ |
| 로그·모니터링 | structured observability 구현됨 (`StructuredLogger` / `StructuredEventSink`, allow-list 로그). Cloud Logging 연동 미구성 | 코드 ✅ / 연동 🔴 |
| 비용·한도 | 🔴 미산정. 비용 항목: Gemini 호출, KIPRIS API, RAG Engine, Cloud Run, Firestore, Cloud Tasks. **후보 상위 6건 제한이 이미 비용 통제 장치** | 🔴 |

### 서비스 계정 분리 계획 (Master Spec §48) — 상용화 설계 소재

| 서비스 계정 | 역할 |
|---|---|
| `app-api-sa` | Cloud Run API |
| `analysis-worker-sa` | Cloud Run Analysis Worker |
| `scheduler-sa` | Cloud Scheduler (Drive watch renewal / reconciliation) |
| `deploy-sa` | 배포 |

### 11.1 배포 구조 — SECTION 05의 GCP 런타임 다이어그램 재사용

### 점검 표 — 전부 🔴 미확인

배포 URL 접근 / Secret 노출 없음 / 오류 로그 확인 가능 / 재배포 후 동작 / README 실행·배포 안내 일치 — **모두 T-07 이후 확인 가능**

> **대안**: 배포가 제출 기한 내 불가능하면, 로컬 실행 스크린샷 + [DEVELOPMENT.md](DEVELOPMENT.md) 기반 재현 절차 + 배포 계획(위 표)으로 채우고 SECTION 17.1에 사유와 보완 계획을 명시한다. 양식 SECTION 00 체크리스트가 이 방식을 명시적으로 허용한다.

---

## SECTION 12 · 기능 검증과 사용자 테스트

### TC 표 — 지금 채울 수 있는 것 / 없는 것

| TC ID | 기능/상황 | **현재 확보 상태** |
|---|---|---|
| TC-01 | 핵심 정상 흐름 (연결→변경→분석→Risk 표시) | 🟡 **통합 경로까지 검증됨** — 로그인 → VWS 생성 → 기기 등록 → Mount 등록 → staging → `/desktop/events` → Control 등록이 `tests/integration` 에서 실제로 이어진다. **브라우저 E2E 와 실제 provider 연동은 미실시** |
| TC-02 | 빈 값 / 형식 오류 | ✅ 자료 있음 — `StrictModel`(`extra="forbid"`) 전면 적용, Control API validation 테스트 |
| TC-03 | 외부 API 실패 | ✅ 자료 있음 — `ProviderFailureError` + `FailureCategory` + `retryable` 분류. KIPRIS 잘못된 키 실측 확인. 지수 백오프 재시도 |
| TC-04 | 근거 부족 | ✅ 자료 있음 — KIPRIS 0건을 실패와 구분(실측). `coverage=PARTIAL` 시 자동 해소 금지. 목록 밖 ID 생성 시 결과 폐기 |
| TC-05 | 모바일/브라우저 | 🔴 **미실시.** 스타일링 자체가 없음 |
| TC-06 | 권한 경계 | ✅ Control `test_phase12_permission_matrix.py`·`test_authorization.py` + **Integration `test_source_authorization.py`**. Owner 도 타인 credential 사용 불가. Source 라우트 무인증 접근 401, VWS 멤버십 없는 Mount 등록 403 |
| TC-07 (추가 권장) | 보안 경계 | ✅ 자료 있음 — Local root escape 거부, GitHub webhook HMAC 잘못된 서명 거부, renderer 임의 fs 호출 불가, 미선택 repo/branch/path 무시 |

### 사용자 테스트 표 (U1~U3) — 🔴 **전면 미실시**

배포 URL이 없어 외부 사용자 테스트를 진행하지 못했다. **로컬 빌드로 3인 이상 과업 수행 테스트를 하는 것이 현실적 대안**이다. 과업 후보:

1. Google 로그인 → VWS 생성 → Local 폴더 연결 → 파일 수정 → Risk 목록에서 결과 확인
2. Risk Detail에서 Evidence 확인 → disposition을 `ACCEPTED_RISK`로 변경 → Timeline에서 이력 확인
3. Security & Data Access 화면에서 "무엇을 실제로 읽었는지" 확인 → `.ipriskignore` 수정 → 제외 반영 확인

### 지표 표 — 🔴 전부 미측정

| 지표 | 측정 방법 후보 | 목표 | 결과 |
|---|---|---|---|
| 과업 성공률 | 위 3과업 완주 비율 | — | 🔴 |
| 응답 시간 | API p50/p95, 분석 파이프라인 소요시간 | — | 🔴 |
| 답변 근거성/정확성 | 근거 ID 무결성 통과율(구조상 100%), 라이선스 판정 정확도 | — | 🟡 실호출 2건만 |
| 사용 만족/이해도 | 사용자 테스트 설문 | — | 🔴 |

---

## SECTION 13 · 품질 개선

### 개선 ID 표 (I-01~) — **실호출로 드러나 실제 고친 것 5건** (그대로 쓸 수 있음)

| 개선 ID | 발견 문제 | 근거 | 개선 내용 | 전/후 결과 | 상태 |
|---|---|---|---|---|---|
| I-01 | KIPRIS 검색 결과가 항상 0건 | 실제 API 호출 | 응답 필드명을 `applicationNumber`/`inventionTitle` → `applicationNo`/`inventionName`으로 수정 | 0건 → 후보 3건 수신 | ✅ 완료 |
| I-02 | 한국어 문서와 영문 초록 대조 시 겹치는 표현을 찾기 어려움 | 실제 API 호출 | `korAbstractInfo.korAbstract` 국문 초록 우선 사용 | 대조 근거 확보 | ✅ 완료 |
| I-03 | Gemini API가 400 반환 | 실제 API 호출 | `extra="forbid"`가 넣는 `additionalProperties`와 `$ref`를 API 전송 스키마에서만 정리하는 변환기 추가 (내부 검증은 엄격 유지) | 400 → 구조화 출력 정상 수신 | ✅ 완료 |
| I-04 | "라이선스를 추측했다"는 사실이 사용자에게 전달되지 않음 | 코드 리뷰 + 실측 | `normalize()`에서 파싱과 추정을 분리 | `inferred_from_free_text`가 항상 `False` → `LICENSE_INFERRED_FROM_FREE_TEXT` 실제 부착 | ✅ 완료 |
| I-05 | 실측에서 모든 특허 후보가 `LOW`로 깔려 우선순위가 정보를 주지 못함 | 실제 파이프라인 실행 | KIPRIS가 청구항 미제공 → 초록 근거 2개 이상이면 `MEDIUM`으로 상향 | 전부 LOW → 우선순위 분화 | ✅ 완료 |
| I-06 | Local MOVE 감지 미구현 | 자체 점검 | 내용 해시 기반 MOVE 감지 구현 (D-3 gap) | 감지 가능 | ✅ 완료 |
| I-07 | Electron watcher가 서버와 연결되지 않음 | 자체 점검 | `/desktop/events` HTTP 엔드포인트로 실제 전송 배선 | 전체 왕복 동작 | ✅ 완료 |
| I-08 | **Source 라우터 7개가 무인증으로 열려 있었음** | 통합 시 코드 점검 | 기본값 `allow_all_authz`(무검사)를 Control RBAC 어댑터로 교체. `resource_id` 의미가 라우트마다 달라 경로별 스코프로 분기 | 무인증 200 → **401/403**. 회귀 테스트로 잠금 | ✅ 완료 |
| I-09 | FastAPI 버전 충돌 (`0.141.1` vs `0.121.2`) | 통합 시 dependency 대조 | 상위 버전 채택 후 반대편 224건을 실제로 재실행해 확인 | 충돌 → 전 Plane 단일 환경 통과 | ✅ 완료 |
| I-10 | `.env.example` 이 코드가 읽는 변수 4개를 누락 | 코드 grep 으로 실제 참조 도출 | `GEMINI_API_KEY`·`KIPRIS_ACCESS_KEY`·`RAG_CORPUS_VERSION`·`IPRISK_SERVER_BASE_URL` 추가 | 배포 시 특허 분석이 **조용히 비활성화**될 위험 제거 | ✅ 완료 |
| I-11 | `pnpm-lock.yaml` 과 `package.json` 불일치 | `--frozen-lockfile` 실패 | lockfile 재생성 후 커밋 | CI 재현 불가 → 통과 | ✅ 완료 |

> I-01 ~ I-05는 "**대역(fake) 테스트만으로는 발견되지 않고 실호출에서만 드러난 결함**"이라는 하나의 이야기로 묶인다. SECTION 15.3 레슨런의 핵심 소재.

### 최종 상태 표 — 채움 자료

| 최종 상태 | 내용 |
|---|---|
| **정상 시연 가능한 기능** | **하나의 앱으로 기동한다** (`uvicorn ip_risk_agent.main:app`). Google 로그인(자격증명 있을 때) → VWS 생성/멤버 관리 → Local Source 연결 → 변경 감지 → Risk Dashboard/Detail/Timeline/Review → Audit·Security 화면. Electron 로컬 감시 전체 왕복, License/Patent 분석 실호출 파이프라인 |
| **부분 구현/제한 기능** | RAG(corpus 3건, RAG Engine 실호출 미검증) / GitHub `reconcile()` no-op / `GET /desktop/mounts/{id}/status` 미구현 / GitHub repo 목록 100개 제한 / `.ipriskignore` fnmatch 기반 / LocalStagingStore 텍스트 전용 / Drive 실제 파일 API 재시도 미적용 |
| **미구현 기능** | GCP 배포(`deploy/` 비어 있음), 브라우저 E2E, 스타일링, 사용자 테스트, Drive/GitHub webhook·mounts 라우터(자격증명 필요), Open Original resolver, Copyright analyzer, multimodal artifact, 조직별 정책 |
| **알려진 오류** | Local MOVE는 내용 해시 기반 추정 — 내용이 완전히 같은 다른 파일이면 오판 가능. symlink escape 테스트 2건은 Windows 관리자 권한 없으면 자동 skip |
| **운영 시 주의사항** | `AuthzDependency` 기본값이 무검사 — **프로덕션 전 반드시 교체.** `FIRESTORE_EMULATOR_HOST`를 production에 설정 금지. 내장 rate limiter는 단일 process 안전망일 뿐 전역 quota 아님. `GEMINI_MODEL_ID` 값 미확정. 특허 후보 상위 6건만 판정(비용) |

### 13.1 최종 서비스 화면 / 13.2 시연 영상 — 🔴 미확보

**확보 가능한 자료**: 1차 프로젝트의 `FireShot Webpage Capture 008 - 'IP Risk Agent' - localhost.pdf`(v1 화면)가 있으나 **v2 화면이 아니다.** v2는 통합·기동 후 캡처해야 한다.

---

## SECTION 14 · 서비스 시연 및 발표

### 발표 순서 표 — 소재 배분안

| 순서 | 발표 내용 | 핵심 메시지 | 근거 자료 |
|---|---|---|---|
| 1 | 문제와 고객 | IP Risk는 정적 검사 한 번으로 끝나지 않는다 | Blueprint §1, SECTION 02 |
| 2 | 서비스 구현 범위 | v1 단일 스캐너 → v2 멀티테넌트 보안 제품 | SECTION 04 기능표 |
| 3 | 데이터·Gemini·RAG·아키텍처 | 판정은 규칙, 설명은 AI. 원본은 저장하지 않는다 | SECTION 05·07·08 |
| 4 | 서비스 시연 | Local 폴더 연결 → 변경 → Risk 확인 → 근거 확인 → disposition | SECTION 12 과업 후보 |
| 5 | 검증 결과와 한계 | 656건 테스트, 실호출로 5가지 결함 발견·수정. 통합·배포 미완 | SECTION 13 |
| 6 | 고도화 계획 | corpus 84종, Advanced RAG, 조직별 정책, 배포 | SECTION 15 |

### 14.2 기술 선택 설명 — Blueprint §35 표 그대로 사용 가능

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
| LLM | Gemini | structured AI analysis |
| Patent | KIPRIS | 특허 후보 source |
| License | SPDX + package metadata | deterministic identity/policy |
| RAG | RAG Engine | managed ingestion/retrieval |
| RAG storage | RagManagedDb Basic | 초기 규모와 관리 단순성 |
| App region | Seoul | application/source/user proximity |
| RAG region | External GA region | Preview core dependency 회피 |
| Core orchestration | Explicit workflow | auditability / deterministic failure handling |

**명시적 비채택 항목**도 Master Spec §3에 기록되어 있어 "대안" 칸에 쓸 수 있다.

### 14.3 예상 질문과 답변 — 준비된 근거

| 예상 질문 | 답변 근거 |
|---|---|
| "AI가 특허 침해를 판단하나?" | 아니다. `patent_compare` 프롬프트가 침해·권리범위·법적 결론 판단을 명시적으로 금지. 검토 지점을 좁힐 뿐 |
| "환각은 어떻게 막나?" | 근거 ID 무결성 — 입력 목록에 없는 ID를 만들면 결과 전체 폐기. `EvidenceLedger`가 참조 무결성 관리 |
| "우리 소스 코드를 저장하나?" | 저장하지 않는다. `SourceSnapshot`은 transient. Gate가 승인한 최소 `AnalysisArtifact` + content-free 접근 이벤트 + bounded Evidence만 남는다 |
| "관리자가 남의 Drive를 볼 수 있나?" | 없다. `VWS Role ≠ Source Provider Authority`. Owner라도 타인 credential 사용 불가 |
| "비용은?" | 특허 후보 상위 6건만 판정하도록 제한. 미판정 시 `coverage=PARTIAL`로 자동 해소 차단 |
| "확장성은?" | Connector / Analyzer / Risk contract 분리. 새 Source나 IP Risk 유형 추가 시 전체 재작성 불필요 |
| "분석이 실패하면?" | 실패를 "Risk 없음"으로 바꾸지 않는다. `FAILED`/`INCONCLUSIVE`는 기존 active state 유지. Source 삭제도 Risk 자동 해소 금지 |
| "왜 아직 배포가 안 됐나?" | 병합·dependency 확정·애플리케이션 배선까지 끝났고 앱은 로컬에서 기동한다. 남은 것은 GCP 자원 연동뿐이며 교체 지점을 `SourcePorts` 한 곳에 모아 뒀다 |

---

## SECTION 15 · 피드백 및 고도화 계획

### 피드백 표 — 🔴 대부분 미확보

| 출처 | 확보 상태 |
|---|---|
| 사용자 | 🔴 미실시 |
| 동료 팀 | 🔴 미확보 |
| 강사/리뷰어 | 🟡 **1차 발표 피드백이 있다면 재활용 가능** — 1차 산출물(`AI부트캠프 5조.pdf`, `IP DeteDog 발표대본.txt`) 확인 필요 |
| 팀 자체 회고 | 🟢 자료 있음 — SECTION 10.1 변경 결정 8건 + SECTION 13 개선 7건 |

### 백로그 표 (B-01~B-05) — 우선순위 제안

| 백로그 ID | 고도화 항목 | 기대 가치 | 노력 | 우선순위 | 검증 방법 |
|---|---|---|---|---|---|
| B-01 | **GCP 배포** (Firestore·Secret Manager·Cloud Tasks·GCS·Cloud Run) | 제품 성립의 전제. 통합·배선은 완료됐고 `SourcePorts` 한 곳만 실물로 교체하면 된다 | 상 | 1 | 배포 URL 접근 + E2E 통과 |
| B-00 | **RAG 관련성 임계값 도입** | corpus 에 없는 라이선스에 엉뚱한 근거가 붙는 것을 막는다. 작업량이 작고 효과가 즉시 | 하 | 1 | corpus 밖 라이선스 평가 질문으로 확인 |
| B-02 | **RAG corpus 84종 확대** | 라이선스 설명 커버리지 | 중 | 2 | `manifest.yaml` 추가 + `corpus_version` 상승 + 평가질문 재실행 |
| B-03 | **특허 청구항 확보 경로** | `HIGH` 우선순위 판정 가능 | 상 | 3 | `PatentDocument.claims`는 이미 구현. 데이터 소스 확보가 관건 |
| B-04 | **조직별 라이선스 정책** | 엔터프라이즈 필수 | 상 | 4 | Contract v2 또는 별도 정책 컨텍스트 설계 |
| B-05 | **UI 스타일링 + 사용성 개선** | 사용자 수용 | 중 | 5 | 사용자 테스트 과업 성공률 |
| B-06 | Advanced RAG (hybrid 검색·재정렬·chunk 실험) | 근거 품질 | 중 | 6 | 평가 질문 정확도 비교 |
| B-07 | Copyright analyzer 추가 | Risk 유형 확대 | 상 | 7 | Analyzer Registry에 추가 등록 |
| B-08 | multimodal artifact (PDF/이미지) | 커버리지 | 상 | 8 | `ArtifactKind` 확장 |
| B-09 | `RiskEvent` cryptographic hash chain | 규제 대응 | 중 | 9 | schema version + key custody + backfill + verifier 설계 필요 |

### 15.2 KPT 회고 — 소재

| 구분 | 내용 |
|---|---|
| **Keep** | 디렉터리 ownership 사전 분할 + Frozen Contract → backend 파일 충돌 **0건**. 실호출 검증 의무화(mock-only 완료 주장 금지) → 결함 5건 발견. Agent별 인계 문서·dependency 문서 필수화 → 통합 시 정보 손실 없음 |
| **Problem** | root manifest를 아무도 수정하지 않아 dependency 충돌이 **통합 시점에 한꺼번에** 드러남(FastAPI, `@types/node`). 문서 간 Python 버전이 3.12/3.13/3.14로 제각각. 프론트엔드 빌드 철학(vitest vs node:test)이 사전 합의되지 않아 유일한 충돌 지점이 됨. 통합·배포를 마지막에 몰아 두어 SECTION 11~13을 채우지 못함 |
| **Try** | dependency는 branch 병합 전 **주기적 dry-run 병합**으로 조기 감지. 프론트엔드 툴체인도 Frozen Contract처럼 사전 고정. 통합을 마지막이 아니라 **주 1회 리허설**로 상시 수행 |

### 15.3 레슨런 — 확보된 소재

1. **대역 테스트는 외부 API의 실제 계약을 검증하지 못한다.** KIPRIS 필드명 오류는 "0건 응답"이라는 정상 처리 경로로 흘러 대역 테스트에서 드러나지 않았다. 실호출 검증에서만 5가지 결함이 나왔다.
2. **공개 API 문서와 실제 응답은 다를 수 있다.** 필드명, 제공 범위(청구항 미제공), 언어별 필드 분리 모두 실측에서 처음 확인됐다.
3. **LLM 제약이 데이터 모델 설계를 역으로 규정한다.** Pydantic `extra="forbid"`가 만드는 `additionalProperties`를 Gemini가 거부해, 내부 검증용 스키마와 API 전송용 스키마를 분리해야 했다.
4. **파일 ownership 사전 분할은 병렬 개발 충돌을 실제로 없앤다.** 3개 branch 291개 파일 변경에서 backend 충돌 0건, 전체 충돌 4건(전부 프론트엔드 설정).
5. **공유 설정 파일은 ownership 분할로 보호되지 않는다.** 충돌 4건이 전부 `frontend/package.json`·`tsconfig.json`·`vite.config.ts`·`index.html`이었다. 코드는 나눌 수 있어도 툴체인 설정은 나눌 수 없다.
6. **"실패를 성공으로 바꾸지 않는다"는 원칙은 코드로 강제해야 한다.** `ResultBuilder`가 `SUCCEEDED`가 아니면 `COMPLETE`를 만들 수 없게 한 것처럼, 원칙을 타입·구조로 강제하지 않으면 지켜지지 않는다.

---

## SECTION 16 · 산출물 · 출처 · 라이선스

### 산출물 표

| 산출물 | URL/경로 | 공개 여부 | 확인 사항 |
|---|---|---|---|
| GitHub 저장소 | `https://github.com/2HyN/ip-risk-agent-v2` | 확인 필요 | 최종 commit: `main` `7cfbec4` / `platform-control` `de1dacc` / `source-integration-desktop` `ee861b7` / `risk-intelligence-rag` `68e07a3` |
| 배포 서비스 | 🔴 없음 | — | 미배포 사유 기재 |
| API 문서 | FastAPI 자동 OpenAPI (`/docs`) — 🔴 앱 미기동으로 접근 불가 | — | 엔드포인트 전체 목록은 SECTION 05 표 참조 |
| 발표 자료 | 1차: `IP DeteDog 발표자료_수정본.pptx` / 2차 🔴 미작성 | — | — |
| 시연 영상 | 🔴 없음 | — | — |
| 설계 문서 | `IP_RISK_AGENT_MEETING_BLUEPRINT.md`(49KB), `CODING_AGENT_MASTER_SPEC.md`(55KB), Agent 명세 3종(85KB) | 저장소 내 | ✅ |
| 구현 현황 | `docs/IMPLEMENTATION_STATUS.md` | 저장소 내 | ✅ |
| 통합 기록 | `docs/INTEGRATION.md` | 저장소 내 | ✅ |
| 의존성 확정 | `docs/DEPENDENCIES.md` | 저장소 내 | ✅ |
| 개발·검증 가이드 | `docs/DEVELOPMENT.md` | 저장소 내 | ✅ |

### 출처·라이선스 표 — 확인된 것

| 구분 | 이름/출처 | URL | 라이선스·이용 조건 | 사용 위치 |
|---|---|---|---|---|
| 데이터 | KIPRIS Plus | `plus.kipris.or.kr` | API 키 필요, 이용약관 — **확인 필요** | 특허 후보 검색 |
| 데이터 | deps.dev (Google) | `deps.dev` | 공개 API, 약관 확인 필요 | 패키지 라이선스 조회 |
| 데이터 | PyPI | `pypi.org` | 공개 | 라이선스 폴백 |
| 데이터 | npm registry | `registry.npmjs.org` | 공개 | 라이선스 조회 |
| 문서/RAG | SPDX License List | `spdx.org/licenses/` | CC-BY-3.0 (**확인 필요**) | 라이선스 식별자 + corpus `canonical_reference` |
| 문서/RAG | 자체 작성 corpus 3건 | `rag-corpus/sources/` | 팀 저작. "공개 자료만 포함" 명시 | RAG 검색 |
| AI 모델/API | Google Gemini | `ai.google.dev` | Google AI 이용약관 | 추출·대조·설명 |
| AI 모델/API | Vertex AI RAG Engine | `cloud.google.com` | GCP 약관 | 근거 검색 |
| API | Google Drive API v3 | — | Google API 서비스 이용약관, OAuth `drive.file` scope | Drive 연결 |
| API | GitHub REST API | — | GitHub 이용약관, GitHub App | GitHub 연결 |
| 오픈소스 (Python) | fastapi / pydantic / httpx / authlib / itsdangerous / google-cloud-firestore / google-api-python-client / google-auth / google-genai / PyJWT / defusedxml / PyYAML / pytest | — | 🔴 **개별 라이선스 확인 필요** (대부분 MIT/Apache-2.0/BSD) | 백엔드 |
| 오픈소스 (Node) | react / react-dom / react-router-dom / vite / vitest / jsdom / Testing Library / electron / chokidar / typescript | — | 🔴 **개별 라이선스 확인 필요** (대부분 MIT/Apache-2.0) | 프론트/데스크톱 |
| 이미지/아이콘 | 🔴 미확인 | — | — | — |

> **자기적용 아이디어**: 이 프로젝트 자체가 라이선스 분석 도구다. `pyproject.toml` / `pnpm-lock.yaml`을 자사 License analyzer에 넣어 이 표를 자동 생성하면 SECTION 16과 SECTION 12(TC-01 정상 흐름 시연)를 동시에 채울 수 있다. **발표에서도 강한 소재.**

### 16.1 README 재현 절차 — 이미 문서화된 자료

[DEVELOPMENT.md](DEVELOPMENT.md) 에 환경 구축부터 검증까지 전체 절차가 있다.

```bash
git clone https://github.com/2HyN/ip-risk-agent-v2 && cd ip-risk-agent-v2
py -V:3.14.7 -m venv .venv && source .venv/Scripts/activate
python -m pip install -e ".[dev]"
pnpm install --frozen-lockfile
cp .env.example .env      # 값 채우기
pnpm run generate && pnpm run typecheck && pnpm run build && pnpm run verify:resolution
pytest
python -m compileall backend/src shared/contracts/python scripts
```

---

## SECTION 17 · 최종 제출 체크리스트

| 확인 | 항목 | **현재 상태** |
|:---:|---|---|
| 🟡 | 문제 정의가 고객·사용자와 근거 데이터에 연결 | 근거 E1/E2는 기술 실증. **사용자 근거 E3 필요** |
| ✅ | 서비스 구현 범위와 제외 범위가 명확하며 실제 구현과 일치 | SECTION 04 표 |
| ✅ | 기능·비기능 요구사항에 확인 가능한 완료 조건 | 각 Agent Acceptance Criteria + 테스트 |
| ✅ | 시스템 아키텍처, 데이터 모델, API 흐름이 최신 | Blueprint + Frozen Contract + 엔드포인트 실측 |
| 🟡 | Gemini 모델명·프롬프트·출력 형식·오류 대응 기록 | 프롬프트 3종 ✅ / **모델명 미확정** 🔴 |
| 🟡 | RAG 지식 범위·분할·검색·출처 표시·평가 결과 기록 | 설계 ✅ / **chunk 전략·평가 결과** 🔴 |
| ✅ | 환경 변수와 Secret 실제 값이 문서·코드·화면에 노출 없음 | `.env.example`은 이름만. 전 Plane 생성자 주입 |
| 🟡 | 공공·산업 데이터와 문서·오픈소스 출처·라이선스 표시 | **개별 라이선스 확인 필요** |
| 🟡 | 정상·경계·실패 테스트 + 사용자 테스트 결과 | 단위 테스트 ✅ / **통합·사용자 테스트** 🔴 |
| 🔴 | 배포 URL과 GitHub URL이 열리고 README로 실행 방법 확인 | **배포 URL 없음** |
| 🔴 | 발표와 시연 흐름, 실패 시 대체 시나리오 준비 | 미작성 |
| ✅ | 한계·미구현·후반기 고도화 계획을 숨기지 않고 작성 | SECTION 13·15 자료 충분 |

### 17.1 미확인 항목 또는 제출 비고 — 반드시 기재할 내용

1. **GCP 미배포** — `deploy/` 가 비어 있고 배포 URL 이 없다. 따라서 SECTION 11 점검 표,
   SECTION 12 사용자 테스트, SECTION 13.1/13.2 최종 화면·영상을 채우지 못했다.
   통합과 배선은 완료되어 앱이 로컬에서 기동하므로, 남은 것은 GCP 자원 연동이다.
   교체 지점은 `composition/container.py` 의 `SourcePorts` 한 곳에 모여 있다.
2. **`GEMINI_MODEL_ID` 미확정** — 명세의 "Gemini 3.6 Flash" 가 실재하지 않는 식별자다.
   검증에는 `gemini-3-flash-preview` 를 사용했다.
3. **RAG Engine 실호출 미검증 + 업로더 미구현** — 검색 클라이언트는 있으나 corpus 를
   RAG Engine 에 올리는 구현이 없다. 콘솔/`gcloud` 수동 업로드가 필요하다.
4. **RAG 평가 질문 미수행** — 위 3번에 종속. 다만 `InMemoryReferenceRetriever` 로
   corpus 3건에 대한 평가는 지금도 가능하다.
5. **RAG corpus 커버리지 18%** — 관련성 임계값이 없어 corpus 에 없는 라이선스에도
   근거가 붙는다. 개선 우선순위 1번으로 올려 두었다.
6. **사용자 테스트 미실시** — 위 1번에 종속. 로컬 빌드로 3인 과업 테스트는 가능하다.
7. **브라우저 E2E 미실시** — `tests/e2e` 가 비어 있다. 통합 테스트 21건은 HTTP 계층까지만
   검증한다.
8. **Cloud Tasks 경로 미완성** — 큐가 content-free `change_event_id` 만 넘기는데 이를
   `SourceChange` 로 되짚는 공개 메서드가 없다. Control 내부를 우회 조회해 임시로 메우지
   않고 contract-change request 대상으로 기록했다.

---

## 부록 A. 문서·설정 정정 (통합 시 처리 완료)

| # | 대상 | 문제 | 상태 |
|---|---|---|---|
| 1 | 환경 문서 | Python **3.12.13** / `py -3.12` 로 기재. 실제는 3.14.7 | ✅ 3.14.7 로 통일. Intelligence 58건을 3.14.7 에서 재검증 |
| 2 | dependency 문서 | `pydantic 2.13.3` 오기 | ✅ 2.13.4 로 정정 |
| 3 | `.env.example` | 코드가 읽는 변수 4개 누락 | ✅ 추가 (`GEMINI_API_KEY`, `KIPRIS_ACCESS_KEY`, `RAG_CORPUS_VERSION`, `IPRISK_SERVER_BASE_URL`) + Agent 2 요구 2개 |
| 4 | `.env.example` | `KIPRIS_API_KEY_SECRET_ID` 를 코드가 읽지 않음 | ✅ Secret Manager 참조 ID 임을 명시하고 주입 흐름 기술 |
| 5 | 줄바꿈 | Windows `core.autocrlf` 로 생성물이 CRLF 가 되어 diff 발생 | ✅ `.gitattributes` 추가 |
| 6 | `pnpm-lock.yaml` | `package.json` 과 불일치로 `--frozen-lockfile` 실패 | ✅ 재생성 |
| 7 | Master Spec 16/35, Blueprint 35 | "Gemini 3.6 Flash" — 실재하지 않는 식별자 | 🔴 **미처리.** 두 문서는 Frozen 명세라 배포 모델 확정 시 함께 정정 |
| 8 | 저장소 루트 | 제출양식 `.docx` 가 untracked | 🔴 미처리. 커밋하거나 `.gitignore` 처리 |

## 부록 B. 자료 출처 대조표

| 보고서 SECTION | 주 자료 위치 |
|---|---|
| 01, 02 | `IP_RISK_AGENT_MEETING_BLUEPRINT.md` 0~1, 47~48 |
| 03 | `CODING_AGENT_MASTER_SPEC.md` 21~26, 41~44 |
| 04 | Master Spec 66, Blueprint 46, [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) |
| 05 | Blueprint 31~35, [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) 1절, 코드 실측 라우트 |
| 06 | `shared/contracts/**`, Master Spec 8~20·37 |
| 07 | `backend/src/ip_risk_agent/intelligence/gemini/prompts/*.md` |
| 08 | `rag-corpus/manifest.yaml`, `intelligence/rag/*.py`, Blueprint 19~20, Master Spec 36 |
| 09 | [DEVELOPMENT.md](DEVELOPMENT.md), Master Spec 57~59 |
| 10 | [INTEGRATION.md](INTEGRATION.md), [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) 3절, git log |
| 11 | Blueprint 31, Master Spec 48, `deploy/`(비어 있음) |
| 12, 13 | [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) 0·2절, [INTEGRATION.md](INTEGRATION.md) 8절 |
| 14 | Blueprint 35·47~48, Master Spec 3 |
| 15 | [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) 각 Plane 제약, Blueprint 46 |
| 16 | `pyproject.toml`, `package.json`, [DEPENDENCIES.md](DEPENDENCIES.md) |
| 17 | 이 문서 전체 |
