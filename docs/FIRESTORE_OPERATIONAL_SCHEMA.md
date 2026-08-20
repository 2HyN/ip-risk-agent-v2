# Firestore operational schema

Source operational collection은 canonical aggregate를 대체하지 않는다. 모든 document
ID는 raw state, token, credential, device credential, provider lookup key 대신 해당 값의
SHA-256이다. document에는 `schema_version: 1`을 둔다.

| collection | 목적 | TTL |
|---|---|---|
| `source_operational_oauth_states` | one-time OAuth/App state와 safe callback context | `expires_at` |
| `source_operational_pending_connections` | canonical mount 생성 전 pending connection | `expires_at` |
| `source_operational_mount_bindings` | deterministic registration key↔mount binding | 없음 |
| `source_operational_device_challenges` | one-time desktop enrollment challenge hash | `expires_at` |
| `source_operational_devices` | owner/session/status와 credential hash | 없음 |
| `source_operational_device_credentials` | credential hash→device ID lookup | 없음 |
| `source_operational_device_mounts` | device↔workspace↔mount binding | 없음 |
| `source_operational_drive_runtime` | Drive cursor/watch runtime | 없음 |
| `source_operational_drive_tracking` | Drive selected file scope | 없음 |
| `source_operational_github_runtime` | GitHub delivery/runtime state | 없음 |
| `source_operational_github_tracking` | repository/branch/path scope | 없음 |
| `source_operational_local_runtime` | Local staging runtime reference | 없음 |

OAuth state consume는 Firestore transaction으로 `consumed_at`을 원자적으로 기록한다.
TTL 삭제는 즉시성을 보장하는 authorization mechanism이 아니므로 consume 시에도
`expires_at`과 `consumed_at`을 반드시 검사한다.

Canonical query index와 operational TTL 선언의 source of truth는
`deploy/firestore.indexes.json`이다. 선언 누락은
`scripts/validate_gcp_deployment.py`가 repository test에서 차단한다.

Emulator 검증은 `FIRESTORE_EMULATOR_HOST`를 명시한 경우에만 실행하며 production에
이 환경변수를 절대 설정하지 않는다. schema 변경은 collection을 제자리에서
추정하지 않고 `schema_version` decoder와 별도 migration dry-run을 먼저 추가한다.
