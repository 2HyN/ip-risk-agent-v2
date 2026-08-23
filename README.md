# IP Risk Agent

**여러 협업 Source Workspace(Local · GitHub · Google Drive)를 하나의 Risk
Workspace 에 연결하고, 변경을 지속적으로 감지해 Patent·License 중심의 잠재적
IP Risk 를 근거 기반으로 분석함으로써, 사용자가 장기적으로 검토·추적·감사할 수
있게 하는 Secure Human-in-the-Loop AI Risk Management System.**

- 웹: https://ip-risk-agent-v2-api-555102774494.asia-northeast3.run.app
- 데스크톱 앱(로컬 폴더 마운트용, Windows):
  [Releases v1.0.0](../../releases/tag/v1.0.0) 에서 `IP-Risk-Agent-1.0.0-win.zip`
  을 받아 압축 해제 후 `IP Risk Agent.exe` 실행 — 별도 설정 없이 운영 서비스에
  붙는다.

> **릴리스 v1.0.0** — `integration-v3` 에서 개발한 최종본을 `main` 에
> fast-forward 반영·태그. 배포 이미지 커밋 `347cbbf`, API/Worker 동일 digest
> (`sha256:4877e4ba…`).

## 핵심 가치

1. **지속 추적 (Continuous Monitoring)** — 점검 결과가 아니라 리스크의 생애를
   관리한다. 같은 리스크를 같은 것으로 이어서 추적하므로 확인할 것은 지난번 이후
   달라진 부분뿐이고, 한 번 내린 판단은 리스크에 계속 붙어 다닌다.
2. **근거 기반 (Evidence-grounded)** — 모든 결과에 실재하는 출처를 붙이고,
   제시된 목록에 없는 근거를 인용한 결과는 통째로 폐기한다. 확인되지 않으면
   내보내지 않는다.
3. **Human-in-the-Loop** — AI 는 판정하지 않는다. 검토가 필요한 지점을 좁혀
   사람에게 넘기는 데까지가 AI 의 역할이고, 처분은 사람의 것이며 분석 갱신이
   사람의 판단을 덮지 않는다.
4. **보안 (Security by Architecture)** — 원본을 넘기지 않아도 점검이 성립한다.
   원문 비저장·자격증명 최소화·fail-closed 게이트. Drive 는 폴더 공유 방식이라
   보관할 자격증명 자체가 없다.

## 팀

**PBL 2차 팀 프로젝트 · 5조 (IP RISK)**

| 이름 | 담당 |
|---|---|
| **윤결** (팀장) | Risk Intelligence Plane 개발 · RAG 파이프라인 구축 · License / Patent Risk 규칙 엔진 구축 · 발표 및 포트폴리오 |
| **이현** | 초기 명세·계약 구축 · Control Plane 개발 · 통합 및 배포 · E2E 테스트 |
| **이은우** | Source Integration Plane 개발 · 소스 별 커넥터 구축 · HITL 검토 및 구축 · 통합 보고서 문서화 |

## 무엇을 하는가

1. **폴더를 마운트한다.** 세 소스 모두 파일이 아니라 **폴더 단위**다.
   - **Google Drive** — 폴더를 서비스 계정 주소로 공유하고 링크를 붙여 넣으면
     끝이다. OAuth 동의 화면도, 보관되는 사용자 자격증명도 없다.
   - **GitHub** — GitHub App 설치에 있는 저장소를 redirect 없이 골라 잇는다.
   - **Local** — 데스크톱 앱이 폴더를 감시한다. 절대 경로는 기기 밖으로 나가지
     않는다.
2. **변경을 계속 감지한다.** Drive watch 채널, GitHub webhook, 로컬 watcher 가
   변경을 밀어 넣고, 주기적 대조(reconcile)가 새는 것을 줍는다.
3. **보안 게이트를 지나서만 분석한다.** `.ipriskignore` 정책, 비밀값 마스킹,
   최소화(발췌)가 분석 입력을 만들고, 원문 전체는 어디에도 저장되지 않는다.
   게이트는 등록·대조·가져오기의 정체성이 어긋나면 fail-closed 로 거부한다.
