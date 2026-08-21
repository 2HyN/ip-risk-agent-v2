# 분석 E2E 샘플 문서

Drive/GitHub/Local mount 에 올려 Patent·License 분석 경로를 실제로 태우기 위한
샘플이다. runtime 이 참조하지 않으므로 삭제해도 build/test/배포에 영향이 없다.

---

## 가장 중요한 것 — 파일 이름이 분석기를 결정한다

Drive 커넥터는 **파일 이름**으로 `ArtifactKind` 를 정하고, 그 종류가 어느 분석기로
갈지를 결정한다 (`connectors/google_drive/adapter.py::_infer_artifact_kind`).

| Drive 파일 이름 | ArtifactKind | 가는 분석기 |
|---|---|---|
| `requirements.txt`, `package.json` (정확히 이 이름) | `MANIFEST` | **License** |
| `*.lock`, `*lockfile` | `LOCKFILE` | **License** |
| 그 밖의 모든 이름 | `DOCUMENT_TEXT` | **Patent** |

따라서 `requirements-sample.txt` 처럼 이름을 바꿔 올리면 License 가 아니라 Patent
분석으로 간다. **이름을 그대로 유지해서 올린다.**

> Drive 는 `pyproject.toml`, `go.mod`, `Cargo.toml`, `package-lock.json` 을 manifest 로
> 인식하지 않는다 (`package-lock.json` 은 `.lock` 으로 끝나지 않는다). License 분석기
> 자체는 `pyproject.toml` 파서를 갖고 있으므로, 이는 커넥터 쪽 분류 범위의 한계다.

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

| 항목 | 노리는 판정 | 비고 |
|---|---|---|
| `pymupdf==1.24.0` | `POLICY_CONFLICT` | deps.dev 는 non-standard 로 답한다. PyPI 원문에서 `AGPL-3.0-only` 를 복원하는 **폴백 경로**까지 함께 검증한다 |
| `certifi`, `psycopg2` | `REVIEW_REQUIRED` | 결합 방식에 따라 의무가 달라지는 계열 |
| `requests==2.32.3` | `NOTICE_REQUIRED` | Apache-2.0 |
| `express@4.19.2`, `lodash` | `NOTICE_REQUIRED` | MIT |
| `urllib3>=2.0.0`, `chalk@^5.3.0` | `VERSION_RANGE_NOT_PINNED` 진단 | `==` 만 확정 버전으로 본다 |
| `iprisk-nonexistent-sample-package` | `NOT_FOUND` / `UNKNOWN` | **실패를 "위험 없음" 으로 바꾸지 않는지** 확인하는 줄 |

> 라이선스 식별자는 deps.dev / PyPI / npm 레지스트리의 **실시간 응답**에서 온다.
> 위 표는 기대값이지 계약이 아니다. 실제 결과가 다르면 그 자체가 관찰 결과다.

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
