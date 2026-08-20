# Agent 3 — Dependencies

Risk Intelligence & RAG plane 이 직접 선택하고 설치한 dependency 목록이다.
각 항목은 실제 provider 호출로 검증했으며 결과를 아래에 적었다.

## Runtime

| 패키지 | 버전 | 용도 | 선택 사유 |
|---|---|---|---|
| `pydantic` | `2.13.4` | Contract 및 모델 출력 스키마 | baseline 에 이미 선언됨 |
| `httpx` | `0.28.1` | deps.dev · PyPI · npm · KIPRIS · RAG REST 호출 | 이 plane 은 의존성 수만큼 조회를 반복한다. 진짜 async 와 연결 재사용이 필요했다. `urllib` + `asyncio.to_thread` 는 스레드를 낭비하고 타임아웃 제어가 거칠다 |
| `defusedxml` | `0.7.1` | KIPRIS XML 파싱 | 외부에서 받은 XML 이다. 표준 `xml.etree` 는 엔티티 확장 공격에 취약하다. 파서만 바꾸면 되므로 비용이 거의 없다 |
| `PyYAML` | `6.0.3` | RAG corpus 매니페스트 | 명세 34 의 형식이 YAML 이다. 이전에는 의존성을 늘릴 수 없어 TOML 로 우회했으나 이제 명세대로 맞췄다. `safe_load` 만 쓴다 |
| `google-genai` | `2.17.0` | Gemini 구조화 출력 | 공식 SDK. AI Studio 와 Vertex 를 같은 코드로 쓴다 |
| `google-auth` | `2.56.3` | RAG Engine 자격증명 | ADC 처리만 맡긴다 |

### 선택하지 않은 것

**`google-cloud-aiplatform`** — RAG Engine SDK. 설치 용량이 100MB 를 넘는데 이 plane 이
쓰는 기능은 `retrieveContexts` 하나뿐이다. `google-auth` 로 토큰만 얻고 REST 를 httpx 로
직접 호출하는 편이 가볍고, 이미 httpx 를 쓰므로 새 의존성이 늘지 않는다.

**`requests`** — httpx 와 역할이 겹친다. 하나만 쓴다.

## Dev

| 패키지 | 버전 | 용도 |
|---|---|---|
| `pytest` | `9.1.1` | 테스트 |
| `pytest-asyncio` | `1.4.0` | async provider 테스트. strict 모드이며 marker 를 명시한다 |

## Environment variables

`.env.example` 에 선언된 이름을 그대로 쓴다. 이 plane 은 환경변수를 직접 읽지 않고
`IntelligenceConfig.from_env(env)` 로 주입받는다.

| 이름 | 필수 | 용도 |
|---|---|---|
| `GEMINI_MODEL_ID` | 예 | 모델 식별자. 결과의 `versions.model_id` 에 기록 |
| `GEMINI_API_KEY` | AI Studio 사용 시 | |
| `VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG` | Vertex 사용 시 | |
| `KIPRIS_ACCESS_KEY` | 특허 분석 시 | Secret Manager 에서 주입 |
| `GCP_PROJECT_ID` · `RAG_REGION` · `RAG_CORPUS_ID` | RAG 사용 시 | |
| `RAG_CORPUS_VERSION` | 권장 | 결과에 기록. 없으면 `unversioned` |

키가 없으면 해당 경로만 비활성화된다. 라이선스 규칙 판정은 키 없이 동작한다.

## 검증 결과

```
pytest tests/intelligence -m "not live"    58 passed     대역 · 자격증명 불필요
pytest tests/intelligence -m live          10 passed     실제 provider 호출
```

### 실제 호출로 확인한 것

| 대상 | 확인 내용 |
|---|---|
| deps.dev | `requests 2.32.3` → `Apache-2.0` 표준 식별자 수신 |
| PyPI 폴백 | `PyMuPDF 1.24.0` 은 deps.dev 가 `non-standard` 로 답한다. 레지스트리 원문에서 `AGPL-3.0-only` 복원 후 `POLICY_CONFLICT` 판정 |
| npm | `express 4.19.2` → `MIT` |
| 미존재 패키지 | `NOT_FOUND` · `retryable=False` 로 분류 |
| KIPRIS 검색 | 정규화된 출원번호 수신 |
| KIPRIS 0건 | 무의미한 검색어에 빈 결과. 실패와 구분됨 |
| KIPRIS 상세 | 초록 수신 |
| KIPRIS 잘못된 키 | 오류 또는 0건으로 안전하게 처리 |
| Gemini | 선언한 스키마대로 구조화 출력 수신 |
| Gemini 비기술 문서 | `is_technical=False` 로 판정 |

