# 특허 파이프라인 E2E — 호출을 아끼면서 끝까지 검증하는 시나리오

> 대상: `https://ip-risk-agent-v2-api-555102774494.asia-northeast3.run.app`
>
> KIPRIS 무료 등급은 **월 1,000 회**다. 이 시나리오는 **약 15~20 회**로 특허
> 기능 전체를 검증한다. 나머지는 캐시가 받는다.

## 0. 호출이 어디서 나가는가

분석 한 건의 비용은 이렇게 나뉜다.

| 단계 | provider | 캐시 | 키 |
|---|---|---|---|
| 기술요소·검색어 추출 | Gemini 1 회 | 30 일 | 문서 내용 체크섬 + 프롬프트 버전 |
| 검색 | **KIPRIS 최대 5 회** | 7 일 | 검색어 + 요청 건수 |
| 상세조회 | **KIPRIS 최대 6 회** | 90 일 | **출원번호** |
| 대조 | Gemini 후보당 1 회 | 없음 | — |
| 설명·권고 | Gemini Risk 당 1 회 | 없음(이미 있으면 건너뜀) | — |

**KIPRIS 는 검색과 상세조회 둘뿐이고 둘 다 캐시된다.** 상세조회 키가 출원번호라서
어느 workspace 의 어느 문서를 분석하든 같은 특허는 한 번만 받아온다.

## 1. 사전 조건

| 확인 | 기대 |
|---|---|
| 새 KIPRIS 키 | Secret Manager `iprisk-v2-kipris-access-key` 에 새 버전 추가 후 재배포 |
| Firestore | 기존 workspace 전부 삭제 |
| 캐시 컬렉션 | `intelligence_patent_*_cache` 도 함께 비운다 (콜드 스타트를 재현하려면) |
| 배포 | API·Worker digest 동일, `/health/ready` 200 |

캐시를 남겨 두면 1 번 단계의 "콜드 비용" 을 관측할 수 없다. 반대로 **비용만 아끼고
싶다면 캐시를 남겨 두는 것이 맞다.**

## 2. 문서 구성 — 왜 이 조합인가

| 문서 | 도메인 | 노리는 것 |
|---|---|---|
| `voice-phishing-detection-design.md` | 음성 | 콜드 비용 측정 |
| `speaker-diarization-recording-analysis.md` | **같은 음성** | 검색어·후보가 겹쳐 캐시 적중 |
| `battery-thermal-runaway-detection-design.md` | 배터리 | 다른 도메인의 콜드 비용 |
| `negative-weekly-meeting-notes.md` | — | 기술 문서가 아님 → KIPRIS 0 회 |
| `requirements.txt` | — | License 경로 → KIPRIS 0 회 |

**같은 도메인 문서를 둘 넣는 것이 핵심이다.** 전처리 용어(켑스트럼, 화자 분리,
음성 특징)가 겹쳐 검색어가 겹치고, 검색어가 겹치면 후보도 겹친다.

---

## S1. 콜드 — 첫 문서

Drive 에 `voice-phishing-detection-design.md` 만 올리고 mount.

| 확인 | 기대 |
|---|---|
| `patent_search_diagnostic` | `query_count` 2~5, `search_failures` 0 |
| `patent_priority_diagnostic` | 후보마다 1 줄. `evidence_strength` 기록됨 |
| Risk | 후보당 1 건. 근거에 `PATENT_CLAIM` + `SOURCE_EXCERPT` |
| Risk 상세 | **설명·권고가 자동으로 붙어 있다** |
| KIPRIS 소모 | 약 **11 회** (검색 5 + 상세 6) |

## S2. 같은 도메인 두 번째 문서 — 캐시가 받는다

`speaker-diarization-recording-analysis.md` 추가.

| 확인 | 기대 |
|---|---|
| 분석 성공 | SUCCEEDED / COMPLETE |
| KIPRIS 소모 | **2~5 회** — 겹치는 검색어와 후보는 캐시가 받는다 |

두 문서의 Risk 에 **같은 출원번호가 등장하면** 상세조회 캐시가 먹었다는 뜻이다.
Risk 자체는 artifact 단위이므로 문서마다 따로 생기는 것이 정상이다.

