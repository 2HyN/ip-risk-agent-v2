# GitHub · Local · Desktop 마무리 계획

이 문서는 **기록과 계획만** 담는다. 코드는 바꾸지 않으므로 빌드·배포와 무관하게
읽고 갱신할 수 있다.

두 갈래에서 왔다.

* `sample_github` 마운트 실측에서 확인된 결함 하나
* `docs/INTEGRATION_V1_CROSSCHECK.md` — 다른 개발자가 v1 과 대조해 남긴 기록.
  v1 은 먼저 굴러가며 **운영에서 실제로 관측한 증상**을 커밋에 적어 두었다

순수한 화면 문제는 UI 대개편으로 미룬다. **기능 자체가 막히는 것만** 여기 담는다 —
GitHub 저장소를 하나밖에 붙일 수 없었던 것이 화면 문제처럼 보였지만 실은 기능이
막힌 것이었던 일이 있었다.

---

## 1. 확인된 결함 — 하위 폴더의 파일이 게이트에서 거부된다

### 증상

`sample_github` 마운트에서 파일 12 개 중 **`docs/battery-thermal-runaway-design.md`
하나만** 실패했다.

```
Change: FAILED · Analysis: FAILED
실패 코드: SECURITY_GATE:CANONICAL_CONTEXT_MISMATCH
```

나머지는 모두 정상이었다. 실패한 것은 **저장소 루트가 아닌 유일한 파일**이다.

### 원인

GitHub 어댑터가 같은 값을 두 자리에서 **다르게** 만든다.

| 자리 | 코드 | `docs/battery-...md` 의 값 |
|---|---|---|
| 변경 등록 | `github/adapter.py:220`<br>`display_name=file.path.rsplit("/", 1)[-1]` | `battery-thermal-runaway-design.md` |
| 스냅샷 | `github/adapter.py:155`<br>`display_name=identity.path` | `docs/battery-thermal-runaway-design.md` |

게이트는 둘이 같아야 한다고 본다 (`security_gate/service.py:444`).

```python
if (... or snapshot.display_name != artifact.display_name):
    return SecurityGateDenialReason.CANONICAL_CONTEXT_MISMATCH
```

**루트 파일은 파일 이름과 경로가 같아서 우연히 통과한다.** 하위 폴더가 생기는
순간 갈라진다. 저장된 artifact 를 확인한 결과도 같다 — `display_name` 은 전부
파일 이름이고 `logical_path` 만 폴더를 포함한다.

```
display_name                           logical_path
battery-thermal-runaway-design.md      sample_github/docs/battery-thermal-runaway-design.md
requirements.txt                       sample_github/requirements.txt
```

`logical_path_hint` 쪽은 문제가 없다. 양쪽 다 `file.path` 를 쓰므로
`_logical_path_from_hint` 가 같은 값을 만든다. **어긋나는 것은 `display_name` 뿐이다.**

### 고칠 자리

스냅샷의 `display_name` 을 **파일 이름**으로 맞춘다. 등록 쪽이 아니라 스냅샷 쪽을
바꾸는 이유는 두 가지다.

* `display_name` 은 사람에게 보여 줄 이름이다. 목록에 폴더 경로가 통째로 들어가면
  읽기 나쁘다. 경로는 `logical_path` 가 이미 들고 있다.
* 이미 저장된 artifact 들이 파일 이름을 쓰고 있다. 등록 쪽을 바꾸면 **기존 artifact
  와 어긋나** 지금 성공하는 파일들까지 같은 이유로 실패한다.

같이 볼 것 — `local/adapter.py` 도 하위 폴더를 다루므로 같은 짝이 맞는지 확인한다.

### 회귀 시험

지금 이 결함을 잡는 시험이 없다. 저장소 루트만 쓰는 시험만 있어서 통과했다.
**하위 폴더에 있는 파일**로 등록 → 스냅샷 → 게이트를 태우는 시험을 넣는다.

`sample_github` 이 이미 그 형태다 — `docs/` 하나, 루트 여럿.

---

## 2. GitHub 경로 실측 결과

저장소 셋을 붙이고 push 까지 태워 확인한 것이다.

**push 변경 감지가 동작한다.** `sample_github_deps` 에 의존성 한 줄을 더해 push 한
결과다.

| 시각(UTC) | 일 |
|---|---|
| 12:37:23 | push |
| 12:37:24 | webhook 수신, 200 |
| 12:38:12 | 분석 점유 — 45 초 coalesce 지연 뒤 |

