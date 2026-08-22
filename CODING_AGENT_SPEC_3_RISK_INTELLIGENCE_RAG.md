# IP Risk Agent — Agent 3 Development Specification
## Risk Intelligence & RAG

> **이 문서는 `CODING_AGENT_MASTER_SPEC.md`와 함께 Agent 3에게 전달한다.**  
> Master Spec이 상위 규약이며, 충돌 시 Master Spec을 우선한다.  
> Agent 3의 입력은 승인된 `AnalysisArtifact`, 출력은 `AnalysisResult`뿐이다.

> **[2026-08-23] 이 문서는 Intelligence Plane 의 설계 참조로 계속 유효하다.**
> 다만 `docs/DEVELOPMENT_SPEC.md` 가 다음 단계 개발의 단일 기준으로 채택되었고, 아래 절이
> 규정한 동작 일부를 **뒤집는다.** 충돌하는 자리에서는 `docs/DEVELOPMENT_SPEC.md` 가
> 우선한다. 뒤집힌 텍스트는 지우지 않는다 — 그때 무엇을 왜 정했는지의 기록이다.
>
> | 이 문서 | 무엇이 뒤집혔나 | 우선하는 곳 |
> |---|---|---|
> | §23 "MVP는 versioned global deterministic license policy" · "VWS별 custom policy는 구현하지 않는다" | 정책은 **workspace 별**이다. Control 의 메서드를 composition 에서 넘겨 계약 변경 없이 다리를 놓는다 | `DEVELOPMENT_SPEC.md` §2 **D7** · §5.10 (항목 2-E) |
> | §24 Dependency File Support (권장 목록) | 인식 표는 `core/artifacts/dependency_files.py` **한 곳**에 있고, `requirements.lock`·`constraints.txt`·`requirements/*.txt` 를 **더한다** | §5.8 · §6.8 · 결함 17 (항목 0-J) |
> | §29 "RAG explanation 실패 시 `SUCCEEDED + PARTIAL`" | `PARTIAL` 은 **"해소 권한 없음"** 으로만 좁아진다. 결정론적 판정을 함께 버리지 않는다 | §7.2 · §8 결함 **5** (항목 0-E) |
> | §29 "RAG는 deterministic policy를 override하지 않는다" | RAG 가 판정에 관여해도 된다. 단 **§4 의 층 규칙** — T3 은 **올릴 수만 있고 내리지 못한다** | §2 **D9** · §4 |
> | §8 Coverage Rule 말미 | Control 이 `SUCCEEDED+COMPLETE` 에서만 해소한다는 전제가 바뀐다 | §7.2 · §8.1 |
> | §26 "Registry fallback을 구현 가능" | 요청한 버전이 레지스트리에 없으면 **모른다.** 문서 전체(=최신 버전)로 폴백하지 않는다 | §5.9 · 결함 19 (항목 0-K) |
> | §27 SPDX Normalization | 원문자열을 **저장 경계 너머까지 보존**하고, `WITH` 예외를 평가에 반영하며 **예외 식별자를 SPDX 예외 목록으로 검증**한다. `OR` 선택은 어느 쪽을 택했는지 기록한다 | §5.2 · §5.3 · 결함 3·4·20 (0-F · 2-A · 2-B) |
> | §28 "정책 테이블은 코드/버전 파일로 명시" | `POLICY_VERSION` 이 모듈 상수가 아니라 `{workspace}:{정책표 판본}:{배포형태축 해시}` 가 된다. 커버리지 표는 코드에서 **데이터로** 옮긴다 | §5.10 · §5.5 (2-D · 2-E) |
> | §35 Corpus Versioning | 배포 검증기가 `corpus_version` 과 소스 3 건을 **하드코딩**해 확대를 막는다. corpus 를 늘리는 작업은 검증기 수정을 포함한다 | §5.4 (2-C · 2-D) |
> | §40 License "RAG 사용 시 `rag_corpus_version`" | retriever 가 **존재하면 부착 여부와 무관하게** 기록한다 | §5.6 · 결함 11 (항목 0-H) |

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

> **[전제 변경 — `docs/DEVELOPMENT_SPEC.md` §7.2 · §8.1]** Control 쪽 규칙이 바뀐다.
> `PARTIAL` 은 **후보 부재로 인한 `RESOLVED` 만** 막고 Risk 생성 · 근거 저장 · 이력 기록은
> 허용한다 (0-E). 그리고 `COMPLETE` 로 들어온 후보 0 건이라도 의존성 아티팩트에서
> **N>0 → 0 전이는 단독으로 권위를 갖지 못한다** (0-L). "보수적으로 PARTIAL 을 준다" 가
> 더 이상 전면 정지를 뜻하지 않으므로, coverage 는 **읽기의 온전함**을 그대로 반영한다 —
> 파싱 실패 · 절단 · 미인식은 `COMPLETE` 가 아니다 (§6.6 · §6.7).

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

