# 비용 최적화 진행 현황 (FinOps)

작성: 이은우 (비용 담당) · 최종 갱신 2026-08-24 · 브랜치: `cost-logging`

이 문서는 `cost-logging` 브랜치에서 지금까지 한 일과 남은 일을 정리한다. 세부 수치가
담긴 리포트(v1~v4)는 별도로 팀 프로젝트 문서함에 있고, 여기는 팀원이 이 브랜치를
받았을 때 "뭘 왜 했는지"를 빠르게 파악하기 위한 요약이다.

## 배경

Gemini 응답의 토큰 사용량(`usage_metadata`)이 지금까지 코드에서 버려지고 있어
"분석 1건에 얼마가 드는가"에 답할 숫자가 없었다. 이 브랜치는 ① 비용을 관측 가능하게
만들고(로깅) ② 그 숫자를 근거로 모델 선택을 실측으로 정당화하는 것을 목표로 한다.
**판정 로직(라이선스 위험 등급 산정)은 이 작업 범위에서 손대지 않는다** — 판정은
규칙 엔진이 하고 Gemini는 추출·대조·설명만 맡는 구조라, 모델을 바꿔도 판정 정확성
리스크가 없다는 게 이 최적화가 성립하는 전제다.

## 지금까지 한 일

### 1. 비용 관측 로그 추가
`gemini_usage`(모델·작업별 토큰) · `registry_call`(deps.dev/PyPI 호출) ·
`rag_clause_search`(캐시 적중 여부) 세 이벤트를 기존 `kipris_call` 패턴과 동일한
방식으로 추가했다. 판정 로직은 건드리지 않았고, 로깅 실패가 분석 자체를 막지
않도록 try/except로 감쌌다.

### 2. 로컬 측정 드라이버 구축
GCP 배포 없이 로컬에서 실제 API(Gemini·KIPRIS·deps.dev·PyPI)를 호출해 비용을
재는 도구를 만들었다 (`scripts/cost_measure.py`, `scripts/cost_report.py`).

### 3. 모델 티어링 비교 (flash-lite / flash / pro)
같은 입력을 세 모델로 돌려 비교한 결과:
- **pro**: 비용 프리미엄(+83%~175%, 표본 크기에 따라 추정치가 달라짐)에 상응하는
  품질 이득이 없어 **채택 근거 없음**으로 기각.
- **PatentComparison**: lite가 caveat(한계 명시)를 덜 붙이는 사례가 있어 —
  "근거 기반, 과판정 방지"라는 이 작업의 핵심 가치와 직결되는 신호라 **flash 유지**
  권고. (`scripts/compare_quality.py`로 원문 대조)
- **TechnicalExtraction**: 정답 고정 회귀 평가(`scripts/eval_extraction.py`)에서
  flash·lite 모두 5편 기준 10/10(100%) 완전 일치 → **lite 전환 확정**, 비용 48% 절감.
- **risk_explain** (특허·라이선스 공통 설명기): 자유 서술이라 정답 대조 대신 규칙
  위반 검사(근거 없는 evidence ID 인용, "침해입니다" 등 금지 표현)로 평가
  (`scripts/eval_risk_explain.py`). 5케이스 기준 flash·lite 모두 10/10(100%) —
  겹침이 강해 보이도록 일부러 설계한 "유혹 케이스"에서도 규율이 깨지지 않았다.
  **lite 후보로 확인**.

### 4. 표본 확대 (5→30) — 최신 작업
표본이 작다는 게 지금까지 결과의 공통 한계였다(v1의 pro 프리미엄 추정이 표본을
5편으로 늘리자 175%→83%로 바뀐 사례가 이걸 스스로 보여준다). 그래서:
- `samples/patent`를 5편 → **30편**(기술 문서 24 + 비기술 대조군 6)으로 확대.
- `eval_extraction.py`의 정답표를 30개 전체로 갱신.
- `eval_risk_explain.py`의 케이스를 5건 → **30건**(라이선스 15 + 특허 15, 라이선스
  타입 12종 추가, "유혹 케이스" 3건 추가)으로 확대.
- 30편으로 늘리면서 `cost_measure.py`가 KIPRIS를 짧은 시간에 몰아 호출해
  `ProviderFailureError`가 다발 — 호출 사이 0.5초 스로틀(`KIPRIS_THROTTLE_SECONDS`)을
  추가해 대응했다.

**중간 결과**: 30편 기준 `eval_extraction.py`는 이미 완주 — flash·lite 모두
**30/30(100%)**, 5편 결과와 동일하게 완전 일치. `eval_risk_explain.py`와
`cost_measure.py`(토큰·비용 측정)는 KIPRIS 이슈로 중단됐다가 스로틀 패치 후
재실행 중이다.

## 왜 이게 "진짜" 최적화인가

- 수업에서 배운 "모델 바꿔보기"를 그대로 적용한 게 아니라, **회귀 평가로 정확도
  손실이 없는지 실측**하고 나서 결정했다. TechnicalExtraction·risk_explain은
  "괜찮아 보인다"가 아니라 "N/N 일치"로 확정했다.
- 작업마다 다르게 결정했다 — PatentComparison은 비용 절감 여지가 커도 근거
  정밀도 신호 때문에 flash를 유지했다. 절감액이 크다고 무조건 내리지 않았다.
- 판정 로직(위험도 산정)은 전혀 건드리지 않았다 — 바뀌는 건 "AI가 추출·설명하는
  모델"뿐이고, 최종 판단은 여전히 규칙 엔진이 한다.

## 남은 일

1. 30건 기준 재측정 마무리 — `cost_measure.py`(토큰·비용), `eval_risk_explain.py`
   (규칙 준수) 재실행 후 리포트 v5로 정리.
2. 인프라 비용(GCP billing, SKU별) 정리 — Gemini 외 비용(Secret Manager, Cloud Run
   등) 확인 중.
3. **코드 반영 (미착수)**: `GEMINI_MODEL_ID` 단일 설정을 작업별로 분리 —
   TechnicalExtraction·risk_explain → flash-lite, PatentComparison → flash.
   Frozen Contract 대상은 아니라 팀 합의만으로 가능할 것으로 보이나 팀장님 확인 필요.
4. main 병합·배포 후 운영 로그로 실사용 기준 재측정, RAG 조항 검색 비용 포함,
   반복 프롬프트 대상 컨텍스트 캐싱 실험.

## 관련 파일

- `backend/src/ip_risk_agent/intelligence/gemini/client.py` — `gemini_usage` 로깅
- `backend/src/ip_risk_agent/intelligence/license/{package_metadata,analyzer}.py` —
  `registry_call`·`rag_clause_search` 로깅
- `scripts/cost_measure.py` — 로컬 측정 드라이버
- `scripts/cost_report.py` — 집계(토큰 수·비용 표)
- `scripts/compare_quality.py` — PatentComparison 원문 정성 비교
- `scripts/eval_extraction.py` — TechnicalExtraction 회귀 평가(정답 대조)
- `scripts/eval_risk_explain.py` — risk_explain 회귀 평가(규칙 위반 검사)
- `samples/patent/*.md` — 측정용 표본 30편
