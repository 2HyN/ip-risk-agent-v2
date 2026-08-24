# 특허 분석 고도화 전략 — 검색·대조·판정 3층과 Ephemeral RAG

> 성격: **최종(3차) 단계 고도화의 규범 문서.** 5개 설계 트랙을 독립 설계 → 적대적
> 비평 → 종합의 순서로 검토해 확정했다 (2026-08-24). 비-RAG 현행 방식은 삭제하지
> 않고 전략 스위치 뒤에 베이스라인으로 병존한다.
>
> 실행 순서 변경 (사용자 결정 2026-08-24): golden dataset 구성 완료를 기다리지
> 않는다. **특정 특허 리스크 후보 문서 1건에 대해 제안된 전체 흐름이 온전히
> 수행되는 것**을 먼저 구현·검증하고, 골든셋이 도착하면 분석 결과를 보정
> (임계값 교정·채택 판정)한다.

## 0. 바뀐 전제

| 전제 | 내용 | 효과 |
|---|---|---|
| KIPRIS 유료 전환 | 월 1,000회 한도 소멸. **초당 호출 횟수만 주의** | 검색 파라미터(질의 5개 × rows 5)를 묶던 이유가 사라짐. 클라이언트 토큰 버킷으로 초당 관리 |
| 골든 데이터셋 | 팀이 거절결정서·의견제출통지서 기반으로 구성 중. 심사관 인용 선행문헌 = 검색 정답 | "라벨 없이 고른 임계값은 근거가 없다"(설계 노트 §5)의 조건이 충족 가능해짐. **단, 도착 전에는 E2E 수행 가능성만 검증하고 교정은 유예** |
| 계약 강제성 완화 | 효과적이면 사용자 허락 후 Frozen Contract 변경 가능 | 본 전략은 **계약 변경 0건**으로 완결 (§6). 승격 후보만 기록 |
| 작업 규칙 | 기존 방식 보존(비교 베이스라인), UI는 맨 마지막, 그 전까지 단위·기능 테스트로만 검증 | 3개 전략 스위치 축, 기본값 = 현행 |

## 1. 현행 베이스라인의 실측 병목

```
추출(v2, 질의 2~5) → 검색(AND, rows 5, 풀 ≤25) → 순위(적중수·위치, cap 6)
  → 상세(청구항 전체 수신) → 대조(앞 3개 청구항만, 문서 전체 재전송, 직렬)
  → 검증(grounding) → 판정(이산 규칙표)
```

1. **Recall 병목 (검색).** 후보 풀 상한 25건. 심사관 인용급 선행문헌이 어느
   질의에서도 상위 5위 안에 못 들면 원리적으로 안 보인다. IPC는 수집되지만
   (`kipris.py`) 미사용.
2. **선별 병목 (순위).** 질의 적중 수는 대부분 1이라 동률이고, 동률은 KIPRIS
   내부 순서(관련도 값 없음)로 갈린다 — cap 6 경계가 사실상 임의적.
3. **대조 병목 (컨텍스트).** `max_claims=3`이 4항 이후의 독립항(물건항+방법항
   2계열)과 종속항 한정을 통째로 버린다. 긴 초록의 600자 절단이 HIGH→MEDIUM
   강등을 오발동. 실측 등급 분포 LOW 38 · MEDIUM 47 · HIGH 5, **MEDIUM 47건 중
   38건이 match_count==1** — 점수 분자가 사실상 상수.

## 2. 전략 스펙트럼 — 비교 검토와 판정

