# Agent 2 — Dependency Requests

Master Spec 57번 절차: root pyproject.toml을 직접 수정하지 않고 여기에 기록한다.

## Runtime dependencies

| Package | Purpose | Version | Notes |
|---|---|---|---|
| google-api-python-client | Google Drive API v3 호출 | >=2.180,<3.0 | 2HyN/ip-risk-agent(팀 저장소)에서 검증된 버전대 |
| google-auth | OAuth Credentials 객체, token refresh | >=2.40,<3.0 | 위와 동일 근거 |

## 현재 상태

connectors/google_drive/client.py는 위 두 패키지 없이는 import 불가.
설치 전까지 tests/connectors/test_google_drive_client.py는 SKIPPED (의도된 동작).
models.py와 그 테스트는 의존성 없이 이미 통과한다.

## 향후 추가 예상

- google-cloud-secret-manager — production CredentialVault용 (Integration 단계)
