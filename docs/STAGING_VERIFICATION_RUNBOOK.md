# Staging and live verification runbook

이 문서는 Phase 9의 GCP 외부 작업을 시작하기 위한 실행 순서와 증거 형식을
고정한다. Phase 7/8에서는 아래 명령을 **실행하지 않는다**. 실제 project, IAM,
provider credential과 비용 발생 resource가 준비된 staging 환경에서 명시적으로
승인받은 뒤 수행한다.

## 1. 진입 조건

- release candidate commit SHA와 container image digest가 기록되어 있다.
- `scripts/validate_gcp_deployment.py`와 전체 non-live suite가 같은 SHA에서 통과했다.
- API, Worker, Cloud Tasks caller, Scheduler caller, Deploy service account가 분리됐다.
- Secret 값은 저장소와 build log에 없고 Secret Manager 또는 secret-mapped environment로만 주입된다.
- callback/webhook URL, Firestore database ID, queue/bucket/RAG region이 확정됐다.
- rollback 대상의 직전 안정 Cloud Run revision과 secret version이 기록됐다.
- shared project가 `proj-aj22-211200020328`이고 `deploy/v2-resource-contract.yaml`의 모든
  canonical v2 이름이 확정됐다. v1 resource에는 변경 계획이 없다.

하나라도 충족하지 못하면 외부 작업을 시작하지 않는다.

## 2. 배포 전 repository 검증

project venv를 먼저 활성화한다. Windows Git Bash는 `source .venv/Scripts/activate`,
PowerShell은 `.\.venv\Scripts\Activate.ps1`을 사용한다. `fastapi`, `yaml`, `google` import
실패나 pytest의 `asyncio_mode` 미인식은 system Python 실행 신호이므로 dependency를 우회하지
말고 venv/lock 설치부터 복구한다.

```powershell
python -m compileall -q backend/src shared/contracts/python scripts
python -m pip check
python -m pytest shared/contracts/tests tests/control tests/connectors tests/intelligence tests/integration tests/e2e -m "not live"
pnpm run generate
git diff --exit-code -- shared/contracts
pnpm run typecheck
pnpm run build
pnpm run verify:resolution
pnpm --filter @iprisk/frontend test
pnpm --filter @iprisk/desktop test
pnpm install --frozen-lockfile
python scripts/validate_gcp_deployment.py
python scripts/prepare_rag_ingestion.py
```

Docker/Cloud Build에서는 같은 commit으로 image를 만들고 digest를 고정한다. `latest`
tag만으로 release evidence를 남기지 않는다.

## 3. resource 순서

1. shared project와 v1 보호 목록 재확인, API enablement와 v2 Artifact Registry
2. API/Worker/Tasks/Scheduler/Deploy service account와 최소 IAM binding
3. Firestore database, `deploy/firestore.indexes.json` index/TTL
4. uniform bucket-level access staging bucket와 `deploy/storage-lifecycle.json`
5. Secret Manager secret와 초기 version
6. private Worker Cloud Run revision
7. Cloud Tasks queue와 Tasks caller→Worker invoker binding
8. public API Cloud Run revision와 Scheduler caller→API invoker binding
9. Scheduler jobs
10. RAG corpus upload 및 corpus version 고정
11. OAuth consent, Drive callback/watch, GitHub App callback/webhook
12. domain/TLS와 browser key/origin restriction

각 단계는 생성된 resource ID와 검증 결과를 남긴 뒤 다음으로 진행한다.

## 4. live test opt-in

기본 test command는 `live`를 제외한다. 실제 provider test는 shared project 안의 v2
resource와 최소 권한 test account에서만 명시적으로 선택한다.

```powershell
python -m pytest tests/intelligence/test_live_providers.py -m live -vv
```

추가 live smoke는 다음 순서를 따른다.