| 전략 | 판정 | 근거 |
|---|---|---|
| **T5 평가 하네스** (골든셋·녹화-재생·지표 4층) | 채택 (골든셋 도착 후 본격 가동) | 모든 채택 판정의 자(尺). SPEC §10 "측정 없이 고도화를 주장하지 않는다" |
| **T1 검색층 확장** (질의 12·rows 30·0-hit 완화·RRF·IPC tie-break·토큰 버킷) | **채택 — 즉시 구현** | 유료 전환의 배당 직접 회수. rows 확대만으로 질의당 가시 범위 6배. 임베딩 없이 결정론 유지 |
| **T3 Ephemeral RAG** (청구항 전량 청킹·BM25 일시 인덱스·독립항 전수·요소 색인 대조) | **채택 — 즉시 구현** | 대조 병목 3종을 정면 해결. 외부 호출 0, KIPRIS 추가 0, 신규 저장 0, 지연 −50~70% |
| **T4 점수·임계값** (score v2·골든 라벨 교정·shadow mode) | 채택 — **골든셋 도착 후** | 임계값은 라벨 없이 정하지 않는다. 그 전에는 관측 필드만 준비 |
| T2 임베딩 하이브리드 re-rank | 조건부 유예 | AND 검색 풀은 어휘 일치 후보뿐이라 한계 이득 미검증 — 하네스 ablation으로 측정 후 결정 |
| LLM cross-encoder re-rank | 불채택 | 결정론적 순위 원칙(`candidate_rank.py` 머리말)과 충돌. 순위는 판정이 아니므로 층 규칙 위반은 아님 — 경계 논증은 §5 |
| 영속 특허 RAG corpus (Vertex RAG Engine) | 불채택 | 후보 집합 자체가 비공개 문서의 파생 정보 — 영속화하면 워크스페이스 간 추론 채널. 원문은 이미 90일 문서 캐시에 있음 |
| getAdvancedSearch (IPC·청구범위 2단계 검색) | probe 조건부 | 파라미터가 2차 출처 근거뿐. 우리 ServiceKey 실측(probe) 통과 후에만. 실패해도 T1은 단독 성립 |

## 3. 채택 아키텍처

```
추출 v3 (다관점 질의 ≤12, 중요 단어 선행)
 → 검색 확장 (rows 30 · 0-hit 완화 · 토큰 버킷 · 단계 deadline)
 → RRF 순위 (+IPC 일관성 tie-break) → 대조 cap 6~8 (+이월 무조건 합류)
 → 상세 (청구항 전체, 캐시 90일)
 → 청구항 파싱 (독립/종속 판별, 전부-파싱-또는-전부-위치)
 → Ephemeral 인덱스 (BM25 어절+bigram, 분석 종료 시 소멸)
 → 대조 v3 (독립항 전수 ∪ claims[:3] ∪ 요소별 관련 종속항 · [En] 요소 색인 · 병렬 3)
 → 검증 (grounding 불변 — 근거 ID·인용 실재, 위반 시 후보 폐기)
 → 판정 (이산 규칙표 불변 · 점수는 관측 · 임계값 전환은 골든셋 교정 후)
```

### 전략 스위치 (3축 독립, 기본값 = 현행)

| 환경변수 | 값 | 뜻 |
|---|---|---|
| `PATENT_SEARCH_STRATEGY` | `baseline` \| `expanded_v1` | 검색·순위 계획 |
| `PATENT_COMPARE_STRATEGY` | `baseline` \| `rag` | 대조 컨텍스트 구성 |
| `PATENT_PRIORITY_STRATEGY` | `rule` (\| `score_shadow` \| `score` — 골든셋 후) | 판정 전략 |

**baseline 조합이면 코드 경로·기록 문자열이 현행과 동일하다.** 기존 테스트의
무수정 통과가 보존의 기계적 증거다. 비-baseline일 때만 `prompt_version`에 전략
버전을 연접한다 — baseline에 연접하면 배포 직후 모든 재검사가
`ChangeCause.MODEL`로 오귀속되기 때문이다 (비평 F1).

### 바뀌지 않는 것

- 근거 ID·인용 실재 검증(grounding) — 위반 시 후보 전체 폐기, 1회 재질의
- 판정 권한의 소재 — 등급은 코드가 정하고 모델은 제안만. 강등은 코드가 아는
  사실로만 (근거 잘림 · 컨텍스트 미완)
- carried-forward — 기존 매칭 특허는 검색·순위와 무관하게 재대조 (조용한 해소
  차단의 안전핀)

## 4. 평가 방법론 (골든셋 도착 후 본격 가동)

- **정답의 출처**: KIPRIS Plus 인용문헌V3 API가 "출원번호 → 심사관 인용문헌"을
  기계가독으로 준다(출원인/심사관 인용 구분). 거절 이유 조항(§29①/②)·청구항
  매핑은 통지서 본문 파싱으로 **보강**하되 optional 필드로 둔다.
