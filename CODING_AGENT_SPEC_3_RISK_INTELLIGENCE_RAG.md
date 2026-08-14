# IP Risk Agent — Agent 3 Development Specification
## Risk Intelligence & RAG

> **이 문서는 `CODING_AGENT_MASTER_SPEC.md`와 함께 Agent 3에게 전달한다.**  
> Master Spec이 상위 규약이며, 충돌 시 Master Spec을 우선한다.  
> Agent 3의 입력은 승인된 `AnalysisArtifact`, 출력은 `AnalysisResult`뿐이다.

---

# 0. Agent 3 임무

> **Security Gate를 통과한 최소 Artifact를 Patent/License 관점에서 분석하고, 외부 근거와 재현 가능한 version metadata를 포함한 엄격한 `AnalysisResult`를 반환한다.**

Agent 3는 AI와 external knowledge를 소유하지만 Product Risk state를 소유하지 않는다.

---

# 1. 절대 경계

## MUST

- `security_context.approved == true`를 검증한다.
- Patent/License analyzer를 독립 구현한다.
- Gemini 호출을 typed/validated output으로 다룬다.
- KIPRIS/provider 실패와 zero-result를 구분한다.
- License policy 결과를 deterministic하게 계산한다.
- RAG Engine을 reference knowledge plane으로 사용한다.
- Evidence ID를 코드로 검증한다.
- `AnalysisResult` strict contract를 반환한다.

## MUST NOT

- Drive/GitHub/Local source를 직접 fetch하지 않는다.
- OAuth/provider credential에 접근하지 않는다.
- Firestore `risks`/membership/mount를 직접 읽거나 쓰지 않는다.
- Risk ID/lifecycle/review disposition을 생성하지 않는다.
- VWS `.ipriskignore`를 재해석하지 않는다.
- Frozen Contract를 수정하지 않는다.

---

# 2. 소유 파일

```text
backend/src/ip_risk_agent/intelligence/
├─ common/
│  ├─ analyzer.py
│  ├─ registry.py
│  ├─ evidence.py
│  ├─ validation.py
│  └─ errors.py
│
├─ patent/
│  ├─ analyzer.py
│  ├─ extraction.py
│  ├─ query_builder.py
│  ├─ kipris.py
│  ├─ candidate_rank.py
│  ├─ evidence_builder.py
│  └─ grounding.py
│
├─ license/
│  ├─ analyzer.py
│  ├─ manifests.py
│  ├─ lockfiles.py
│  ├─ dependency_models.py
│  ├─ package_metadata.py
│  ├─ spdx.py
│  ├─ policy.py
│  └─ explanation.py
│
├─ gemini/
│  ├─ client.py
│  ├─ schemas.py
│  ├─ retry.py
│  └─ prompts/
│
└─ rag/
   ├─ engine.py
   ├─ ingestion.py
   ├─ retrieval.py
   ├─ corpus_manifest.py
   └─ versioning.py

rag-corpus/**
tests/intelligence/**
```

Product frontend 직접 소유 없음.

---

# 3. Public Integration Surface

Integration Layer가 사용할 public facade/factory를 제공한다.

권장:

```text
intelligence/public.py
```

예:

```python
def create_analyzer_registry(config, providers) -> AnalyzerRegistry: ...

class IntelligenceFacade:
    async def analyze(self, artifact: AnalysisArtifact) -> list[AnalysisResult]: ...
```

하나의 AnalysisArtifact에 PATENT/LICENSE 둘 다 요청될 수 있으므로 결과 list를 반환 가능.

개별 Analyzer는 `AnalysisResult` 하나를 반환.

---

# 4. Analyzer Interface

Agent 3 내부 interface 예:

```python
class Analyzer(Protocol):
    analysis_type: AnalysisType

    def supports(self, artifact: AnalysisArtifact) -> bool: ...

    async def analyze(self, artifact: AnalysisArtifact) -> AnalysisResult: ...
```

`AnalysisArtifact.requested_analyzers`에 자신이 없으면 실행하지 않는다.

