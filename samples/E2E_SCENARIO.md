# 백지 환경 E2E 테스트 시나리오

대상: `https://ip-risk-agent-v2-api-555102774494.asia-northeast3.run.app`

이 문서는 **저장 데이터를 모두 지운 상태에서** 서비스 한 줄 정의를 끝까지 관통시키는
절차다. 각 단계는 **관측 가능한 성공 기준**을 갖고, 실패하면 무엇을 볼지까지 적는다.

> 한 줄 정의 — Local Directory, GitHub Repository, Google Drive 등 여러 실제 협업 Source
> Workspace를 하나의 Risk Workspace에 연결하고, 변경을 지속적으로 감지하여 Patent·License
> 중심의 잠재적 IP Risk를 근거 기반으로 분석하고, 사용자가 장기적으로 검토·추적·감사할 수
> 있게 하는 Secure Human-in-the-Loop AI Risk Management System.

---

## 0. 사전 조건

| 확인 | 기대 |
|---|---|
| 배포 이미지 | API·Worker digest 동일, `/health/ready` 가 `ready` |
| Firestore `ip-risk-agent-v2` | 문서 0건 |
| `iprisk-v2-cred-*` secret | 0건 |
| Cloud Tasks 큐 | 비어 있음 |
| Scheduler 4종 | ENABLED (리셋 중 일시중지했다면 재개) |
| Google 계정 | 앱 접근 권한 해제 완료 → 재동의 화면이 다시 뜬다 |

### 브라우저 준비 — 시크릿 창을 쓰지 않는다

백지 조건에서 지워야 하는 것은 **이 앱의 세션 쿠키** 하나뿐이고, 그것은 API 와 같은
origin 이다. 반면 Google Picker 는 `apis.google.com` iframe 에서 Google 세션 쿠키를
**서드파티 컨텍스트**로 읽는다. 시크릿 창은 이를 기본 차단하므로 Picker 가 뜨지 않는다.

다음 중 하나를 쓴다.

| 방법 | 절차 |
|---|---|
| **새 브라우저 프로필** (권장) | Chrome 프로필 추가 → 그 창에서만 진행. 쿠키가 비어 있고 서드파티 제한은 정상 |
| 현재 창에서 사이트 데이터만 삭제 | DevTools → Application → Storage → **Clear site data** (API origin 에서 실행) |
| 시크릿 창을 계속 쓰려면 | 주소창의 눈/차단 아이콘 → 해당 사이트에 **서드파티 쿠키 허용** |

어느 쪽이든 **Google 계정의 앱 접근 권한 해제**는 별도로 해야 재동의 화면이 뜬다.

---

## S1. 로그인과 Risk Workspace 생성

1. 루트 접속 → 미인증이면 `/login` 으로 수렴
2. Google 로그인
3. Workspace 생성 (이름: `E2E-A`)

| 성공 기준 |
|---|
| `/api/v1/auth/me` 200 |
| Workspace 목록에 `E2E-A` 표시 |
| Risk 목록 비어 있음 (0건) |

실패 시 — API 로그에서 `diagnostic_code` 확인. 로그인 경로는
`authentication_required` / `csrf_validation_failed` / `identity_provider_unavailable` 로 갈린다.

---

## S2. Drive 최초 연결과 파일 선택

**핵심 검증 — 계정 단위 Source Workspace**

1. Add Source → Google Drive → OAuth 동의 (재동의 화면이 떠야 정상)
2. Picker 에서 **파일 2개** 선택
   - `requirements.txt`
   - `voice-phishing-detection-design.md`
3. 이름을 바꾸지 않고 그대로 올린 파일이어야 한다 (§samples/README.md 의 이름 규칙)

| 성공 기준 |
|---|
| `POST .../drive/mounts` → **200** |
| Sources 화면에 mount 1건, alias 가 **계정 이메일 기반** (digest 아님) |
| 추적 파일 2건 표시 |
| `iprisk-v2-cred-google_drive-*` secret 1건 생성 |

실패 시 — 그 요청의 **request body 와 response body 를 함께** 캡처.
이제 `diagnostic_code` 가 Cloud Logging 에 남으므로 아래로 확인한다.

```bash
gcloud logging read 'resource.labels.service_name="ip-risk-agent-v2-api" AND jsonPayload.diagnostic_code!=""' \
  --limit 20 --freshness=30m --format='value(timestamp,jsonPayload.diagnostic_code,jsonPayload.status_code)'
```

---

## S3. 분석 결과와 Risk 생성 — **이 시나리오의 성패를 가르는 단계**

mount 직후 초기 스캔이 두 파일에 대해 SourceChange 를 만들고 Cloud Tasks → Worker 로 흐른다.

| 성공 기준 |
|---|
| Worker request log **≥ 2건**, 전부 200 |
| Worker 로그에 `FileNotFoundError` **없음** (프롬프트 wheel 포함 검증) |
| `requirements.txt` → Analysis **SUCCEEDED / COMPLETE** |
| Risk **≥ 4건** 생성 |
| `voice-phishing-detection-design.md` → Analysis **SUCCEEDED** |

### Risk 기대 내역 (`requirements.txt`)

| 패키지 | 라이선스 | 판정 |
|---|---|---|
| `pymupdf` | AGPL-3.0-only | **POLICY_CONFLICT** |
| `certifi` | MPL-2.0 | REVIEW_REQUIRED |
| `psycopg2` | LGPL-2.1-only WITH exceptions | REVIEW_REQUIRED |
| `requests` | Apache-2.0 | NOTICE_REQUIRED |
| `click` | BSD-3-Clause | NOTICE_REQUIRED |
| `urllib3` | UNKNOWN | UNKNOWN (버전 범위 미고정) |