> **[뒤집힘 — `docs/DEVELOPMENT_SPEC.md` D7 · §5.10, 항목 2-E]** 정책은 **workspace 별**이고
> 워크스페이스는 서로 완전히 독립이다. 아래의 "Contract v2 가 필요하다" 는 전제가 틀렸다 —
> **계약을 고치지 않고 다리를 놓는 선례가 이미 있다.** 특허 쪽이 Control 의 메서드를
> composition 에서 Intelligence 로 넘긴다:
>
> ```
> public_facade/service.py:298    async def previously_matched_patents(...)
> composition/production.py:422   previously_matched_patents=context.control_facade.previously_matched_patents
> intelligence/public.py:107,125  받아서 분석기에 전달
> ```
>
> 같은 모양으로 `workspace_license_policy(risk_workspace_id)` 를 넘긴다. `LicenseAnalyzer.
> __init__` 이 지금 `retriever` 를 받는 자리(`analyzer.py:66-73`)와 같은 키워드로 받는다.
> **Agent 3 가 Control DB 를 직접 조회하지 않는다는 금지는 그대로다** — 넘어가는 것은
> 함수 하나이고 Intelligence 는 그것이 어디서 오는지 모른다 (§3 의 경계).
>
> `POLICY_VERSION` 도 모듈 상수(`policy.py:24` = `global-license-policy-2026-08-14.1`)에서
> **`{risk_workspace_id}:{정책표 판본}:{배포형태축 해시}`** 로 바뀐다.
> `AnalysisVersions.policy_version` 이 자유 문자열이라 계약 변경이 없다 (§12.1).
>
> **설정 전에는 등급을 매기지 않는다 [결정]** — 파이프라인 1~3 단계(파싱 · 식별 · 전문
> 조회)는 그대로 돌고 **4~5 단계(조항 검색 · 의무 판정)를 하지 않는다.** 가장 무거운 쪽으로
> 가정하면 첫 화면이 전부 빨강이 되고, 그러면 사용자는 진짜 HIGH 도 함께 무시한다.

Frozen `AnalysisArtifact`에는 VWS-specific license policy payload가 없다.

따라서 **MVP는 versioned global deterministic license policy**를 사용한다.

VWS별 custom license policy/profile은 현재 구현하지 않는다.

이 기능이 필요해지면 Contract v2 또는 별도 approved policy-context contract가 필요하므로 후속으로 둔다.

Agent 3가 임의로 Control DB를 조회해 VWS policy를 가져오면 안 된다.

---

# 24. Dependency File Support

> **[대체됨 — `docs/DEVELOPMENT_SPEC.md` §5.8 · §6.8, 결함 17, 항목 0-J]** 인식 목록은 더
> 이상 이 문서의 권장이 아니라 **`core/artifacts/dependency_files.py` 한 곳의 표**이고
> 커넥터와 분석기가 함께 본다 (`78a6490` 에서 통일). 현재 7 형식 —
> `requirements*.txt/.in`, `pyproject.toml`, `setup.cfg`, `package.json`,
> `package-lock.json`, `uv.lock`, `poetry.lock`. **읽을 수 있는 이름만 인정한다** —
> 파서 없는 이름을 의존성으로 분류하면 어느 분석기도 맡지 못해 분석이 계약 위반으로
> 실패한다 (`setup.py` 가 그래서 빠져 있다).
>
> 여기에 **`requirements.lock`, `constraints.txt`, 하위 경로의 `requirements/*.txt` 를
> 더한다.** 이 저장소 자신의 `requirements.lock` 이 지금 `dependency_format()` 에 없어
> **기존 `requirements` 파서로 그대로 읽으면 68 건이 나오는데 한 건도 안 보인다.**
> 함께 볼 것 — `requirements` 계열 파서는 `EXACT_PIN` 을 내는데 잠금 파일은 `LOCKFILE`
> 이어야 한다. 지금 두 값이 동률이라 먼저 온 쪽이 이긴다.
>
> glob 지정과 모르는 파일의 형식 판별·추출은 [유예] 다 (§12.2, D5).

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

