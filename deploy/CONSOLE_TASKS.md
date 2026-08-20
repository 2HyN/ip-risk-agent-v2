# Cloud Console 과제

**코드로 할 수 있는 일은 전부 끝났다.** 여기 남은 것은 GCP Console 또는
`gcloud` 로 사람이 직접 자원을 만들고 값을 넣어야 하는 작업뿐이다.

각 과제마다 **끝났는지 확인하는 방법**을 함께 적었다. 대부분 `/health` 하나로
확인된다.

```bash
curl -s https://<API-URL>/health | jq
```

---

## 순서 요약

```
1. 프로젝트·API·서비스계정
2. Firestore + 인덱스
3. Artifact Registry
4. 1차 배포 → 배포 URL 확보     ← 여기가 분기점. OAuth 등록에 URL 이 필요하다
5. Secret Manager
6. Google 로그인 등록
7. Cloud Tasks + 워커 연결
8. GCS staging 버킷
9. Google Drive 앱 등록
10. GitHub App 등록
11. Intelligence (Gemini · KIPRIS · RAG)
12. Cloud Scheduler
13. 모니터링·비용
14. 최종 점검
```

---

## 1. 프로젝트 · API · 서비스 계정

**콘솔**

- 프로젝트 생성, 결제 계정 연결
- API 활성화: Firestore, Cloud Run, Cloud Tasks, Secret Manager, Cloud Storage,
  Cloud Scheduler, Artifact Registry, Vertex AI
- 서비스 계정 4개 생성

| 계정 | 필요한 역할 |
|---|---|
| `app-api-sa` | Datastore User, Secret Manager Secret Accessor, Cloud Tasks Enqueuer, Storage Object Admin |
| `analysis-worker-sa` | Datastore User, Secret Manager Secret Accessor, Storage Object Viewer, Vertex AI User |
| `scheduler-sa` | Cloud Run Invoker |
| `deploy-sa` | Cloud Run Admin, Artifact Registry Writer, Service Account User |

**리전** — 앱·Firestore 는 `asia-northeast3`(서울). RAG Engine 만 외부 GA 리전.

✅ `gcloud services list --enabled` 에 위 API 가 전부 보인다.

---

## 2. Firestore + 인덱스

**콘솔**

- Firestore **Native 모드** 데이터베이스 생성 (서울)

**gcloud** — 인덱스 생성 스크립트는 코드에서 이미 만들어져 있다.

```bash
bash deploy/firestore/create-indexes.sh
```

> 인덱스 8개는 `scripts/generate_firestore_indexes.py` 가 코드의
> `REQUIRED_COMPOSITE_INDEXES` 에서 만든다. **손으로 고치지 않는다.**
>
> gcloud 는 인덱스를 하나씩 개별 플래그로 받는다. `firestore.indexes.json` 은
> Firebase CLI 형식이라 gcloud 에 그대로 넘길 수 없다. 둘 다 같은 manifest 에서
> 생성한다. 이미 있는 인덱스는 `ALREADY_EXISTS` 로 실패하는데 정상이다.
> 코드가 바뀌면 스크립트를 다시 돌린다.

✅ 배포 후 `/health` 의 `control_backend` 가 `"firestore"`.

---

## 3. Artifact Registry

```bash
gcloud artifacts repositories create ip-risk-agent \
  --repository-format=docker --location=$REGION
```

✅ `gcloud artifacts repositories list` 에 보인다.

---

## 4. 1차 배포 — 여기서 URL 을 얻는다

**이 순서가 중요하다.** Google 로그인과 Drive/GitHub OAuth 는 공개 HTTPS 콜백
URL 을 **미리 등록**해야 한다. 배포를 마지막에 하면 6·9·10 단계에서 막힌다.

```bash
export PROJECT_ID=... REGION=asia-northeast3
./deploy/deploy.sh
```

최소 환경변수만 넣고 배포한다 (`deploy/cloudrun/api.env.example` 참고).

```
APP_PUBLIC_BASE_URL, SESSION_SECRET, GCP_PROJECT_ID, FIRESTORE_DATABASE
```

✅ `https://<API-URL>/health` 가 200. 로그인은 아직 502 — 정상이다.

---

## 5. Secret Manager

**콘솔** — 아래 secret 을 만들고 Cloud Run 이 주입하도록 연결한다.

| Secret | 쓰는 곳 |
|---|---|
| `session-secret` | API. **최소 32자.** 없으면 재시작마다 전원 로그아웃 |
| `google-login-client-secret` | API |
| `google-drive-client-secret` | API · 워커 |
| `drive-watch-channel-token` | API |
| `github-app-private-key` | API · 워커 (PEM 전문) |
| `github-webhook-secret` | API |
| `gemini-api-key` | 워커 |
| `kipris-access-key` | 워커 |

