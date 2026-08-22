# 분석 E2E 샘플 문서

Drive/GitHub/Local mount 에 올려 Patent·License 분석 경로를 실제로 태우기 위한
샘플이다. runtime 이 참조하지 않으므로 삭제해도 build/test/배포에 영향이 없다.

---

## 가장 중요한 것 — 파일 이름이 분석기를 결정한다

커넥터는 **파일 이름**으로 `ArtifactKind` 를 정하고, 그 종류가 어느 분석기로 갈지를
결정한다. 한 문서는 둘 중 **하나만** 받는다.

어떤 이름이 의존성 선언인지는 세 커넥터와 License 분석기가 **같은 표**를 본다
(`core/artifacts/dependency_files.py`). 경로는 보지 않고 파일 이름만 본다 —
`deps/requirements.txt` 도 `requirements.txt` 와 같게 다룬다.

| 파일 이름 | ArtifactKind | 가는 분석기 |
|---|---|---|
| `requirements*.txt`, `requirements*.in` | `MANIFEST` | **License** |
| `pyproject.toml`, `setup.cfg`, `package.json` | `MANIFEST` | **License** |
| `package-lock.json`, `uv.lock`, `poetry.lock` | `LOCKFILE` | **License** |
| 그 밖의 이름 | 아래 "되돌림" 참고 | 대개 **Patent** |

**읽을 수 있는 이름만 의존성으로 인정한다.** 읽지 못할 것을 의존성으로 분류하면
License 분석기는 파서가 없어 거절하고 Patent 분석기는 종류가 맞지 않아 거절해,
어느 쪽도 맡지 않은 채 분석이 계약 위반으로 실패한다. `setup.py` 가 그랬다 —
임의의 파이썬 코드라 실행하지 않고서는 의존성을 확정할 수 없으므로 표에 없고,
저장소에서는 소스 코드로 다뤄진다. 선언 파일인 `setup.cfg` 만 대상이다.

### 되돌림은 커넥터마다 다르다

표에 없는 이름을 어떻게 볼지는 소스의 성격에 따라 다르며, 이는 의도된 차이다.

* **Drive** — 사용자가 파일을 하나씩 골라 붙인다. 고른 것은 보겠다는 뜻이므로
  나머지를 `DOCUMENT_TEXT` 로 본다. 확장자가 없는 파일도 검사된다.
* **GitHub · Local** — 저장소나 폴더를 통째로 훑는다. 코드·문서 확장자만 각각
  `SOURCE_CODE`·`DOCUMENT_TEXT` 로 보고 나머지는 `UNKNOWN` 으로 두어, 이미지와
  바이너리까지 분석하지 않는다.

## 읽을 수 있는 형식

Drive 는 아래 MIME 만 읽는다 (`SELECTABLE_MIME_TYPES`). 그 밖은
`ContentScope.UNSUPPORTED` 로 처리되어 **본문 없이** 넘어간다.

```
application/vnd.google-apps.document   (Google 문서)
text/plain
text/markdown
application/json
```

`.md` 와 `.txt` 는 그대로 올리면 되고, `package.json` 은 `application/json` 으로 잡힌다.
PDF·DOCX·이미지는 읽지 않는다.

---

## License 분석 샘플

`license/requirements.txt` 와 `license/package.json`.

정책 판정은 `intelligence/license/policy.py` 의 전역 정책
`global-license-policy-2026-08-14.1` 기준이다.

아래는 **실제 deps.dev / PyPI / npm 에 붙여 확인한 결과**다 (2026-08-21).

`requirements.txt` — `SUCCEEDED / COMPLETE`, 후보 6건, provider 실패 0건

| 패키지 | 식별된 라이선스 | 판정 | 비고 |
|---|---|---|---|
| `pymupdf==1.24.0` | `AGPL-3.0-only` | `POLICY_CONFLICT` | deps.dev 는 non-standard 로 답한다. PyPI 원문에서 복원하는 **폴백 경로**를 함께 태운다 (`LICENSE_INFERRED_FROM_FREE_TEXT`) |
| `certifi==2024.7.4` | `MPL-2.0` | `REVIEW_REQUIRED` | |
| `psycopg2==2.9.9` | `LGPL-2.1-only WITH exceptions` | `REVIEW_REQUIRED` | |
| `requests==2.32.3` | `Apache-2.0` | `NOTICE_REQUIRED` | |
| `click==8.1.7` | `BSD-3-Clause` | `NOTICE_REQUIRED` | |
| `urllib3>=2.0.0` | `UNKNOWN` | `UNKNOWN` | `VERSION_RANGE_NOT_PINNED`. 조회는 성공하므로 coverage 는 유지된다 |