새 줄이 그대로 Risk 가 됐다(`pypi:python-dateutil@2.9.0`). GitHub 은 push webhook
하나에만 의존하는데(예약 조정 작업이 없다) 그 하나가 동작한다.

**저장소별 Risk 수와 무시 규칙**

| 저장소 | Risk | 기대와 |
|---|---|---|
| `sample_github` | 18 | 맞음 |
| `sample_github_deps` | 4 | 맞음 (3 + push 로 더한 1) |
| `sample_github_quiet` | **0** | 맞음 — Risk 가 없어야 하는 저장소다 |

**`.ipriskignore` 가 저장소마다 따로 동작한다.** 새어 나오면 보이도록 심어 둔
`flask`(sample_github)와 `bottle`(sample_github_quiet)이 **둘 다 나타나지 않았다.**

**하위 폴더 파일도 통과한다.** 1 절의 수정 뒤 `docs/battery-thermal-runaway-design.md`
가 재검사에서 통과했다.

그 밖에 확인된 것.

* **`.ipriskignore` 가 GitHub 마운트에서 동작한다.** 파일 12 개 중 artifact 는
  10 개다. `.ipriskignore` 와 `vendor/requirements.txt` 는 변경 이벤트조차 생기지
  않았다. 새어 나오면 보이도록 심어 둔 `flask` 는 나타나지 않았다.
* **의존성 형식 판정이 맞다.** 오늘 한 곳으로 합친 표(`78a6490`)대로 `setup.cfg`,
  `requirements-dev.txt`, 잠금 파일 세 종이 모두 License 로 갔다.
* **마운트 별칭이 저장소 이름이다.** Drive 에서 터졌던 별칭 충돌이 GitHub 에는
  없다.

---

## 3. v1 이 이미 밟은 자리

`docs/INTEGRATION_V1_CROSSCHECK.md` 에서 **기능이 막히는 것**만 추렸다. 판정과 근거는
그 문서에 있으므로 여기서는 **GitHub·Local·Desktop 에 무엇을 뜻하는지**만 적는다.

### 3-1. [높음] 감시를 재개해도 Risk 가 되살아나지 않는다

변경 fingerprint 에 `mount_id` 가 들어 있고 재연결은 **같은 mount** 로 수렴한다.
파일이 그대로면 fingerprint 도 그대로라 재분석이 돌지 않고, `should_revive` 는
분석 결과를 수락하는 경로에서만 불린다. **되살릴 계기가 없다.**

GitHub 도 `github_change_fingerprint` 가 `mount_id` 를 포함하므로 같은 구조다.
Local 도 확인할 것.

판정 정책이 정해져 있기는 하다(`docs/RISK_DISPOSITION_POLICY.md` — 되살릴 때
NEW/UNREVIEWED 로 되돌린다). 다만 `docs/DEVELOPMENT_SPEC.md` §7.1 이 그 규칙을 **개정
중**이다 — 방아쇠가 수동 해제에서 삭제·폴더 이탈로 넓어지면 흔한 파일 이동이 사용자의
처분을 지우므로, 판본이 같으면 처분을 복원하도록 바꾼다. 그리고 "계기만 만들면 된다" 도
정확하지 않다: `should_revive` 는 `_reconcile` 안, 권위 게이트 뒤에서만 불리므로 "분석 없이
되살리기" 에는 새 경로가 필요하다.

확인 방법은 비용이 없다 — mount 를 일시중지해 Risk 가 EXCLUDED 로 닫히는 것을 보고,
**파일을 바꾸지 않은 채** 다시 연결한 뒤 Risk 목록을 본다.

### 3-2. [중간] 좀비 실행을 손으로 풀 수 없다

lease 만료 회수가 있어 큐가 두드리는 동안은 풀린다. 그런데 큐 재시도가 소진된 뒤에는
두드릴 것이 없고, 그때 화면의 "다시 검사" 는 `reanalyze_analysis_job` 이
`status in {QUEUED, RUNNING}` 을 **lease 만료와 무관하게** 거부한다.

소스 종류와 무관하다. **처리했다** — "진행 중" 의 기준을 상태가 아니라 **lease** 로
바꿨다. worker 가 죽으면 상태는 남고 lease 만 만료되므로, 상태만 보면 좀비와 진짜
실행을 구분할 수 없다. `claim` 은 이미 lease 로 판단하고 있었고 재검사 경로만
어긋나 있었다.