> **[제한 — `docs/DEVELOPMENT_SPEC.md` §5.9, 결함 19, 항목 0-K]** 폴백이 **없는 버전을
> 최신 버전으로 대체하면 안 된다.** 지금 npm 폴백이 `info["versions"].get(version, info)`
> 라(`package_metadata.py:142`) 요청한 버전이 없으면 **문서 전체로 폴백**해 최신 버전의
> 라이선스를 그 버전의 라이선스로 기록하고, `inferred_from_free_text` 같은 표시도 붙지
> 않는다. 요청한 버전이 없으면 **모른다** — `UNKNOWN` + 불확실 표시로 남긴다. 라이선스를
> 바꾼 패키지가 바로 이 제품이 잡으려는 대상이다.

Provider 결과는 법적 authoritative conclusion이 아니라 evidence fact.

---

# 27. SPDX Normalization

> **[강화 — `docs/DEVELOPMENT_SPEC.md` §5.2 · §5.3, 결함 3·4·20, 항목 0-F · 2-A · 2-B]**
> 아래 MUST 는 방향이 옳지만 실제 코드가 그 반대다. 셋을 더한다.
>
> * **원문자열을 저장 경계 너머까지 보존한다** (0-F). 지금은 미상 식별자가 저장 경계
>   이전에 문자열 `UNKNOWN` 으로 치환된다 — 소거하는 곳은 `spdx.normalize` 가 아니라
>   그 아래의 `spdx.canonicalize` 이고, **운영에서 실제로 도는 레지스트리 폴백 경로는
>   `normalize` 를 부르지 않는다.** 고칠 곳은 `package_metadata.py` 의 120-126 ·
>   152-166 · 228-234 세 군데다. `'MIT AND BUSL-1.1'` 이 `'MIT AND UNKNOWN'` 으로
>   **부분 소거**되므로 정책 표에 행을 추가해도 소급 구제가 되지 않는다. 계약은 열지
>   않는다 — `Evidence.metadata_safe` 의 `PACKAGE_METADATA` 근거에 실어 넘긴다 (§12.1).
> * **`WITH` 예외를 평가에 반영한다.** 파서는 `WITH` 를 제대로 읽어 `exception` 에 담는데
>   (`spdx.py:227`) 정책이 그 필드를 **한 번도 보지 않는다** (`policy.py:90-92`). 그래서
>   `GPL-2.0-only WITH Classpath-exception-2.0` 이 맨 GPL 과 같은 `POLICY_CONFLICT` 가
>   되어 **오탐이 자바 생태계 전반에 걸린다.**
> * **예외 식별자를 SPDX 예외 목록으로 검증한다.** 지금은 `MIT WITH totally-made-up` 이
>   조용히 통과해 `NOTICE_REQUIRED` 가 된다 — 날조된 예외가 완화를 얻는다. 목록에 없으면
>   완화하지 않고 `UNKNOWN` 으로 다룬다.
>
> `OR` 선택은 결과에 **어느 쪽을 택했는지 기록한다.** 지금은 조용히 최소 심각도를 고르고
> (`AGPL-3.0-only OR MIT` → `NOTICE_REQUIRED`) 그 선택이 원장에 남지 않는다.
> 어휘는 SPDX 전체로 넓힌다 — 표 밖 식별자는 `UNKNOWN` 이되 **원문자열이 남으므로**
> 나중에 표가 넓어지면 재평가로 구제된다 (2-A).

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

> **[뒤집힘 — `docs/DEVELOPMENT_SPEC.md` §5.10 · §5.5, 항목 2-D · 2-E]** 두 표가 코드를
> 떠난다. **정책 판본**은 모듈 상수(`policy.py:24`)가 아니라
> `{risk_workspace_id}:{정책표 판본}:{배포형태축 해시}` 로 workspace 마다 달라지고(D7),
> **커버리지 표**는 manifest 에서 생성한 색인을 package-data 로 실어 문서를 늘릴 때 `.py`
> 를 고치지 않게 한다 — 프롬프트 `.md` 가 `pyproject.toml:46` 에서 이미 그렇게 실린다.
> `UNKNOWN`/non-standard 를 자동 허용하지 않는다는 규칙은 그대로다.

---

# 29. License RAG 설명

