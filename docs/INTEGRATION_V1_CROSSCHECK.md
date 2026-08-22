# integration(v1) 수정 대조 기록

| | |
|---|---|
| 대조 기준 | `origin/integration` **4cf3cde** (2026-08-22) |
| 대조 대상 | `integration-v3` **78a6490** (2026-08-22) |
| 공통 조상 | `ee861b7` (Agent 2 인수인계) |
| 갈라진 뒤 커밋 | v1 48 개 / v3 86 개, 서로 반영 없음 |

## 이 문서가 있는 이유

두 브랜치는 같은 요구사항을 **각각 구현한 것**이지 한쪽이 다른 쪽의 후속이 아니다.

v1 은 먼저 굴러가면서 실제 문제를 만났다. 그쪽 수정 커밋의 본문에는 **운영에서
관측한 증상**이 적혀 있다 — "재실행 26 건이 실시간으로 전멸", "New 0 / Resolved
29 화면", "갇혔던 13 건". 추측이 아니라 실측이고, 같은 요구사항을 다르게 구현한
v3 에도 같은 함정이 있을 수 있다.

v3 에서 오늘 찾은 결함은 하나같이 **한 번도 실행된 적 없는 경로**에 있었고 시험은
전부 통과하고 있었다. v1 이 이미 밟아 본 자리를 v3 에서 다시 밟을 이유가 없다.

## 판정 기준

| 판정 | 뜻 |
|---|---|
| **잠재 문제** | v3 에 같은 결함이 있다고 볼 근거가 있다. 근거를 코드 위치로 적는다 |
| **이미 처리됨** | v3 도 같은 결론에 도달했거나 미리 막아 두었다 |
| **해당 없음** | v3 의 구조가 달라 그 문제가 성립하지 않는다 |
| **미검토** | 아직 대조하지 않았다 |

확인한 사실과 추측을 섞지 않는다. 코드를 열어 본 것만 확인으로 적는다.

---

## 요약

| 심각도 | 항목 | v1 커밋 |
|---|---|---|
| **높음** | 감시를 재개해도 Risk 가 되살아나지 않는다 | `c73505b` |
| **높음** | Drive 가 붙인 mime 만 믿어 텍스트 파일이 조용히 빠진다 | `d8df6f1` |
| 중간 | 좀비 실행을 화면에서 되살릴 수 없다 | `ef035c2` |
| 낮음(구조) | 게이트가 `/` 선행 경로를 그대로 내보낸다 | `08deba3` |

---

## 1. [높음] 감시를 재개해도 Risk 가 되살아나지 않는다

**v1 이 겪은 것** (`c73505b`) — 감시 중단이 Risk 를 RESOLVED 로 내리는 것까지는
됐는데 같은 대상을 다시 연결해도 돌아오지 않았다. 파일이 그대로면 변경 이벤트의
fingerprint 도 그대로라 재분석이 돌지 않고, 그러면 되살릴 계기가 없다. 재선택 뒤
**"New 0 / Resolved 29"** 화면이 실제로 그 상태였다.

**v3 의 해당 코드** — 같은 고리가 그대로 있다.

1. `workspace_admin/service.py:435` — mount 를 일시중지하면 `exclude_mount_risks`
   가 그 mount 의 Risk 를 RESOLVED + EXCLUDED 로 닫는다.
2. `public_facade/service.py:762-773` — 다시 연결하면 **같은 mount id** 가 DISABLED
   에서 ACTIVE 로 돌아온다. 새 mount 를 만들지 않는다. "계정 단위 정체성 때문에
   재연결은 같은 mount 로 수렴한다" 는 주석이 그렇게 적고 있다.
3. `connectors/common/fingerprint.py:53` — Drive fingerprint 는
   `(mount_id, file_id, resolved_revision)` 이다. mount id 도 파일도 그대로면
   **fingerprint 가 같다** → 중복으로 걸러져 분석이 돌지 않는다.
4. `risk_reconcile/service.py:304` — `should_revive` 는 **분석 결과를 수락하는
   경로에서만** 불린다. 분석이 돌지 않으면 발화하지 않는다.