| 흐름 | 성공 증거 | 필수 negative case |
|---|---|---|
| Google login | session 발급 후 `/api/v1/auth/me` | 잘못된 state/replay 거부 |
| Drive | OAuth→Picker 선택→mount→fetch→watch/reconcile | 선택하지 않은 file, 잘못된 channel token 거부 |
| GitHub | App install→private repo/branch mount→signed push | 잘못된 HMAC와 다른 repo/path 거부 |
| Local | enrollment→mount→staging→event→cleanup | challenge replay, 다른 device/mount, path escape 거부 |
| Worker | ID-only Cloud Tasks OIDC delivery→terminal job | 사용자 session/static bearer, duplicate delivery 거부/무해화 |
| Intelligence | Gemini structured output, KIPRIS 0건/실패 구분 | malformed/partial provider 결과를 success로 취급하지 않음 |
| RAG | retrieval evidence에 exact corpus version | private workspace/source 원문 ingestion 없음 |

## 5. managed resource 확인

- Firestore: client가 `ip-risk-agent-v2` named database에 연결됐고 `(default)`에 v2
  document/index/TTL/IAM 변경이 없음을 먼저 확인한 뒤 transaction contention/retry,
  정확히 8개 composite index, OAuth/device challenge 2개 TTL과 operational namespace를
  검증한다. ACTIVE pending connection에는 TTL이 없어야 한다.
- Secret Manager: 새 version 추가 후 adapter read/refresh, 이전 version rollback window를 확인한다.
- GCS: private upload/read/delete와 lifecycle, public ACL/signed URL 부재를 확인한다.
- Cloud Tasks: exact OIDC audience/email, retry/backoff, concurrency와 duplicate task name을 확인한다.
- Cloud Run: `/health/live`, `/health/ready`, API public/Worker private ingress와 non-root
  process를 확인한다.
- Scheduler: 네 endpoint가 caller identity 없이는 401/403이고 batch limit 500을 넘지 않는지 확인한다.
- Namespace: v1 Run service/job/service account, `ipra-*` secret, 기존 bucket 및
  `cloud-run-source-deploy` repository의 IAM/update timestamp가 작업 전후 동일한지 확인한다.
- OAuth: v2 client는 별도지만 Branding/Audience/Data Access/authorized domain은 project-level
  shared configuration이므로 v1 영향 검토 기록 없이는 변경하지 않는다.
- RAG: `ip-risk-agent-v2-legal-reference` corpus만 사용하고 기존 corpus는 재사용하지 않는다.

## 6. 관측·보안 증거

허용 evidence에는 timestamp, release SHA/image digest, resource ID, HTTP status,
safe failure code, duration, queue age와 terminal state만 둔다. 다음 값은 ticket,
screenshot, log export에도 남기지 않는다.

- OAuth/access/refresh/device token과 Authorization header
- private key, client secret, webhook secret, KIPRIS key
- SourceSnapshot 원문, source file content, local absolute path
- signed URL 또는 provider raw response

stuck lease, queue age/error, provider latency/failure, analyzer coverage, terminal latency,
staging cleanup failure alert를 각각 한 번 test signal로 확인한다.

## 7. rollback과 중단 기준

다음 중 하나면 rollout을 중단하고 API traffic 또는 Worker revision을 직전 안정
revision으로 되돌린다.

- readiness 실패 또는 production in-memory adapter 발견
- `(default)` Firestore 또는 v1/non-v2 resource에 v2 read/write/IAM 변경 발견
- 권한 없는 Source/Worker/Scheduler 요청이 성공
- raw content/credential/path가 task, Firestore operational document 또는 log에 노출
- duplicate가 duplicate Risk를 생성하거나 failed/partial 분석이 기존 Risk를 자동 해소
- queue age/stuck lease가 alert threshold를 넘어 회복하지 않음

queue는 purge하지 않고 새 enqueue만 멈춘다. Firestore canonical Risk를 삭제하거나
대량 resolve하지 않는다. Secret은 이전 version을 rollback window 동안 보존하고,
schema는 backward-compatible reader를 먼저 유지한다.

### 422 `Method Not Allowed` 관측 시 진단 절차

