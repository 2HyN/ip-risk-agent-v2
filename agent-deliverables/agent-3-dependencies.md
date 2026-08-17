# Agent 3 — Dependency Request

Master Spec 57 에 따라 root manifest 를 직접 수정하지 않고 여기에 기록한다.
Integration Agent 가 `pyproject.toml` 에 반영한다.

## 현재 상태

**추가 없이 동작한다.** 아래 구현은 표준 라이브러리만 사용한다.

| 기능 | 사용 모듈 |
|---|---|
| KIPRIS XML/HTTP | `urllib.request`, `xml.etree.ElementTree` |
| 패키지 메타데이터 조회 | `urllib.request`, `json` |
| 매니페스트 파싱 | `tomllib`, `json` |
| 비동기 | `asyncio` |
| 스키마 | `pydantic` (이미 선언됨) |

`tests/intelligence` 58건이 현재 `pyproject.toml` 그대로 통과한다.

## Runtime — 실제 provider 연결 시 필요

| 패키지 | 최소 버전 | 용도 | 없을 때 |
|---|---|---|---|
| `google-genai` | `>=1.0` | Gemini 구조화 출력 호출 | `GoogleGenAIClient` 생성 시 명시적 오류. 다른 경로는 정상 |
| `google-cloud-aiplatform` | `>=1.71` | RAG Engine 검색 | `RagEngineRetriever` 생성 시 명시적 오류 |

두 패키지 모두 **선택 의존성으로 다룬다.** import 를 생성자 안에 두어, 설치되지
않은 환경에서도 나머지 기능과 테스트가 동작한다.

## Dev

없음. `pytest` 로 충분하다.

## Environment variables

`.env.example` 에 이미 선언된 이름을 그대로 쓴다.

| 이름 | 필수 | 용도 |
|---|---|---|
| `GEMINI_MODEL_ID` | 예 | 모델 식별자. 결과의 `versions.model_id` 에 기록된다 |
| `GEMINI_API_KEY` | AI Studio 사용 시 | |
| `VERTEX_AI_LOCATION_OR_ENDPOINT_CONFIG` | Vertex 사용 시 | region/endpoint |
| `KIPRIS_API_KEY_SECRET_ID` | 특허 분석 시 | Secret Manager 참조. 실제 값은 `KIPRIS_ACCESS_KEY` 로 주입 |
| `GCP_PROJECT_ID` | RAG 사용 시 | |
| `RAG_REGION` | RAG 사용 시 | 외부 GA region (Blueprint 20) |
| `RAG_CORPUS_ID` | RAG 사용 시 | |
| `RAG_CORPUS_VERSION` | 권장 | 결과에 기록. 없으면 `unversioned` |
| `PACKAGE_METADATA_BASE_URL` | 아니오 | deps.dev 기본값을 바꿀 때만 |

키가 없으면 해당 경로만 비활성화된다. 라이선스 규칙 판정은 키 없이 동작한다.

## External services

| 서비스 | 호출 | 실패 처리 |
|---|---|---|
| deps.dev | 패키지 버전별 라이선스 | 404 는 정상 미발견, 그 외는 `ProviderFailure` |
| PyPI / npm registry | deps.dev 가 `non-standard` 를 줄 때 보완 | 동일 |
| KIPRIS Plus | 특허 검색·초록·국문 명칭 | 0건과 실패를 구분 |
| Gemini | 기술 요소 추출·대조·설명 | 스키마 불일치는 재시도, 초과 시 실패 |
| RAG Engine | 참조 조항 검색 | 실패 시 coverage 를 PARTIAL 로 낮춤 |

## 확인 필요 — Integration 결정 사항

1. **`GEMINI_MODEL_ID` 의 실제 값.** Master Spec 16 과 35 는 "Gemini 3.6 Flash" 로
   적고 있으나 그 이름의 모델 식별자는 존재하지 않는다. 배포 전에 실제 식별자를
   정해야 한다. 코드는 환경변수로 받으므로 코드 변경은 필요 없다.

2. **Python 런타임.** `pyproject.toml` 은 `>=3.14,<3.15`, `ENVIRONMENT_SETUP.md` 는
   3.12.13 으로 서로 다르다. 이 plane 은 3.13 에서 개발·검증했으며 3.12 이상이면
   동작한다 (`tomllib` 때문에 3.11 이 하한이다).
