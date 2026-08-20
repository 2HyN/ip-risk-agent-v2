# Agent 3 — Risk Intelligence & RAG 통합 참조

> 문서 상태: Agent 3 최종 유지 문서 (Phase 8 원본 제거 완료)
> 코드 기준: `risk-intelligence-rag` merge 결과 (`68e07a3fdf543bcb4871cb13aee95fcc64b5749d`)
> 적용 branch: `integration-v2`
> 최종 dependency 결정: [`../INTEGRATION_V2_DEPENDENCY_BASELINE.md`](../INTEGRATION_V2_DEPENDENCY_BASELINE.md)
> 전체 조립 계획: [`../INTEGRATION_V2_EXECUTION_PLAN.md`](../INTEGRATION_V2_EXECUTION_PLAN.md)

이 문서는 Agent 3의 delivery와 dependency/실호출 기록을 하나로 정리한 유지 문서다. 과거 model/runtime 판단은 당시 검증 이력으로 보존하되 production 결정은 통합 기준 문서를 따른다.

## 1. 통합한 원본

| 원본 | 이 문서에 흡수한 내용 |
|---|---|
| `AGENT_3_DELIVERY.md` | 구현 범위, public entrypoint, test, contract 준수, wiring, 제약 |
| `agent-deliverables/agent-3-dependencies.md` | package 선택, live provider 결과, 수정 이력, Integration 요청 |

원본은 Phase 7 전체 검증 통과 후 Phase 8에서 제거했으며 Git history로만 보존한다.

## 2. 역할과 경계

Agent 3는 Gate가 승인한 `AnalysisArtifact`를 받아 Patent와 License 관점의 `AnalysisResult`를 반환한다.

제공 기능:

- analyzer protocol, registry와 result/evidence builder
- manifest/lockfile/dependency parsing과 SPDX normalization
- package metadata lookup과 license policy evaluation
- patent feature extraction, KIPRIS search/detail, candidate ranking/grounding
- Gemini structured output, retry와 prompt versioning
- RAG corpus manifest/checksum/version, ingestion preparation와 retrieval
- provider failure classification과 conservative status/coverage

하지 않는 일:

- Source provider나 local filesystem 직접 접근
- raw `SourceSnapshot` 수신
- Security Gate 우회
- Risk ID/state/lifecycle 생성 또는 해소
- human review 결정
- canonical persistence
- final Worker/Cloud Run/GCP resource 조립

### 핵심 불변식

- `security_context.approved`가 아니면 provider 호출 전에 거부한다.
- evidence에 없는 reference를 candidate가 인용하지 못한다.
- non-SUCCEEDED result는 COMPLETE coverage를 주장하지 못한다.
- FAILED result는 candidate를 만들지 않는다.
- provider failure를 후보 0건의 complete success로 바꾸지 않는다.
- Risk 해소 판단은 Control만 수행한다.
- prompt/model/policy/RAG corpus version을 결과에 기록한다.

## 3. 코드 지도

```text
backend/src/ip_risk_agent/intelligence/
  public.py
  common/
    analyzer.py errors.py evidence.py registry.py validation.py
  license/
    spdx.py policy.py dependency_models.py manifests.py lockfiles.py
    package_metadata.py explanation.py analyzer.py
  patent/
    kipris.py extraction.py query_builder.py candidate_rank.py
    evidence_builder.py grounding.py analyzer.py
  gemini/
    client.py schemas.py retry.py
    prompts/license_explain_v1.md
    prompts/patent_extract_v1.md
    prompts/patent_compare_v1.md
  rag/
    corpus_manifest.py versioning.py retrieval.py engine.py ingestion.py

rag-corpus/
  manifest.yaml README.md sources/

tests/intelligence/
```

Gemini prompt Markdown와 RAG corpus source Markdown는 runtime/data provenance 자산이므로 agent 문서 삭제 대상이 아니다.

## 4. Public surface

Integration은 다음 entrypoint를 사용한다.

```python
from ip_risk_agent.intelligence.public import (
    IntelligenceConfig,
    IntelligenceFacade,
    create_analyzer_registry,
    create_facade_from_env,
)
```

### `IntelligenceConfig`

```text
gemini_model_id
gemini_api_key optional
vertex_config optional
kipris_access_key optional
patent_candidate_cap = 6
```

`from_env()`는 `GEMINI_MODEL_ID`, `GEMINI_API_KEY`, `KIPRIS_ACCESS_KEY`를 읽는다. 현재 Vertex env를 `vertex_config`로 변환하지 않으므로 production은 Integration settings에서 명시적으로 구성한다.

### `IntelligenceFacade`

```python
results = await facade.analyze(artifact)  # list[AnalysisResult]
supported = facade.supports(artifact)
```

### Registry factory

```python
create_analyzer_registry(
    *,
    metadata_provider,
    model_client,
    search_provider=None,
    retriever=None,
    explainer=None,
    prompts=None,
    patent_candidate_cap=6,
)
```

