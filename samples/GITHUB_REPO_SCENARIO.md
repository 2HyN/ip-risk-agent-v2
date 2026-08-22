# GitHub 연결 확인용 저장소 — 구성과 기대값

`samples/github-repo/` 의 내용을 **새 저장소에 그대로 올려** GitHub 경로를
확인한다. 이 문서는 저장소에 넣지 않는다 — 기술 문서라 Patent 분석 대상이 되어
KIPRIS 를 더 쓴다.

## 왜 새 저장소인가

저장소를 마운트하면 **브랜치의 추적 대상 파일 전부**에 대해 변경 이벤트가 하나씩
생기고, 문서와 소스 코드는 각각 Patent 분석을 받는다. 파일 하나당 KIPRIS 검색
최대 5 회 + 상세조회 최대 6 회다.

`ip-risk-agent` 같은 실제 저장소를 붙이면 파일 수백 개 × 약 11 회로 **월 1,000 회
한도를 한 번의 마운트로 넘긴다.** 그래서 소모량이 예측 가능한 작은 저장소를 따로
만든다.

## 올리는 것

```
README.md                                 비기술 문서
docs/battery-thermal-runaway-design.md    기술 기획서  ← KIPRIS 를 쓰는 유일한 파일
requirements.txt                          pip 매니페스트
requirements-dev.txt                      pip 매니페스트 (접두 일치)
pyproject.toml                            PEP 621
setup.cfg                                 setuptools 선언
package.json                              npm 매니페스트
package-lock.json                         npm 잠금
uv.lock                                   uv 잠금
poetry.lock                               poetry 잠금
.ipriskignore                             거부 목록
vendor/requirements.txt                   **분석되면 안 되는 파일**
```

읽을 수 있는 의존성 형식 일곱 가지를 하나씩 덮는다. 파일마다 패키지를 다르게 둔
이유는, Risk 가 (artifact, 생태계, 패키지) 로 구분되므로 **어느 파일이 어느 Risk 를
만들었는지 이름만 보고 알 수 있게** 하기 위해서다.

## 기대값

| 파일 | 가는 분석기 | KIPRIS | 기대 |
|---|---|---|---|
| `docs/battery-thermal-runaway-design.md` | Patent | **약 11 회** | 후보 대조 후 Risk 생성 |
| `README.md` | Patent | **0 회** | `is_technical=false` → **SKIPPED**, Risk 0 |
| 의존성 파일 8 개 | License | **0 회** | 선언 14 건에서 Risk 생성 |
| `.ipriskignore` | — | 0 회 | 무시 목록에 자기 자신이 있다 |
| `vendor/requirements.txt` | — | 0 회 | **변경 이벤트조차 생기지 않아야 한다** |

KIPRIS 총 소모는 **약 11 회**다. 저장소 전체를 붙였을 때와 비교하면 이것이 작은
저장소를 따로 만드는 이유다.

### License 등급이 갈리는 것

앞선 실측에서 확인된 조합을 각 파일에 하나씩 심었다.

| 파일 | 패키지 | 기대 등급 |
|---|---|---|
| `requirements.txt` | `pymupdf` (AGPL-3.0-only) | **HIGH** — 결합 저작물의 소스 공개를 요구 |
| `pyproject.toml` | `certifi` (MPL-2.0) | **HIGH** — 결합 방식에 따라 의무가 달라짐 |
| `setup.cfg` | `psycopg2` (LGPL-2.1) | **HIGH** — 정적 링크 여부가 갈림 |
| 나머지 | MIT · Apache-2.0 · BSD | MEDIUM — 고지와 사본 첨부로 충족 |

`requirements-dev.txt` 의 `ruff>=0.6.0` 은 확정 버전이 아니므로
`VERSION_RANGE_NOT_PINNED` 진단이 붙는다. 조회 자체는 성공하므로 coverage 는
`COMPLETE` 를 유지하고, 그래서 같은 파일의 다른 Risk 가 함께 막히지 않는다.

**존재하지 않는 패키지는 한 줄도 넣지 않았다.** 조회 실패 하나가 그 파일의
coverage 를 `PARTIAL` 로 떨어뜨리고, 그러면 `analysis_is_authoritative()` 가
거짓이 되어 **그 파일의 Risk 가 하나도 생기지 않는다.** 실패를 "위험 없음" 으로
바꾸지 않는 동작이며, 그것을 확인하려면 별도 저장소에서 따로 돌린다.

## `.ipriskignore` 로 확인하는 것

문법은 fnmatch 글롭 **거부 목록**이다. gitignore 와 달리 `!` 부정 패턴과 디렉터리
전용 슬래시를 지원하지 않는다 (`connectors/common/ipriskignore.py` 에 의도된
단순화로 기록되어 있다). 따라서 **"이것만 보라" 는 쓸 수 없고 "이건 보지 마라" 만
쓸 수 있다.**

`vendor/requirements.txt` 는 그 규칙이 실제로 동작하는지 보는 파일이다. 다른
샘플과 겹치지 않는 `flask` 를 담았으므로, `flask` Risk 가 보이면 무시 규칙이
GitHub 마운트에서 동작하지 않는 것이고 그 자체가 결함이다.

## 순서

1. 새 저장소를 만들고 `samples/github-repo/` 의 내용을 **루트에** 올린다
   (`.ipriskignore` 를 빠뜨리지 않는다 — 숨김 파일이라 놓치기 쉽다)
2. 앱에서 GitHub 소스를 추가한다. GitHub 설치 화면이 뜨면 **이 저장소만** 선택한다
3. 첫 분석 결과를 확인한다 — 위 표와 맞는지, `flask` 가 보이지 않는지
4. 파일 하나를 고쳐 push 하고 **변경 감지가 도는지** 확인한다

4 번이 GitHub 경로에서 가장 확인이 덜 된 부분이다. Drive 는 폴링과 webhook 이
모두 있지만 GitHub 은 **push webhook 하나에만 의존한다** — 예약 작업에 GitHub
조정(reconciliation)이 없다. webhook 이 오지 않으면 변경은 영영 감지되지 않는다.