4. **근거와 함께 판정한다.**
   - **특허** — 문서에서 기술 요소를 뽑아 KIPRIS 를 검색하고, 모델 대조 결과는
     인용 실재 검증(grounding)을 통과한 것만 남는다. 화면은 원본 문장 ↔ 청구항을
     좌우로 놓고 겹친 구간을 하이라이트한다.
   - **라이선스** — 매니페스트 파싱 → 레지스트리 조회 → 전문 조회 → 조항 검색 →
     권장 행동의 5단계. 배포 형태(SaaS/배포/수정/링크)에 따라 판정이 달라진다.
     판정을 못 내린 건은 중간 등급에 묻히지 않고 **확인 필요(INDETERMINATE)** 로
     따로 올라온다.
5. **바깥의 변화도 잡는다.** 파일이 그대로여도 패키지가 라이선스를 바꾸면
   일일 재검증이 그것을 잡고, 이력에는 "우리가 바꿨는가, 바깥이 바뀌었는가" 의
   원인이 귀속되어 남는다.
6. **사람이 결론을 낸다.** 분석은 Risk 를 만들 뿐 처분(Monitoring · Accept)은
   사람의 것이고, 분석 갱신이 사람의 판단을 덮지 않는다. 모든 사건은 append-only
   이력으로 남고, 파일이 추적 범위로 되돌아오면 판본이 같을 때 이전 처분이
   복원된다.

## 화면

| 탭 | 내용 |
|---|---|
| Overview | 위험 요약 · 소스 건강 · **작업 현황**(분석 진행 바, 5초 폴링) |
| Files | 마운트한 폴더들의 **통합 파일 탐색기**. 파일을 누르면 그 파일의 Risk 목록으로 |
| Review | **파일 단위로 묶인** Risk. 상세는 원본 ↔ 근거 대조 + 하이라이트 + 처분 |
| Members & roles | 멤버 초대·역할 (OWNER / SOURCE_MANAGER / RISK_REVIEWER / VIEWER) |
| Activity & audit | Risk 사건 · 관리 행위 · 원문 접근 기록 (내보내기 지원) |
| Security & data | `.ipriskignore` 정책 · 보존 원칙 · workspace 삭제(전체 말소) |

## 아키텍처

```
 [Electron Desktop] ──┐                        ┌── KIPRIS Plus (특허 검색)
 [Web Browser] ───────┤                        ├── deps.dev · PyPI · npm (라이선스)
                      ▼                        ├── Vertex AI Gemini (추출·대조·설명)
        Cloud Run: ip-risk-agent-v2-api ───────┤── Vertex AI RAG Engine (조항 근거)
          · FastAPI + React 정적 서빙          │
          · 소스 연결/마운트/게이트/원장       ▼
        Cloud Run: ip-risk-agent-v2-worker ── 분석 파이프라인
                      │
        Firestore (ip-risk-agent-v2) · Secret Manager · Cloud Tasks
        Cloud Scheduler 5종 (watch 갱신 · 대조 · 정리 · 헬스 · 라이선스 재검증)
```

세 Plane 의 경계 — **Source Plane**(커넥터 3종)은 content-free `SourceChange` 를
만들고, **Control Plane**(게이트·Risk 원장)이 정책·수명주기와 canonical 상태를
소유하며, **Intelligence Plane**(License/Patent)은 공급된 스냅샷을 분석해 근거를
반환할 뿐 canonical 상태를 직접 바꾸지 않는다.

| 디렉터리 | 내용 |
|---|---|
| `backend/` | Python · FastAPI. API 와 Worker 가 **같은 이미지**, `APP_ROLE` 만 다름 |
| `frontend/` | React 19 + Vite. 빌드 산출물을 API 컨테이너가 서빙 |
| `apps/desktop/` | Electron. 로컬 폴더 감시·기기 등록. 화면은 배포된 웹을 그대로 실음 |
| `shared/contracts/` | Python·TypeScript 공용 계약 (**Frozen**) |
| `deploy/` | 리소스·IAM·빌드 계약 (검증 스크립트가 대조) |
| `scripts/` | RAG corpus 구축·적재, 배포 검증, 백필 등 운영 도구 |

## 설치

고정 툴체인: **CPython 3.14.7 · Node 24.19.0 · pnpm 11.19.0**
(`.python-version` / `.node-version` / lock 파일이 기준) · 배포·운영 시 gcloud CLI.

```bash
git clone https://github.com/2HyN/ip-risk-agent-v2.git
cd ip-risk-agent-v2

# 백엔드 — Dockerfile 과 같은 순서
python -m venv .venv
.venv/Scripts/pip install -r requirements.lock   # (macOS/Linux: .venv/bin/pip)
.venv/Scripts/pip install --no-deps -e .

# 프런트엔드 · 데스크톱 (pnpm workspace)
pnpm install
pnpm --filter @iprisk/contracts build
```

