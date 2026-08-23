# 통합 시험 시나리오

| | |
|---|---|
| 무엇인가 | 배포된 운영본이 0 단계에서 고친 것들을 **실제로** 하는지 확인한다 |
| 기준 | `dae2bfe` · API `00045-fmz` / Worker `00046-zxp` · digest `sha256:75e620c9…` |
| 왜 지금인가 | 0 단계는 전부 "운영 데이터를 잘못 만들던 것" 이었다. 단위 시험은 우리 가정 안에서만 참이다 |
| KIPRIS | **0 회.** 아래 픽스처는 전부 의존성 파일이라 License 경로로만 간다 |

단위 시험 1,023 건이 통과했지만 그것은 **우리가 가정한 대로 코드가 도는가**까지다.
가정 자체가 틀렸는지는 실물로만 안다 — 이번에도 그랬다. `matplotlib` 이 최고 위험으로
올라가던 것은 시험이 아니라 실제 레지스트리 응답을 들여다보다 나왔다 (§5.13).

---

## 0. 지금 운영은 비어 있다

시작 조건이 좋다. 실측(2026-08-23)에서 `workspaces` · `source_mounts` · `artifacts` ·
`analysis_jobs` · `risks` 가 **전부 0 건**이다. 이전 측정에 쓰던 workspace 를 지웠기
때문이고, 그래서 이번 시험은 **깨끗한 상태에서 처음부터** 도는 것을 본다.

연결은 남아 있다. 연결은 workspace 가 아니라 **사용자**의 것이라 workspace 를 지워도
살아 있고, 그것이 맞다.

| 연결 | 상태 | 쓸 수 있는가 |
|---|---|---|
| GitHub (설치 `155365447`) | ACTIVE | **예.** 이 시나리오가 쓴다 |
| Google Drive (`aj22@iceu.kr`) | ACTIVE | 자격증명은 있으나 1-A(서비스 계정 마운트) 미구현 |
| LOCAL 기기 2 대 | ACTIVE | 데스크톱 앱을 띄워야 한다 |

**GitHub 으로 한다.** 이미 설치되어 있고, 의존성 파일만 담으면 KIPRIS 를 한 번도 쓰지
않는다.

---

## 1. 픽스처 저장소

`tests/fixtures/integration-repo/` 의 13 개 파일을 **그대로** 새 GitHub 저장소에 올린다.
private 이어도 된다 — App 이 설치된 곳이면 된다.

**소스 코드도 문서도 넣지 않는다.** `SOURCE_CODE` 와 `DOCUMENT_TEXT` 는 특허 경로로 가고
분석 한 건이 KIPRIS 를 11 회쯤 쓴다. 한도가 월 1,000 회다. `README.md` 도 `LICENSE` 도
넣지 말 것 — `LICENSE.txt` 는 지금 특허 경로로 간다 (결함 26).

```powershell
gh repo create iprisk-integration-fixture --private
git -C <새 폴더> init
Copy-Item -Recurse tests/fixtures/integration-repo/* <새 폴더>
git -C <새 폴더> add -A; git -C <새 폴더> commit -m "fixture"; git -C <새 폴더> push
```

### 파일마다 무엇을 붙잡는가

| 파일 | 무엇을 확인하는가 |
|---|---|
| `package.json` | 0-A 통짜 분석 · 0-B redaction 이 패키지 이름을 안 건드림 |
| `package-lock.json` | 0-J 잠금 파일 신뢰도 (`LOCKFILE`) |
| `requirements.txt` | 기본 경로 |
| `requirements-dev.txt` | **0-J** — 예전에는 이름이 안 맞아 특허 경로로 샜다 |
| `requirements/base.txt` | **0-J** — 폴더로 나누는 관행 |
| `constraints.txt` | **0-J** — pip 제약 목록 |
| `requirements.lock` | **0-J** — 문법은 같고 신뢰도만 `LOCKFILE` 로 오른다 |
| `pyproject.toml` | 커넥터마다 다르게 분류되던 파일 |
| `setup.cfg` | 같음 |
| `uv.lock` · `poetry.lock` | 잠금 파일 두 종 |
| `broken/package.json` | **0-C** — 못 읽은 것이 `PARTIAL` 이지 0 건이 아니다 |
| `missing-version/package.json` | **0-K** — 없는 버전을 최신으로 덮지 않는다 |

13 개가 전부 인식되고, 12 개가 **선언 17 건**을 내고, 1 개가 `PARTIAL` 이다.
`tests/integration/test_integration_fixture.py` 가 이것을 붙잡아 둔다.

