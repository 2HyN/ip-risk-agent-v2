# Agent 3 — Risk Intelligence & RAG

Master Spec 60 형식.

---

## 1. 구현한 범위

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

## 2. 변경한 파일

Agent 3 ownership 영역만 수정했다. Frozen Contract 와 root manifest 는 건드리지 않았다.

```
backend/src/ip_risk_agent/intelligence/
  public.py
  common/    errors · validation · evidence · analyzer · registry
  license/   spdx · policy · dependency_models · manifests · lockfiles ·
             package_metadata · explanation · analyzer
  patent/    kipris · extraction · query_builder · candidate_rank ·
             evidence_builder · grounding · analyzer
  gemini/    client · schemas · retry · prompts/{patent_extract,patent_compare,
             license_explain}_v1.md
  rag/       corpus_manifest · versioning · retrieval · engine · ingestion

rag-corpus/          manifest.yaml · sources/ 3건 · README.md
tests/intelligence/  test_license · test_patent · test_rag
agent-deliverables/  AGENT_DELIVERY.md · agent-3-dependencies.md
```

## 3. 외부 dependency

`httpx` · `defusedxml` · `PyYAML` · `google-genai` · `google-auth` (runtime),
`pytest-asyncio` (dev). 버전과 선택 사유, 검증 결과는 `agent-3-dependencies.md` 참조.

`google-cloud-aiplatform` 은 쓰지 않는다. 100MB 가 넘는데 필요한 기능은
`retrieveContexts` 하나뿐이라 `google-auth` + REST 로 대체했다.

## 4. Environment variables

`GEMINI_MODEL_ID`, `GEMINI_API_KEY`, `KIPRIS_ACCESS_KEY`, `GCP_PROJECT_ID`,
`RAG_REGION`, `RAG_CORPUS_ID`, `RAG_CORPUS_VERSION`.
이 plane 은 환경변수를 직접 읽지 않는다. `IntelligenceConfig.from_env(env)` 로 주입받는다.

## 5. 실행 방법

```python
from ip_risk_agent.intelligence.public import create_facade_from_env

facade = create_facade_from_env(env, retriever=retriever)
results = await facade.analyze(artifact)   # list[AnalysisResult]
```

provider 를 직접 지정하려면 `create_analyzer_registry(...)` 를 쓴다.

## 6. Test

```bash
export PYTHONPATH="shared/contracts/python;backend/src"

python -m pytest tests/intelligence -m "not live"   # 58 passed · 자격증명 불필요
python -m pytest tests/intelligence -m live         # 10 passed · 실제 provider
```

| 파일 | 건수 | 내용 |
|---|---|---|
| `test_license.py` | 24 | 파서·SPDX·정책·provider 실패·환각 인용 |
| `test_patent.py` | 19 | 0건과 실패 구분·중복 제거·순위·근거 검증·우선순위 |
| `test_rag.py` | 15 | 버전·검색·매니페스트·적재·경로 이탈 방지 |
| `test_live_providers.py` | 10 | deps.dev·PyPI·npm·KIPRIS·Gemini 실호출 |

`live` 표시가 붙은 것은 키가 없으면 건너뛴다. CI 는 자격증명 없이 58건을 돌리면 된다.

전체 파이프라인을 실제 API 로 한 번 통과시켰다. 라이선스는
`PyMuPDF → AGPL-3.0-only → POLICY_CONFLICT`, 특허는 KIPRIS 후보 3건에 대해
근거가 붙은 결과를 얻었다.

## 7. Shared Contract 준수

| 항목 | 처리 |
|---|---|
| `security_context.approved` 검증 | Analyzer 진입점에서 확인. 미승인이면 provider 호출 전에 거부 |
| `AnalysisResult` strict | `ResultBuilder` 가 조립. `SUCCEEDED` 가 아니면 `COMPLETE` 를 만들 수 없다 |
| evidence 참조 무결성 | `EvidenceLedger` 가 등록·참조를 함께 관리 |
| Risk ID/lifecycle | 생성하지 않는다 |
| Source Provider 직접 호출 | 하지 않는다 |
| Frozen Contract 수정 | 없음 |

## 8. Contract change request

**없다.** Contract v1 로 구현 범위를 모두 표현할 수 있었다.

다만 VWS 별 라이선스 정책은 `AnalysisArtifact` 에 담을 자리가 없어, Spec 23 에 따라
버전이 붙은 전역 정책(`global-license-policy-2026-08-14.1`) 하나만 사용했다.
조직별 정책이 필요해지면 Contract v2 또는 별도 정책 컨텍스트가 필요하다.

## 9. Integration wiring point

```
1. IntelligenceConfig.from_env(env)
2. RagEngineRetriever(RagEngineConfig.from_env(env))     ← RAG 사용 시
3. create_facade_from_env(env, retriever=...)
4. Worker 에서 facade.analyze(artifact) 호출
5. 반환된 list[AnalysisResult] 를 Control 의 reconcile 로 전달
```

`facade.supports(artifact)` 로 실행 대상 여부를 미리 확인할 수 있다.

**Risk 해소 판단은 Control 이 한다.** 이 plane 은 `status` 와 `coverage` 를 보수적으로
설정할 뿐이다. provider 가 하나라도 실패하면 `COMPLETE` 를 반환하지 않는다.

## 10. 미완성·제약·known issue

**RAG corpus 가 초기 3건이다.**
AGPL-3.0, LGPL-2.1, 고지형 라이선스 의무사항만 있다. 84종 전체 적재는 자료 확보 후
`manifest.yaml` 에 추가하고 `corpus_version` 을 올리면 된다.

**특허 청구항을 쓰지 못한다.**
KIPRIS Plus 가 제공하는 범위가 초록이다. `PatentDocument.claims` 는 구현되어 있어
청구항을 얻을 수 있게 되면 그대로 동작한다. 현재는 초록 근거만 쌓이므로 `HIGH` 가
나오지 않는다. 그래서 초록 근거 둘 이상이면 `MEDIUM` 으로 올리도록 조정했다.
국문 초록이 있으면 그것을 우선 사용한다. 검사 대상 문서가 대개 한국어이기 때문이다.

**후보를 상위 6건만 판정한다.**
비용 때문이다. 판정하지 못한 후보가 있으면 coverage 가 `PARTIAL` 이 되어 Control 이
자동 해소하지 않는다.

**모델 식별자가 정해지지 않았다.**
Master Spec 의 "Gemini 3.6 Flash" 는 실재하는 식별자가 아니다. 환경변수로 받으므로
코드 변경 없이 지정할 수 있으나 배포 전에 값이 필요하다.

**RAG Engine 만 실호출 미검증이다.**
deps.dev·PyPI·npm·KIPRIS·Gemini 는 실제 호출로 확인했다. RAG Engine 은 GCP 프로젝트와
corpus 가 있어야 해서 아직 확인하지 못했다. 요청 형식과 오류 분류는 구현되어 있으며,
`RAG_CORPUS_ID` 가 준비되면 `test_live_providers.py` 에 같은 방식으로 추가하면 된다.

**실호출로 다섯 가지를 고쳤다.**
KIPRIS 응답 필드명, 국문 초록 사용, Gemini 스키마 호환, 라이선스 추정 표시,
우선순위 기준. 상세는 `agent-3-dependencies.md` 의 특이사항 항목에 있다.
