# 골든셋 확장 v2 — 재료 검수 결과와 재현율 검증 준비

작성 2026-08-25. 근거 요청서: advanced_rag `docs/PATENT_NEGATIVE_PAIRS_HANDOFF.md` (v2).
이 브랜치(`gold-expansion-recall`)는 cost-logging `0486d1d` 에서 분기했다.

## 1. 무엇이 들어왔나

재료 3종을 기존 파일에 행 추가 방식으로 확장했다 (기존 행은 바이트 단위로 보존 — 검수 5c 통과).

| 파일 | 기존 | 확장 후 | 순증 |
|---|---|---|---|
| `gold_target_claims_all.csv` (출원별 청구항) | 71출원 | 206출원 | +135 |
| `gold_cited_fulltext_all.csv` (인용 전문) | 125건 | 417건 | +292 |
| `gold_reject_decisions_all.csv` (출원↔인용 매핑) | 72행 | 223행 | +151 |

신규 출원은 `domain` 컬럼이 붙어 있다: 안면인식 28 · 스마트팜 28 · 드론 27 ·
정수처리 25 · 풍력발전 19 (출원 기준, 신규 127출원 + 매핑 없는 청구항-only 8출원).
요청서 §3의 "+30~50출원" 목표를 크게 넘는다.

## 2. 요청서 §4 체크리스트 판정 — 통과

`python scripts/validate_gold_materials.py --baseline-ref cost-logging` 재현 가능.

| 항목 | 결과 |
|---|---|
| CSV 3개 UTF-8 읽기 · 컬럼명 §1 일치 | PASS |
| A.claims / C.kr_citations `ast.literal_eval` 파싱 | PASS (실패 0) |
| C 의 모든 식별자가 B 에 존재 | PASS (누락 0) |
| B 원문에서 `(21)`·`(51)` 검출 ≥90% | PASS — 원문이 있는 행 기준 100% (334/334) |
| 기존 출원과 중복 없음 | PASS (기존 71 유실 0·변경 0, 순증 +135) |

유의 1 — 빈 원문 83건: B 에 행은 있으나 `원문텍스트` 가 빈 행이 83건 있다
(등록특허공보 78 + 공개특허공보 5). 기존 셋에서도 등록특허공보 6건이 같은
상태였다(163→157 차이의 원인). 이 83건이 걸린 93쌍은 재현율 셋에서 제외했고,
요청서 §3 2순위(전문 보충)의 후속 수집 대상으로 남는다. 전체 행 기준
`(21)`·`(51)` 검출률 80.1% 가 90% 를 밑도는 것도 전부 이 빈 원문 때문이다
— 원문이 존재하는 행에서는 100% 다.

유의 2 — `has_29_1` 컬럼은 여전히 미완성(확정 인용 행에서도 False)이라 어떤
필터에도 쓰지 않았다. 기존 163 파일의 수기 필터(174→163)는 재현 불가라서,
v2 쌍은 재료에서 전량 결정적으로 재구성했다.

## 3. 재현율 검증 쌍 (신규 산출물)

`python scripts/build_verification_pairs.py` 로 생성.

| 파일 | 내용 | 규모 |
|---|---|---|
| `samples/patent/verification_pairs_v2_all.csv` | 매핑 전량 (빈 원문 포함, 보충 추적용) | 523행 |
| `samples/patent/verification_pairs_v2.csv` | 원문 있는 행만 = 재현율 평가 입력 | **430행 · 182출원 · 유일 쌍 377** |

기존 157행(126 유일 쌍) 대비 유일 쌍 기준 **3.0배**. 스키마는 157/163 과 동일
(`applicationNumber, sendNumber, target_claims, cited_식별자, cited_fulltext`)
+ `domain` 컬럼 추가. 유일 쌍의 도메인 분포: 기존분 126 · 안면인식 66 ·
스마트팜 59 · 드론 57 · 정수처리 42 · 풍력발전 27.

## 4. 재현율 검증 실행 방법

이 저장소 프로토콜 기준(모든 쌍이 심사관 확정 인용 = 정답은 "겹침 존재",
hit = `matched_elements` 비어 있지 않음):

```bash
# cost-logging 하네스 (KIPRIS 불필요, GEMINI_API_KEY 만)
GEMINI_API_KEY=... python scripts/eval_patent_compare.py \
  --in samples/patent/verification_pairs_v2.csv \
  --out eval-results/patent_compare_recall_v2.csv
```

비교 기준선: 같은 하네스로 기존 157쌍 재현율 92.4% (커밋 `1693a1f`),
advanced_rag 프로토콜(접지 검증 포함)로는 85%(v2)/79%(v3).
확장 셋에서 도메인별 재현율은 `domain` 컬럼으로 층화 집계하면 된다.
`eval_patent_compare.py` 에는 확장 셋의 대형 필드(최대 25만자)를 위해
`csv.field_size_limit` 상향 패치만 넣었고 판정 로직은 그대로다.

advanced_rag 쪽 `scripts/evaluate_compare_pairs.py`(접지 검증·전략 A/B 포함)
로 돌릴 때도 v2 파일을 `--pairs` 로 그대로 줄 수 있다 — 원문 있는 행은
`(21)` 줄이 100% 검출되므로 인용 출원번호 추출이 걸리지 않는다.
(그쪽은 KIPRIS_ACCESS_KEY + GEMINI_API_KEY|GCP_PROJECT_ID 필요.)