`public_facade/service.py:773` 의 `reactivated_mount` 는 커밋 여부를 정할 뿐(819 행)
Risk 를 되살리지 않는다. `workspace_admin/service.py:434` 의 주석은 "다시 mount 되면
`should_revive` 가 되살린다" 고 적고 있으나, **파일이 변하지 않으면 그 계기가 없다.**

**판정: 잠재 문제.** 증상은 v1 과 같다 — 감시를 재개했는데 Risk 목록이 비어 있다.

**확인 방법** — Drive mount 를 일시중지하고(Risk 가 EXCLUDED 로 닫히는 것 확인)
파일을 **바꾸지 않은 채** 같은 소스를 다시 연결한 뒤 Risk 목록을 본다.

**참고** — v1 은 mount 재생성 시점에 "감시 중단으로 해소된 것" 만 골라 직접
되살리는 방식으로 고쳤다. v3 는 되살릴 때 NEW/UNREVIEWED 로 되돌리는 정책이므로
(`docs/RISK_DISPOSITION_POLICY.md`) 판정 부분은 그대로 두고 **계기만** 만들면 된다.

## 2. [높음] Drive 가 붙인 mime 만 믿어 텍스트 파일이 조용히 빠진다

**v1 이 겪은 것** (`d8df6f1`) — Drive 는 업로드 파일의 mime 을 신뢰할 수 있게 붙여
주지 않는다. `.md` 가 `application/octet-stream` 으로 오는 일이 흔하다. mime 목록만
믿은 결과 운영에서 `text/plain`(requirements.txt)과 `application/json`(package.json)
만 통과했고 **기획서 `.md` 는 전부 미지원으로 조용히 빠졌다.** 특허 분석기는 그
텍스트를 받아본 적이 없었다.

**v3 의 해당 코드** — 더 좁다. 두 겹으로 걸러진다.

* `connectors/google_drive/models.py:17` — `SELECTABLE_MIME_TYPES` 는
  Google Doc / `text/plain` / `text/markdown` / `application/json` **네 개뿐**이다.
  `adapter.py:186` 이 여기 없는 mime 을 `ContentScope.UNSUPPORTED` 로 떨군다.
* `security_gate/service.py:508-553` — 게이트도 mime 만 본다. 확장자는 보지 않는다.
  `application/octet-stream` 은 어느 허용 목록에도 없어 거부된다.

즉 Drive 가 `.md` 에 `application/octet-stream` 을 붙이면 v3 도 같은 자리에서
빠진다. 오늘 `.md` 검사가 성공한 것은 Drive 가 그 파일들에 `text/markdown` 을 붙여
주었기 때문이지, v3 가 확장자를 보기 때문이 아니다.

`text/x-python`, `text/csv`, `application/toml`, `text/yaml` 같은 흔한 텍스트 형식도
`SELECTABLE_MIME_TYPES` 에 없어 같은 취급을 받는다.

**판정: 잠재 문제.** 사용자가 고른 파일이 이유 없이 빠지는 것처럼 보인다.

**확인 방법** — `.md` 파일을 Drive API 나 mime 을 명시하지 않는 도구로 올려
`application/octet-stream` 으로 등록시킨 뒤 마운트한다. 또는 `.py` 파일을 올려 본다.

**참고** — v1 은 "mime 이 텍스트이거나 **확장자가 텍스트 계열이면** 읽고, 내용이
실제 바이너리면 UTF-8 디코드 실패를 정직한 미지원으로 처리" 하는 방식으로 고쳤다.
v3 는 허용 목록이 어댑터와 게이트 두 곳에 나뉘어 있어, 고칠 때 **두 곳을 함께**
봐야 한다.

## 3. [중간] 좀비 실행을 화면에서 되살릴 수 없다

**v1 이 겪은 것** (`ef035c2`) — 분석기가 죽으면 이벤트가 PROCESSING 에 갇히고 큐
재시도·폴더 재선택·재실행 버튼 어디에도 걸리지 않았다. **"실패한 분석이 없습니다"
가 뜨는데 특허 분석은 영영 돌지 않는** 상태가 됐다.

**v3 의 해당 코드** — 절반은 이미 막혀 있고 절반은 열려 있다.