`supports=False`이면 SKIPPED/NONE을 안전하게 반환하거나 registry에서 호출하지 않는다.

---

# 5. Defense-in-Depth Input Validation

모든 Analyzer 진입 전에 공통 validator:

```text
contract_version == "1"
security_context.approved == true
analysis_job_id present
artifact_id/revision present
text_segments valid
requested_analyzers includes target
```

`approved=false`이면 provider/AI 호출 전에 즉시 거부.

이 경우 programmer/security error로 취급하고 safe failure를 반환하거나 typed exception을 Integration에 전달한다. Master Contract semantics를 지킨다.

---

# 6. AnalysisResult Construction Rule

모든 결과는 공통 builder/validator를 거친다.

필수:

- started_at/completed_at
- versions.analyzer_version
- model을 썼으면 model_id/prompt_version
- RAG를 썼으면 rag_corpus_version
- policy를 썼으면 policy_version
- provider failure safe metadata
- candidate evidence IDs exist

후보 0개라도 성공 가능.

---

# 7. 공통 Failure Semantics

### FAILED

필수 단계가 실패.

예:

- KIPRIS timeout
- Gemini unavailable/malformed after retry
- required package metadata provider unavailable
- required RAG lookup impossible when explanation/evidence is mandatory

### INCONCLUSIVE

파이프라인은 정상이나 근거 부족.

예:

- technical content too weak
- unresolved package version
- unknown/non-standard license metadata

### SKIPPED

적용 대상 아님.

### SUCCEEDED

분석 정상 완료. 후보 0개 가능.

`FAILED`를 빈 candidates SUCCEEDED로 바꾸지 않는다.

---

# 8. Coverage Rule

### COMPLETE

해당 Analyzer가 현재 revision에서 평가하기로 한 범위를 전부 처리.

### PARTIAL

일부 후보/근거/provider 결과만 처리.

### NONE

유효 분석 범위 없음.

Agent 3는 resolution을 결정하지 않지만 Control이 `SUCCEEDED+COMPLETE`에서만 resolution 가능하다는 점을 고려해 coverage를 보수적으로 정확히 설정한다.

---

# 9. Gemini Provider

Core model은 Master Spec 기준 Gemini 3.6 Flash.

Provider abstraction:

```python
class GeminiProvider(Protocol):
    async def generate_structured(...): ...
```

실제 Google SDK를 analyzer logic에서 직접 난사하지 않고 client layer에 격리한다.

MUST:

- structured output/schema validation
- timeout/retry budget
- malformed output handling
- model ID 기록
- prompt version 기록
- raw prompt/source/output full logging 금지

---

# 10. Prompt Versioning

Prompt는 코드 inline string으로 흩뿌리지 않는다.

권장:

```text
intelligence/gemini/prompts/
├─ patent_extract_v1.*
├─ patent_compare_v1.*
└─ license_explain_v1.*
```

Prompt loader는 stable version ID를 반환.

Result에 prompt_version 기록.

Prompt 변경은 version bump.

---

# 11. Patent Analyzer 목표

법적 침해 판정을 생성하지 않는다.

출력은:

- candidate patent
- grounded matched technical elements
- minimal evidence
- suggested review priority

이다.

사용자-facing 법률 결론 표현을 model schema에서 요구하지 않는다.

---

# 12. Patent Pipeline

고정 flow:

```text
AnalysisArtifact
 ↓
Technical relevance / element extraction
 ↓
Search query generation
 ↓
KIPRIS search
 ↓
Normalize + deduplicate
 ↓
Candidate ranking / cap
 ↓
Patent detail fetch
 ↓
Claims/abstract evidence chunks
 ↓
Grounded Gemini comparison
 ↓
Evidence reference validation
 ↓
Suggested priority
 ↓
PatentCandidate + Evidence
 ↓
AnalysisResult
```

---

# 13. Technical Extraction

Gemini structured schema 예:

```text
TechnicalExtraction
- is_technical: bool
- technical_elements[]
- search_queries[]
- source_segment_ids[]
```

검색 query는 과도하게 많이 생성하지 않는다.

MVP 권장 2~5개 정도 config.

Technical content가 매우 부족하면 INCONCLUSIVE 또는 SKIPPED semantics를 명확히 선택.

추천:

- 실제 patent analyzer target인데 기술 context 부족 -> INCONCLUSIVE/NONE
- 명백히 비기술 문서 -> SKIPPED/NONE

---

# 14. KIPRIS Provider

Provider abstraction:

```python
class PatentSearchProvider(Protocol):
    async def search(query: str) -> list[PatentSearchHit]: ...
    async def fetch_detail(application_number: str) -> PatentDocument: ...
```

KIPRIS-specific XML/HTTP parsing은 `patent/kipris.py`에 격리.

MUST:

- timeout
- throttling/rate control
- safe retry
- malformed response handling
- provider failure typed
- no secret logs

---

# 15. Patent Search 0건 vs Failure

반드시 분리.

```text
KIPRIS request succeeded + []
→ valid zero-result

KIPRIS timeout/error
→ ProviderFailure + FAILED/PARTIAL 판단
```

모든 query가 성공하고 candidate 0개면:

```text
SUCCEEDED + COMPLETE + candidates=[]
```

가능.

일부 query failure, 일부 success면:

```text
SUCCEEDED or FAILED는 정책에 따라
coverage = PARTIAL
provider_failures populated
```

기존 Risk resolution을 막기 위해 coverage를 PARTIAL로 설정하는 것이 안전하다.

---

# 16. Patent Normalization/Dedup

Application number를 canonical normalization.

같은 patent가 여러 query에서 나오면 하나로 합친다.

ranking features 예:

- multiple query hit count
- provider relevance score if safe
- title/abstract semantic relevance

결정론적 tie-breaker를 둔다.

Candidate cap config.

---

# 17. Patent Detail/Evidence

가능하면 claims 우선, abstract 보조.

내부:

```text
PatentDocument
- normalized_application_number
- title
- claims[]
- abstract
- status metadata safe
- source reference
```

Evidence chunk:

```text
evidence_id stable within analysis
PATENT_CLAIM / PATENT_ABSTRACT
excerpt
reference
metadata_safe
```

전체 특허 문서를 AnalysisResult에 넣지 않는다.

---

# 18. Grounded Comparison

Gemini에는:

- Source minimal segments
- shortlisted patent evidence chunks

만 전달.

Structured output 예:

```text
PatentComparison
- application_number
- matched_elements[]
  - source_segment_id
  - patent_evidence_id
  - explanation
- suggested_priority
- uncertainty_flags[]
```

Model이 반환한 모든 evidence ID가 실제 집합에 존재하는지 code validation.

존재하지 않으면 malformed output로 retry 또는 failure.

---

# 19. Patent Quote Validation

가능하면 model이 직접 quote를 생성하게 하기보다 evidence ID/reference 중심으로 한다.

Quote/excerpt가 포함되면 normalized substring validation 가능.

Hallucinated evidence는 결과에서 제거하는 것이 아니라 전체 comparison을 invalid 처리하는 것이 안전.

---

# 20. Patent Priority

최종 legal risk probability가 아니라 Review Priority.

권장 enum/string:

```text
LOW
MEDIUM
HIGH
```

Calculation은 가능한 한 deterministic post-processing을 포함.

예:

- claim evidence 존재
- matched technical element 수
- comparison strength categories
- uncertainty

Model이 단독으로 최종 priority를 마음대로 만들지 않도록 schema + code rules 혼합을 권장.

---

# 21. Patent Candidate Contract Mapping

최종 Candidate:

```text
normalized_application_number
title
suggested_review_priority
matched_elements
evidence_ids
provider_metadata_safe
```

Risk ID 생성 금지.

---

# 22. License Analyzer 목표

License analyzer는 AI가 license compatibility를 자유 서술하는 시스템이 아니다.

