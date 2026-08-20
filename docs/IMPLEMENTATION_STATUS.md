# Implementation Status

세 Plane 의 구현 범위·검증 실적·알려진 제약을 하나로 모은 문서다.
Master Spec 60 이 요구하는 Agent 별 인계 문서(`AGENT_DELIVERY.md`)의 내용을
Plane 별 절로 흡수했다.

**기준** — branch `integration`, CPython 3.14.7 / Node.js 24.19.0 / pnpm 11.19.0

---

## 0. 전체 현황

| Plane | 소유 branch | 상태 | 규모 |
|---|---|---|---|
| Platform & Control | `platform-control` | Phase 0~13 완료 | 112 파일 / 약 14,700 LOC + frontend 33 파일 |
| Source Integration & Desktop | `source-integration-desktop` | Phase A~F 완료 | 45 파일 / 약 3,200 LOC + Electron 29 파일 |
| Risk Intelligence & RAG | `risk-intelligence-rag` | 전 영역 완료 | 35 파일 / 약 3,700 LOC |
| Integration | `integration` | 조립 완료, GCP 연동 대기 | `composition/` 8 모듈 |

### 검증 실적 (통합 트리 기준)

| 대상 | 명령 | 결과 |
|---|---|---|
| 전체 Python | `pytest` | **593 passed / 7 skipped** |
| Frozen Contract | `pytest shared/contracts/tests` | 27 passed |
| Control | `pytest tests/control` | 259 passed / 1 skipped |
| Source | `pytest tests/connectors` | 224 passed |
| Intelligence | `pytest tests/intelligence -m "not live"` | 58 passed |
| Intelligence (실호출) | `pytest tests/intelligence -m live` | 10건 — 자격증명 있을 때만 |
| Integration | `pytest tests/integration` | 21 passed |
| Frontend | `pnpm --filter @iprisk/frontend test` | 23 passed (6 files) |
| Desktop | `pnpm --filter @iprisk/desktop test` | 65 — 63 passed / 2 skipped |

skip 사유: Firestore emulator 미설정 1건, provider 자격증명 없음 6건, symlink 생성 권한 없음 2건.
모두 환경 제약이며 로직 결함이 아니다.

---

## 1. Platform & Control Plane

### 구현 범위

canonical Control domain, RBAC 와 provider authority 경계, Firestore persistence,
SourceChange/AnalysisJob orchestration, Security Gate, AnalysisResult/Risk reconciliation,
human review/history/audit/notification, Google App Login, Control API, Product Web UI,
structured observability.

범위 밖 — provider API/credential 처리, local filesystem 접근, analyzer/Gemini/KIPRIS/RAG,
Cloud Tasks adapter, 최종 app/worker 조립과 배포 설정.
**Control Plane 은 raw source 를 장기 저장하거나 HTTP API 로 proxy 하지 않는다.**

### 공개 접점

```python
from ip_risk_agent.application.public_facade import (
    ControlPlaneFacade, ControlPlaneFacadeConfig, CorrelationIds,
    PublicVwsAction, SourceAccessReceiptContext,
    SourceAuthorizationCallback, SourceMetadataRegistrationCallback,
    SourceMetadataRegistrationCommand, SourceScopeInput,
    StructuredEventSink, StructuredLogger,
)
from ip_risk_agent.api import (
    ApplicationHardeningConfig, ApplicationSessionConfig,
    ControlApiDependencies, create_control_api_bundle,
)
from ip_risk_agent.persistence.core_firestore import FirestoreControlUnitOfWorkFactory
```

`ControlPlaneFacade` 공개 async 메서드 12개:

| 메서드 | 입력 |
|---|---|
| `authorize_vws_action` | `*, actor_user_id, risk_workspace_id, action, mount_id=None, provider_credential_owner_user_id=None` |
| `register_source_metadata` | `command: SourceMetadataRegistrationCommand` |
| `register_source_change` | `change: SourceChange` |
| `claim_analysis` | `change_event_id: str` |
| `fail_analysis` | `change_event_id: str, *, failure_safe: str` |
| `retry_failed_analysis` | `change_event_id: str` |
| `register_source_access` | `context: SourceAccessReceiptContext` |
| `build_analysis_artifact` | `snapshot, analysis_job_id, *, source_scope=None` |
| `accept_analysis_result` | `result: AnalysisResult` |
| `get_mount_ref` | `mount_id: str` |
| `get_source_workspace_context` | `source_workspace_id: str` |
| `get_original_source_request` | `*, actor_user_id, risk_workspace_id, artifact_id` |

`tests/control/test_delivery_contract.py` 가 이 표면의 드리프트를 자동 탐지한다.

### Control API

prefix `/api/v1/{auth,workspaces,invitations,notifications}`

```
GET    /auth/google/login, /google/callback, /me      POST /auth/logout
GET    /workspaces                                    POST /workspaces
GET    /workspaces/{id}   PATCH /workspaces/{id}      DELETE /workspaces/{id}
GET    /workspaces/{id}/dashboard
GET    /workspaces/{id}/members
PATCH  /workspaces/{id}/members/{user_id}             DELETE /workspaces/{id}/members/{user_id}
GET    /workspaces/{id}/membership
GET    /workspaces/{id}/mounts, /mounts/{mount_id}
PATCH  /workspaces/{id}/mounts/{mount_id}/alias
POST   /workspaces/{id}/mounts/{mount_id}/disable
GET    /workspaces/{id}/risks/{risk_id}, /{risk_id}/timeline
PATCH  /workspaces/{id}/risks/{risk_id}/review
GET    /workspaces/{id}/activity, /audit, /audit/export, /source-access
GET    /workspaces/{id}/data-access-summary
PUT    /workspaces/{id}/ipriskignore
GET    /notifications                                 POST /notifications/{id}/read
```

### Firestore

`CANONICAL_COLLECTIONS` 16개, `REQUIRED_COMPOSITE_INDEXES` 8개:

| Collection | Fields |
|---|---|
| `memberships` | `record_kind`, `risk_workspace_id` |
| `memberships` | `record_kind`, `user_id`, `status` |
| `memberships` | `record_kind`, `email` |
| `workspace_mounts` | `record_kind`, `risk_workspace_id` |
| `workspace_mounts` | `record_kind`, `risk_workspace_id`, `mounted_by_user_id` |
| `risks` | `record_kind`, `artifact_id`, `analysis_type`, `lifecycle_state` |
| `risks` | `record_kind`, `risk_workspace_id` |
| `change_events` | `risk_workspace_id` |

이 tuple 은 코드 query 의 요구사항이지 배포 가능한 `firestore.indexes.json` 형식이 아니다.
실제 project 에서 요구하는 index 와 대조해 배포 config 로 변환해야 한다.

### 알려진 제약

**외부 환경이 있어야 완료되는 항목**

- 실제 Google credential/callback domain 의 OIDC roundtrip
- 실제 Firestore emulator/production transaction 과 index 배포
- Cloud Tasks de-dup/retry/dead-letter, distributed ingress quota, proxy trust

**의도적 설계 결정**

- Source metadata callback 은 create/idempotent 등록이다. credential rotation·reconnect·
  provider status transition 은 Source Plane endpoint 와 함께 조립한다.
- pagination 은 scope-bound signed offset cursor 다. live write 중 offset 특성이 있으며,
  native document cursor 로 바꾸려면 endpoint 전체의 stable sort/index/snapshot 의미를
  함께 설계해야 한다.
- Dashboard failed count 는 canonical ChangeEvent→AnalysisJob read 를 쓴다.
  production trace 없이 임의 projection 을 추가하지 않았다.
- Risk list 는 request-scope 캐시만 쓴다. process-global 캐시는 stale authorization
  위험 때문에 쓰지 않는다.