* 막힌 쪽 — `composition/pipeline.py:213` 의 catch-all 이 분석기 예외를 FAILED 로
  남긴다. `analysis_jobs/service.py:101-115` 는 PROCESSING + RUNNING 이라도
  **lease 가 만료됐으면 회수**한다. 그래서 큐가 다시 두드리는 한 좀비는 풀린다.
* 열린 쪽 — 큐 재시도가 소진된 뒤에는 두드릴 것이 없다. 그때 화면의 "다시 검사" 는
  `analysis_jobs/transitions.py:48` 의 `reanalyze_analysis_job` 이
  `status in {QUEUED, RUNNING}` 을 **lease 만료 여부와 무관하게** 거부한다
  ("analysis is already in flight"). 좀비는 RUNNING 이므로 **사람이 손으로 풀 수
  없다.**

**판정: 잠재 문제(중간).** 자동 회수가 있어 v1 만큼 자주 나오지는 않으나, 재시도가
소진된 좀비는 v1 과 똑같이 갇힌다.

**확인 방법** — 코드 검토로 충분하다. 운영에서 재현하려면 분석 도중 워커 인스턴스를
죽이고 Cloud Tasks 재시도(20 회)를 소진시켜야 해서 비용이 크다.

**참고** — v1 은 "15 분 넘게 PROCESSING 인 이벤트는 워커 사망으로 보고 FAILED 로
내린 뒤 같은 재큐잉 경로에 태운다" 로 고쳤다. v3 는 이미 lease 를 들고 있으므로
재실행 경로에서 **lease 만료를 확인해 회수를 허용**하면 된다.

## 4. [낮음·구조] 게이트가 `/` 선행 경로를 그대로 내보낸다

**v1 이 겪은 것** (`08deba3`) — 게이트가 ignore 매칭을 위해 경로를 `/` 선행
canonical 로 정규화하는데 그 값이 그대로 `AnalysisArtifact.logical_path` 로 나갔다.
특허 분석기가 그것을 근거의 reference 로 쓰고, 보존 검증이 선행 `/` 를 로컬
절대경로로 보고 거부했다. **특허 대조가 끝까지 성공한 결과 전부가 수락 단계에서
죽었다** — "라이선스만 잡히는" 증상이 됐다.

**v3 의 해당 코드** — 같은 모양이지만 소비자 쪽에서 막고 있다.

* `security_gate/service.py:245,302` — 게이트는 v1 과 똑같이 `/` 선행 경로를
  `logical_path` 로 내보낸다.
* `intelligence/patent/analyzer.py:222` — 특허 분석기는 `source_reference()` 로
  선행 `/` 를 떼고 나서 reference 에 쓴다. 그래서 지금은 통과한다. 오늘 저장된
  근거의 reference 가 `Google Drive .../voice-phishing-detection-design.md` 로
  정상인 것을 확인했다.
* License 분석기는 경로를 reference 로 쓰지 않는다 — `fact.source`(패키지 메타데이터
  URL)를 쓴다. v1 이 "라이선스만 살아남았다" 고 한 것과 같은 이유다.

**판정: 증상은 이미 처리됨, 구조는 잠재 문제.** 지금 터지지는 않는다. 다만 v3 는
**소비자 한 곳**에서 막고 v1 은 **생산자**에서 막았다. `logical_path` 를 보존 필드에
쓰는 코드가 새로 생기면 v3 는 같은 함정을 다시 밟는다 — `sanitize_reference` 는
`retention.py:64` 에서 선행 `/` 를 거부한다.

**참고** — 고친다면 게이트가 상대 경로를 내보내고 ignore 매칭에서만 `/` 를 붙이는
쪽이 낫다. 다만 `_logical_path_from_hint`(`service.py:489`)와 근거 reference 형식이
함께 바뀌므로 **이미 저장된 근거와의 정합성**을 먼저 확인해야 한다.

---

## 이미 처리됨 / 해당 없음