되돌려도 옛 시도의 결과가 새 시도를 덮지는 않는다 — 결과 수락이 `started_at` 으로
시도를 구분해 앞선 것을 거절한다.

관련해서 v1 은 큐 재시도 창을 5 회에서 20 회로 넓혔다. 여기 "v3 는 하루라 넉넉하다"
고 적었던 것은 **틀렸다.** `maxRetryDuration: 86400s` 는 하루가 맞지만
`maxAttempts: 8` 이 먼저 닿는다. 백오프가 5 → 10 → 20 → 40 → 80 → 160 → 320 초로
늘어나므로 8 회는 **10 분 남짓**이다 (`docs/V3_DEVELOPMENT_WATCH.md` 가 잡아냈다).

배포 한 바퀴가 빌드 2 분 + 배포 1 분이므로 절망적이지는 않으나, 원인을 찾는 시간을
넣으면 빠듯하다. 좀비 회수를 고친 뒤로 **급한 정도는 줄었다** — 큐가 포기해도 사람이
화면에서 되살릴 수 있다. 다만 재시도가 조용히 끝나는 것 자체는 그대로다.

큐 설정 변경은 배포 영역이므로 값은 건드리지 않는다.

### 3-3. state 가 만료됐을 때 무엇을 하라고 말해야 한다

승인 화면을 오래 붙들거나 뒤로가기로 옛 URL 을 다시 열면 콜백이 그 경로로 온다.
v3 는 GitHub·Drive 양쪽 다 `"invalid or expired oauth state"` 만 돌려준다.

**GitHub 연결에서 실제로 만난 자리다.** 이번에 소비되지 않은 oauth state 가 4 개
남아 있었다 — 시작만 하고 돌아오지 못한 시도들이다. 무엇을 다시 해야 하는지 알 수
없으면 사용자가 같은 실패를 반복한다. 고칠 값이 크고 비용이 작다.

### 3-4. 마운트 순간의 초기 스캔 비용

**이미 대응했다.** `samples/GITHUB_REPO_SCENARIO.md` 가 소모량이 예측 가능한 작은
저장소를 쓰는 이유를 적고 있고, 기술 문서를 한 저장소에만 두어 저장소를 늘려도
KIPRIS 총량이 늘지 않게 했다.

남은 구멍 하나 — `include_patterns` / `exclude_patterns` 는 API 가 받는데 **프론트가
항상 빈 배열을 보낸다**(`sources/api/connectionClient.ts`). 실사용 저장소를 붙이려면
`.ipriskignore` 를 저장소에 두거나 workspace `global_ignore_text` 를 채워야 한다.

### 3-5. 감시 중인 것을 보여 줄 길

추적 스코프는 Integration 소유라 Control API 로는 보이지 않는다. 연결한 뒤 **무엇이
인식됐는지 확인할 방법이 없다.** Drive 카드는 추적 파일 목록을 보여 주는데 GitHub
카드는 저장소·브랜치를 보여 주지 않는다.

GitHub 은 파일 단위가 아니므로 "저장소@브랜치" 서술이면 충분하다. 소스마다 표현이
다른 것을 인정하는 설계다.

### 3-6. mime 만 믿어 텍스트가 빠지는 문제 — GitHub·Local 에는 해당이 적다

v1 이 Drive 에서 겪은 것이다. GitHub 과 Local 은 provider 가 붙인 mime 이 아니라
**파일 이름**으로 종류를 정하므로 같은 함정이 아니다. 다만 게이트는 mime 도 보므로,
GitHub 어댑터가 mime 을 어떻게 채우는지는 확인이 필요하다.

Drive 쪽 문제는 그대로 남아 있다 — 이 문서의 범위 밖이며 v1 대조 문서에 있다.

### 3-7. UI 중에서 기능을 막는 것

* **이미 연결돼 있으면 다시 연결하게 하지 않는다** — 저장소를 하나 붙인 뒤 다음
  것을 붙일 길이 없던 문제. **`79207f2` 로 처리했고 배포 대기 중이다.**
* **실패에 손잡이가 있어야 한다** — 3-2 의 좀비와 같은 자리다. 재검사 버튼이 이제
  좀비를 푼다. 남은 것은 여러 건을 한 번에 되살리는 화면인데, 그건 UI 대개편에서
  볼 일이다.

순수 표현 문제(좌우 대조 배치, 하이라이트 색, 진행 바)는 UI 대개편으로 미룬다.
다만 v1 이 **하이라이트를 배경 칩에서 굵은 색 글자로 되돌렸다**는 것은 기록해 둔다 —
v3 는 지금 배경 칩(`evidence-highlight.tsx`)이고, v1 은 그 길을 가 보고 돌아왔다.