## 환경 변수

이름은 `.env.example` 에만 두고 **실제 값은 어디에도 기록하지 않는다.** Secret 은
Secret Manager 경유이며 서비스 계정 key 파일은 쓰지 않는다. 로컬
개발(`APP_ENV=local`)은 in-memory 저장소로 돌아 GCP 없이 시작할 수 있고,
운영(`APP_ENV=production`)은 `deploy/cloud-run-services.yaml` 계약대로 받는다.
핵심만 추리면:

| 변수 | 뜻 |
|---|---|
| `APP_ROLE` | `api` 또는 `worker` — 같은 이미지가 역할을 가른다 |
| `APP_ENV` | `local` / `production` |
| `SESSION_SECRET` | 세션 서명 키 |
| `GCP_PROJECT_ID` · `GCP_REGION` | GCP 프로젝트·리전 |
| `FIRESTORE_DATABASE` | `ip-risk-agent-v2` (v1 의 `(default)` 와 격리) |
| `GOOGLE_LOGIN_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` | Google OIDC 로그인 |
| `GOOGLE_DRIVE_SERVICE_ACCOUNT` | Drive 폴더를 공유받는 서비스 계정 주소 |
| `GITHUB_APP_ID` · `GITHUB_APP_SLUG` · `GITHUB_APP_PRIVATE_KEY_SECRET_ID` · `GITHUB_WEBHOOK_SECRET_ID` | GitHub App 연동 |
| `KIPRIS_API_KEY_SECRET_ID` | KIPRIS 접근 키의 Secret 이름 (키 자체는 파일·로그에 남기지 않는다) |
| `GEMINI_MODEL_ID` | 분석 모델 |
| `RAG_CORPUS_ID` · `RAG_CORPUS_VERSION` · `RAG_REGION` | 조항 근거 corpus |
| `CLOUD_TASKS_QUEUE` / `_LOCATION` / `_SERVICE_ACCOUNT` · `ANALYSIS_WORKER_URL` | 분석 작업 큐 |
| `LOCAL_STAGING_BUCKET` | 데스크톱 스냅샷 스테이징 버킷 |
| `DRIVE_WATCH_CHANNEL_TOKEN` | Drive watch 채널 검증 토큰 (Secret) |

데스크톱 앱: 포장본은 설정이 필요 없다. 개발 실행은 기본이 로컬 서버
(`http://127.0.0.1:8000`)이며 `IPRISK_SERVER_BASE_URL` 로 바꾼다.

## 실행

```bash
# 백엔드 API (로컬, in-memory)
APP_ROLE=api APP_ENV=local \
  .venv/Scripts/python -m uvicorn ip_risk_agent.main:create_app --factory --port 8000

# 프런트엔드 개발 서버
pnpm --filter @iprisk/frontend dev

# 데스크톱 앱 (로컬 서버 대상)
pnpm --filter @iprisk/desktop build
pnpm --filter @iprisk/desktop start
```

로그인·Drive·GitHub 등 외부 연동 기능은 해당 환경 변수와 GCP 자원이 있어야
동작한다. 전체 기능은 배포된 운영 서비스에서 확인하는 것이 가장 빠르다.

## 데이터 준비 (RAG corpus)

라이선스 조항 근거는 SPDX 라이선스 전문 672편 + 의무 해설 3편(총 675편)으로
구성되며, 판본 단위로 적재한다.

```bash
# ① SPDX 목록에서 라이선스 데이터 파생
.venv/Scripts/python scripts/generate_spdx_data.py

# ② corpus 문서 생성 → ③ 적재 전 검증(외부 쓰기 없음) → ④ RAG Engine 적재
.venv/Scripts/python scripts/build_rag_corpus.py
.venv/Scripts/python scripts/prepare_rag_ingestion.py
.venv/Scripts/python scripts/ingest_rag_corpus.py

# SPDX 갱신 확인부터 재적재·검증까지 한 명령으로
.venv/Scripts/python scripts/refresh_rag_corpus.py
```

적재 후 `RAG_CORPUS_ID` / `RAG_CORPUS_VERSION` 을 새 판본으로 올린다. corpus
판본은 조항 검색 캐시 키에 포함되므로 갱신해도 무효화가 필요 없고, 되돌리면 이전
캐시가 그대로 살아 있다. Firestore 복합 색인·TTL 은
`deploy/firestore.indexes.json` 이 기준이고 배포 검증기가 대조한다.

