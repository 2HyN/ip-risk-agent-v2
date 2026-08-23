# IP Risk Agent

**Local · GitHub · Google Drive 를 하나의 Risk Workspace 로 잇고, 변경을 계속
감지해 특허·라이선스 위험을 근거와 함께 분석하는 Secure Human-in-the-Loop
IP 리스크 관리 시스템.**

- 웹: https://ip-risk-agent-v2-api-555102774494.asia-northeast3.run.app
- 데스크톱 앱(로컬 폴더 마운트용): [Releases](../../releases) 에서 zip 을 받아
  압축 해제 후 `IP Risk Agent.exe` 실행 — 별도 설정 없이 운영 서비스에 붙는다.

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
5. **바깥의 변화도 잡는다.** 파일이 그대로여도 패키지가 라이선스를 바꾸면
   일일 재검증이 그것을 잡고, 이력에는 "우리가 바꿨는가, 바깥이 바뀌었는가" 의
   원인이 귀속되어 남는다.
6. **사람이 결론을 낸다.** 분석은 Risk 를 만들 뿐 처분(Monitoring · Accept)은
   사람의 것이고, 분석 갱신이 사람의 판단을 덮지 않는다. 모든 사건은 append-only
   이력으로 남는다.

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
 [Web Browser] ───────┤                        ├── Vertex AI Gemini (대조·설명)
                      ▼                        │
        Cloud Run: ip-risk-agent-v2-api ───────┤
          · FastAPI + React 정적 서빙          │
          · 소스 연결/마운트/게이트/원장       ▼
        Cloud Run: ip-risk-agent-v2-worker ── 분석 파이프라인
                      │
        Firestore (ip-risk-agent-v2) · Secret Manager · Cloud Tasks
        Cloud Scheduler 5종 (watch 갱신 · 대조 · 라이선스 재검증 등)
```

- `backend/` — Python 3.14 · FastAPI. API 와 Worker 가 **같은 이미지**로
  배포되어 역할(APP_ROLE)만 다르다.
- `frontend/` — React 19 + Vite. 빌드 산출물을 API 컨테이너가 서빙한다.
- `apps/desktop/` — Electron. 로컬 폴더 감시와 기기 등록(자격증명은 OS 암호화
  저장)만 맡고, 화면은 배포된 웹을 그대로 싣는다.
- `shared/contracts/` — Python·TypeScript 공용 계약 (Frozen).
- `deploy/` — 리소스·IAM·빌드 계약. `scripts/validate_gcp_deployment.py` 가
  계약 일관성을 검증한다.

## 보안 원칙

- **원문은 저장하지 않는다.** 남는 것은 최소 발췌와 판정·이력뿐이다.
- **자격증명 최소화.** Drive 는 공유 기반이라 보관할 토큰 자체가 없고, 로컬
  기기 자격증명은 기기 밖으로 나가지 않는다.
- **게이트는 fail-closed.** 정체성 불일치·정책 위반·읽기 실패는 분석 거부다.
- **로그 정책.** 토큰·키·원문·로컬 절대 경로는 로그에 남기지 않는다.
- **삭제는 전체 말소.** workspace 삭제는 상태 변경이 아니라 데이터(자격증명
  Secret 포함) 제거이고, 중단되면 재시도로 이어서 끝난다.

## 개발

요구 사항: Python 3.14 · Node 24 · pnpm 11 · (배포 시) gcloud.

```bash
# 백엔드 시험 (외부 API 를 부르는 live 표식 제외)
python -m pytest tests -m "not live"

# 프런트엔드
pnpm --filter @iprisk/frontend test
pnpm --filter @iprisk/frontend build

# 데스크톱
pnpm --filter @iprisk/desktop build     # tsc
pnpm --filter @iprisk/desktop test
pnpm --filter @iprisk/desktop start     # 로컬 서버(127.0.0.1:8000) 대상
pnpm --filter @iprisk/desktop package   # 릴리스 zip (운영 서버 기본)
```

배포는 Cloud Build 로 이미지 하나를 만들어 API·Worker 에 같은 digest 를 얹는다.

```bash
gcloud builds submit --config=deploy/cloudbuild.yaml --substitutions=SHORT_SHA=<sha>
gcloud run deploy ip-risk-agent-v2-api    --image <image@digest> --region asia-northeast3
gcloud run deploy ip-risk-agent-v2-worker --image <image@digest> --region asia-northeast3
```

## 문서

| 문서 | 지위 |
|---|---|
| `docs/DEVELOPMENT_SPEC.md` | **규범.** 무엇을 왜 만들었는가, 알려진 결함과 닫힌 자리 |
| `docs/DEVELOPMENT_PROGRESS.md` | 현재 상태 — 어디까지 왔고 무엇이 배포되어 있는가 |
| `deploy/*.yaml` | 리소스·IAM·빌드 계약 (검증 스크립트가 대조) |
| `docs/USAGE_VERIFICATION.md` | 사용 검증 절차 |

---

PBL 2차 팀 프로젝트 · 5조 · 2026