---

## 2. 기대 결과 — 패키지별

아래는 **배포된 코드로 실제 조회해 계산한 값**이다 (2026-08-23). 짐작이 아니다.

| 패키지 | 식별자 | 등급 | 출처 | |
|---|---|---|---|---|
| `left-pad@1.3.0` | WTFPL | **LOW** | deps.dev | |
| `chalk@5.3.0` | MIT | MEDIUM | deps.dev | |
| `requests@2.31.0` | Apache-2.0 | MEDIUM | deps.dev | |
| `node-forge@1.3.1` | BSD-3-Clause OR GPL-2.0-only | MEDIUM | deps.dev | **0-G** — `OR` 에서 이끄는 leaf 만 본다 |
| `matplotlib@3.11.1` | PSF-2.0 | MEDIUM | pypi.org | **회귀 감시** — 한때 GPL-2.0 → HIGH 였다 |
| `pandas@3.0.5` | BSD-3-Clause | MEDIUM | pypi.org · 추정 | **회귀 감시** — 한때 Apache-2.0 이었다 |
| `weasyprint@69.0` | BSD-3-Clause | MEDIUM | pypi.org · 추정 | **회귀 감시** — 한때 UNKNOWN 이었다 |
| `paramiko@3.4.0` | LGPL-2.1-only | **HIGH** | pypi.org · 추정 | 약한 반대급부 |
| `pikepdf@8.13.0` | MPL-2.0 | **HIGH** | deps.dev | |
| `mysqlclient@2.2.4` | GPL-2.0-only | **HIGH** | deps.dev | |
| `PyQt5@5.15.10` | GPL-3.0-only | **HIGH** | deps.dev | |
| `PyMuPDF@1.28.2` | AGPL-3.0-only | **HIGH** | pypi.org · 추정 | deps.dev 가 못 푼 것을 원문에서 되살린다 |
| `nvidia-cudnn-cu12@9.24.0.43` | UNKNOWN | **INDETERMINATE** | pypi.org | 어디에도 SPDX 가 없다 |
| `pyarmor@9.2.6` | UNKNOWN | **INDETERMINATE** | pypi.org | 독점. 모르는 것이 맞다 |
| `chalk@99.99.99` | UNKNOWN | **INDETERMINATE** | registry.npmjs.org | **0-K** — `VERSION_NOT_IN_REGISTRY` |

분포는 LOW 1 · MEDIUM 6 · HIGH 5 · INDETERMINATE 3 이다.

> **MEDIUM 이 많은 것은 정상이다.** MIT·Apache-2.0 도 고지 의무가 있어
> `NOTICE_REQUIRED` → MEDIUM 이다. `LOW` 는 의무가 정말 없는 것(WTFPL)에만 붙는다.

---

## 3. 절차

### 3.1 workspace 를 만들고 마운트한다

브라우저가 필요하다. 로그인이 Google server-side flow 라 세션을 대신 만들 수 없다.

1. `https://ip-risk-agent-v2-api-555102774494.asia-northeast3.run.app` 에서 Google 로그인
2. workspace 생성
3. GitHub 연결에서 픽스처 저장소를 **저장소 루트로** 마운트

### 3.2 무엇을 볼 것인가

분석이 끝나면 `GET /api/v1/workspaces/{id}/risks` 와 대시보드를 본다.

---

## 4. 합격 판정

### A. 네 손실 경로가 닫혔는가 (0-A~0-E)

| # | 확인 | 불합격 신호 |
|---|---|---|
| A1 | 아티팩트 13 개가 전부 **License** 분석을 받았다 | 하나라도 Patent 로 갔다 → KIPRIS 가 줄었는지 본다 |
| A2 | `broken/package.json` 의 결과가 `PARTIAL` 이다 | `COMPLETE` + 0 건 → 0-C 회귀 |
| A3 | 나머지 12 개가 `COMPLETE` 다 | `PARTIAL` → 게이트가 잘랐다 (0-D) |
| A4 | 후보 17 건이 전부 보인다 | 모자라면 조각화나 redaction 이 먹었다 |

**A4 가 핵심이다.** 이 네 가지가 닫히기 전에는 `COMPLETE` + 0 건이 "정말 없다" 를 뜻하지
못했다. 이제는 뜻한다.

### B. 등급이 §2 의 표와 같은가

특히 **회귀 감시 세 줄**이다. `matplotlib` 이 HIGH 로 보이면 §5.13 이 되돌아간 것이고,
그것은 이 제품에서 가장 나쁜 종류의 오답이다 — 사용자가 근거를 열면 우리가 GPL 이라고
적어 둔 것이 있다.