`422` status와 `{"detail":"Method Not Allowed"}` body의 조합은 이 저장소의 코드가 한
응답으로 만들어낼 수 없다. FastAPI/Starlette의 method mismatch는 정확히
`405 {"detail":"Method Not Allowed"}`이고, 이는 route regression test로 고정돼 있다 —
`tests/connectors/test_drive_mounts.py:290`의
`test_mount_route_method_mismatch_is_405_not_422`가 GET
`/api/v1/source-mounts/{mount_id}/drive/mounts`에 대해 `405`와 그 body를 함께 단언한다
(`:296-297`). request validation 422와 domain 422는 서로 다른 safe error envelope을 쓴다.

staging live에서 이 조합이 두 번 보고됐고, 두 조사 모두 저장소 안에서 원인을 찾지
못한 채 끝났다.

- **1차 (Drive mount callback POST).** mount callback은 Google Drive를 전혀 호출하지
  않았으므로 외부 Drive의 405를 이 코드가 옮긴 것이 아니었다. POST route coverage는
  유지하고 wrong-method regression을 405로 고정했다. 이후 mount 완료에서 새로 생긴
  provider 호출은 Picker scope로 한정된 초기 metadata fetch 하나뿐이며, 그 실패는
  contradictory 422가 아니라 safe envelope으로 반환된다.
- **2차 (두 번째 서로 다른 Drive 선택).** 저장소가 실제로 재현한 제품 오류는
  모든 Drive mount alias가 `Google Drive`로 같아 생긴 workspace alias unique
  collision이었고, 설치된 error handler 계약상 409 conflict 경로였다. 즉 관측된 422와는
  다른 status다. 이 alias collision과 추가 파일 선택 시의 OAuth 재시작 우회는 이후
  변경으로 제거됐다.

따라서 새 revision에서 같은 조합이 다시 관측되면 **같은 Network request 한 건의
status, response body, response headers를 한 번에 다시 수집한다.** 저장소가 그 쌍을
낼 수 없다는 사실이 위 test로 고정돼 있으므로, 서로 다른 request나 서로 다른 화면에서
status와 body를 따로 모은 관측(split-source observation)이 그 조합을 만들어냈다고 본다.
세 값이 같은 request에서 함께 나오기 전에는 이 조합을 위의 중단 기준으로 취급하지 않는다.

관련 계약 확인점.

- 초기 metadata fetch의 provider HTTP 실패는 source connector error boundary로 매핑돼
  `DRIVE_INITIAL_SYNC_FAILED` safe envelope으로 반환된다.
  `tests/connectors/test_drive_mounts.py:241`은 `502`와
  `{"code": "DRIVE_INITIAL_SYNC_FAILED", "operation": "drive_file_metadata",
  "provider_error": "TEMPORARY_UNAVAILABLE", "retryable": false}`를 고정하고, 선택된
  file ID가 response body에 없음을 함께 확인한다. provider URL, file ID, response body,
  credential은 제외된다.
- 현재 alias는 선택 집합이 아니라 **연결된 Drive 계정**에서 파생한다
  (`backend/src/ip_risk_agent/composition/source_registration.py:461` `_drive_mount_alias`:
  계정 라벨이 있으면 `Google Drive {label}`, 없으면 `Google Drive {subject digest 8자}`).
  파일을 더 추가해도 alias가 바뀌지 않는다. 선택한 파일이 이미 전부 추적 중이면
  오류가 아니라 기존 binding을 돌려주는 **멱등 200**이고
  (`source_registration.py:282`), `409 selected files are already tracked`는 추적 중인데
  binding이 없는 불가능 상태의 guard로만 남아 있다(`:280`).

## 8. 승인 기록

| 항목 | 기록값 |
|---|---|
| RC commit SHA | |
| image digest | |
| project/application/RAG region | |
| API/Worker revision | |
| Firestore index/TTL 확인 | 8 indexes / 2 TTL policies |
| queue/bucket/lifecycle 확인 | |
| provider/RAG live 결과 | |
| negative security 결과 | |
| alert/rollback drill 결과 | |
| 최종 Go/No-Go 승인자·시간 | |

모든 칸과 알려진 제한이 채워지기 전 production readiness를 승인하지 않는다.