> **[뒤집힘 — `docs/DEVELOPMENT_SPEC.md` D9 · §4 · §7.2, 결함 5, 항목 0-E]** 이 절이 두
> 군데에서 뒤집힌다.
>
> * **RAG 는 판정에 관여해도 된다** (D9). 다만 전부 여는 것이 아니라 층을 나눈다 (§4) —
>   T1 결정론(파서 · SPDX 표현식 · 정책 함수)과 T2 검증된 대조는 판정을 **만들고**,
>   **T3(RAG · 모델)은 등급을 올릴 수만 있고 내리지 못한다.** 근거가 있다 — 특허 쪽에서
>   모델 자기신고로 강등했더니 **HIGH 자격 13 건이 13 건 모두 강등되어 HIGH 가 한 번도
>   안 나왔다** (`intelligence/patent/grounding.py:120-137`). T3 이 올릴 때는
>   **corpus chunk id + 실재가 확인된 인용**이 반드시 있어야 하고, 인용이 없으면 모델
>   출력을 전혀 쓰지 않는다. 상향 발화율은 계측하고 상한을 둔다 (§10).
> * **아래 "MVP 권장" 의 `SUCCEEDED + PARTIAL` 이 결함 5 다.** `_attach_reference_evidence`
>   가 RAG 예외에서 coverage 를 PARTIAL 로 낮추고, Control 이
>   `analysis_is_authoritative(SUCCEEDED, COMPLETE)` 안에서만 reconcile 하므로
>   (`risk_reconcile/service.py:196`) **RAG 가 죽으면 표가 낸 판정까지 함께 버려진다.**
>   `explanation.py` 머리말의 "두 기능이 모두 실패해도 정책 결과는 그대로 남는다" 는
>   canonical 계층에서 사실이 아니다. 새 기준은 `PARTIAL` 을 **"해소 권한 없음"** 으로만
>   좁힌다 — Risk 생성 · 근거 저장 · 이력 기록은 허용하고 후보 부재로 인한 `RESOLVED` 만
>   막으며, 부분성은 근거 행 자체에 표시한다.
>
> **retrieval 자체도 바뀐다** (§5.5, 결함 2, 항목 0-G). `reference_gate.is_relevant` 가
> 판정을 이끈 leaf 가 아니라 **표현식의 모든 leaf** 를 봐서
> `'Apache-2.0 AND GPL-3.0-only'`(`POLICY_CONFLICT`)에 "소스코드 공개 의무는 없다" 는
> `permissive-notice` 가 붙는다 — **판정과 정반대의 근거다.** 게이트가 보는 집합을
> **판정을 이끈 leaf**(AND 는 최대 심각도, OR 은 선택된 leaf)로 좁히고, 검색은 **거르고
> 나서 찾는다**: SPDX 식별자로 정확 조회 → 그 안에서만 임베딩으로 구절 선택.

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

> **[제약 — `docs/DEVELOPMENT_SPEC.md` §5.4, 항목 2-C · 2-D]** **배포 검증기가 corpus
> 확대를 막는다.** `scripts/validate_gcp_deployment.py:286-294` 가 `corpus_version` 을
> 문자열 `"2026-08-14.1"` 로, 소스를 **정확히 3 건**으로, source_id 집합을
> `RAG_SOURCE_IDS` 로 하드코딩해 검사한다 — **문서를 하나만 더해도 배포가 막힌다.** 같은
> 파일 `:640-666` 은 `CORPUS_SUBJECT_COVERAGE` 를 manifest 와 교차검증한다. **2-C 와 2-D 는
> 배포 검증기 수정을 포함한다.**
>
> 지금 corpus 는 손으로 쓴 문서 3 개, 총 **2,120 바이트**(789 + 734 + 597)이고 RAG 를
> 부르는 대상 22 개 중 **4 개**만 덮는다. 내용은 SPDX license-list-data 의 **전문**(CC0)
> + 배포 형태별 의무 해설로 간다 (D4). 임의의 웹 문서를 긁지 않으며 manifest 의
> `approved_for_rag` 가 그 관문이다. `manifest.yaml` 의 `corpus_version`(`2026-08-14.1`)
> 과 배포 환경변수(`2026-08-21.1`)가 서로 다른 것은 [미결] 이다 (§13-5) — 강제하는 쪽은
> manifest 값이다.

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

> **[뒤집힘 — `docs/DEVELOPMENT_SPEC.md` §5.6, 결함 11, 항목 0-H]** "RAG 사용 시" 가
> 아니라 **retriever 가 존재하면 부착 여부와 무관하게 기록한다.** 지금은 조각이 실제로
> 붙었을 때만 기록되어 주제 불일치로 전부 버린 경우와 조회 실패가 `None` 이고, 실측에서
> 저장된 LICENSE 결과 **15 건이 전부 `None` 인데 `LICENSE_REFERENCE` 근거는 8 건 존재**
> 했다. corpus 갱신이 판정을 바꾸는 구조에서 이 필드가 **감사의 전부**가 된다.
> 아울러 `policy_version` 은 §5.10 에 따라 workspace 마다 다른 값이 된다.

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