## 테스트

배포 전 게이트는 아래 전부다. 최종 릴리스(v1.0.0) 기준 **백엔드 1,137건 ·
프런트엔드 55건 · 데스크톱 83건** 통과.

```bash
# 컴파일·의존성 무결성
.venv/Scripts/python -m compileall -q backend/src shared/contracts/python scripts
.venv/Scripts/python -m pip check

# 백엔드 — 외부 API(live) 표식 제외 (KIPRIS 는 월 1,000회 한도이므로 live 는 신중히)
.venv/Scripts/python -m pytest tests -m "not live"

# 계약 생성물이 커밋과 일치하는지
pnpm run generate && git diff --exit-code -- shared/contracts

# 타입·빌드·의존성 해석
pnpm run typecheck && pnpm run build && pnpm run verify:resolution

# 프런트엔드 · 데스크톱
pnpm --filter @iprisk/frontend test
pnpm --filter @iprisk/desktop build && pnpm --filter @iprisk/desktop test

# 배포 계약 검증 (리소스·IAM·색인·이미지 계약의 일관성)
.venv/Scripts/python scripts/validate_gcp_deployment.py
```

외부 API 실호출 시험은 `-m live` 로 분리되어 있고, 실제 자격증명과 명시적
opt-in 없이는 실행하지 않는다.

## 배포 핵심 순서

Cloud Build 로 이미지 하나를 만들어 API·Worker 에 **같은 digest** 를 얹는다.

```bash
# ① 계약 검증
python scripts/validate_gcp_deployment.py

# ② 이미지 빌드 (smoke import 포함)
gcloud builds submit --config=deploy/cloudbuild.yaml --substitutions=SHORT_SHA=<커밋 SHA>

# ③ digest 조회
gcloud artifacts docker images describe \
  asia-northeast3-docker.pkg.dev/<PROJECT>/ip-risk-agent-v2/application:<SHORT_SHA> \
  --format="value(image_summary.digest)"

# ④ 두 서비스에 동일 digest 배포
gcloud run deploy ip-risk-agent-v2-api    --image <image@digest> --region asia-northeast3
gcloud run deploy ip-risk-agent-v2-worker --image <image@digest> --region asia-northeast3
```

Scheduler 5종·Cloud Tasks 큐·색인·IAM 은 `deploy/` 의 계약 파일이 기준이다.
v2 는 v1 과 프로젝트를 공유하므로 **v1 자원(`(default)` Firestore, `ipra-*`
Secret 등)의 재사용·IAM 변경은 금지**이며 검증기와 프로덕션 스타트업이
fail-closed 로 막는다. 롤백은 revision 지정 트래픽 전환. 데스크톱 릴리스는
`pnpm --filter @iprisk/desktop package` 로 zip 을 만들어 GitHub Releases 에
올린다.

## 보안 원칙

- **원문은 저장하지 않는다.** 남는 것은 최소 발췌와 판정·이력뿐이다.
- **자격증명 최소화.** Drive 는 공유 기반이라 보관할 토큰 자체가 없고, 로컬
  기기 자격증명은 OS 암호화 저장소에 있으며 기기 밖으로 나가지 않는다.
- **게이트는 fail-closed.** 정체성 불일치·정책 위반·읽기 실패는 분석 거부다.
- **근거 없는 결과는 도달하지 않는다.** 목록에 없는 근거 ID 를 인용한 AI 결과는
  전체 폐기된다.
- **로그 정책.** 토큰·키·원문·로컬 절대 경로는 로그에 남기지 않는다.
- **삭제는 전체 말소.** workspace 삭제는 자격증명 Secret 까지 지우며, 중단되면
  재시도로 이어서 끝난다.

## 문서

| 문서 | 지위 |
|---|---|
| `docs/DEVELOPMENT_SPEC.md` | **규범.** 무엇을 왜 만들었는가, 알려진 결함과 닫힌 자리 |
| `docs/DEVELOPMENT_PROGRESS.md` | 현재 상태 — 어디까지 왔고 무엇이 배포되어 있는가 |
| `docs/USAGE_VERIFICATION.md` | 사용 검증 절차 |
| `deploy/*.yaml` | 리소스·IAM·빌드 계약 (검증 스크립트가 대조) |

---

PBL 2차 팀 프로젝트 · 5조 (IP RISK) · 2026