---

## 3-8. [중간] 하위 폴더 파일의 이름이 첫 push 이후 바뀐다

`e7440ab` 는 어댑터와 게이트를 맞췄지만, 같은 artifact 에 이름을 붙이는 곳이 하나
더 있다 (`docs/V3_DEVELOPMENT_WATCH.md` 가 잡아냈다).

| 어디서 | `display_name` |
|---|---|
| 마운트 (`initial_changes`) | 파일 이름 |
| push (`webhook_processor`) | **전체 경로** — GitHub 페이로드의 `filename` |

**실패하지는 않는다.** 등록이 기존 artifact 의 이름을 갱신하고 `display_name` 은
불변 조건이 아니라, 게이트 검사는 이벤트마다 자기정합적이다. `logical_path` 도
양쪽 다 같다.

증상은 표시다 — 하위 폴더 파일의 이름이 첫 push 이후 `design.md` 에서
`docs/design.md` 로 바뀐다. 같은 화면에서 루트 파일과 표기 규칙이 달라 보인다.

**파일 이름으로 통일한다.** `logical_path` 가 이미 폴더를 들고 있으므로 화면에서
폴더를 보여 주는 데 `display_name` 이 필요하지 않고, 이미 저장된 artifact 들도
파일 이름을 쓰고 있다.

다음 배포에 함께 싣는다 — 지금 급한 것은 Local · Desktop 이다.

---

## 3-9. Desktop 을 실제로 켜기

한 번도 켜 본 적이 없었다. 켜 보니 코드 문제는 없었고, **설치가 덜 되어 있었다.**

`electron` 은 devDependency 로 선언돼 있지만 **바이너리가 내려받아지지 않은
상태**였다(`node_modules/.../electron/dist` 없음, `path.txt` 없음). 설치 스크립트가
건너뛰어진 것으로 보인다. 다음으로 받는다.

```
pnpm rebuild electron
```

그다음 서버를 가리켜 켠다. 렌더러는 배포된 웹 앱(`{서버}/app`)을 그대로 띄우므로
UI 개편이 desktop 에도 그대로 반영된다.

```
IPRISK_SERVER_BASE_URL=https://ip-risk-agent-v2-api-555102774494.asia-northeast3.run.app APP_ENV=production pnpm --filter @iprisk/desktop start
```

`APP_ENV=production` 이면 렌더러 주소가 서버와 같은 origin 이어야 한다는 검사가
켜진다(`main/index.ts`). 로컬 서버로 붙일 때는 이 변수 없이 켜면
`http://127.0.0.1:8000` 을 본다.

**주의 — 개발 도구 안에서 켜지 않는다.** VS Code 같은 Electron 기반 도구의
터미널은 `ELECTRON_RUN_AS_NODE=1` 을 물려준다. 그 값이 있으면 Electron 이 순수
Node 로 동작해 내장 `electron` 모듈이 없고, 앱은 `app` 이 undefined 라며 죽는다.
**앱의 결함이 아니다** — 이 자리에서 한 번 잘못 짚어 빌드 방식까지 바꿨다가
되돌렸다. 별도 터미널에서 켜거나 그 변수를 지우고 켠다.

### `GET /desktop/mounts/{id}/status` 는 만들지 않는다 [결정]

Desktop 의 서버 route 는 넷뿐이다 — `POST /desktop/devices/register`,
`POST /desktop/mounts/register`, `POST /desktop/staging`, `POST /desktop/events`
(`local/routes.py:96,104,111,118` 의 `create_local_desktop_router`). **별도
`GET /desktop/mounts/{id}/status` 는 만들지 않는다.** 그 자리를 대신하는 것이 이미
둘 있고, 둘은 **서로 다른 것을 소유한다.**

| 무엇을 묻는가 | 어디서 읽는가 |
|---|---|
| canonical mount 상태 | Control 의 data-access summary — `GET .../data-access-summary`<br>(`api/security/router.py:200`, `security_policy/service.py:225`). workspace 의 mount 를 모아 `ConnectedSourceSummary` 로 낸다 |
| 그 Desktop 의 enrollment · local registry 상태 | allow-listed `getDesktopConnectionStatus` IPC<br>(`apps/desktop/main/index.ts:148` → `core/local-source-service.ts:129`). `deviceId` 와 `mountCount` 를 내고, main 의 `desktopStatus` 가 credential 유무로 `enrolled` 를 더한다 |