License analyzer는 항상 등록된다. `search_provider`가 있을 때 Patent analyzer가 등록된다. 이 optional 동작은 local test에는 유용하지만 production에서 analyzer 누락을 조용히 허용하는 근거가 아니다.

## 5. Analyzer registry와 result 완결성

Registry는 `artifact.requested_analyzers` 순서를 유지해 지원 analyzer를 선택하고 `asyncio.gather`로 실행한다. analyzer 예외를 삼키지 않는다.

Integration 규칙:

- 활성 analyzer set과 `ControlPlaneFacadeConfig.requested_analysis_types`를 startup에서 일치시킨다.
- production 목표는 PATENT + LICENSE다.
- 반환 result type 집합이 `artifact.requested_analyzers`와 정확히 같은지 확인한다.
- 누락/중복/예상 밖 type은 canonical failure로 끝낸다.
- 일부 result만 Control에 수락한 채 job을 RUNNING으로 남기지 않는다.

## 6. License analysis

주요 단계:

1. artifact kind/content 확인
2. manifest/lockfile parser로 dependency 추출
3. deps.dev 우선 package metadata 조회
4. PyPI/npm registry fallback
5. SPDX expression normalize/validate
6. 전역 versioned policy 판정
7. optional RAG/explainer로 obligation 설명
8. evidence와 provider failure를 포함한 result 생성

지원 예:

- exact/범위 dependency version
- free-text license 추정과 `LICENSE_INFERRED_FROM_FREE_TEXT` 표시
- policy conflict, notice required 등 outcome
- metadata not-found와 provider failure 구분

현재 VWS별 license policy는 Contract v1에 별도 context가 없어 versioned global policy를 사용한다. 조직별 정책은 Contract v2 또는 별도 정책 context가 필요하다.

## 7. Patent analysis

주요 단계:

1. Gemini로 technical feature 추출
2. query 생성
3. KIPRIS 검색
4. application number 정규화와 중복 제거
5. 상세/국문 초록 확보
6. deterministic candidate ranking
7. Gemini comparison/grounding
8. evidence와 review priority 생성

KIPRIS 0건과 provider 실패를 구분한다. 후보 cap은 기본 6이며, 평가하지 못한 후보가 있으면 coverage를 PARTIAL로 내려 Control의 자동 resolve를 막는다.

현재 KIPRIS 응답 범위에서는 claims보다 abstract가 중심이다. 초록 근거만 있을 때 HIGH를 만들지 않고, 겹치는 구성 근거가 둘 이상이면 MEDIUM까지 허용한다.

## 8. Gemini client

`GoogleGenAIClient`는 structured output, retry, schema 변환과 prompt library를 제공한다.

실호출에서 확인한 schema 주의점:

- Google API가 Pydantic schema의 `additionalProperties`를 거부할 수 있다.
- 내부 Pydantic `extra="forbid"`는 유지한다.
- provider로 보내는 schema에서만 incompatible keyword와 `$ref`를 정리한다.

Production model ID는 dependency baseline에서 확정한 `gemini-3.6-flash`를 사용한다. 과거 Agent 3 검증의 `gemini-3-flash-preview`와 “식별자 미정” 기록은 역사적 정보이며 production 결정을 덮어쓰지 않는다.

GCP production은 API key보다 attached service identity/Vertex configuration을 우선한다.

## 9. RAG

### Retrieval

```python
RagEngineConfig(
    project_id,
    region,
    corpus_id,
    corpus_version="unversioned",
    top_k=3,
    timeout_seconds=15.0,
)

retriever = RagEngineRetriever(config)
chunks = await retriever.retrieve(query, filters=..., top_k=...)
```

구현은 `google-cloud-aiplatform` 대신 `google-auth` ADC + `httpx` REST `retrieveContexts`를 사용한다. retriever가 만든 client는 lifespan에서 `aclose()`한다.

### Ingestion

현재 제공:

- YAML manifest `safe_load`
- approved source validation
- path가 corpus root 밖으로 나가는 것 거부
- SHA-256 checksum 검증
- normalized `PreparedDocument`
- strict partial-failure policy
- corpus version
- `CorpusUploader` protocol과 `InMemoryCorpusUploader`

현재 없는 것:

- 실제 RAG Engine production uploader

Phase 6의 repository script는 approved path와 checksum을 검증하는 write-free dry-run으로
고정했다. 실제 ADC 기반 upload는 corpus resource가 생성되는 Phase 9에서 runbook에
따라 수행하며 private Source Workspace 자료는 corpus에 넣지 않는다.

초기 corpus는 AGPL-3.0, LGPL-2.1, permissive notice 자료 3건뿐이다. 지원 라이선스 전체 coverage가 아니다.

## 10. Provider failure 의미

대표 category:

- AUTH
- RATE_LIMITED
- TIMEOUT
- UNAVAILABLE
- INVALID_RESPONSE
- NOT_FOUND