```bash
gcloud run services update ip-risk-agent-api --region=$REGION \
  --set-secrets=SESSION_SECRET=session-secret:latest,...
```

> 코드는 `SecretManagerCredentialVault` 로 **Drive OAuth 토큰을 런타임에
> 저장·갱신**한다. 위 목록은 그것과 별개로 배포가 주입해야 하는 값이다.

✅ `/health` 의 `credential_vault` 가 `SecretManagerCredentialVault`.

---

## 6. Google 로그인 등록

**콘솔**

- OAuth 동의 화면 구성
- OAuth 2.0 클라이언트 ID 생성
- 승인된 리디렉션 URI: `https://<API-URL>/api/v1/auth/google/callback`

**환경변수** — `GOOGLE_LOGIN_CLIENT_ID`, `GOOGLE_LOGIN_CLIENT_SECRET`(secret),
`GOOGLE_LOGIN_REDIRECT_URI`

✅ `/health` 의 `google_login` 이 `"configured"`.
✅ 브라우저에서 로그인 → VWS 생성 → Dashboard 가 뜬다. **제품이 처음 보이는 지점.**

---

## 7. Cloud Tasks + 워커 연결

**콘솔 / gcloud**

```bash
gcloud tasks queues create analysis-queue --location=$REGION
gcloud tasks queues update analysis-queue --location=$REGION \
  --max-attempts=5 --max-concurrent-dispatches=10 \
  --max-dispatches-per-second=10 --min-backoff=10s --max-backoff=300s
```

설정값 근거는 `deploy/cloudtasks/queue.yaml` 에 적어 두었다.

**워커 호출 권한** — 워커는 공개하지 않는다.

```bash
gcloud run services add-iam-policy-binding ip-risk-agent-worker \
  --region=$REGION --member=serviceAccount:$TASKS_SA --role=roles/run.invoker
```

**환경변수 (API)**

```
CLOUD_TASKS_LOCATION=$REGION
CLOUD_TASKS_QUEUE=analysis-queue
ANALYSIS_WORKER_URL=https://<WORKER-URL>/internal/analysis/dispatch
CLOUD_TASKS_SERVICE_ACCOUNT=<tasks SA 이메일>
```

> 코드는 `change_event_id` 로 task 이름을 만들어 **같은 ID 를 중복 적재하지
> 않는다.** 워커는 그 ID 로 relay 저장소에서 `SourceChange` 를 되찾아 실행한다.

✅ `/health` 의 `queue` 가 `"cloud-tasks"`.
✅ 변경 이벤트 발생 시 큐에 작업이 쌓이고 워커 로그에 처리 기록이 남는다.

---

## 8. GCS staging 버킷

```bash
gcloud storage buckets create gs://<BUCKET> --location=$REGION \
  --uniform-bucket-level-access
gcloud storage buckets update gs://<BUCKET> \
  --lifecycle-file=deploy/storage/staging-lifecycle.json
```

**환경변수** — `LOCAL_STAGING_BUCKET`, `IPRISK_SERVER_BASE_URL`(데스크톱 배포용)

> 수명주기 규칙은 **필수**다. 원본을 오래 두지 않는 것이 이 버킷의 존재 이유이며,
> Agent 2 보안 체크리스트 17번이 문서화만 되고 미완인 채로 남아 있던 항목이다.

✅ `/health` 의 `staging_store` 가 `GcsLocalStagingStore`.
✅ 파일 수정 → GCS 에 객체 생성 → 2일 후 자동 삭제.

---

## 9. Google Drive 앱 등록

**콘솔**

- Drive API 활성화
- OAuth 클라이언트 생성 (scope: `drive.file`)
- 리디렉션 URI 등록
- Drive push notification 도메인 소유 확인

**환경변수** — `GOOGLE_DRIVE_CLIENT_ID`, `..._SECRET`(secret), `..._REDIRECT_URI`,
`GOOGLE_DRIVE_WEBHOOK_BASE_URL`, `DRIVE_WATCH_CHANNEL_TOKEN`(secret)

✅ `/health` 의 `sources.mounted` 에 `google_drive:oauth`, `:mounts`, `:webhook`
세 개가 모두 보인다.

---

## 10. GitHub App 등록

**GitHub (GCP 아님)**

- GitHub App 생성
- Webhook URL: `https://<API-URL>/webhooks/github`
- Webhook secret 생성
- Private key 발급 (PEM)
- 권한: Contents(Read), Metadata(Read)
- Callback URL 등록

**환경변수** — `GITHUB_APP_ID`, `GITHUB_APP_SLUG`, `GITHUB_APP_CALLBACK_URL`,
`GITHUB_APP_PRIVATE_KEY`(secret), `GITHUB_WEBHOOK_SECRET`(secret)