**두 상태의 소유권을 섞는 중복 Source endpoint 는 추가하지 않는다.** canonical mount 는
Control 것이고 enrollment 와 local registry 는 그 기기 것이다. 하나의 Source endpoint 가
둘을 함께 답하면 어느 쪽이 진실인지가 endpoint 안에서 정해져 버린다.

**이 결정은 `CODING_AGENT_SPEC_2_SOURCE_DESKTOP.md` §875 를 뒤집는다.** 그 명세의 Local
route 목록에는 `GET /desktop/mounts/{id}/status` 가 다섯 번째 줄로 들어 있다. 그리고
이제는 지워진 `INTEGRATION_V2_EXECUTION_PLAN.md`(git 이력에 있다) §19 는 이것을
**"Desktop mount status endpoint 없음 ·
P0 UX/ops · UI 연결 전에 구현"** 으로 열어 둔 채 남겼다(P0 는 Gate C 전에 모두 닫는다고
적혀 있다). **그 P0 를 처분하는 기록은 이것 하나뿐이다** — 없으면 다음 사람이 그 endpoint 를
만든다.

---

## 3-10. Local 실측 결과와 남은 것

배포(`c81e4fd`) 뒤 `sample_github` 폴더를 붙여 끝까지 확인했다.

| 확인 | 결과 |
|---|---|
| 첫 훑기 (이미 있던 파일) | 2 건 올라감 |
| **하위 폴더** `docs/...` | SUCCEEDED, Risk 2 건 |
| 파일 수정 → UPDATE | 감지·전송·분석 |
| 파일 삭제 → DELETE | 감지·전송 |
| `/desktop/events` | **6 건 전부 200** (수정 전에는 40 건 전부 422) |
| KIPRIS | **0 회** — 같은 내용을 GitHub 으로 이미 분석해 캐시가 받았다 |
| 기술 내용 없는 문서 | `ANALYSIS:NOT_APPLICABLE` — 회색 안내 |

### 남은 것 — [낮음] 새 파일이 `CREATE` 가 아니라 `UPDATE` 로 기록된다

`notes-temp.md` 를 새로 만들었더니 `UPDATE` 로 올라왔다. chokidar 가 `add` 뒤에
`change` 를 연달아 내고, 3 초 디바운스가 **마지막 것으로 덮어쓰기** 때문이다
(`watcher.ts` 의 `schedule`).

동작에는 영향이 없다 — 서버는 어느 쪽이든 artifact 를 만들고 분석한다. 다만
이력에 "이 파일이 언제 생겼는지" 가 부정확하게 남는다.

고친다면 디바운스 창 안에서 **먼저 온 `CREATE` 를 유지**하면 된다. 뒤이은
`change` 는 같은 파일의 같은 저장이므로 종류를 바꿀 이유가 없다.

### 링크 탈출 차단 — 확인했고 구멍이 하나 있었다

감시 폴더 안에 폴더 밖을 가리키는 **디렉터리 junction** 을 심어 확인했다 (파일
심볼릭 링크는 Windows 에서 권한이 필요해 만들지 못했다. junction 도 `realpath`
가 같은 방식으로 푼다).

가드 자체는 정확하다.

| 경로 | 결과 |
|---|---|
| junction 을 통해 폴더 밖 | 차단 |
| `../` 상대 경로 탈출 | 차단 |
| junction 자체 | 차단 |
| 폴더 안 (없는 파일) | 허용 |

링크가 **살아 있는 동안**에는 폴더 밖 파일이 하나도 보고되지 않았다.

**그런데 링크를 지우자 그 파일들이 삭제 이벤트로 서버까지 갔다.** artifact 두 개가
`escape/…` 라는 경로로 만들어졌다. 내용은 가지 않았고(삭제에는 본문 업로드가 없다)
분석도 돌지 않았지만, 애초에 우리 것이 아닌 이름이 기록에 남았다.

이유는 가드가 할 수 있는 일의 한계다. **탈출을 알아보려면 링크가 있어야 한다.**
링크가 지워지면 그 경로는 "폴더 안의 없는 경로" 와 구별되지 않아 가드를 그냥
통과한다. 지울 근거가 사라진 뒤이기 때문이다.