| v1 커밋 | v1 이 고친 것 | v3 |
|---|---|---|
| `27f88da` | 미결(INCONCLUSIVE) 작업 재큐잉이 409 로 죽음 | **이미 처리됨** — v3 도 같은 벽을 만나 `c91d5c2` 로 고쳤다. 규칙("이전이 QUEUED 가 아니면 새 attempt")이 in-memory·Firestore 양쪽에 동일하다. v1 커밋 본문도 v3 를 언급한다 |
| `0284cc3` | 프롬프트 `.md` 가 wheel 에서 빠져 배포에서만 FileNotFoundError | **이미 처리됨** — `pyproject.toml:46` 에 package-data 로 선언돼 있고 주석이 같은 사고를 적고 있다. 비코드 자원은 프롬프트뿐이다 |
| `a430abb` | Cloud Tasks 작업 이름 tombstone 으로 재시도가 사라짐 | **이미 처리됨** — `gcp/cloud_tasks.py` 가 이름을 붙이지 않으며 같은 이유가 주석에 있다 |
| `9161721` | `index.html` 캐시로 흰 화면 / 옛 코드 | **이미 처리됨** — `composition/frontend_hosting.py:22` 가 `Cache-Control: no-cache` 를 붙인다 |
| `ef035c2` (전반) | 분석기 예외가 FAILED 로 남지 않음 | **이미 처리됨** — `pipeline.py:213` catch-all. 후반부(좀비 회수)는 위 3 번 |
| `9df5952` | 해소 이벤트 id 가 mount 기준이라 재제거 시 409 | **해당 없음** — v3 는 `risk_exclusion.py:96` 에서 `id_factory` 로 생성한 id 를 쓴다. 회차마다 다르다 |

## 미검토

아직 대조하지 않았다. 위 항목들과 성격이 비슷해 훑을 값이 있다.

**먼저 볼 것**

* `1a205f8` provider 재연결을 자격증명 회전으로 다룸 — v3 의 재연결 경로
  (`public_facade/service.py:745-773`)와 맞대 볼 것. 1 번 항목과 같은 자리다
* `c79ec5c` 워커가 컨테이너의 provider 어댑터를 물려받도록 — v3 의 worker 조립
* `f50a15b` / `ea70787` / `96be197` Drive 폴더 전체를 걷는 범위 — v3 는 파일 단위
  선택이라 구조가 다를 수 있다
* `b58b5f1` 폴더 경로를 artifact 이름에 반영 — 4 번 항목과 같은 자리를 건드린다

**낮음**

* UI 커밋(`b371683`, `b5d7d74`, `8e16423`, `e3f5b89`, `5e85440`)은 코드 대조 대신
  **선택의 이유**를 6 절에 정리했다. v3 는 UI 대개편이 예정돼 있어 구현을 맞대는
  것보다 그쪽이 값이 크다
* 배포 스캐폴딩(`37e8204`, `3dd8e0e`, `fa933a5`, `60fd468`, `8c8cf63`, `3dcfc4e`,
  `e6f2fd2`) — v3 는 배포 구성이 별개이고 이미 굴러가고 있다
* OAuth·연결 UX(`e3f5b89`, `3439f2b`, `1c749c1`, `f78aa12`, `f01dbb7`, `8a059ba`,
  `eb6a3d9`, `e743280`, `5a003a8`, `e062415`) — v3 의 Drive 연결은 실측으로 동작을
  확인했다

## 다음에 이어서 할 때

`origin/integration` 을 다시 fetch 해 **4cf3cde 이후** 커밋만 보면 된다.

```
git fetch origin integration
git log --oneline --reverse 4cf3cde..origin/integration
```

이 문서 맨 위의 기준 커밋을 그때 갱신한다.

---

## 5. GitHub / Local / Desktop 을 구현할 때

### 먼저 알아야 할 것 — v1 에 가져다 쓸 코드는 거의 없다

세 영역의 코드는 **공통 조상에서 온 같은 것**이고, 갈라진 뒤 v1 의 48 커밋은
Drive·분석·UI 에 집중됐다. 파일 수는 같고(github 15, local 6, drive 12), 내용을
맞대면 **v3 쪽이 더 앞서 있다.**

| 경로 | v1 이 더 가진 줄 | v3 가 더 가진 줄 |
|---|---|---|
| `connectors/github` | 40 | 171 |
| `connectors/local` | 17 | 24 |
| `connectors/common` | 6 | 234 |
| `apps/desktop` | 128 | 681 |