Analyzer가 정상적으로 failure result로 표현할 수 있는 provider 실패는 conservative status/coverage로 반환한다. 예상하지 못한 programming/contract 예외는 registry 밖으로 전파해 Worker가 canonical failure로 처리한다.

성공 후보 0건은 provider가 정상 응답하고 필요한 범위를 모두 검사했을 때만 SUCCEEDED+COMPLETE가 될 수 있다.

## 11. Agent 검증 dependency 이력

| Package | Agent 3 검증값 | 용도 |
|---|---:|---|
| Pydantic | 2.13.3 | model/schema 당시 환경 |
| httpx | 0.28.1 | metadata/KIPRIS/RAG HTTP |
| defusedxml | 0.7.1 | KIPRIS XML 안전 파싱 |
| PyYAML | 6.0.3 | corpus manifest |
| google-genai | 2.17.0 | Gemini structured output |
| google-auth | 2.56.3 | ADC/RAG token |
| pytest | 9.1.1 | test |
| pytest-asyncio | 1.4.0 | strict async test |

최종 통합에서는 frozen contract 기준 Pydantic 2.13.4와 Python 3.14.7을 사용한다. Agent 3의 Python 3.13/Pydantic 2.13.3 기록은 통합 재검증 대상이지 최종 pin이 아니다.

선택하지 않은 package:

- `google-cloud-aiplatform`: retrieval 하나를 위해 큰 SDK를 추가하지 않음
- `requests`: application HTTP는 httpx로 통일; 단 ADC refresh transport는 최종 dependency baseline의 `google-auth[requests]`가 제공

## 12. 환경 변수

```text
GEMINI_MODEL_ID
GEMINI_API_KEY                         # local/AI Studio only
VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG  # Integration이 변환
KIPRIS_ACCESS_KEY
GCP_PROJECT_ID
RAG_REGION
RAG_CORPUS_ID
RAG_CORPUS_VERSION
```

통합 settings는 Secret Manager의 KIPRIS reference와 runtime injected key를 구분한다. 일부만 설정된 production group은 silent disable하지 않는다.

## 13. 검증 증거

Agent 3 인계 시점:

```text
tests/intelligence -m "not live": 58 passed
tests/intelligence -m live:       10 passed
```

| Test | 당시 건수 | 내용 |
|---|---:|---|
| license | 24 | parser/SPDX/policy/failure/hallucinated citation |
| patent | 19 | 0건/실패/중복/rank/evidence/priority |
| RAG | 15 | version/retrieval/manifest/ingestion/path escape |
| live provider | 10 | deps.dev/PyPI/npm/KIPRIS/Gemini |

당시 실제 pipeline 예:

- PyMuPDF 1.24.0 → AGPL-3.0-only → POLICY_CONFLICT
- requests → Apache-2.0 → notice-required 계열 판정
- KIPRIS 후보 3건과 grounded evidence

실호출로 수정한 사항:

1. KIPRIS 실제 필드 `applicationNo`/`inventionName`
2. `korAbstractInfo.korAbstract` 우선 사용
3. Gemini schema compatibility transform
4. free-text license 추정 표시 복구
5. abstract-only evidence priority 조정

RAG Engine 실제 project/corpus 호출은 인계 시점에 미검증이었다.

## 14. 통합 후 재실행

```powershell
python -m pytest tests/intelligence -m "not live" -q
python -m pytest tests/intelligence -m live -q
```

Non-live suite는 CI 기본이다. live suite는 명시적 opt-in과 credential이 있을 때만 실행한다.

추가 Integration test:

- Gate 미승인 artifact가 provider 호출 전에 거부
- PATENT+LICENSE 결과 set 완결성
- 한 analyzer failure가 기존 Risk를 resolve하지 않음
- model/prompt/policy/corpus version 보존
- Vertex ADC path
- 실제 RAG retrieval
- missing production config readiness failure

## 15. Known issues와 Integration 의무

### Phase 2~4

- Python 3.14.7/Pydantic 2.13.4에서 전체 재검증
- Vertex settings를 `vertex_config`로 명시 조립
- 활성 analyzer와 Control requested type 일치
- partial/missing result set의 canonical terminal 처리
- shared lifecycle에서 Gemini/RAG HTTP client close

### Phase 9 live 범위

- RAG production ingestion 방법
- exact RAG GA region/corpus resource
- 실제 RAG live test
- service account IAM
- model access와 structured output staging 검증

### Product limitation

- corpus 초기 3건
- KIPRIS abstract 중심
- patent candidate cap 6
- global license policy
- 일부 provider 설정이 없을 때 local-only feature disable 가능하나 production silent disable 금지

## 16. Phase 8 원본 삭제 결과

| 원본 | 대체 section |
|---|---|
| delivery | §2~10, §13~15 |
| dependency request | §8, §11~13 |

build/test/운영 절차의 원본 파일명 참조를 이 문서와 최종 개발/운영 문서로 교체한 뒤 원본을 삭제했다. 보호 대상 명세·기준 문서와 provenance/history 구간의 과거 참조는 실행 경로가 아니므로 보존한다.