규칙 하나로 닫았다 — **보고한 적 없는 파일은 삭제도 보고하지 않는다.** 내용 해시는
우리가 보고할 때만 남으므로, 그것이 없다는 것은 그 파일이 한 번도 감시 대상이 아니
었다는 뜻이다. 링크가 살아 있을 때 가드가 막았으니 해시도 남지 않았다.

새어 나간 기록은 workspace 와 함께 지웠다.

### 설계로 보장되지 않고 **환경에 기대는** 확인 두 가지

위 표는 junction 으로 실측한 것이다. 그런데 **symlink 시험 2 건은 이 환경에서 돌지
않는다.** 권한이 없으면 `t.skip` 으로 넘어가고, 넘어간 것은 통과로 집계된다.

| 시험 | 자리 |
|---|---|
| `rejects symlink escaping root (skips gracefully if symlink creation is not permitted)` | `apps/desktop/security/path-guard.test.ts:47` |
| `rejects events for symlinked paths escaping root (skips gracefully if unsupported)` | `apps/desktop/watcher/watcher.test.ts:129` |

둘 다 `symlinkSync` 가 `EPERM`/`EACCES` 를 내면 건너뛴다. path-guard 쪽 skip 메시지가
조건을 그대로 적어 둔다 — *"Windows without Developer Mode/admin — run as admin or enable
Developer Mode to exercise this test."* Agent 2 인계 시점의 Desktop TypeScript 집계가
**65 tests, 63 passed / 2 Windows symlink skip** 이었던 것이 이 둘이다(총 297 tests,
295 passed / 2 skipped). **권한이 있는 CI runner 에서 별도로 돌려야 한다.** 4 절의 "시험
70 건이 통과한다" 를 이 2 건이 통과했다는 뜻으로 읽으면 안 된다 — 이 환경에서 이 둘은
돌지 않는다.

같은 성격의 구멍이 하나 더 있다 — **Drive file ID 이동 안정성은 설계상 보장이지만 그것을
확인하는 별도 시험이 없다.** 파일을 옮겨도 ID 가 유지된다는 것에 Drive 추적 스코프가
기대고 있는데, 보장의 근거는 설계뿐이다.

(같은 목록의 셋째 항목 — **staging TTL 은 문서화만 됐고 실제 bucket lifecycle 은
Integration 책임**이다. 4 절 끝의 "TTL 이 진짜 안전망" 과 같은 이야기다.)

---

## 4. 순서

| | 할 일 | 상태 |
|---|---|---|
| 1 | 1 절의 `display_name` 어긋남 수정 + 하위 폴더 회귀 시험 | **완료, 배포 대기** |
| 2 | 저장소 추가 마운트 (`79207f2`) | 배포됨 (`00038`) |
| 2-1 | "Add Source → GitHub" 도 기존 연결을 쓰도록 | **완료, 배포 대기** |
| 3 | 3-3 state 만료 안내 | **완료, 배포 대기** |
| 4 | 나머지 두 저장소 마운트 + 기대값 대조 | **확인됨** |
| 5 | push → 변경 감지 확인 | **확인됨** |
| 6 | 3-1 재연결 부활 — 실측으로 재현부터 | 확인 후 판단 |
| 7 | 3-2 좀비 회수 허용 | **완료, 배포 대기** |
| 8 | **Local · Desktop 구성** | **확인됨** (3-10) |
| 9 | 3-8 push 표시 이름 통일 | 미착수(표시만) |
| 10 | 3-1 재연결 부활 | 미착수 |

**2 를 배포하고도 막혔던 이유** — 저장소를 더 붙이는 길을 연결된 GitHub 카드에만
두었는데, 저장소를 더 붙이려는 사람이 먼저 누르는 것은 **"Add Source"** 다. 거기서는
여전히 설치 화면으로 나갔다. 기능을 만들어 두고 **사람이 가는 길에 두지 않은** 것이다.
2-1 이 그 길을 잇는다 — 살아 있는 GitHub 연결이 있으면 "Add Source → GitHub" 가
나가지 않고 저장소 목록을 바로 연다.

Local · Desktop 은 v1 에서 가져올 것이 없다. v3 가 앞서 있고(`apps/desktop` 기준
v3 전용 681 줄) 시험 70 건이 통과한다. 다만 **한 번도 실행된 적이 없다** — 오늘
찾은 결함이 모두 그런 경로에서 나왔다는 것을 기억할 것.

확인할 한 가지는 v1 이 남긴 주의다 — staging 삭제는 best-effort 이고 **TTL 이 진짜
안전망**이다(Agent 2 Spec 30/32). v3 도 같은 구조인지 본다.
