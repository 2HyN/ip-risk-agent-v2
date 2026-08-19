# Agent 2 — Dependency Requests & Verification

Master Spec §57 절차: root pyproject.toml을 직접 수정하지 않고 여기에 기록한다.
팀 정책 업데이트에 따라, 각 Agent가 자기 venv에 직접 설치해 검증한 뒤 그 결과를 기록한다
(root pyproject.toml/lockfile 자체는 여전히 건드리지 않음 — 실제 반영은 Integration 단계에서 병합).

## Runtime dependencies

| Package | Version (검증됨) | 용도 / 선택 사유 | 검증 결과 | 특이사항 |
|---|---|---|---|---|
| google-api-python-client | 2.198.0 (요청 범위: `>=2.180,<3.0`) | Google Drive API v3 호출 (`connectors/google_drive/client.py`) | 로컬 venv에 설치 후 `pytest tests/connectors/` 실행, `test_google_drive_client.py` 3개 포함 전체 **89 passed, 0 skipped** 확인 | 2HyN/ip-risk-agent(팀 공개 저장소)에서 검증된 버전대를 그대로 채택 |
| google-auth | 2.56.3 (요청 범위: `>=2.40,<3.0`) | OAuth Credentials 객체 생성, access token 자동 refresh | 위와 동일 검증 (같은 pytest 실행에 포함) | 위와 동일 근거 |

### 부수 설치된 transitive dependency (직접 요청 대상 아님, 참고용)
`google-api-core`, `google-auth-httplib2`, `httplib2`, `googleapis-common-protos`, `protobuf`, `proto-plus`, `cryptography`, `pyasn1`, `pyasn1-modules`, `cffi`, `pycparser`, `uritemplate`, `requests`, `urllib3`, `certifi`, `idna`, `charset_normalizer`, `pyparsing` — 위 두 패키지의 의존성으로 자동 설치됨. 개별 버전 고정 요청 없음, pip가 해석한 범위 그대로 사용.

## 검증 방법 (재현 절차)

```bash
source .venv/Scripts/activate
pip install "google-api-python-client>=2.180,<3.0" "google-auth>=2.40,<3.0"
pytest tests/connectors/ -v
```

기대 결과: `89 passed` (SKIPPED 없음)

## 특이사항 / 트러블슈팅 기록

- 최초 설치 시도에서 `cryptography` 설치 도중 `ERROR: Operation cancelled by user`로 중단된 적 있음 (터미널 조작 중 실수로 취소된 것으로 추정, 패키지 자체 문제 아님). 동일 명령어 재실행으로 정상 완료됨. — 다른 팀원이 같은 현상 겪으면 그냥 재시도하면 됨.

## 향후 추가 예상

- google-cloud-secret-manager — production CredentialVault용 (Integration 단계, 아직 미검증)

## Node.js / Electron dependencies (apps/desktop)

| Package | Version (검증됨) | 용도 | 검증 결과 | 특이사항 |
|---|---|---|---|---|
| electron | 43.4.0 | Local Desktop 앱 shell (Agent2 Spec §23 Electron main/preload) | `pnpm --filter @iprisk/desktop add -D electron` 로컬 설치 후, main process에서 BrowserWindow 생성 스모크 테스트 실행 → 실제 데스크톱 창 렌더링 확인 (스크린샷 보관) | root `pnpm-lock.yaml`은 workspace 공유 파일이라 커밋하지 않음. `apps/desktop/package.json`에 electron을 정식으로 선언하는 시점(D-3, 실제 watcher 코드 작성 시)에 다시 다룰 예정. 그 전까지 로컬 재현은 `pnpm --filter @iprisk/desktop add -D electron` 재실행으로 가능. |