**v1 의 그 코드를 그대로 참고하면 오히려 퇴행한다.** 확인한 것만 적는다.

* `install_routes.py` / `mounts_routes.py` / `local/routes.py` 의 인가 기본값이
  `allow_all_authz` 다. v3 는 `deny_all_authz` 다 — 라우터를 조립하며 인가를
  넘겨주는 것을 잊어도 v3 는 막히고 v1 은 열린다.
* 어댑터가 본문을 `TextSegment(segment_id="full")` 한 조각으로 넘긴다. v3 는
  `connectors/common/segmentation.py` 의 `split_document` 로 나눈다 — 근거의 줄
  범위와 인용 구간이 여기서 나온다.
* `_MANIFEST_NAMES` 가 커넥터마다 중복 정의돼 있다. v3 는 방금
  `core/artifacts/dependency_files.py` 한 곳으로 합쳤다(`78a6490`).

### 그래도 옮겨 붙는 것 — Drive 에서 치른 대가

v1 이 Drive 로 겪은 것 중 **소스 종류와 무관한** 것들이다. GitHub·Local 에서 같은
자리를 밟게 된다.

**1. 마운트 순간의 초기 스캔 비용** (`96be197`, `ea70787`)

v1 은 "마운트 시점에 이미 있던 파일도 분석한다" 를 기능으로 넣었다. 연결만 하고
아무 일도 일어나지 않으면 쓸모가 없기 때문이다. 그런데 그 순간 **파일 수만큼 분석이
한꺼번에 뜬다.**

v3 의 GitHub 은 이미 그렇게 되어 있다 — `github/adapter.py:166` 의
`initial_changes` 가 브랜치의 추적 대상 파일 전부에 변경 이벤트를 하나씩 만든다.
파일당 Gemini 추출 1 회 + KIPRIS 검색 최대 5 회 + 상세 최대 6 회다. 저장소 하나를
마운트하면 **KIPRIS 월 한도(1,000)를 한 번에 넘길 수 있다.**

거를 수단은 세 가지이고 현재 상태는 이렇다.

| 수단 | 어디서 걸리나 | 현재 |
|---|---|---|
| 저장소의 `.ipriskignore` | 변경 이벤트가 **아예 안 생긴다** | 테스트 저장소에 없음 |
| workspace `global_ignore_text` | 관문이 막아 provider 호출 없음(이벤트·조회는 발생) | 빈 문자열 |
| `include_patterns` / `exclude_patterns` | 스코프 단계 | API 는 받는데 **프론트가 항상 빈 배열을 보낸다** (`sources/api/connectionClient.ts:179`) |

**저장소를 붙이기 전에 셋 중 하나는 채워야 한다.**

**2. fingerprint 에 mount 를 넣는다** (v3 가 이미 겪음)

`connectors/common/fingerprint.py:53` 의 주석이 v3 의 사고를 적고 있다 — mount 를
빼면 같은 파일을 다른 workspace 에 연결할 수 없었다(422). GitHub 의
`github_change_fingerprint` 도 `mount_id` 를 포함한다. 새 소스를 붙일 때 이 규칙을
빠뜨리지 말 것.

단 그 대가가 1 번 항목이다 — mount 가 같으면 fingerprint 도 같아서 **재연결이
재분석을 부르지 않는다.**

**3. Connection 과 Mount 는 다르다** (`e3f5b89`)

OAuth / App 설치가 끝나면 Connection 만 생기고 **아직 아무것도 감시하지 않는다.**
v1 은 그 다음 단계 화면이 없어서 "연결에 성공했는데 아무 일도 일어나지 않는" 상태를
만들었다. GitHub 은 설치 → 저장소 선택 → mount 생성이 별개 단계라 이 함정이 더 크다.

v1 의 선택 — 목록은 **Control 이 canonical** 이다. Source Plane 응답을 그대로 믿으면
provider 상태와 Control 기록이 갈릴 때 거짓을 보여준다.

**4. 콜백은 브라우저를 앱으로 돌려보내야 한다**