- `RiskEvent` 는 append-only/transactional 이지만 **cryptographic hash chain 은 아니다.**
  규제 요구가 생기면 schema version, key custody, backfill, verifier 를 함께 설계한다.
- 내장 rate limiter 는 단일 process 안전망일 뿐 전역 quota 가 아니다.
- legacy document 가 존재할 때만 `User.session_version`, `RiskWorkspace.global_ignore_text`
  backfill migration 이 필요하다.
- UI 는 signed cursor incremental loading 을 지원하지만 초대형 table virtualization 은
  실제 row/profile 측정 후 적용한다.

---

## 2. Source Integration & Desktop Plane

### 구현 범위

Drive/GitHub/Local 3개 provider 전부 `SourceAdapter` 계약 구현.
**연결 시작(OAuth/App 설치) → 파일·저장소 선택 → Mount 생성 → 변경 감지·수신**까지
라이프사이클 전체가 끊김 없이 이어진다. Electron 앱은 폴더 선택 → 서버 등록 → 로컬 저장 →
watcher 시작 → 변경 감지 → 서버 전송까지 실제로 왕복한다. 외부 API 호출에는 지수 백오프
재시도(5xx/429 + 네트워크 단절)가 적용돼 있다.

| Phase | 내용 | 상태 |
|---|---|---|
| A | 공통 도구함 (errors, fingerprint, credential_vault, runtime_store, retry) | 완료 |
| B | GitHub SourceAdapter + webhook + App 설치 + 저장소목록/Mount 생성 | 완료 |
| C | Google Drive SourceAdapter + webhook + OAuth + Picker/Mount 생성 | 완료 |
| D | Local SourceAdapter + Electron 전체 배선 | 완료 |
| E | Source UI (React 부트스트랩, Drive/GitHub 버튼 실연결) | 완료 (스타일 제외) |
| F | 하드닝 (security tests, retries, cleanup) | 완료 |

### Source 라우트

```
POST /api/v1/source-connections/google-drive/start
POST /api/v1/source-connections/github/install/start
POST /webhooks/google-drive          POST /webhooks/github
POST /desktop/devices/register       POST /desktop/mounts/register
POST /desktop/staging                POST /desktop/events
```

전부 `APIRouter` 를 반환한다. 조립은 [INTEGRATION.md](INTEGRATION.md) 참조.

### 검증 방식

real fake(`FakeDriveProvider`, `FakeGitHubProvider`, `FakeDriveOAuthClient`,
`FakeMountRegistrationClient`)와 실제 파일시스템·실제 chokidar·실제 FastAPI `TestClient`·
실제 `httpx.MockTransport`·실제 Electron(헤드리스 실행 + 폴더선택창 확인)으로 검증했다.
mock-only 로 완료를 주장한 부분은 없다 (Master Spec 59 금지사항 10번 준수).

### 보안 체크리스트 (Spec 45, 20항목)

| 상태 | 개수 | 항목 |
|---|---:|---|
| 완료 | 17 | OAuth state mismatch 거부, 계정별 metadata 격리, Picker token 추상화, 미선택 파일 차단, webhook HMAC 검증, 미선택 repo/branch 무시, 제외 path fetch 차단, private repo 동작, token 미노출, Local root escape 거부, 절대경로 미포함, renderer fs 접근 차단, staging cleanup, OriginalSourceLocator 정확성, fingerprint 안정성, SourceAccessReceipt scope 반영 |
| 부분 | 3 | Drive file ID 안정성(설계상 보장, 별도 테스트 없음) / symlink escape(코드 존재, 환경 권한 제약으로 skip) / staging TTL(문서화만, 실제 설정은 배포 몫) |
| 미구현 | 0 | — |

### 알려진 제약