원칙:

```text
Dependency facts + SPDX normalization + deterministic policy
                     ↓
                policy outcome
                     ↓
            RAG/Gemini explanation
```

---

# 23. MVP License Policy Scope — 중요 결정

Frozen `AnalysisArtifact`에는 VWS-specific license policy payload가 없다.

따라서 **MVP는 versioned global deterministic license policy**를 사용한다.

VWS별 custom license policy/profile은 현재 구현하지 않는다.

이 기능이 필요해지면 Contract v2 또는 별도 approved policy-context contract가 필요하므로 후속으로 둔다.

Agent 3가 임의로 Control DB를 조회해 VWS policy를 가져오면 안 된다.

---

# 24. Dependency File Support

MVP 우선:

### Python

- requirements.txt
- pyproject.toml (지원 가능한 dependency sections)
- lockfile 지원은 실제 parser 구현 가능 범위 우선
  - uv.lock / poetry.lock 중 최소 하나 이상 권장

### Node

- package.json
- package-lock.json

추가 lockfile은 시간 허용 시.

ArtifactKind와 logical path로 parser dispatch.

---

# 25. Resolved Version Priority

원칙:

```text
lockfile exact resolved version
  > exact manifest pin
  > unresolved range
```

unresolved range를 최신 package version으로 실제 사용 version처럼 단정하지 않는다.

`uncertainty_flags`에 기록.

---

# 26. Package Metadata Provider

여러 ecosystem을 통합할 수 있는 provider abstraction을 사용.

예:

```python
class PackageMetadataProvider(Protocol):
    async def get_version_metadata(ecosystem, package, version): ...
```

가능한 primary source는 deps.dev 계열 API를 고려하되, 실제 구현은 Master Spec의 현재 기술 방향과 충돌하지 않는 범위에서 선택.

Registry fallback을 구현 가능.

Provider 결과는 법적 authoritative conclusion이 아니라 evidence fact.

---

# 27. SPDX Normalization

`spdx.py`에서 deterministic.

MUST:

- canonical SPDX identifier mapping
- common alias normalization
- expression parse
- `AND`, `OR`, `WITH`를 단순 prefix/worst-case string hack으로 처리하지 않음
- unknown/non-standard 표시

가능하면 SPDX data snapshot/version을 명시적으로 관리.

---

# 28. Global License Policy v1

정확한 조직 정책은 아직 없으므로 정책 engine은 **법적 결론이 아니라 review outcome taxonomy**를 제공한다.

권장 outcome:

```text
NO_ACTION
NOTICE_REQUIRED
REVIEW_REQUIRED
POLICY_CONFLICT
UNKNOWN
```

Policy v1은 SPDX family/known obligations에 따른 보수적 분류.

`UNKNOWN`/non-standard는 자동 허용 금지.

정책 테이블은 코드/버전 파일로 명시하고 test한다.

---

# 29. License RAG 설명

RAG는 deterministic policy를 override하지 않는다.

RAG 목적:

- SPDX/license reference evidence
- obligation explanation
- why review required

Flow:

```text
normalized license + policy outcome
 ↓
RAG retrieval
 ↓
reference chunks
 ↓
Gemini explanation
```

RAG 장애가 policy fact 자체를 무효화하는지 여부:

- policy 결과는 계산 가능
- 그러나 제품에서 grounded explanation을 필수로 정의했다면 coverage PARTIAL 또는 provider failure 기록 가능

MVP 권장:

> deterministic result는 유지하되 RAG explanation 실패 시 `SUCCEEDED + PARTIAL`로 반환하여 자동 resolution을 막고, provider_failures에 RAG failure를 남긴다.

이는 안전 측면에서 보수적이다.

---

# 30. License Candidate

```text
ecosystem
normalized_package_name
resolved_version optional
normalized_license_expression
policy_outcome
evidence_ids
uncertainty_flags
```

package 하나에서 복수 license expression semantics가 있으면 normalization 결과를 명확히 유지.