- **표본**: 의견제출통지서 수령 출원 **전체**에서 표집 (거절 확정 건만 모으면
  recall 과대평가).
- **지표 4층**: R 검색(Recall@pool/@cap·MRR — 검색이 못 데려온 몫과 순위가 자른
  몫을 가름) / C 대조(gold-injection으로 검색과 독립 측정, CCR) /
  G 등급(조항→기대 등급: 신규성=HIGH, 진보성 주인용=HIGH, 부인용=MEDIUM;
  AUC(evidence_strength)) / $ 비용(호출·토큰·지연).
- **규율**: 녹화-재생(스냅샷 miss는 빈 결과가 아니라 예외 — "모른다 ≠ 0건") ·
  자기/패밀리 인용 제외 · dev/holdout 분리(IPC 층화) · paired bootstrap 95% CI +
  부호검정 — CI가 0을 배제할 때만 "개선"이라 말한다.
- **골든셋 팀 요청 3가지**: ① 인용문헌V3를 뼈대로(조항 파싱은 보강)
  ② 통지서 수령 출원 전체에서 표집 ③ 인용 번호의 출원번호 정규화 최우선
  (+ KIPRIS Plus API 통합설명서 사본).

## 5. 원칙 정합성

- **판정 권한 층(T1/T2/T3)**: 검색·순위·청크 선별은 판정 이전의 후보·컨텍스트
  구성이며 전부 결정론 계산(T1 성격). 등급 함수의 입력은 여전히 검증된 사실뿐.
  탈락 후보는 "미판정"이지 LOW가 아니다 — IPC는 제외 필터가 아니라 tie-break
  신호. 단 "후보 집합 구성 층" 원칙은 SPEC §4에 없는 확장 해석이므로 명문화에
  사용자 승인이 필요하다.
- **match_count 재정의**: 대조 v3에서 "distinct 요소 인덱스 수"로 계산 (중복
  서술 부풀림 차단, 상한 = 추출 요소 수). 규칙 버전 표기로 남긴다.
- **Frozen Contract 영향: 변경 0건.** 신규 관측값은 전부
  `provider_metadata_safe`(자유 dict). 전략 버전은 `prompt_version` 문자열 연접.
  `AnalysisVersions.policy_version`이 계약에 이미 존재하고 특허가 미사용 —
  임계값·규칙 버전은 여기 싣는다 (§4.2 "임계값은 정책이다"의 정공법).
  장래 승격 후보(= 사용자 허락 필요)만 기록: 검색 전략·연속 점수의 1급 필드화.

## 6. 비평이 잡은 필수 수정 (구현 조건)

1. baseline 플랜은 `prompt_version` 무연접 (원인 귀속 오염 방지)
2. 완화 히트는 캐시 객체를 변이하지 않고 `dataclasses.replace`로 재생성
3. 검색 단계 deadline (확장 전략에서 최악 지연이 300초 예산을 뚫는 tail 차단)
4. 대조 컨텍스트 상위집합 불변식: `claims[:3]` ∪ 독립항 전수 ∪ 검색 종속항
5. 청구항 번호 파싱은 문서 단위 전부-파싱-또는-전부-위치 (혼합 금지 — 원장 ID
   충돌 크래시 방지)
6. `query_reach`는 판정 점수에서 제외 (이월/주입 후보에서 구조적 0 — 편향)
7. gold-injection 콜백은 async + 주입 수 하드 assert (침묵 실패 차단)
8. 골든 평가에서 자기·패밀리 인용 제외 필터
9. Gemini 스냅샷 키에 동일 프롬프트 호출 순번 포함 (재질의 재생 일치)
10. RRF 기대치는 "단일 채널 델타 ≈ 0, 가치는 다채널 융합 인프라"로 정직 선언

## 7. 실행 계획 (수정판 — E2E 우선)