provider 가 브라우저를 콜백으로 보낸다. JSON 을 그대로 반환하면 사용자가 원시 응답
화면에 갇힌다. **v3 는 이미 처리돼 있다** — `install_routes.py:80` 의
`completion_redirect` 가 `production.py:267,301` 에서 배선된다.

**5. state 가 만료됐을 때 무엇을 하라고 말해야 한다** (`3439f2b`)

state 는 일회용이고 수명이 짧다. 승인 화면을 오래 붙들거나 **뒤로가기로 옛 URL 을
다시 열면** 콜백이 그 경로로 온다.

v3 는 GitHub·Drive 양쪽 다 `"invalid or expired oauth state"` 만 돌려준다
(`install_routes.py:69`, `oauth_routes.py:80`). 무엇을 다시 해야 하는지 알 수 없어
사용자가 같은 실패를 반복한다. v1 은 원인과 다음 행동을 함께 적었다.

GitHub 연결을 실제로 눌러 보면 바로 만나는 자리다. **고칠 값이 크고 비용이 작다.**

**6. 큐 재시도 창** (`5e85440`)

v1 은 5 회(~2.5 분)에서 **20 회(~2 시간)** 로 넓혔다. 이유 — 배포로 고치는 유형의
장애에서, 수정이 배포되기 전에 일감이 전부 폐기되는 창이었다. v3 의 큐 설정을 같은
눈으로 볼 것.

**7. 감시 중인 파일을 보여 줄 길** (`b371683`)

추적 스코프는 Integration 소유라 Control API 로는 보이지 않는다. 폴더/저장소를
연결한 뒤 **무엇이 인식됐는지 확인할 방법이 없었다.** v1 은 경로와 개수만 여는
라우트를 냈다. GitHub 은 파일 단위가 아니므로 "저장소@브랜치 전체" 서술을 돌려준다 —
소스마다 표현이 다르다는 것을 인정한 설계다.

### Local / Desktop

v1 에 참고할 것이 **없다.** v3 가 앞서 있다(`apps/desktop` 기준 v3 전용 681 줄).
v3 의 desktop 은 경로 가드, chokidar 워처, `.ipriskignore`, 기기 자격증명 암호화,
이벤트 큐 재시도를 갖추고 있고 시험 70 건이 통과한다. 렌더러는 배포된 웹 앱
(`{서버}/app`)을 그대로 띄우므로 UI 개편이 desktop 에도 그대로 반영된다.

주의할 것은 v1 이 남긴 한 줄이다 — staging 삭제는 best-effort 이고 **TTL 이 진짜
안전망**이라는 것(Agent 2 Spec 30/32). v3 도 같은 구조인지 확인할 것.

---

## 6. UI — v1 이 고민하고 고른 것

v3 는 UI 대개편이 예정돼 있다. v1 이 화면을 만들며 **왜 그렇게 골랐는지**를 남긴
것들이다. 결론만이 아니라 이유를 함께 적는다.

### 대조가 화면의 주인공이다

**좌우 대조** (`8e16423`) — 왼쪽에 검사 문서, 오른쪽에 선행 특허문/라이선스 근거.
한 줄로 섞어 나열하면 "무엇과 무엇을 비교한 것인지" 를 **독자가 재구성해야 한다.**

**검토 패널을 접는다** (`b5d7d74`) — Reviewer decision 사이드 패널이 대조의 폭을
절반으로 줄이고 있었다. 기본으로 접고 상단 버튼으로 연다. 접힌 상태에서 대조가 전체
폭을 쓴다.

v3 는 지금 근거를 한 줄로 나열한다. 대개편에서 가장 먼저 볼 항목이다.

### 하이라이트는 배경 칩이 아니라 굵은 색 글자

`b5d7d74` 가 뒤집은 결정이다. 배경 칩은 **본문 흐름을 끊고**, LOW 등급을 회색으로
칠하면 **아예 보이지 않는다** — "특허 대조가 안 보인다" 는 피드백을 받았다.

선택: HIGH 빨강, 그 외 주황. 굵은 글자.

v3 는 `<mark className="evidence-quote">` 로 배경 칩을 쓴다
(`frontend/src/risk/evidence-highlight.tsx`). v1 이 그 길을 가 보고 되돌아왔다는 것을
알고 고를 것.

