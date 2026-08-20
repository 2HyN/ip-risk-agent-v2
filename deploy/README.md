# Deploy

배포에 필요한 설정과 스크립트다. **여기 있는 것은 코드로 만들 수 있는 전부이고,
Cloud Console 에서 사람이 직접 해야 하는 일은 [CONSOLE_TASKS.md](CONSOLE_TASKS.md)
에 따로 정리했다.**

```
deploy/
├─ Dockerfile               API 이미지 (워커도 같은 베이스를 쓴다)
├─ Dockerfile.worker        워커 진입점만 바꾼 이미지
├─ .dockerignore
├─ firestore/
│  └─ firestore.indexes.json    코드에서 생성됨. 손으로 고치지 않는다
├─ cloudtasks/
│  └─ queue.yaml            큐 설정 (재시도·동시성·dead-letter)
├─ storage/
│  └─ staging-lifecycle.json    staging 버킷 TTL 규칙
├─ cloudrun/
│  ├─ api.env.example       API 서비스 환경변수 목록
│  └─ worker.env.example    워커 서비스 환경변수 목록
├─ deploy.sh                이미지 빌드 → 푸시 → 두 서비스 배포
└─ CONSOLE_TASKS.md         콘솔에서만 가능한 작업 목록
```

---

## 순서

배포 URL 이 있어야 OAuth 콜백을 등록할 수 있으므로, **최소 구성으로 먼저 배포한
뒤** provider 를 붙인다.

```
Firestore 생성 + 인덱스 배포
  → 이미지 빌드·푸시
  → Cloud Run 2개 배포 (최소 환경변수)
  → 배포 URL 확보
  → Google OIDC 등록 → 로그인 동작
  → Secret Manager → Cloud Tasks → GCS
  → Drive/GitHub 등록 → provider 연결
  → Intelligence 키 주입
```

각 단계가 끝났는지는 `/health` 하나로 확인한다. 무엇이 붙었고 무엇이 왜 빠졌는지
그대로 나온다.

```bash
curl -s https://<API-URL>/health | jq
```

| 필드 | 미완료 상태 | 완료 상태 |
|---|---|---|
| `control_backend` | `in-memory` | `firestore` |
| `queue` | `in-memory` | `cloud-tasks` |
| `credential_vault` | `InMemoryCredentialVault` | `SecretManagerCredentialVault` |
| `staging_store` | `InMemoryLocalStagingStore` | `GcsLocalStagingStore` |
| `oauth_state_store` | `InMemoryOAuthStateStore` | `FirestoreOAuthStateStore` |
| `change_relay` | `InMemoryChangeRelayStore` | `FirestoreChangeRelayStore` |
| `google_login` | `unconfigured` | `configured` |
| `intelligence` | `disabled` | `enabled` |
| `sources.skipped` | 이유가 채워져 있음 | `{}` |

`sources.skipped` 가 비면 provider 라우터가 전부 붙은 것이다.

---

## 인덱스

코드의 `REQUIRED_COMPOSITE_INDEXES` 에서 생성한다. 손으로 고치지 않는다.

```bash
python scripts/generate_firestore_indexes.py          # 다시 생성
python scripts/generate_firestore_indexes.py --check  # 최신인지 확인 (CI 용)
```

배포:

```bash
gcloud firestore indexes composite create --file=deploy/firestore/firestore.indexes.json
```

---

## 배포 실행

```bash
export PROJECT_ID=... REGION=asia-northeast3
./deploy/deploy.sh
```

환경변수는 Cloud Run 서비스에 설정한다. 값 목록은 `cloudrun/*.env.example` 참고.
**실제 secret 은 Secret Manager 에 두고 Cloud Run 이 주입한다** — 평문으로 넣지
않는다.

---

## 확인해야 할 것

- `FIRESTORE_EMULATOR_HOST` 가 production 서비스에 **없어야** 한다
- `/internal/analysis/*` 는 ingress 에서 차단하고 Cloud Tasks 서비스 계정만
  호출할 수 있어야 한다
- staging 버킷에 수명주기 규칙이 실제로 걸려 있어야 한다
- `SESSION_SECRET` 을 주입하지 않으면 프로세스마다 임시값이 생겨 재시작 때마다
  전원 로그아웃된다