| 단계 | 내용 | 게이트 |
|---|---|---|
| **E1 (지금)** | T1 expanded_v1 + T3 ephemeral rag 구현, 전략 스위치, E2E 러너(`scripts/run_patent_e2e.py`) — **후보 문서 1건에 대해 전체 흐름 완주** | 기존 테스트 무수정 통과 + 신규 단위/기능 테스트 통과 + 러너로 흐름 완주 |
| E2 (골든셋 도착) | T5 하네스 가동 → 베이스라인 기준표 → 전략별 paired 비교 | Recall/CCR 개선 CI가 0 배제 시 채택 |
| E3 | T4 임계값 교정 (t_med/t_high) + shadow mode → 게이트 통과 시 score 전환 | rule 베이스라인의 recall·HIGH 총량 비하회 + 불일치 20건 수동 검토 |
| E4 (조건부) | T2 임베딩 re-rank ablation · probe 통과 시 getAdvancedSearch | 측정으로 채택/기각 — 기각도 보고서의 결론 |

## 7.1 E1 구현 기록 (2026-08-24)

**E1 코드 구현 완료.** 전체 비-live 스위트 1,203건 통과(기존 전량 무수정 통과 —
베이스라인 보존의 기계적 증거), 신규 시험 48건(claims 9 · ephemeral 7 ·
strategy 16 · rag e2e 7 + 기존 확장). 실모델(Gemini) 호출을 포함한 러너 실행은
자격증명 주입 후 1명령이다 (§7 E1 게이트의 마지막 칸).

| 구역 | 내용 |
|---|---|
| 신규 | `intelligence/patent/{search_strategy,rate_limit,claims,ephemeral_index}.py` · `gemini/prompts/patent_{extract,compare}_v3.md` · `scripts/run_patent_e2e.py` · `tests/intelligence/test_patent_{claims,ephemeral,strategy,rag}.py` |
| 수정 | `extraction.py`(clamp·프롬프트 파라미터화) · `query_builder.py`(rows·0-hit 완화·단계 마감) · `candidate_rank.py`(RRF+IPC, 기존 함수 보존) · `kipris.py`(rate limiter 주입·번호 메타 수집) · `grounding.py`(v3 검증, distinct match) · `evidence_builder.py`(rag 근거 등록) · `analyzer.py`(전략 분기·rag 병렬 대조) · `schemas.py`(V3) · `public.py`(설정 배선) |
| 스위치 | `PATENT_SEARCH_STRATEGY` / `PATENT_COMPARE_STRATEGY` / `KIPRIS_MAX_RPS` — 기본값 전부 baseline (조립: `IntelligenceConfig.from_env`) |
| 러너 | `python scripts/run_patent_e2e.py --doc samples/patent/... --kipris corpus\|live --search-strategy expanded_v1 --compare-strategy rag` (Gemini 는 실호출 — `GEMINI_MODEL_ID` + `GEMINI_API_KEY` 또는 `GCP_PROJECT_ID`/ADC) |
| §6 수정 반영 | 1(baseline 무연접) · 2(완화 replace 재생성) · 3(단계 마감) · 4(상위집합: 독립항∪claims[:3]∪검색 종속항) · 5(전부-파싱-또는-전부-위치) · 10(RRF 단채널 델타≈0 을 시험으로 고정) — 6·7·8·9 는 E2(하네스) 소관 |

### E1 실검증 완료 (2026-08-24, 유료 KIPRIS 키 v3 + Vertex ADC)

**실재 문서 1건(보이스피싱 탐지 기획서)에 대해 전체 흐름이 실 API 로 완주됐다.**
단계별 입출력 검증을 거쳤고, 실측이 코드 보정 2건을 만들었다.

**실측 발견과 보정 (probe 를 겸함):**

1. **`getWordSearch` 의 `docsStart`/`docsCount` 는 무시된다** — 5 를 보내도 30 을
   보내도 서버 기본 10 건. 즉 현행 "rows=5" 는 줄곧 10 건을 받고 있었다. 실제로
   듣는 파라미터는 **`pageNo`/`numOfRows`** (numOfRows=30 → 30 건 유니크 실측).
   보정: rows=5(베이스라인)는 요청 모양을 보존하고, rows≠5(확장)만 실측
   파라미터를 쓴다 (`kipris.py`).
2. **상세조회 청구항은 "1. 본문…" 번호 형식**, 보정 삭제 청구항은 "N. 삭제".
   보정: 파서가 이 머리도 읽고(삭제 청구항으로 번호에 구멍이 나도 ID 불변),
   삭제 청구항은 조각화에서 제외 (`claims.py`).

**같은 문서 A/B 실측:**