### C. `INDETERMINATE` 가 자기 칸에 있는가

세 건이 HIGH 도 MEDIUM 도 아닌 **네 번째 등급**으로 보여야 한다.
`chalk@99.99.99` 에는 `VERSION_NOT_IN_REGISTRY` 가 붙어 있어야 한다 — 왜 모르는지가
남지 않으면 사용자가 조회 실패와 구분하지 못한다.

### D. 근거와 판본 (0-H · 결함 22)

| # | 확인 | 왜 |
|---|---|---|
| D1 | HIGH·INDETERMINATE 건에 `rag_corpus_version` = `2026-08-23.4` 가 있다 | 검색을 시도했으면 남는다 |
| D2 | LOW 건에는 **없다** | 부르지도 않은 검색의 판본을 적는 것도 거짓말이다 |
| D3 | 근거가 전부 **같은 분석 작업**의 것이다 | 판정과 근거의 시점이 어긋나지 않는다 |
| D4 | 붙은 조각이 그 라이선스를 다룬다 | 0-G · 주제 불일치 게이트 |

D1 을 보려면 corpus 가 675 편 그대로여야 한다. 실측으로 675 편·전부 고유임을 확인했다.

### E. 두 번 돌려도 같은가 (결함 22 · 0-L)

`POST /api/v1/workspaces/{id}/security/reanalyze` 로 다시 돌린다.

| # | 확인 |
|---|---|
| E1 | 등급이 그대로다 |
| E2 | 근거 건수가 **늘지 않는다** — 읽을 때 현재 실행으로 거른다 |
| E3 | 해소된 Risk 가 없다 — 후보가 그대로 17 건이다 |
| E4 | `risk_events` 에는 옛 근거가 그대로 남아 있다 (원장은 지우지 않는다) |

E2 와 E4 는 함께 봐야 한다. **지운 것이 아니라 가린 것**이므로 둘 다 참이어야 맞다.

### F. 바뀐 것만 다시 도는가

픽스처의 `requirements.txt` 에서 `PyQt5` 한 줄을 지우고 push 한다.

| # | 확인 |
|---|---|
| F1 | webhook 이 들어오고 그 파일만 다시 분석된다 |
| F2 | `PyQt5` Risk 가 해소된다 — `COMPLETE` 이고 후보가 실제로 줄었다 |
| F3 | 다른 12 개 파일의 Risk 는 **건드려지지 않는다** |

F2 가 0-L 이다. 예전에는 파싱이 깨져 0 건이 된 것과 정말 지운 것이 구별되지 않아,
**멀쩡한 위험이 조용히 해소**됐다.

---

## 5. 관측

로그는 §13-10 의 허용 목록만 본다. Cloud Logging 에서:

```powershell
gcloud logging read 'resource.labels.service_name="ip-risk-agent-v2-worker" severity>=WARNING' --limit=50 --freshness=1h --format='value(timestamp,jsonPayload.event,jsonPayload.failure_category)'
```

원문·토큰·키는 로그에 없어야 한다. 있으면 그 자체가 불합격이다.

---

## 6. 되돌리기

| | |
|---|---|
| 직전 안정본 | API `00044-cmr` / Worker `00045-9wq` · digest `sha256:d239c5c1…` |
| 그 앞 | API `00043-frc` / Worker `00044-clm` · digest `sha256:acc50a21…` |

```powershell
gcloud run services update ip-risk-agent-v2-api --region=asia-northeast3 --image=<digest>
```

데이터는 되돌리지 않는다. 잘못 만들어진 것이 있으면 **workspace 를 지운다** —
`DELETE /api/v1/workspaces/{id}` 가 전체 말소이고, `scripts/purge_workspace.py` 가 같은
eraser 를 부른다. 0 단계의 목적이 "지우고 다시 하면 이번엔 맞다" 를 만드는 것이었다.

---

## 7. 이 시나리오가 확인하지 않는 것

정직하게 적어 둔다.

* **Drive 마운트** — 1-A 가 미구현이다 (서비스 계정 위임 권한 대기).
* **LOCAL** — 데스크톱 앱이 필요하다. 별도 시나리오.
* **특허 경로** — 일부러 뺐다. KIPRIS 한도 때문이다. 따로 열 때 한 번만 돈다.
* **주기적 재평가** (결함 24) — 촉발이 아직 없다. 2-F 캐시 뒤에 선다.
* **`.ipriskignore`** — 결함 25 로 매처가 셋이 다르다. 열기 전에는 시험 대상이 아니다.

