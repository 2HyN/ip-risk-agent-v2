# IP Risk Agent — API Reference

> 기준: `main` v1.0.0. 모든 경로·모델·상태 코드는 `backend/src/ip_risk_agent/api/**`,
> `connectors/*/routes*.py`, `composition/*.py` 의 라우터 정의에서 추출했다.
>
> Base URL (운영): `https://ip-risk-agent-v2-api-555102774494.asia-northeast3.run.app`

## 0. 공통 규약

**인증** — Google OIDC 로 로그인하면 서명된 세션 쿠키(itsdangerous)가 발급된다.
이후 모든 `/api/v1/**` 호출은 이 쿠키로 인증된다. 상태 변경 메서드(POST/PATCH/PUT/DELETE)는
CSRF 가드를 함께 통과해야 한다. 인증은 애플리케이션 신원만 수립하며 원문 소스 접근
권한을 부여하지 않는다(소스 권한은 provider 쪽에서 별도 성립).

**권한(RBAC)** — workspace 스코프 API 는 호출자의 membership 역할
(VIEWER < RISK_REVIEWER < SOURCE_MANAGER < OWNER)을 `VwsAction` 단위로 검사한다.
부족하면 403 `PERMISSION_DENIED`.

**페이지네이션** — 목록 응답은 `Page[T]` 봉투: `{ "items": [...], "next_cursor": "..." | null }`.
요청은 `cursor`, `limit`(1~100, 기본 50) 쿼리를 받는다. 커서가 깨지면 400 `INVALID_CURSOR`.

**오류 봉투** — 실패는 `{ "code": "...", "message": "..." }` (ApiError) 로 통일된다.

| HTTP | code | 뜻 |
|---|---|---|
| 401 | `AUTHENTICATION_REQUIRED` | 세션 없음/만료 |
| 403 | `CSRF_VALIDATION_FAILED` / `PERMISSION_DENIED` | CSRF 실패 / 역할 부족 |
| 404 | `NOT_FOUND` | 리소스 없음 (다른 workspace 의 것 포함) |
| 409 | `VERSION_CONFLICT` | 낙관적 잠금 실패 (`expected_*` 값이 낡음) |
| 400 | `INVALID_CURSOR` | 페이지네이션 커서 불량 |
| 422 | — | 요청 본문 검증 실패 (StrictApiModel — 미정의 필드도 거부) |
| 502 | `IDENTITY_PROVIDER_UNAVAILABLE` | Google OIDC 장애 |

**content-free 원칙** — 어떤 응답에도 원문 본문이 실리지 않는다. 이력·감사 계열 텍스트
필드는 `*_safe` 정화를 거친 값이다.

---

## 1. Auth — `/api/v1/auth`

| Method | Path | 설명 | 응답 |
|---|---|---|---|
| GET | `/google/login` | Google OIDC 로 리다이렉트 | 307 |
| GET | `/google/callback` | 콜백 처리 → 세션 발급 후 앱으로 리다이렉트 | 307 |
| POST | `/logout` | 세션 종료 | 204 |
| GET | `/me` | 현재 사용자 | `UserResponse` |

## 2. Workspaces — `/api/v1/workspaces`