deps.dev/PyPI 실시간 응답이므로 값이 다르면 그 자체가 관찰 결과다.

**Analysis 가 INCONCLUSIVE 로 끝나면** provider 조회가 하나라도 실패했다는 뜻이다.
`coverage=PARTIAL` 이면 Risk 는 하나도 만들어지지 않는다 — 후보 단위가 아니라 **파일 전체**가
비권위적으로 취급된다. Worker 에서 deps.dev 로 나가는 egress 를 먼저 의심한다.

```bash
gcloud logging read 'resource.labels.service_name="ip-risk-agent-v2-worker"' \
  --limit 50 --freshness=30m --format='value(timestamp,jsonPayload.event,jsonPayload.diagnostic_code)'
```

---

## S4. HITL — 검토·추적·감사

**이 프로젝트에서 한 번도 검증된 적 없는 영역이다.**

1. Risk 목록에서 `pymupdf` POLICY_CONFLICT 항목 열기
2. 근거(Evidence) 가 붙어 있는지 확인
3. Timeline 확인
4. review 처분 적용 (예: 승인/보류)
5. Activity / Audit 화면 확인

| 성공 기준 |
|---|
| Risk 상세에 **근거가 실제로 표시** (빈 근거 아님) |
| Timeline 에 생성 이벤트 존재 |
| review 처분 후 상태가 바뀌고 Timeline 에 이벤트가 추가됨 |
| Audit 에 `SOURCE_CONNECTED` / `MOUNT_CREATED` 기록 |
| 원문 열기(Open Original) 가 정확히 `drive.google.com` 으로 이동 |

> 근거 품질 주의 — RAG corpus 가 3건뿐이고 관련성 임계값이 없다. `GPL-3.0` 계열 분석에
> AGPL 문서가 근거로 붙을 수 있다. 근거가 **주제와 맞는지** 눈으로 확인한다. 어긋나면
> Phase 5 의 임계값 도입 대상이다.

---

## S5. 같은 계정 재연결과 파일 추가 — **계정 단위 모델 검증**

1. 같은 Drive 카드에서 **Add files**
2. Picker 에서 `package.json` 추가 선택

| 성공 기준 |
|---|
| **새 Source Workspace 가 생기지 않는다** (mount 여전히 1건) |
| 기존 mount 의 추적 파일이 2건 → 3건으로 **누적** |
| alias 가 바뀌지 않는다 |
| `package.json` 분석 → SUCCEEDED / COMPLETE, Risk 4건 (전부 NOTICE_REQUIRED) |

### S5-b. 이미 추적 중인 파일 재선택

동일 파일을 다시 고른다.

| 성공 기준 |
|---|
| 오류가 아니라 **멱등 응답** — 화면이 깨지지 않고 추적 목록도 그대로 |

---

## S6. 두 번째 Risk Workspace에 같은 계정 연결 — **409 회귀 검증**

1. Workspace `E2E-B` 생성
2. 같은 Google 계정으로 Drive 연결
3. 파일 1개 선택 (`battery-thermal-runaway-detection-design.md`)

| 성공 기준 |
|---|
| `POST .../drive/mounts` → **200** (이전에 409 로 막히던 지점) |
| `E2E-B` 에 mount 1건 생성 |
| `E2E-A` 의 추적 목록이 **영향받지 않음** |

두 workspace 의 데이터가 서로 새지 않는지가 핵심이다. `E2E-A` 의 Risk 수가 그대로여야 한다.

---

## S7. 변경 지속 감지

1. Drive 에서 `requirements.txt` 를 수정한다 — 예: `pymupdf==1.24.0` 줄을 지운다
2. Drive watch 알림 또는 reconciliation(15분 주기)을 기다린다

| 성공 기준 |
|---|
| 새 ChangeEvent 발생 → Worker 재호출 |
| 재분석 후 `pymupdf` Risk 가 **RESOLVED** 로 전이 |
| 나머지 Risk 는 유지 |

수동으로 당기려면:

```bash
gcloud scheduler jobs run ip-risk-agent-v2-drive-reconciliation --location=asia-northeast3
```

---

## S8. 음성 대조군과 negative

| 케이스 | 방법 | 기대 |
|---|---|---|
| 기술 문서가 아닌 문서 | `negative-weekly-meeting-notes.md` 추가 | Analysis **INCONCLUSIVE**, Risk 0건 (`is_technical=false → SKIPPED`) |
| provider 조회 실패가 결과를 덮는지 | `requirements.txt` 의 주석 처리된 nonexistent 줄을 켜서 별도 파일로 | Analysis INCONCLUSIVE, **Risk 0건** — 파일 전체가 비권위적 |
| 미선택 파일 접근 | Drive 에 있지만 고르지 않은 파일 | 분석 대상에 나타나지 않음 |
| scheduler 무인증 호출 | `curl -X POST .../internal/scheduler/drive-reconciliation` | 401/403 |
| 잘못된 method | `curl -X GET .../drive/mounts` | **405** (422 아님) |

---

## 9. 판정

| | 조건 |
|---|---|
| **Go** | S1~S6 전부 성공 + S8 negative 전부 기대대로 |
| **조건부 Go** | S7 미검증(대기시간) 외 전부 성공 |
| **No-Go** | S3 에서 Risk 가 생기지 않음, 또는 S6 이 여전히 409 |

각 단계 결과는 timestamp·HTTP status·revision·`diagnostic_code` 로 기록한다.
**토큰, Picker callback 원문, Drive 응답 본문, 로컬 절대경로는 기록하지 않는다.**