| | baseline (v2) | expanded_v1 + rag |
|---|---|---|
| 소요 | 104.7초 (직렬 대조) | **46.4초** (병렬 3) |
| 검색 | 질의 4 · hit 40 | 질의 10 · **hit 285** · 0-hit 0 |
| 결과 | 4건 (HIGH 1) | 3건 (HIGH 1) · coverage COMPLETE · 실패 0 |
| 화자분리 특허 1020140095570 | **MEDIUM** (초록 근거) | **HIGH** — 분할 청구항(claim:1:part:1, claim:2) 근거 확보 |
| 근거 | 30건 | **89건** — claim:19:part:2 처럼 앞-3개 창 밖 청구항이 검색으로 편입 |
| 기록 | prompt_version 현행 그대로 (무연접 보존 확인) | `…+search_expanded_v1+patent_rank_rrf_v1+claimchunk-v1+bm25-v1` |

관측 메모: 두 전략의 match_count 는 뜻이 다르다(v2=서술 수, v3=distinct 요소 수).
baseline 이 매칭한 2건(스팸차단·음성 구간 분리)이 rag 에서 빠진 것은 요소 단위
대조의 더 엄격한 기준 때문일 수 있다 — 정밀도/재현율 판정은 골든셋(E2)이 한다.

미실행: getAdvancedSearch probe(§2 조건부), 골든셋 하네스(E2).

## 7.2 E2 진행 기록 (2026-08-25)

### E2-0 — ui-change 병합 (완료)

팀원 B 의 `origin/ui-change`(골든셋 스크립트 5종 · opt-in 검색 실험 · UI 강조)를
advanced_rag 에 병합했다. 백엔드 3파일(analyzer·extraction·kipris) 충돌은 B 의
opt-in 손잡이(prior_art_cutoff · search_rows · query_expansion · search_fields)를
**생성자 인자 표면 그대로 유지**한 채 SearchPlan 체계와 공존시키는 방향으로
해소 — 평가 스크립트(evaluate_golden.py)는 직접 인자로, 전략 경로는 계획으로
같은 손잡이를 잡는다. 전체 스위트 1,205건 통과.

B 의 골든셋 실측이 §2 판정 하나를 뒤집었다: **getAdvancedSearch(항목별검색)는
probe 조건부가 아니라 핵심 채널이다.** 전문(getWordSearch) AND 검색은 2단어
질의("셔터 연동")도 8,166건 속에 심사관 인용 문헌을 묻지만(60위 밖), 같은
질의를 제목 필드로 좁히면 19건 중 4위, 초록 필드는 394건 중 9위였다. 또한
getAdvancedSearch 는 getWordSearch 와 달리 **docsCount 를 20 까지 존중한다** —
엔드포인트별 파라미터 차이는 `kipris.py` 주석으로 명문화했다.

### E2-1 — `fielded_v1` 전략 프리셋 (완료)

B 의 최적 조건(필드별 검색 × 질의 확장)을 세 번째 정식 전략으로 승격:

| 손잡이 | 값 | 근거 |
|---|---|---|
| search_fields | (inventionTitle, astrtCont) | 제목 정밀 우선 병합 + 초록 재현 보충 (실측) |
| expand_queries | true — 2단어 부분조합, cap 15, 질의별 라운드로빈 | AND 검색 어휘 민감성 완화 |
| rows | 20 | getAdvancedSearch 실측 상한 |
| relax_zero_hits | false | 확장이 같은 문제를 앞단에서 깎는다 — 겹치면 호출만 는다 |
| use_rrf | true | 다질의 융합 (완화 채널 없음) |
| 기록 | `search_fielded_v1` 연접 | 후보 풀 지문 |

배선: 검색 채널은 KiprisClient 속성이므로 조립부(public.py ·
run_patent_e2e.py)가 계획의 search_fields 를 클라이언트에 넘긴다. 신규 시험 5건
(계획 상수 · 채널 보존 · 필드 병합/중복 제거 · 계획發 확장 · 컷오프 필터).

남은 E2: 골든셋 하네스 러너(Layer R — B 셋 59건 recall · Layer C — A 셋 157쌍
대조 A/B · Layer G — 라벨×evidence_strength 분포) 및 전략별 paired 비교.