**v3 가 앞선 부분** — v1 은 정밀한 문장 대응을 "대조 근거에 인용 위치가 실려야
하므로 후속(v3 의 span 검증 이식)" 으로 남겼다. v3 는 이미 갖고 있다. 근거 38 건 중
37 건에 `quote_start`/`quote_end` 가, 소스 발췌 19 건에 `line_start`/`line_end` 가
저장돼 있고, 지어낸 인용은 대조 전체를 폐기해 화면까지 오지 않는다.

### 침묵은 고장으로 읽힌다

**진행 바** (`8e16423`) — 특허 한 건이 수십 초다. 아무 표시가 없으면 사용자는
고장으로 읽는다. v1 은 `/analyses/progress` 집계와 진행 바를 넣고 **검토가 남아
있는 동안 5 초 폴링**한다.

v3 는 실측에서 분석이 1~2 분 걸렸고, 오늘 45 초 debounce 를 넣어 감지에서 분석까지가
더 늘었다. 진행 표시 없이는 그 시간이 전부 침묵이다.

### 해소된 것을 기본으로 보여 주지 않는다

`45c1d8c` — Risks 화면의 lifecycle 기본 필터를 **Active(NEW+EXISTING)** 로 바꿨다.
해소된 위험이 기본으로 보이면 "중단했는데 계속 남아 있다" 로 읽힌다. All 을 고르면
여전히 전부 볼 수 있다.

v3 는 오늘 EXCLUDED 를 기본 목록에서 접었다. 같은 감각이고, 나머지 RESOLVED 도 같은
기준으로 볼 것.

### 실패는 손잡이가 있어야 한다

`5e85440` — 큐 재시도가 소진되면 작업은 폐기되지만 이벤트는 FAILED 로 남고 원본
SourceChange 는 relay 에 7 일 보관된다. **되살릴 재료는 다 있는데 묶는 손잡이가
없어서**, 폴더 재선택이라는 우회로로 같은 fingerprint 를 재주입해야 했다.

v1 이 고른 세 가지가 그대로 참고가 된다.

* 여러 번 눌러도 안전하게 — 성공분(DONE)은 건너뛴다
* relay 보존이 지난 실패는 **숨기지 않고 개수로 알린다.** 조용히 빼면 "전부 다시
  돌렸다" 로 읽힌다
* 이후는 기존 재큐잉 경로가 처리한다 — 화면은 재료를 잇기만 한다

v3 의 3 번 항목(좀비를 손으로 풀 수 없음)이 정확히 이 자리다.

### 실패 문구가 원인을 오진하면 엉뚱한 곳을 의심한다

`9df5952` — 409 를 화면이 "OWNER 인지 확인하라" 로 오진했다. 사용자가 권한 문제를
의심하며 시간을 썼다. v1 의 결론 — OWNER 안내는 **실제 권한 거부(403)일 때만**.

v3 도 오늘 같은 종류를 겪었다. `INCONCLUSIVE` 를 "분석에 실패했습니다" 로 보여
주면서 영어 원문(`one or more requested analyses were non-authoritative`)을 실패
코드 자리에 노출했다. 미판정은 실패가 아니고, 그렇게 보여 주면 **이미 확인된 Risk
까지 믿을 수 없는 것처럼 읽힌다.**

### 이름은 바꿀 수 있어야 하고, 무엇을 바꾸는지 말해야 한다

`8e16423` — Mount 표시 이름 변경. 백엔드의 alias PATCH 는 있었는데 화면이 없었다.
그리고 **실제 폴더/저장소 이름은 건드리지 않는다는 것을 대화에 명시한다.**

### 이미 연결돼 있으면 다시 연결하게 하지 않는다

`8e16423` — 살아 있는 연결이 있으면 OAuth 를 다시 타지 않고 폴더 선택으로 바로
간다. 연결 목록 라우트가 그 구분을 가능하게 한다.

GitHub 도 같다 — App 이 이미 설치돼 있으면(현재 `2HyN` 계정에 installation
155365447 이 있다) 저장소 선택만 하면 된다.