> `GITHUB_WEBHOOK_SECRET` 이 없으면 코드가 **webhook 라우터를 아예 붙이지
> 않는다.** 서명 검증 없이 받으면 위조 요청을 신뢰하게 되기 때문이다.

✅ `sources.mounted` 에 `github:install`, `:mounts`, `:webhook` 이 모두 보인다.

---

## 11. Intelligence — Gemini · KIPRIS · RAG

**Gemini** — 🔴 **모델 식별자를 팀이 확정해야 한다.**
명세의 "Gemini 3.6 Flash" 는 실재하지 않는 값이다. 검증에는
`gemini-3-flash-preview` 를 썼다. 이 값은 분석 결과의 `versions.model_id` 에
기록되므로, 나중에 바꾸면 과거 판정을 설명할 수 없게 된다.

**KIPRIS** — KIPRIS Plus 에서 API 키 발급 → Secret Manager 에 저장

**RAG Engine** — 외부 GA 리전에 corpus 생성 후 `rag-corpus/sources/` 3건 업로드

> 🔴 **corpus 업로드는 콘솔/`gcloud` 로 해야 한다.** 코드에 RAG Engine 업로더가
> 없다 (`CorpusUploader` 구현체가 `InMemoryCorpusUploader` 뿐). 매니페스트 검증·
> 체크섬 대조·정규화까지는 코드가 하지만 실제 전송 경로가 없다.

**환경변수** — `GEMINI_MODEL_ID`, `GEMINI_API_KEY`(secret),
`KIPRIS_ACCESS_KEY`(secret), `RAG_REGION`, `RAG_CORPUS_ID`, `RAG_CORPUS_VERSION`

선택 — `RAG_DISTANCE_THRESHOLD` (기본 `0.6`). corpus 에 없는 라이선스에 엉뚱한
근거가 붙는 것을 막는 값이다. 끄려면 `none` 을 명시해야 한다.

✅ `/health` 의 `intelligence` 가 `"enabled"`.
✅ 실제 Risk 가 Dashboard 에 나타난다.

---

## 12. Cloud Scheduler

```bash
gcloud scheduler jobs create http drive-watch-renewal \
  --location=$REGION --schedule="0 */6 * * *" \
  --uri=https://<WORKER-URL>/internal/... \
  --oidc-service-account-email=$SCHEDULER_SA
```

- Drive watch 채널 갱신 (만료 전)
- reconciliation 정기 실행

> 갱신 엔드포인트는 아직 코드에 없다. Drive watch 를 실제로 쓰기 시작할 때
> 워커에 추가한다.

---

## 13. 모니터링 · 비용

- **Cloud Logging** — `StructuredLogger` 출력 확인. 원본·토큰·절대경로가
  기록되지 않는지 실제 로그로 검증
- **알림** — 워커 실패율, 큐 적체, dead-letter 유입
- **비용 한도** — Gemini · KIPRIS · RAG 호출량. 특허 후보 상위 6건 제한이 이미
  코드 레벨 통제 장치다

---

## 14. 최종 점검

| 항목 | 확인 방법 |
|---|---|
| 배포 URL 접근 | 브라우저 |
| `/health` 의 `sources.skipped` 가 `{}` | curl |
| 모든 백엔드가 in-memory 가 아님 | `/health` 필드 6개 |
| **`FIRESTORE_EMULATOR_HOST` 가 production 에 없음** | Cloud Run 환경변수 |
| `/internal/analysis/*` 가 외부에서 차단됨 | 인증 없이 호출 → 403 |
| staging 버킷 TTL 이 실제로 걸림 | `gcloud storage buckets describe` |
| Secret 이 로그·응답에 없음 | Cloud Logging 검색 |
| 재배포 후 세션 유지 | 로그인 후 재배포 → 세션 살아 있음 |

---

## 코드가 이미 해결해 둔 것 (콘솔 작업 아님)

혼동을 막기 위해 적어 둔다. 아래는 **환경변수만 넣으면 자동 전환**된다.

| 자원 | 전환 조건 |
|---|---|
| Firestore 저장소 | `GCP_PROJECT_ID` + `FIRESTORE_DATABASE` |
| Secret Manager vault | 위와 동일 |
| Firestore OAuth state | 위와 동일 (다중 인스턴스 필수) |
| Firestore change relay | 위와 동일 |
| Cloud Tasks | `CLOUD_TASKS_*` 4개 |
| GCS staging | `LOCAL_STAGING_BUCKET` |
| Drive/GitHub 라우터 | 각 provider 자격증명 |
| Intelligence | `GEMINI_MODEL_ID` |

값이 없으면 in-memory 로 내려가고, **무엇이 왜 그런지 `/health` 가 밝힌다.**
반쯤 조립된 상태로 런타임에 실패하는 경로는 만들지 않았다.