## S3. 재검사 — **KIPRIS 0 회여야 한다**

`voice-phishing-detection-design.md` 를 **바꾸지 않고** "다시 검사".

| 확인 | 기대 |
|---|---|
| KIPRIS 소모 | **0 회** |
| Risk 목록 | **하나도 새로 생기지 않고 하나도 RESOLVED 되지 않는다** |
| lifecycle | 기존 Risk 가 `NEW` → `EXISTING` 로만 바뀐다 |

이것이 이번 수정의 핵심 검증이다. 예전에는 같은 문서를 재검사했더니 특허 2 건이
새로 잡히고 2 건이 RESOLVED 됐다. 추출이 모델이라 실행마다 검색어가 달라졌기
때문이고, 그 RESOLVED 는 "판정해 보니 아니다" 가 아니라 **"이번엔 보지도 않았다"**
였다.

## S4. 문서 수정 — 이월이 작동하는가

`voice-phishing-detection-design.md` 에 **문단 하나를 추가**한다. 기존 내용은
지우지 않는다.

| 확인 | 기대 |
|---|---|
| 변경 감지 | 새 ChangeEvent (또는 "다시 검사") |
| KIPRIS 소모 | **1~3 회** — 새로 생긴 검색어만 |
| 기존 Risk | 검색이 데려오지 않아도 **다시 대조되어 `EXISTING` 유지** |
| 새 Risk | 추가 문단이 새 후보를 부르면 `NEW` |

이월은 출원번호로 이뤄지고 상세조회는 90 일 캐시라 **KIPRIS 실호출이 없다.**

## S5. 문서 내용을 크게 바꿔 겹침을 없앤다 — 진짜 해소

`voice-phishing-detection-design.md` 의 기술 서술을 **다른 주제로 교체**한다.

| 확인 | 기대 |
|---|---|
| 기존 Risk | 이월되어 대조되었으나 겹치지 않음 → **`RESOLVED`** |
| 이때의 RESOLVED | "판정해 보니 더 이상 겹치지 않는다" 는 **진짜 판정** |

S3 의 RESOLVED 없음과 이 단계의 RESOLVED 가 함께 나와야 규칙이 맞는 것이다.

## S6. 대조군 — KIPRIS 를 쓰지 않는 경로

| 문서 | 기대 |
|---|---|
| `negative-weekly-meeting-notes.md` | `is_technical=false` → **SKIPPED**, Risk 0, KIPRIS 0 회 |
| `requirements.txt` | License 경로. Risk 생성, 설명·권고 붙음, KIPRIS 0 회 |
| Google 문서(확장자 없음) | `FILE_TYPE_DENIED` 가 **더 이상 나지 않는다** |

## S7. 한도 안내 (선택)

한도를 일부러 소진시킬 필요는 없다. 다만 소진되면 화면에 이렇게 떠야 한다.

> **특허 조회 한도를 다 썼습니다** — 다시 검사해도 같은 결과입니다.

다른 실패(빨강)와 톤이 구분되는지만 확인한다.

---

## 예상 총 소모

```
S1  콜드 첫 문서          ~11
S2  같은 도메인 두 번째    ~3
S3  재검사                  0   ← 핵심
S4  문단 추가             ~2
S5  주제 교체             ~4
S6  대조군                  0
                        ─────
                        ~20 회  (월 1,000 의 2 %)
```

## 판정

| | 조건 |
|---|---|
| **Go** | S3 이 KIPRIS 0 회 + Risk 변화 없음, S4 가 이월로 EXISTING 유지, S5 가 진짜 RESOLVED |
| **조건부 Go** | 위 셋 중 S5 만 미검증 (문서 교체 수고) |
| **No-Go** | S3 에서 Risk 가 새로 생기거나 RESOLVED 가 발생 |

기록할 것 — 단계마다 `patent_search_diagnostic` 의 `query_count`,
`patent_priority_diagnostic` 의 등급과 `evidence_strength`, 그리고 Risk 의
lifecycle 변화. **토큰·API 키·문서 원문은 기록하지 않는다.**