- **`GET /desktop/mounts/{id}/status` 미구현** (조회용)
- **GitHub `reconcile()` 은 안전한 no-op** (Spec 43 최소 기준 충족)
- **Local MOVE 감지는 내용 해시 기반 추정** — 내용이 완전히 같은 다른 파일이면 오판 가능
- **`.ipriskignore` 는 fnmatch 기반** — gitignore 전체 문법 미구현
- **Drive id_token 서명 검증 생략** — 표시용이며 실제 보안은 state CSRF + code exchange 에서 끝난다
- **GitHub `list_installation_repositories()` 는 단일 페이지(최대 100개)만**
- **Drive 실제 파일 API(이식된 sync 코드)는 재시도 미적용** — 구조가 sync 라 범위에서 제외
- **`LocalStagingStore` 는 텍스트만 처리** — 바이너리는 확장 필요
- **스타일링 없음** — 기능 우선, 순수 로직만 자동 테스트

---

## 3. Risk Intelligence & RAG Plane

### 구현 범위

승인된 `AnalysisArtifact` 를 받아 Patent/License 관점에서 분석하고 `AnalysisResult` 를
돌려주는 경로 전체.

| 영역 | 상태 |
|---|---|
| 공통 검증·결과 조립·Analyzer registry | 완료 |
| License analyzer (매니페스트·잠금파일·SPDX·정책·설명) | 완료 |
| Patent analyzer (추출·검색·순위·근거·대조·검증·우선순위) | 완료 |
| Gemini client (구조화 출력·재시도·프롬프트 버전) | 완료 |
| RAG (매니페스트·적재·검색·버전) | 완료 |
| corpus 초기 자료 3건 | 완료 |

### 공개 접점

```python
from ip_risk_agent.intelligence.public import create_facade_from_env
facade = create_facade_from_env(env, retriever=retriever)
results = await facade.analyze(artifact)   # list[AnalysisResult]
facade.supports(artifact)                  # 실행 대상 사전 확인
```

**Risk 해소 판단은 Control 이 한다.** 이 Plane 은 `status` 와 `coverage` 를 보수적으로
설정할 뿐이며, provider 가 하나라도 실패하면 `COMPLETE` 를 반환하지 않는다.

### 실호출로 검증한 것

| 대상 | 확인 내용 |
|---|---|
| deps.dev | `requests 2.32.3` → `Apache-2.0` 표준 식별자 |
| PyPI 폴백 | `PyMuPDF 1.24.0` 은 deps.dev 가 `non-standard` 로 답한다. 레지스트리 원문에서 `AGPL-3.0-only` 복원 후 `POLICY_CONFLICT` |
| npm | `express 4.19.2` → `MIT` |
| 미존재 패키지 | `NOT_FOUND` · `retryable=False` |
| KIPRIS | 검색/0건/상세/잘못된 키 — 0건과 실패를 구분 |
| Gemini | 선언한 스키마대로 구조화 출력, 비기술 문서는 `is_technical=False` |

전체 파이프라인 실측:

```
LICENSE  SUCCEEDED/COMPLETE
  pymupdf   1.24.0  AGPL-3.0-only  POLICY_CONFLICT   [LICENSE_INFERRED_FROM_FREE_TEXT]
  requests  None    Apache-2.0     NOTICE_REQUIRED   [VERSION_RANGE_NOT_PINNED]

PATENT   SUCCEEDED/COMPLETE · 후보 3건 · 근거 4건
  1020080080388  보이스-피싱 검출을 위한 GMM 모델...
```

### 실호출에서만 드러난 결함 5건 (전부 수정 완료)

대역 테스트로는 하나도 발견되지 않았다.

1. **KIPRIS 응답 필드명이 문서와 달랐다.** `applicationNumber`/`inventionTitle` 이 아니라
   `applicationNo`/`inventionName` 이다. 잘못된 이름으로 읽어 검색 결과가 항상 0건이었고,
   0건은 정상 처리 경로라서 드러나지 않았다.