| Method | Path | 설명 | 응답 |
|---|---|---|---|
| POST | `` | 생성 (`name`, `description?`) — 생성자가 OWNER | 201 `WorkspaceResponse` |
| GET | `` | 내가 속한 workspace 목록 | `Page[WorkspaceResponse]` |
| GET | `/{vws_id}` | 단건 조회 | `WorkspaceResponse` |
| PATCH | `/{vws_id}` | 수정 — `expected_updated_at` 필요 (409 가능) | `WorkspaceResponse` |
| DELETE | `/{vws_id}` | 삭제 = 전체 말소(자격증명 Secret 포함, 중단 시 재시도 이어감) — OWNER | `WorkspaceResponse` |
| GET | `/{vws_id}/membership` | 내 역할 조회 | `MembershipResponse` |
| GET | `/{vws_id}/dashboard` | Overview KPI — 신규/모니터링/해소(30d)/**analysis_failed** | `WorkspaceDashboardResponse` |
| GET | `/{vws_id}/analyses/progress` | 작업 현황 — 진행률·Running/Queued/Waiting/Failed (화면은 5초 폴링) | `AnalysisProgressResponse` |

### 멤버·초대

| Method | Path | 설명 | 응답 |
|---|---|---|---|
| GET | `/{vws_id}/members` | 멤버 목록 | `Page[MembershipResponse]` |
| POST | `/{vws_id}/members/invitations` | 초대 (verified email + 역할) — OWNER | 201 `InvitationResponse` |
| PATCH | `/{vws_id}/members/{user_id}` | 역할 변경 — OWNER | `MembershipResponse` |
| DELETE | `/{vws_id}/members/{user_id}` | 제거 — OWNER | `MembershipResponse` |

### 마운트 관리 (조회 VIEWER+ · 조작 SOURCE_MANAGER+)

| Method | Path | 설명 | 응답 |
|---|---|---|---|
| GET | `/{vws_id}/mounts` | 마운트 목록 | `Page[MountResponse]` |
| GET | `/{vws_id}/mounts/{mount_id}` | 단건 조회 | `MountResponse` |
| PATCH | `/{vws_id}/mounts/{mount_id}/alias` | 별칭 변경 — alias 는 표시명일 뿐 identity 를 바꾸지 않음 | `MountResponse` |
| POST | `/{vws_id}/mounts/{mount_id}/disable` | 추적 중지 | `MountResponse` |
| DELETE | `/{vws_id}/mounts/{mount_id}` | 마운트 해제 | 204 |

## 3. Invitations — `/api/v1/invitations` (개인 스코프)

| Method | Path | 설명 | 응답 |
|---|---|---|---|
| GET | `` | 내 이메일로 온 대기 초대 | `Page[PendingInvitationResponse]` |
| POST | `/{invitation_id}/accept` | 수락 → membership 생성 | `InvitationAcceptanceResponse` |

## 4. Risks — `/api/v1/workspaces/{vws_id}/risks`

| Method | Path | 설명 | 응답 |
|---|---|---|---|
| GET | `` | 목록. 필터: `analysis_type`, `lifecycle_state`, `review_disposition`, `review_priority`, `mount_id`, `source_type`, `artifact_id`(파일 하나의 Risk — Files 진입 경로). **EXCLUDED 처분은 기본 목록에서 접히며** `review_disposition=EXCLUDED` 로 불러야 나온다 | `Page[RiskResponse]` |
| GET | `/{risk_id}` | 상세 — risk + 근거 목록 + open_original 액션 | `RiskDetailResponse` |
| PATCH | `/{risk_id}/review` | 처분 입력 (RISK_REVIEWER+). 본문: `expected_review_version`(낙관적 잠금), `disposition`(UNREVIEWED·MONITORING·ACCEPTED_RISK·EXCLUDED), 사유. 기계 lifecycle 은 건드리지 않음 | `RiskResponse` |
| GET | `/{risk_id}/timeline` | append-only 이력 | `RiskTimelineResponse` |

`RiskResponse` 주요 필드: `analysis_type`(license·patent) · `lifecycle_state`(NEW·EXISTING·RESOLVED, 기계) ·
`review_disposition`(사람) · `review_priority`(LOW·MEDIUM·INDETERMINATE·HIGH) · `summary` ·
`review_version` · `explanation_safe`/`recommendation_safe`(모델 설명 — 판정 아님) ·
`artifact_display_name`/`artifact_logical_path`/`mount_alias`.
`RiskDetailResponse.evidence[]`: `evidence_type`(SOURCE_EXCERPT·PATENT_ABSTRACT 등) · `excerpt` ·
`reference`(KIPRIS 출원번호·조항) · `source_revision`(근거의 판본 고정).

## 5. History — `/api/v1/workspaces/{vws_id}`

| Method | Path | 설명 | 응답 |
|---|---|---|---|
| GET | `/activity` | 전체 활동 (통합 탭) | `Page[HistoryEntryResponse]` |
| GET | `/risk-events` | Risk 사건만 | `Page[HistoryEntryResponse]` |
| GET | `/audit` | 관리 행위 감사 | `Page[HistoryEntryResponse]` |
| GET | `/source-access` | 원문 접근 기록 (access_type·revision·**content_bytes 만** — 내용 없음) | `Page[HistoryEntryResponse]` |
| GET | `/audit/export` | safe JSON 내보내기 | `HistoryExportResponse` |

## 6. Security & Data — `/api/v1/workspaces/{vws_id}/security` (조작 OWNER)

| Method | Path | 설명 | 응답 |
|---|---|---|---|
| GET | `` | 현재 정책 조회 | `SecuritySettingsResponse` |
| PUT | `/ipriskignore` | 분석 제외 규칙 저장 — `expected_policy_version` + `global_ignore_text`. 걸린 파일의 기존 Risk 는 EXCLUDED 로 닫힘 | `SecurityPolicyUpdateResponse` |
| PUT | `/license-profile` | 배포 형태 축(SaaS/배포/수정/링크) 설정 | `LicenseProfileResponse` |
| POST | `/reanalyze` | "다시 검사" — 본문 `{ "change_event_id": ... }` | **202** |
| GET | `/data-access-summary` | Files 탭의 데이터 원천 — `tracked_artifacts[]`(파일별 `analysis_status`·`analysis_failure_safe`·`risk_count`·`highest_risk_priority`·`change_event_id`), `mounts[]`, `connected_sources[]`, `recent_access[]`, 보존 보증 3 플래그(`raw_source_persisted=false` 등) | `DataAccessSummaryResponse` |

## 7. Notifications — `/api/v1/notifications` (본인 것만)

| Method | Path | 설명 | 응답 |
|---|---|---|---|
| GET | `` | 개인 인박스 (UNREAD/READ) | `NotificationInboxResponse` |
| POST | `/{notification_id}/read` | 읽음 처리 | `NotificationReadResponse` |

## 8. Source 연결 (SOURCE_MANAGER+)

### Google Drive (D1 — 서비스 계정 + 폴더 공유, 보관 자격증명 없음)

| Method | Path | 설명 |
|---|---|---|
| GET | `/api/v1/source-connections/google-drive/sharing-address` | 폴더를 공유할 서비스 계정 주소 |
| POST | `/api/v1/source-connections/google-drive/folders` | 공유된 폴더 주소 등록 → Mount 생성. 응답에 추적 대상 개수 포함. 폴더 미공유·접근 불가면 404·422 |

### GitHub (GitHub App)

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/v1/source-connections/github/install/start` | App 설치 시작 (설치 URL 반환) |
| GET | `/api/v1/source-connections/github/install/callback` | 설치 콜백 → SourceConnection 성립 |
| GET | `/api/v1/source-connections/{connection_id}/github/repositories` | 설치가 노출하는 저장소 목록 |
| POST | `/api/v1/source-connections/{connection_id}/github/mounts` | 저장소·브랜치 선택 → Mount 생성 (`owner`·`repo`·`tracked_branch`·`include/exclude_patterns`) |
| GET | `/api/v1/source-mounts/{mount_id}/github/repositories` | 기존 마운트 기준 저장소 조회 |
| POST | `/api/v1/source-mounts/{mount_id}/github/mounts` | 기존 연결에 마운트 추가 |

### Desktop (Local 폴더)

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/v1/desktop/enrollment-challenges` | 기기 등록 challenge 발급 |
| POST | `/desktop/devices/enroll` | 기기 등록 (자격증명은 기기 OS 암호화 저장소에만) |
| POST | `/api/v1/desktop/devices/{device_id}/revoke` | 기기 해지 (204) |
| POST | `/desktop/devices/register` · `/desktop/mounts/register` | 기기·로컬 폴더 마운트 등록 |
| POST | `/desktop/staging` | 스냅샷 스테이징 업로드 |
| POST | `/desktop/events` | 로컬 변경 이벤트 수신 (기기 자격증명 인증) |

## 9. 원문 열기 — Artifacts

| Method | Path | 설명 | 응답 |
|---|---|---|---|
| POST | `/api/v1/workspaces/{vws_id}/artifacts/{artifact_id}/open-original` | provider 원문 위치로 안내 (서버는 원문을 보관하지 않으므로 위치만). 실패 시 원인과 함께 fail-closed | `OriginalSourceResponse` |

## 10. Webhooks · 런타임 (사용자 인증 아님 — provider/서명 검증)

| Method | Path | 설명 |
|---|---|---|
| POST | `/webhooks/google-drive` | Drive watch 채널 알림 (`DRIVE_WATCH_CHANNEL_TOKEN` 검증) |
| POST | `/webhooks/github` | GitHub App webhook (`GITHUB_WEBHOOK_SECRET` 서명 검증) |
| GET | `/api/v1/runtime-config` | 프런트 런타임 설정 |
| GET | `/health/live` · `/health/ready` | 헬스 체크 (각 200 = 정상) |

## 11. Internal (외부 호출 불가 — 서비스 간 OIDC 인증)

Worker(`APP_ROLE=worker`, ingress internal)와 Scheduler 전용. 사용자 세션으로는 호출할 수 없다.

| Method | Path | 호출자 | 설명 |
|---|---|---|---|
| POST | `/internal/tasks/analyze-change` | Cloud Tasks | 분석 파이프라인 실행 (`change_event_id`) |
| POST | `/internal/scheduler/drive-watch-renewal` | Cloud Scheduler | Drive watch 채널 갱신 |
| POST | `/internal/scheduler/drive-reconciliation` | Cloud Scheduler | Drive 주기 대조 |
| POST | `/internal/scheduler/expired-state-cleanup` | Cloud Scheduler | 만료 상태 정리 |
| POST | `/internal/scheduler/source-health-refresh` | Cloud Scheduler | 소스 헬스 갱신 |
| POST | `/internal/scheduler/license-revalidation` | Cloud Scheduler | 라이선스 일일 재검증 (외부 사실 변화 감지) |

---

## 부록 — 화면 ↔ API 대응

| 화면 | 사용하는 API |
|---|---|
| Workspaces | GET/POST `/workspaces`, GET `/invitations` |
| Overview | GET `/{vws}/dashboard`, GET `/{vws}/analyses/progress` (5초 폴링) |
| Files | GET `/{vws}/security/data-access-summary` (tracked_artifacts), POST `/{vws}/security/reanalyze`, 마운트 관리 API |
| Add Source | Drive `sharing-address`→`folders` · GitHub `install/start`→`mounts` · Desktop 앱 등록 API |
| Review / Risk 상세 | GET `/{vws}/risks`(+필터), GET `/risks/{id}`, PATCH `/risks/{id}/review`, GET `/risks/{id}/timeline`, POST `.../open-original` |
| Members & roles | GET `/{vws}/members`, POST `.../invitations`, PATCH/DELETE `.../members/{user_id}` |
| Activity & audit | GET `/{vws}/activity`·`/risk-events`·`/audit`·`/source-access`·`/audit/export` |
| Security & data | GET/PUT `/{vws}/security/**` |
| Notifications | GET `/notifications`, POST `/{id}/read` |