### 전체 파이프라인 실측

```
LICENSE  SUCCEEDED/COMPLETE
  pymupdf   1.24.0  AGPL-3.0-only  POLICY_CONFLICT   [LICENSE_INFERRED_FROM_FREE_TEXT]
  requests  None    Apache-2.0     NOTICE_REQUIRED   [VERSION_RANGE_NOT_PINNED]

PATENT   SUCCEEDED/COMPLETE · 후보 3건 · 근거 4건
  1020080080388  보이스-피싱 검출을 위한 GMM 모델...
     통화 음성의 복호화 과정에서 추출된 파라미터를 특징 벡터로 구성하는 기술적 특징이 일치함
```

## 특이사항 — 실제 호출로 드러나 고친 것

세 가지 모두 대역 테스트만으로는 발견되지 않았다.

**1. KIPRIS 응답 필드명이 문서와 달랐다.**
검색 응답은 `applicationNumber`/`inventionTitle` 이 아니라 `applicationNo`/`inventionName` 이다.
잘못된 이름으로 읽고 있어 검색 결과가 항상 0건이었다. 0건은 정상 처리 경로이므로
대역 테스트에서는 드러나지 않았다.

**2. 국문 초록이 따로 있었다.**
`korAbstractInfo` 가 `korAbstract` 를 제공한다. 검사 대상 문서는 대개 한국어이므로
국문 초록을 우선 사용하도록 바꿨다. 영문 초록과 한국어 문서를 대조하면 겹치는 표현을
찾기 어렵다.

**3. Gemini 가 `additionalProperties` 를 거부했다.**
Pydantic 의 `extra="forbid"` 가 스키마에 그 필드를 넣는데 API 가 400 을 돌려준다.
우리 쪽 검증은 엄격하게 유지하고, API 로 보내는 스키마에서만 해당 항목과 `$ref` 를
정리하도록 변환기를 두었다.

**4. 추정 여부 표시가 동작하지 않았다.**
`normalize()` 가 내부에서 자유 서술 추정까지 수행해 `inferred_from_free_text` 가 항상
`False` 였다. 라이선스를 추측했다는 사실이 사용자에게 전달되지 않는 상태였다.
파싱과 추정을 분리해 `LICENSE_INFERRED_FROM_FREE_TEXT` 가 실제로 붙도록 고쳤다.

**5. 우선순위가 실측에서 전부 LOW 로 깔렸다.**
KIPRIS 는 청구항을 제공하지 않는다. 청구항 근거를 요구하는 규칙에서는 모든 후보가
LOW 가 되어 우선순위가 정보를 주지 못했다. 초록 근거만으로도 겹치는 구성이 둘 이상이면
MEDIUM 으로 올리도록 조정했다.

## Integration 이 알아야 할 것

**`GEMINI_MODEL_ID`** — Master Spec 16/35 의 "Gemini 3.6 Flash" 는 실재하는 식별자가
아니다. 검증에는 `gemini-3-flash-preview` 를 사용했다. 배포 시 값을 정해야 한다.

**Python** — 3.13 에서 개발·검증했다. `tomllib` 를 더 쓰지 않으므로 하한은 3.10 이다.
~~`pyproject.toml` 의 `>=3.14` 와 `ENVIRONMENT_SETUP.md` 의 3.12 가 서로 다르니 통일이 필요하다.~~
→ Integration 단계에서 **3.14.7 로 통일**했고, 이 plane 의 58 건을 3.14.7 에서 재검증해 전부 통과했다.

**버전 고정** — 위 버전에서 검증했다. 다른 Agent 와 충돌하지 않으면 그대로 반영하고,
충돌 시 조정 후 `pytest tests/intelligence` 로 재검증하면 된다.