`package.json` — `SUCCEEDED / COMPLETE`, 후보 4건, provider 실패 0건
(`express`·`lodash`·`chalk` MIT, `typescript` Apache-2.0, 모두 `NOTICE_REQUIRED`.
`chalk` 는 `VERSION_RANGE_NOT_PINNED`.)

> 라이선스 식별자는 레지스트리의 **실시간 응답**에서 온다. 실제 결과가 위와 다르면
> 그 자체가 관찰 결과다.

### ⚠ provider 실패 1건이 그 파일의 Risk 를 전부 없앤다

Risk 생성은 `core/risk/transitions.py::analysis_is_authoritative()` 가 참일 때만 일어난다.

```python
return status is AnalysisStatus.SUCCEEDED and coverage is AnalysisCoverage.COMPLETE
```

provider 조회가 **하나라도** 실패하면 coverage 가 `PARTIAL` 이 되고, 그 결과 전체가
비권위적으로 취급되어 `_reconcile()` 이 아예 호출되지 않는다. 즉 존재하지 않는 패키지
한 줄 때문에 같은 파일의 `POLICY_CONFLICT` 를 포함한 **나머지 후보 전부가 Risk 로
승격되지 않는다.**

"불완전한 분석이 Risk 의 진실을 바꾸지 못한다" 는 의도된 설계다. 다만 판정 단위가
**파일 전체**라서, 무관한 의존성 하나의 조회 실패가 확인된 다른 위반까지 덮는다.
이 입자도를 후보 단위로 낮출지는 별도 결정 사항이다.

그래서 NOT_FOUND 확인용 줄은 `requirements.txt` 안에 **주석으로 꺼 두었다.**
그 동작만 따로 보고 싶으면 그 줄만 켜서 별도로 돌린다. 기대값은
`Analysis INCONCLUSIVE + 0 risks` 다.

## Patent 분석 샘플

`patent/` 아래 3 개.

| 파일 | 기대 |
|---|---|
| `voice-phishing-detection-design.md` | `is_technical=true`, 특허 후보 검색됨 |
| `battery-thermal-runaway-detection-design.md` | `is_technical=true`, 다른 도메인에서 후보 검색됨 |
| `negative-weekly-meeting-notes.md` | **`is_technical=false` → `SKIPPED`** |

### 기술 문서 두 개를 이렇게 쓴 이유

추출 프롬프트(`gemini/prompts/patent_extract_v1.md`)는 `is_technical` 을 다음일 때만
참으로 둔다.

- 구체적인 처리 방식·구조·알고리즘·장치 구성이 서술되어 있다
- 일정·회의록·사업 계획·용어 정리가 아니다
- **기능 목록만 나열된 문서는 참이 아니다**

두 샘플은 신호 처리 파라미터, 임계값, 결합식, 단계별 판정 조건을 실제 수치와 함께
적었다. "무엇을 어떻게 처리하는지" 가 있어야 통과한다.

또한 검색 대상이 **KIPRIS(한국 특허)** 이므로 국내 특허가 두터운 도메인
(통화 음성 분석, 배터리 열관리)을 골랐다.

### 음성 대조군이 필요한 이유

`negative-weekly-meeting-notes.md` 에서 **후보가 나오지 않는 것이 정상**이다.
이 파일이 있어야 "분석기가 고장났다" 와 "이 문서는 특허 검토 대상이 아니다" 를
구별할 수 있다. 세 파일을 함께 올려 결과를 비교한다.

---

## 알려진 판정 한계

특허 후보가 나오더라도 **우선순위가 `HIGH` 까지 오르지 않는다.** KIPRIS Plus 가
제공하는 범위가 초록이라 청구항 근거를 요구하는 규칙을 만족할 수 없기 때문이다.
초록 근거가 둘 이상이면 `MEDIUM` 까지 오른다. `PatentDocument.claims` 는 구현되어
있어 청구항을 얻을 수 있게 되면 그대로 동작한다.

또한 상위 6 건만 판정하므로 미판정 후보가 남으면 coverage 가 `PARTIAL` 이 되고,
Control 은 해당 Risk 를 자동 해소하지 않는다. 이는 설계된 보수적 동작이다.