2. **국문 초록이 따로 있었다.** `korAbstractInfo.korAbstract`. 검사 대상 문서가 대개
   한국어이므로 국문 초록을 우선하도록 바꿨다.
3. **Gemini 가 `additionalProperties` 를 거부했다.** Pydantic 의 `extra="forbid"` 가
   스키마에 넣는 항목인데 API 가 400 을 돌려준다. 내부 검증은 엄격하게 유지하고 API 전송
   스키마에서만 정리하는 변환기를 두었다.
4. **추정 여부 표시가 동작하지 않았다.** `normalize()` 가 자유 서술 추정까지 수행해
   `inferred_from_free_text` 가 항상 `False` 였다. 파싱과 추정을 분리했다.
5. **우선순위가 실측에서 전부 LOW 로 깔렸다.** KIPRIS 가 청구항을 제공하지 않아 청구항
   근거를 요구하는 규칙에서 모든 후보가 LOW 가 됐다. 초록 근거가 둘 이상이면 MEDIUM 으로
   올리도록 조정했다.

### 알려진 제약

- **RAG corpus 가 초기 3건** (AGPL-3.0 / LGPL-2.1 / 고지형, 총 2,120 bytes).
  84종 확대는 `manifest.yaml` 에 추가하고 `corpus_version` 을 올리면 된다.
- **특허 청구항을 쓰지 못한다.** KIPRIS Plus 제공 범위가 초록이다. `PatentDocument.claims`
  는 구현되어 있어 청구항을 얻을 수 있게 되면 그대로 동작하고 `HIGH` 판정이 가능해진다.
- **후보 상위 6건만 판정한다** (비용). 미판정 후보가 있으면 coverage 가 `PARTIAL` 이 되어
  Control 이 자동 해소하지 않는다.
- **`GEMINI_MODEL_ID` 값 미확정** — [DEPENDENCIES.md](DEPENDENCIES.md) 5절 참조.
- **RAG Engine 만 실호출 미검증** — GCP 프로젝트와 corpus 가 필요하다.
- **VWS 별 라이선스 정책 불가** — `AnalysisArtifact` 에 담을 자리가 없어 전역 정책
  `global-license-policy-2026-08-14.1` 하나만 쓴다. 조직별 정책이 필요해지면 Contract v2
  또는 별도 정책 컨텍스트가 필요하다.

### 🔴 RAG 관련 추가 발견 (인계 문서에 없던 것)

통합 단계에서 코드를 읽어 확인한 항목이다. "미검증"이 아니라 **미구현·오동작**이다.

| # | 문제 | 위치 | 영향 |
|---|---|---|---|
| A | **RAG Engine 업로더 미구현.** `CorpusUploader` 구현체가 `InMemoryCorpusUploader` 하나뿐이고 `engine.py` 에 `importFiles`/`ragFiles` 호출이 없다 | `rag/ingestion.py`, `rag/engine.py` | Spec 36 의 `upload/import RAG Engine` 미충족. 콘솔/`gcloud` 수동 업로드 없이는 검색 대상이 없다 |
| B | **`filters` 가 운영 경로에서 무시된다.** `RagEngineRetriever.retrieve()` 가 인자를 받지만 payload 에 넣지 않는다 | `rag/engine.py` | 매니페스트의 `jurisdiction`/`tags` 가 무용지물. 테스트는 `InMemoryReferenceRetriever` 만 검증해 이 불일치를 잡지 못한다 |
| C | **관련성 임계값 부재.** `threshold`/`vector_distance`/`similarity` 설정이 없다 | `intelligence/**` | 관련도와 무관하게 항상 `top_k=3` 반환 |
| D | **corpus 커버리지 18%.** RAG 를 타는 식별자는 `POLICY_CONFLICT` 9종 + `REVIEW_REQUIRED` 13종 + `UNKNOWN` 인데 대응 문서가 있는 것은 AGPL-3.0·LGPL-2.1 계열 4개뿐 | `license/policy.py` vs `rag-corpus/` | C 와 결합해 **`GPL-3.0-only` 분석 시 "이 점이 GPL-3.0 과 다르다"고 적힌 AGPL 문서가 근거로 붙는다.** 근거 ID 검증과 프롬프트 제약을 모두 통과한 채로 틀린 근거가 나간다 |

