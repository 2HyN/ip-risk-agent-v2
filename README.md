# IP Risk Agent

**여러 협업 Source Workspace(Local · GitHub · Google Drive)를 하나의 Risk
Workspace 에 연결하고, 변경을 지속적으로 감지해 Patent·License 중심의 잠재적
IP Risk 를 근거 기반으로 분석함으로써, 사용자가 장기적으로 검토·추적·감사할 수
있게 하는 Secure Human-in-the-Loop AI Risk Management System.**

- 웹: https://ip-risk-agent-v2-api-555102774494.asia-northeast3.run.app
- 데스크톱 앱(로컬 폴더 마운트용, Windows):
  [Releases](../../releases) 최신판(v1.0.1)의 zip 을 받아 압축 해제 후
  `IP Risk Agent.exe` 실행 — 별도 설정 없이 운영 서비스에 붙는다.

> **릴리스는 `main` 이다.** `main` 에 병합되면 CI 게이트를 통과한 커밋만
> 자동으로 빌드·배포된다(아래 [배포](#6-배포--pr--main-병합이-곧-배포다) 참고).
> v1.0.0 은 2차 최종본 태그, 이후 최종 단계 고도화(특허 분석 재설계 · CI/CD ·
> UI 개편)는 main 에 연속 반영되어 있다.

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
4. **보안 (Security by Architecture)** — 원본을 보관하지 않아도 점검이
   성립한다. 분석은 게이트가 최소화(선별·상한·시크릿 삭제)한 사본의 일시
   전달로만 이루어지고, 남는 것은 인용 실재가 검증된 발췌뿐이다. fail-closed
   게이트. Drive 는 폴더 공유 방식이라 보관할 자격증명 자체가 없다.

## 팀

**PBL 최종 프로젝트 · 5조 (IP RISK)**

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
     좌우로 놓고 겹친 구간을 하이라이트한다. 검색·선별·대조 전 단계는 심사관
     인용 골든셋으로 실측하며 재설계했다(운영 조합 `fielded_v5 × hybrid` —
     5계열 질의 추출 · `*` AND 필드 검색 · BM25 재순위 · 정밀 채널 스크리닝 ·
     조각 근거 hybrid 대조. 실측 기록은 `docs/PATENT_RAG_ENHANCEMENT_PLAN.md`).
   - **라이선스** — 매니페스트 파싱 → 레지스트리 조회 → 전문 조회 → 조항 검색 →
     권장 행동의 5단계. 배포 형태(SaaS/배포/수정/링크)에 따라 판정이 달라지므로,
     **Security & data 의 배포 프로파일을 설정하기 전에는 등급을 짐작하지 않고
     전부 확인 필요(INDETERMINATE)** 로 둔다 — 설정을 저장하면 자동으로 재평가된다.
     판정을 못 내린 건은 중간 등급에 묻히지 않고 따로 올라온다.
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
| Security & data | `.ipriskignore` 정책 · **라이선스 배포 프로파일** · 데이터 처리 원칙 · workspace 삭제(전체 말소) |

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

---

# 빠른 시작 — 블록을 위에서 아래로 복사-실행

규칙은 셋뿐이다.

- **모든 블록은 bash 기준이다.** Windows 는 **Git Bash** 를 연다 (PowerShell ✗).
- **저장소 루트에서 실행한다.** 새 터미널을 열었으면 `cd ip-risk-agent-v2` 부터.
- 블록 안의 명령은 실패하면 거기서 멈추고, 끝까지 가면 `... OK` 를 찍는다.
  `OK` 가 안 보이면 그 블록의 마지막 출력이 원인이다.

각 블록 첫 줄의 `PY=...` 는 OS 에 맞는 가상환경 파이썬을 자동으로 고르는
한 줄이다 — 신경 쓰지 말고 같이 복사하면 된다.

## 0) 도구 준비 (기계당 1회)

[Python 3.14.7](https://www.python.org/downloads/) 과
[Node.js 24.19.0](https://nodejs.org/) 을 설치한 뒤 (Windows 는 Git Bash 포함
[Git](https://git-scm.com/) 도), 아래로 pnpm 을 맞추고 버전을 확인한다.

```bash
corepack enable && corepack prepare pnpm@11.19.0 --activate
python --version   # Python 3.14.x
node --version     # v24.x
pnpm --version     # 11.x
```

## 1) 받기

```bash
git clone https://github.com/2HyN/ip-risk-agent-v2.git
cd ip-risk-agent-v2
```

## 2) 설치 (백엔드 + 프런트엔드 + 데스크톱)

```bash
python -m venv .venv
PY=.venv/bin/python; [ -e .venv/Scripts/python.exe ] && PY=.venv/Scripts/python
$PY -m pip install -q -r requirements.lock \
&& $PY -m pip install -q --no-deps -e . \
&& $PY -c "import ip_risk_agent, iprisk_contracts" \
&& pnpm install \
&& pnpm --filter @iprisk/contracts build \
&& echo "INSTALL OK"
```

## 3) 로컬 실행

**터미널 1 — 백엔드** (GCP 없이 in-memory 로 돈다. `SESSION_SECRET` 은 즉석
생성 — 아무 값이든 32자 이상이면 된다):

```bash
PY=.venv/bin/python; [ -e .venv/Scripts/python.exe ] && PY=.venv/Scripts/python
APP_ROLE=api APP_ENV=local \
SESSION_SECRET=$($PY -c "import secrets;print(secrets.token_hex(32))") \
  $PY -m uvicorn ip_risk_agent.main:create_app --factory --port 8000
```

**터미널 2 — 프런트엔드** (저장소 루트에서):

```bash
pnpm --filter @iprisk/frontend dev
```

- 화면: http://localhost:5173 (dev 서버가 `/api` 를 8000 으로 프록시)
- 서버 확인: `curl http://127.0.0.1:8000/health/ready` →
  `"status":"ready"` 면 정상

**터미널 3 — 데스크톱 앱** (선택, 로컬 서버 대상):

```bash
pnpm --filter @iprisk/desktop build && pnpm --filter @iprisk/desktop start
```

로컬 실행에서 로그인·Drive·GitHub 같은 외부 연동은 동작하지 않는다(해당 환경
변수 묶음과 GCP 자원이 필요 — 아래 [환경 변수](#환경-변수) 참고). 전체 기능은
배포된 운영 서비스에서 확인하는 것이 가장 빠르다.

## 4) 테스트 — 전체 게이트 한 블록

배포 전 게이트 전부다. 마지막에 `ALL GATES PASSED` 가 나와야 한다.
최종 기준 **백엔드 1,205건 · 프런트엔드 62건 · 데스크톱 83건** 통과 —
새로 clone 한 환경에서도 같은 결과를 재검증했다.

```bash
PY=.venv/bin/python; [ -e .venv/Scripts/python.exe ] && PY=.venv/Scripts/python
$PY -m compileall -q backend/src shared/contracts/python scripts \
&& $PY -m pip check \
&& $PY -m pytest tests -m "not live" -q --basetemp .pytest-tmp \
&& $PY scripts/generate_contracts.py \
&& git diff --exit-code -- shared/contracts \
&& pnpm run typecheck && pnpm run build && pnpm run verify:resolution \
&& pnpm --filter @iprisk/frontend test \
&& pnpm --filter @iprisk/desktop test \
&& $PY scripts/validate_gcp_deployment.py \
&& echo "ALL GATES PASSED"
```

(백엔드 pytest 가 5~10분으로 가장 길다. 외부 API 실호출 시험은 `-m live` 로
분리되어 있고, 실제 자격증명과 명시적 opt-in 없이는 실행하지 않는다. KIPRIS 는
유료 등록으로 월 한도가 없으며 **초당 호출 제한만** 지키면 된다 — 공용 키라
호출 간격 규율이 코드(토큰버킷·큐 동시 상한)에 배선되어 있다.)

## 5) 데이터 준비 — RAG corpus

라이선스 조항 근거는 SPDX 라이선스 전문 672편 + 의무 해설 3편(총 675편)이다.
**①~③은 자격증명 없이 돈다** (SPDX 목록을 내려받으므로 네트워크만 필요):

```bash
PY=.venv/bin/python; [ -e .venv/Scripts/python.exe ] && PY=.venv/Scripts/python
$PY scripts/generate_spdx_data.py \
&& $PY scripts/build_rag_corpus.py \
&& $PY scripts/prepare_rag_ingestion.py \
&& echo "CORPUS READY"
```

**④ 실제 적재는 팀 GCP 프로젝트 권한이 필요하다** (Vertex AI RAG Engine).
운영 corpus 는 이미 적재되어 있으므로(판본 `2026-08-23.4`) 판본을 갱신할 때만
실행한다:

```bash
gcloud auth application-default login
PY=.venv/bin/python; [ -e .venv/Scripts/python.exe ] && PY=.venv/Scripts/python
$PY scripts/ingest_rag_corpus.py
# SPDX 갱신 확인부터 재적재·검증까지 한 명령: $PY scripts/refresh_rag_corpus.py
```

적재 후 `RAG_CORPUS_ID` / `RAG_CORPUS_VERSION` 을 새 판본으로 올린다. corpus
판본은 조항 검색 캐시 키에 포함되므로 갱신해도 무효화가 필요 없고, 되돌리면
이전 캐시가 그대로 살아 있다.

## 6) 배포 — PR → main 병합이 곧 배포다

배포는 자동이다. Cloud Build 트리거 2개(`asia-northeast3`)가 저장소에 연결되어
있다:

- **`ci-pr`** — `main` 대상 PR 이 열리거나 갱신되면 `deploy/cloudbuild-ci.yaml`
  이 실행된다(검증만, 배포 없음): 런타임과 같은 환경의 pytest + 계약 드리프트
  검사, pip-audit(차단형), node 트랙(typecheck·verify:resolution·frontend
  vitest·desktop build+test·pnpm audit).
- **`deploy-main`** — `main` 에 push(병합)되면 `deploy/cloudbuild-cd.yaml` 이
  **7단계**로 실행된다: ① pytest 게이트 → ② docker build → ③④ API·Worker
  import 스모크 → ⑤ Artifact Registry push → ⑥ **같은 digest** 를 두 Cloud Run
  서비스에 배포 → ⑦ 배포 후 `api /health/ready` 200 검증(실패 시 빌드 FAILURE).
  게이트를 통과하지 못한 커밋은 이미지를 만들지도 배포하지도 않는다.

그래서 표준 릴리스 절차는 이것뿐이다:

```bash
git push origin <기능브랜치>      # PR 생성 → ci-pr 통과 확인
# PR 을 main 에 병합 → deploy-main 이 빌드·배포·헬스 검증까지 자동 수행
curl -s https://ip-risk-agent-v2-api-555102774494.asia-northeast3.run.app/health/ready
```

**주의: `main` 푸시 = 배포 행위다.** 문서 하나만 바꿔도 재빌드·재배포가 돈다.
배포 명령(`gcloud run deploy`)은 `--image` 만 갱신하므로 서비스 env(분석 전략
설정 포함)는 보존된다. 롤백은 이전 이미지 digest 재지정.

**수동 경로(보조)** — 트리거를 우회해야 할 때만. 팀 프로젝트 권한(Cloud Build
제출, `iprisk-v2-deploy` actAs, Cloud Run 배포)이 필요하다. 수동 제출은
`.gcloudignore` 가 `tests/` 를 빼므로 `cloudbuild.yaml`(빌드·스모크까지만)을
쓴다 — `cloudbuild-cd.yaml` 을 수동 제출하면 pytest 단계가 소스 부재로 실패한다:

```bash
SHA=$(git rev-parse --short HEAD)
IMG="asia-northeast3-docker.pkg.dev/proj-aj22-211200020328/ip-risk-agent-v2/application"
gcloud builds submit --config=deploy/cloudbuild.yaml \
  --substitutions=SHORT_SHA=$SHA --region asia-northeast3 \
&& DIGEST=$(gcloud artifacts docker images describe "$IMG:$SHA" \
     --format="value(image_summary.digest)") \
&& gcloud run deploy ip-risk-agent-v2-api    --image "$IMG@$DIGEST" --region asia-northeast3 --quiet \
&& gcloud run deploy ip-risk-agent-v2-worker --image "$IMG@$DIGEST" --region asia-northeast3 --quiet \
&& echo "DEPLOYED $SHA @ $DIGEST"
```

**데스크톱 릴리스** (zip 을 만들어 GitHub Releases 에 올린다 — 데스크톱은 화면을
배포된 웹에서 불러오는 셸이라, 웹 변경은 재릴리스 없이 반영되고 **main process
변경(메뉴·마운트 등록 등)만 재패키징이 필요하다**):

```bash
pnpm --filter @iprisk/desktop build && pnpm --filter @iprisk/desktop package
ls apps/desktop/release/
```

Scheduler 5종·Cloud Tasks 큐·색인·IAM 은 `deploy/` 의 계약 파일이 기준이다.
v2 는 v1 과 프로젝트를 공유하므로 **v1 자원(`(default)` Firestore, `ipra-*`
Secret 등)의 재사용·IAM 변경은 금지**이며 검증기와 프로덕션 스타트업이
fail-closed 로 막는다. 롤백은 revision 지정 트래픽 전환.

---

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
| `SESSION_SECRET` | 세션 서명 키 — **32자 이상, `APP_ROLE=api` 면 `APP_ENV=local` 에서도 필수** |
| `GCP_PROJECT_ID` · `GCP_REGION` | GCP 프로젝트·리전 |
| `FIRESTORE_DATABASE` | `ip-risk-agent-v2` (v1 의 `(default)` 와 격리) |
| `GOOGLE_LOGIN_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` | Google OIDC 로그인 |
| `GOOGLE_DRIVE_SERVICE_ACCOUNT` | Drive 폴더를 공유받는 서비스 계정 주소 |
| `GITHUB_APP_ID` · `GITHUB_APP_SLUG` · `GITHUB_APP_PRIVATE_KEY_SECRET_ID` · `GITHUB_WEBHOOK_SECRET_ID` | GitHub App 연동 |
| `KIPRIS_API_KEY_SECRET_ID` | KIPRIS 접근 키의 Secret 이름 (키 자체는 파일·로그에 남기지 않는다) |
| `PATENT_SEARCH_STRATEGY` · `PATENT_COMPARE_STRATEGY` | 특허 분석 전략 (운영 확정: `fielded_v5` × `hybrid` — 미설정 시 baseline, 이전 전략은 비교 기준선으로 보존) |
| `KIPRIS_MAX_RPS` | 인스턴스당 KIPRIS 초당 호출 상한 (운영 2.0 — 큐 동시 8 과 함께 합산 16rps 보장) |
| `GEMINI_MODEL_ID` | 분석 모델 |
| `RAG_CORPUS_ID` · `RAG_CORPUS_VERSION` · `RAG_REGION` | 조항 근거 corpus |
| `CLOUD_TASKS_QUEUE` / `_LOCATION` / `_SERVICE_ACCOUNT` · `ANALYSIS_WORKER_URL` | 분석 작업 큐 |
| `LOCAL_STAGING_BUCKET` | 데스크톱 스냅샷 스테이징 버킷 |
| `DRIVE_WATCH_CHANNEL_TOKEN` | Drive watch 채널 검증 토큰 (Secret) |

데스크톱 앱: 포장본은 설정이 필요 없다. 개발 실행은 기본이 로컬 서버
(`http://127.0.0.1:8000`)이며 `IPRISK_SERVER_BASE_URL` 로 바꾼다.

**`.env` 파일은 자동으로 읽히지 않는다** — `main.py` 가
`Settings.from_env(os.environ)` 으로 OS 환경변수만 보므로(`load_dotenv` 없음),
파일로 관리하려면 셸에서 직접 export 한다:

```bash
cp .env.example .env        # SESSION_SECRET= 뒤에 32자 이상 값을 채운다
set -a; source .env; set +a
PY=.venv/bin/python; [ -e .venv/Scripts/python.exe ] && PY=.venv/Scripts/python
$PY -m uvicorn ip_risk_agent.main:create_app --factory --port 8000
```

외부 연동 변수는 **묶음 단위 전부-또는-전무** 검사를 받는다(Google 로그인 ·
Drive watch · GitHub App · Cloud Tasks · RAG). 일부만 채우면 기동 시
`SettingsError` 가 나므로, 로컬은 `SESSION_SECRET` 만 넣고 나머지는 전부
비워 두고 시작한다.

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
| `docs/PATENT_RAG_ENHANCEMENT_PLAN.md` | 특허 분석 고도화 — 전략 계보·골든셋 실측·채택/기각 근거 |
| `docs/PATENT_VERIFICATION_LEDGER.md` | 누적 검증 원장 — 환경 감사·CI/CD 검증·라이브 실측 기록 |
| `docs/USAGE_VERIFICATION.md` | 사용 검증 절차 |
| `deploy/*.yaml` | 리소스·IAM·빌드 계약 (검증 스크립트가 대조) |

---

PBL 최종 프로젝트 · 5조 (IP RISK) · 2026
