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

하나라도 충족하지 못하면 외부 작업을 시작하지 않는다.

## 2. 배포 전 repository 검증

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

1. API enablement와 Artifact Registry
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

기본 test command는 `live`를 제외한다. 실제 provider test는 전용 staging project와
최소 권한 test account에서만 명시적으로 선택한다.

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

- Firestore: transaction contention/retry, 모든 required query, TTL field와 operational
  namespace를 확인한다. emulator 결과와 실제 index 결과를 구분해 기록한다.
- Secret Manager: 새 version 추가 후 adapter read/refresh, 이전 version rollback window를 확인한다.
- GCS: private upload/read/delete와 lifecycle, public ACL/signed URL 부재를 확인한다.
- Cloud Tasks: exact OIDC audience/email, retry/backoff, concurrency와 duplicate task name을 확인한다.
- Cloud Run: `/health/live`, `/health/ready`, API public/Worker private ingress와 non-root
  process를 확인한다.
- Scheduler: 네 endpoint가 caller identity 없이는 401/403이고 batch limit 500을 넘지 않는지 확인한다.

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
- 권한 없는 Source/Worker/Scheduler 요청이 성공
- raw content/credential/path가 task, Firestore operational document 또는 log에 노출
- duplicate가 duplicate Risk를 생성하거나 failed/partial 분석이 기존 Risk를 자동 해소
- queue age/stuck lease가 alert threshold를 넘어 회복하지 않음

queue는 purge하지 않고 새 enqueue만 멈춘다. Firestore canonical Risk를 삭제하거나
대량 resolve하지 않는다. Secret은 이전 version을 rollback window 동안 보존하고,
schema는 backward-compatible reader를 먼저 유지한다.

## 8. 승인 기록

| 항목 | 기록값 |
|---|---|
| RC commit SHA | |
| image digest | |
| project/application/RAG region | |
| API/Worker revision | |
| Firestore index/TTL 확인 | |
| queue/bucket/lifecycle 확인 | |
| provider/RAG live 결과 | |
| negative security 결과 | |
| alert/rollback drill 결과 | |
| 최종 Go/No-Go 승인자·시간 | |

모든 칸과 알려진 제한이 채워지기 전 production readiness를 승인하지 않는다.