### E2-2 — 하네스 + 소규모 측정 (완료)

`evaluate_golden.py` 확장(`--search-strategy` 프리셋 모드 · GOLDEN_DIR ·
Vertex 폴백 · 자기 출원 제외)과 대조 층 러너 `evaluate_compare_pairs.py`
(A 셋 157쌍, 검색 축 고정 v2/v3 쌍대) 를 만들고 소규모(11출원·8쌍)로 돌렸다.

* **Layer C (A 셋 8쌍)**: v3(rag) 매칭 재현 6/8 vs v2 5/8, 강도 중앙값
  0.70 vs 0.60, v2 만 잡은 쌍 0건 — 대조 축은 v3 우세 방향.
* **Layer R**: 모든 검색 조건(baseline·B 의 개선 3종·fielded_v1)이
  공통 10출원·인용 23건에서 1/23 로 동률 — 조건 간 차이가 없다.
* **교란 발견**: 평가 실행마다 Gemini 질의가 다시 뽑혀 검색 풀 자체가
  달라진다(같은 출원이 후보 5건 → 0건). 순위 변경의 A/B 는 라이브
  평가로는 불가능 — 고정 풀 오프라인 ablation(`ablate_rank.py`)으로 전환.

### E2-3 — 검색 miss 원인 분해와 rank v2/BM25 (완료)

`diagnose_golden_misses.py` 로 놓친 인용 24건을 도달 가능성으로 분류했다.

| 분류 | 건수 | 뜻 |
|---|---|---|
| STRUCTURAL (초록 입력의 한계) | **0** | 입력을 바꿀 필요가 없다 |
| QUERY_GAP (더 나은 질의 존재 가능) | 8 | 질의 생성의 여지 |
| RANKED_OUT (질의가 실제로 매치하는데 상위 미달) | **16** | 깊이·순위의 문제 |

추적 실측 (전부 재현 가능한 probe):

1. **인용이 풀에 실재한다** — "셔터 연동"(전체 19건) 4위로 검색 풀(172건)에
   들어와 있는데 cap 8 선별에서 탈락. 원인: ① 광역 질의(2,769건) 적중과
   같은 무게 ② 확장 변형들의 가짜 합의 ③ 자기 출원이 1위 점유.
2. **getAdvancedSearch 페이징** — docsStart 는 이 경로에서도 무시(1페이지
   반복). pageNo/numOfRows 는 실제로 듣는다 → rows 60 으로 **풀 천장
   4/25 → 10/25**. 인용들이 21~60위 구간에 실재한다.
3. **검색 응답에 초록·등록번호가 실려 온다**(astrtCont·registerNumber) —
   상세조회 없이 어휘 재순위가 가능하고, 3-번호 대조도 히트 수준에서 공짜.

고정 풀 ablation (11출원 · 인용 25건 · cap 8 · rows 60):

| 순위 기계 | 인용 적중 |
|---|---|
| 현행 (적중수·위치) / rrf_v1 | 1/25 |
| rank v2 (계열max+특이도+제목유사도) | 2/25 |
| **BM25 (원문↔제목+초록, 풀 IDF) × (1+RRF)** | **4/25** — 운영 코드로 재현 확인 |

처방을 **`fielded_v2`** 프리셋으로 구현: rows 60 + BM25 재순위
(`rank_candidates_bm25`, `patent_rank_bm25_v1` 연접) + 계열 묶기
(`query_families`) + 평가 시 자기 출원 제외. 라이브 E2E 1건 완주 확인.
잔여: 나머지 인용 출원 ~26건으로 확대 검증(라벨 표본 확대), QUERY_GAP 8건을
겨냥한 질의 생성 개선, rows 60 초과 페이징(pageNo=2+)은 후속 판단.

## 8. 사용자 결정 필요 항목 (기록)

1. SPEC §4 "후보 집합 구성 층" 문단 추가 (원칙 명문화)
2. KIPRIS probe 실행 (getAdvancedSearch·docsCount=30·openNumber, 5~7회 호출)
3. 골든셋 스키마 합의 (§4의 팀 요청 3가지)
4. match_count 의미 변경 승인 (distinct 요소 인덱스)
5. 구현 범위: E1 즉시, E2~E3 골든셋 후, E4 측정 후