Risk key는 Control이 만든다.

---

# 31. RAG Engine — 목적

RAG Engine은 **reference knowledge plane**이다.

Persistent corpus:

- SPDX/license texts
- OSS obligation guides
- curated IP guidance
- approved internal policy references
- future copyright/IP references

Persistent corpus에 기본적으로 넣지 않음:

- private GitHub repo source
- Drive private project docs
- Local source corpus
- unpublished invention/project raw data

---

# 32. Hybrid Region Assumption

Application plane은 Seoul.

RAG Engine은 외부 GA region.

Agent 3는 region을 config로 받는다.

예:

```text
RAG_REGION
RAG_CORPUS_ID
```

Root deployment binding은 Integration Agent.

Agent 3는 특정 preview Seoul RAG를 hardcode하지 않는다.

---

# 33. RAG Backend

Master Spec 기준 `RagManagedDb` Basic 우선.


RAG Engine SDK/API abstraction을 둔다.

```python
class ReferenceRetriever(Protocol):
    async def retrieve(query, filters, top_k) -> list[ReferenceChunk]: ...
```

Analyzer는 RAG Engine SDK에 직접 종속되지 않고 이 abstraction 사용.

---

# 34. RAG Corpus Manifest

`rag-corpus/`에는 원본 전체를 무작정 저장하지 말고 ingestion manifest/source metadata 중심으로 관리.

예:

```text
rag-corpus/
├─ manifest.yaml
├─ sources/
│  ├─ spdx.yaml
│  └─ approved-guidance.yaml
└─ README.md
```

Manifest item:

```text
source_id
version
source_type
canonical_reference
checksum
jurisdiction/tags
approved_for_rag
```

실제 public/reference document ingestion path는 script/config로 제공.

---

# 35. Corpus Versioning

RAG corpus version은 deterministic release/version 문자열.

예:

```text
2026-08-14.1
```

AnalysisResult에 기록.

Corpus 변경 시 version bump.

---

# 36. RAG Ingestion

Agent 3가 구현할 ingestion command/service:

```text
load manifest
 -> validate approved sources
 -> fetch/read curated material
 -> normalize
 -> upload/import RAG Engine
 -> record corpus version
```

Private SourceWorkspace를 ingestion 대상에 넣는 기능은 만들지 않는다.

Credential/raw secret logs 금지.

---

# 37. RAG Retrieval Evidence

Retrieval result를 `EvidenceType.RAG_REFERENCE` 또는 LICENSE_REFERENCE로 매핑.

Evidence:

- minimal excerpt
- canonical reference
- source/version metadata

모델 설명이 retrieval reference와 연결되게 한다.

---

# 38. Evidence ID Strategy

한 AnalysisResult 내 unique.

예:

```text
src:segment-1
patent:KRxxxx:claim:1
rag:spdx:MIT:chunk-3
pkg:pypi:requests:2.32.0
```

실제 형식은 내부 결정 가능하나 deterministic/readable하면 debugging에 유리.

Model input/output reference validation에 사용.

---

# 39. Evidence Minimization

AnalysisResult evidence에 전체 source/full patent/full RAG doc를 넣지 않는다.

최대 excerpt 길이를 config.

Reference로 원문 provider/canonical source를 남긴다.

Source excerpt는 AnalysisArtifact의 최소 segment에서만 파생.

---

# 40. Analysis Versions

모든 결과:

```text
analyzer_version
model_id
prompt_version
policy_version
rag_corpus_version
```

사용하지 않는 값은 null 허용.

### Patent

- analyzer_version required
- model_id/prompt_version required if Gemini used
- rag_corpus_version 보통 null 가능

### License

- analyzer_version
- policy_version required
- RAG 사용 시 rag_corpus_version
- Gemini explanation 시 model/prompt version

---

# 41. Retry Policy

Provider마다 제한된 retry.

MUST NOT:

- 무한 retry
- retry 후 실패를 empty success로 변환

권장 category:

```text
retryable network/429/5xx
nonretryable auth/validation/unsupported
```