---

## 8. 1 회차 결과 — 2026-08-23 05:05 UTC

픽스처가 아니라 `sample_github` 저장소로 돌았다. 판정은 UI 가 아니라 **저장된 기록**에서
읽었다 — UI 는 판정만 보여 주고 "온전히 읽었는가 · 어느 판본이 답했는가 · 근거가 이번
실행의 것인가" 는 기록에만 있다.

배포본 `dae2bfe` (API `00045-fmz` / Worker `00046-zxp`) 가 이 실행을 처리했다.

### 통과

| | 확인한 것 | 실측 |
|---|---|---|
| A1 | 경로 배정 | 10/10 정확. `.md` 둘은 특허로, 의존성 8 개는 라이선스로 |
| A3 | 온전히 읽었는가 | 라이선스 8 건 전부 `SUCCEEDED` + `COMPLETE`. `PARTIAL` 0 |
| 0-E | 못 한 것을 못 했다고 하는가 | `README.md` → `INCONCLUSIVE` · `NONE` · `ANALYSIS:NOT_APPLICABLE`. 권한이 없으므로 **아무 Risk 도 만들지 못한다** |
| 0-H | 판본 기록 | corpus `2026-08-23.4` 가 **검색을 시도한 세 파일에만** 있다 (`pyproject.toml`·`requirements.txt`·`setup.cfg`). 나머지 다섯은 `null` — 부르지 않았기 때문이다 |
| 결함 22 | 근거 수명 | `risk_evidence` 20 건 전부 현재 작업의 것. `risk_events` 16 건은 그대로 남아 원장이 끊기지 않았다 |
| 0-G | 주제 일치 | HIGH 세 건의 `LICENSE_REFERENCE` 가 `spdx-mpl-2.0` · `lgpl-2.1-obligations` · `agpl-3.0-obligations`. **오부착 0** |
| 0-K | 미해결 버전 | `ruff@unresolved` 이 요약·발췌·`metadata_safe.resolution=RANGE` **세 곳**에 "버전 미상" 을 남긴다 |
| 특허 | 끝에서 끝까지 | `SOURCE_EXCERPT` + `PATENT_CLAIM` (KIPRIS 출원번호 1020200110749) |

**RAG 는 HIGH 에만 붙었다.** MEDIUM 12 건은 `PACKAGE_METADATA` 하나뿐이다. 이것이 맞다 —
`needs_review` 가 거짓이면 검색하지 않고, 그래서 판본도 남지 않는다. 세 가지가 서로
어긋나지 않는다.

### §5.13 이 실물에서 확인됐다

같은 날 고친 것이 이 실행에 그대로 나타났다.

| 패키지 | 어제 | 오늘 | 왜 |
|---|---|---|---|
| `typing-extensions@4.12.2` | **UNKNOWN → 확인 필요** | PSF-2.0 → MEDIUM | `license` 도 `license_expression` 도 **비어 있고** deps.dev 는 non-standard 다. **분류자가 유일한 출처**였다 (결함 28) |
| `psycopg2@2.9.9` | `LGPL-2.1-only WITH exceptions` | `LGPL-2.1-only` | `exceptions` 는 등록된 예외가 아니라 완화도 못 받았다. 지어낸 예외를 뺐다 (결함 30) |

`typing-extensions` 는 파이썬에서 거의 모든 것이 전이 의존으로 끌고 오는 패키지다.
분류자를 읽기 시작한 것이 몇 시간 차이로 이 실행을 살렸다.

### 아직 확인하지 못한 것

| | 왜 |
|---|---|
| **`INDETERMINATE` 가 한 번도 안 나왔다** | 16 건 중 0 건. **네 번째 등급이 운영에서 한 번도 그려지지 않았다** — 목록·필터·정렬이 미검증이다 |
| §4 E (재분석) | 아직 안 돌렸다 |
| §4 F (바뀐 것만) | 아직 안 돌렸다 |
| 회귀 감시 3 줄 | `sample_github` 에 `matplotlib`·`pandas`·`weasyprint` 가 없다 |

**다음은 §1 의 픽스처다.** 그것이 위 네 칸을 정확히 겨냥해 만들어졌다 — `INDETERMINATE`
세 건과 회귀 감시 세 줄이 들어 있고, KIPRIS 를 쓰지 않는다.

> `sample_github` 에는 `README.md` 와 설계 문서가 있어 특허 경로가 돌았다. 한도를 아끼려면
> 픽스처 저장소에는 **의존성 파일만** 둔다.