부수 사항 — `permissive-notice.md` 가 다루는 MIT/BSD/Apache-2.0/ISC 는 전부
`NOTICE_REQUIRED` 라 `needs_review` 가 `False` 다. corpus 3건 중 1건은 자기 용도로는
검색되지 않고 `UNKNOWN` 케이스에서 잘못 끌려 나올 수만 있다.

**최소 조치** — C(임계값)를 먼저 넣고 임계 미달이면 근거 없이 `policy.describe()` 고정
문구로 대체한다. 이것만으로 D 의 오근거 위험이 사라진다.

---

## 4. Shared Contract 준수

세 Plane 모두 다음을 지켰다.

| 항목 | 결과 |
|---|---|
| Frozen Pydantic source 수정 | 없음 |
| schema/TypeScript generated 수동 편집 | 없음 |
| `pnpm run generate` 후 tracked diff | 없음 |
| contract-change request | **0건** — Contract v1 로 전 범위를 표현할 수 있었다 |
| cross-plane payload | Frozen Contract 또는 facade-owned content-free DTO |
| `canonical_root_path` | 어떤 요청 스키마에도 없음 (Spec 25) |

---

## 5. 전역 불변조건

구현을 확장하더라도 다음은 유지해야 한다.

| 불변조건 | 의미 |
|---|---|
| **Raw source 비영속** | `SourceSnapshot` 은 transient. persistence 에는 승인된 최소 `AnalysisArtifact`, content-free access event, bounded Evidence 만 남는다 |
| **Provider authority 이중 검증** | `provider_authority_required=True` 는 Control RBAC 통과만 의미한다. Source Plane/provider 가 실제 credential 과 접근 권한을 다시 검증해야 한다 |
| **Gate-only boundary** | Intelligence 는 Gate 가 승인한 artifact 뒤에서만 동작한다. `security_context.approved` 미승인이면 provider 호출 전에 거부한다 |
| **Failure preserves risk** | provider/system failure 를 성공이나 "Risk 없음" 으로 바꾸지 않는다 |
| **Backend-authoritative RBAC** | 권한 판단은 항상 backend. UI 는 표시만 한다 |
| **Credential/raw 로그 금지** | raw source·credential 을 로그나 Shared Contract 에 넣지 않는다 |
| **Risk 해소 판단은 Control** | Intelligence 는 `status`/`coverage` 를 보수적으로 설정할 뿐이다 |

---

## 6. 문서 이력

이 문서는 아래 Agent 별 인계 문서를 통합해 대체한다. 원문은 git 히스토리에 남아 있다
(`git log --all -- AGENT_1_DELIVERY.md` 등).

| 원 문서 | 처리 |
|---|---|
| `AGENT_1_DELIVERY.md` | 1절 + 4·5절로 흡수. 조립 코드는 [INTEGRATION.md](INTEGRATION.md) |
| `AGENT_2_DELIVERY.md` | 2절 + 4·5절로 흡수. wiring point 는 [INTEGRATION.md](INTEGRATION.md) |
| `AGENT_3_DELIVERY.md` | 3절 + 4·5절로 흡수 |
| `AGENT_1_PLATFORM_CONTROL_IMPLEMENTATION_PLAN.md` | Phase 단위 진행 로그(183KB)는 삭제. 최종 상태·완료 정의·제약만 1절에 남겼다 |
| `agent-deliverables/agent-{1,2,3}-dependencies.md` | [DEPENDENCIES.md](DEPENDENCIES.md) |
| `LOCAL_RUN_AND_TEST_GUIDE.md` | [DEVELOPMENT.md](DEVELOPMENT.md) |