실제 Cloud Tasks retry와 중복되지 않게 provider 내부 retry는 짧고 제한적으로 둔다.

---

# 42. ProviderFailure Mapping

```text
provider
category
retryable
safe_message
```

예:

```text
KIPRIS / TIMEOUT / true
GEMINI / MALFORMED_OUTPUT / true or false
RAG_ENGINE / UNAVAILABLE / true
PACKAGE_METADATA / NOT_FOUND / false
```

raw response/token stack을 contract에 넣지 않는다.

---

# 43. Logging

Structured log:

```text
analysis_job_id
artifact_id
analysis_type
provider
operation
status
latency_ms
candidate_count
evidence_count
model_id
prompt_version
```

금지:

- full AnalysisArtifact text
- full prompt
- raw model output
- tokens/keys

---

# 44. Patent Tests

MUST:

1. unapproved artifact rejected
2. non-technical document skipped/inconclusive semantics
3. extraction schema validation
4. zero KIPRIS result => SUCCEEDED/COMPLETE/[]
5. KIPRIS failure != zero result
6. partial query failure => PARTIAL coverage
7. application number normalize/dedup
8. repeated hit ranking deterministic
9. claims evidence preferred
10. malformed Gemini output retry/fail
11. hallucinated evidence ID invalid
12. priority post-processing deterministic
13. legal conclusion not required/emitted in candidate schema
14. strict AnalysisResult validation

---

# 45. License Tests

MUST:

1. requirements parser
2. package.json parser
3. package-lock exact version preference
4. at least one Python lockfile parser if implemented
5. exact pin > range semantics
6. unresolved range uncertainty
7. SPDX alias normalization
8. AND/OR/WITH expression cases
9. unknown license => UNKNOWN/review semantics
10. deterministic policy not overridden by Gemini
11. package metadata provider failure semantics
12. RAG explanation success evidence IDs
13. RAG failure => conservative PARTIAL semantics
14. strict LicenseCandidate contract

---

# 46. RAG Tests

실제 cloud service를 unit test에 요구하지 않는다.

FakeReferenceRetriever로:

- top-k retrieval
- reference mapping
- corpus version
- unavailable exception

테스트.

Production RAG Engine client implementation/skeleton 필수.

Ingestion manifest validation test.

---

# 47. Golden Fixtures

`tests/intelligence/fixtures/`에 synthetic/non-sensitive fixture 사용.

추천:

```text
patent/source_algorithm.txt
patent/kipris_candidates.json
license/requirements.txt
license/package.json
license/package-lock.json
license/spdx_cases.json
```

실제 private project source를 fixture에 넣지 않는다.

---

# 48. Analyzer Registry

Registry는 requested analyzers에 대해 Analyzer를 resolve한다.

```text
PATENT -> PatentAnalyzer
LICENSE -> LicenseAnalyzer
```

한 artifact에 두 analyzer 실행 가능.

병렬 실행을 해도 각 결과는 독립적이어야 한다.

하나 실패했다고 다른 analyzer 성공 결과를 버리지 않는다.

---

# 49. Multi-result Aggregation

`IntelligenceFacade.analyze(artifact)`가 여러 결과를 반환한다면:

- 각 AnalysisType 별 started/completed time 독립
- provider failures 독립
- 한 analyzer exception을 다른 result까지 crash시키지 않음

Integration/Control이 aggregate AnalysisJob state를 계산하도록 한다.

---

# 50. Product UI Needs

Agent 3는 UI를 만들지 않지만 AnalysisResult/Evidence가 다음을 표현할 수 있어야 한다.

### Patent

- patent title/application number
- review priority
- matched elements
- evidence references
- uncertainty/failure/coverage

### License

- package/version
- normalized license
- policy outcome
- uncertainty
- reference evidence/explanation

UI-specific HTML/markdown을 result에 넣지 않는다.

Structured data + safe explanation text만 제공.

---

# 51. Security

MUST:

- only approved AnalysisArtifact
- no provider source fetch
- no persistent private source RAG ingestion
- evidence minimization
- no full prompt logging
- no user secret propagation

AI provider에 전달하는 것은 이미 Control SecurityGate를 거친 data라는 전제를 유지하되, obvious secret placeholder/unsafe state가 있으면 추가 defense 가능.

---

# 52. Environment/Dependency Requests

예상:

```text
GCP_PROJECT_ID
VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG
GEMINI_MODEL_ID

KIPRIS_API_KEY_SECRET_ID

RAG_REGION
RAG_CORPUS_ID
RAG_MANAGED_DB_CONFIG optional

PACKAGE_METADATA_BASE_URL optional
```

실제 root config는 수정하지 않고 delivery에 기록.

---

# 53. 구현 순서

## Phase A — Common Intelligence

- Analyzer interface/registry
- AnalysisResult builder
- evidence validation
- errors/provider failure
- Gemini client/schema framework

## Phase B — License deterministic core

- manifests/lockfiles
- package metadata abstraction
- SPDX
- policy v1

## Phase C — RAG

- retriever abstraction
- production RAG Engine client
- corpus manifest/version
- ingestion
- license explanation

## Phase D — Patent

- extraction
- KIPRIS
- candidate ranking
- evidence
- grounded comparison

## Phase E — Hardening

- retry/failure semantics
- golden tests
- security checks
- delivery docs

Patent/License 순서는 팀 우선순위에 따라 바꿀 수 있다.

---

# 54. Integration Wiring Points

`AGENT_DELIVERY.md`에 최소:

1. `create_analyzer_registry()` import path
2. `IntelligenceFacade` import/constructor
3. Gemini provider constructor/config
4. KIPRIS provider constructor/config
5. package metadata provider constructor
6. RAG retriever/ingestion constructor
7. required secrets/env
8. RAG corpus bootstrap command
9. analyzer version/prompt version locations
10. known unsupported file formats

---

# 55. Acceptance Criteria

### Architecture

- AnalysisArtifact 외 Source input path 없음.
- Source API import 없음.
- canonical Risk DB access 없음.

### Patent

- KIPRIS query→candidate→detail→grounded evidence flow 구현.
- zero result와 failure 분리.
- evidence ID 검증.
- review priority 결과.

### License

- deterministic manifest/lockfile parsing.
- SPDX normalization.
- global policy v1.
- RAG/Gemini explanation이 policy를 override하지 않음.

### RAG

- RAG Engine production integration path.
- managed reference corpus only.
- corpus versioning/ingestion.
- private workspace corpus ingestion 기능 없음.

### Reliability

- status/coverage semantics 정확.
- provider failure safe mapping.
- strict AnalysisResult contract.

### Tests

- shared contract tests 통과.
- intelligence tests 통과.
- fake providers로 offline unit tests 가능.

### Delivery

- `AGENT_DELIVERY.md`
- dependency request
- prompt/corpus/version inventory
- known issues

---

# 56. Agent 3가 결정하지 말아야 할 사항

- VWS role/security policy
- Source tracking scope
- `.ipriskignore` parsing semantics 변경
- raw source fetching
- Risk stable key hash implementation
- Risk lifecycle transitions
- Firestore schema
- Cloud Tasks wiring
- Web UI
- Contract 변경

---

# 57. 최종 성공 정의

Agent 3 구현만 단독으로 놓았을 때 synthetic approved AnalysisArtifact와 fake providers를 사용해 다음이 가능해야 한다.

```text
Approved AnalysisArtifact
  ├─ PATENT -> Patent AnalysisResult
  └─ LICENSE -> License AnalysisResult
```

그리고 실패 fixture를 넣었을 때:

```text
provider failure
→ FAILED/PARTIAL/INCONCLUSIVE가 규칙대로 반환
→ 빈 성공 결과로 숨겨지지 않음
```

이 과정에 Drive/GitHub/Local/Firestore/Risk lifecycle 코드가 전혀 필요하지 않아야 한다.
