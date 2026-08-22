# Fork C — 실측

`DEVELOPMENT_SPEC.md` 의 1-A · 1-B 를 맡는다. **코드를 고치지 않는다.** 산출물은 기록이다.

## 쥐고 있는 파일

```
docs/SOURCE_MEASUREMENT.md
docs/status/fork-c-measurement.md
```

두 개뿐이다. 다른 세션의 경로는 읽기만 했다.

## KIPRIS 사용량 — **0 회. 아직 한 번도 쓰지 않았다**

1-B 를 **호출하지 않고** 쟀다. 한도가 월 1,000 회인데 재보려고 마운트하면 그것으로 한도가
날아가므로, 커넥터·분석기의 규칙을 코드에서 그대로 불러와 파일을 세는 방식으로 갈음했다.
**한도는 아직 온전하다.** 쓰기 전에 여기에 먼저 적겠다.

## 1-B — 끝났다

전체 결과는 `docs/SOURCE_MEASUREMENT.md` 에 있다. 다른 세션의 행동을 바꾸는 것만 적는다.

**이 저장소 하나를 붙이면 한도를 넘긴다.**

| | 특허 경로 파일 | KIPRIS 최대 | 한도 대비 |
|---|---|---|---|
| GitHub 마운트 | 417 | 4,587 | **4.6 배** |
| Local 마운트 | 20,764 | 228,404 | **228 배** |

GitHub 은 추적 파일만 보므로 `.gitignore` 가 걸러 준다. **Local 은 디스크를 본다** —
`node_modules`·`.venv`·`.pytest-tmp` 가 전부 들어와 50 배가 벌어진다. 폴더 마운트를 여는
것은 Local 쪽 문을 여는 일이다.

빌드 산출물을 빼면 228 배 → 4.8 배로 GitHub 과 같은 자리에 온다. 거기서 더 줄이려면 소스
코드를 빼야 하고(0.6 배), **그것이 한도 안에 들어오는 유일한 조합이다.**

## 1-B 를 재다 나온 것 — 제외 목록이 조용히 아무것도 안 거른다

**이게 수치보다 중요할 수 있다.** §9.1 이 비용을 막는 수단으로 든 셋이 **서로 다른 매처**를
쓴다.

| 수단 | 구현 | 패턴이 틀리면 |
|---|---|---|
| source `.ipriskignore` | `connectors/common/ipriskignore.py` — `fnmatch(path, pattern)` 한 줄 | **조용히 0 개를 거른다** |
| workspace `global_ignore_text` | `application/security_gate/ignore.py` — 정규식 `fullmatch`, 선행 `/` 필수 | `IgnorePolicyError` → `POLICY_INVALID` 로 거부 |
| tracking scope `exclude_patterns` | `connectors/github/tracking_scope.py:26` — `fnmatch` | 조용히 0 개를 거른다 |

`/backend/node_modules/a/b.js` 로 실측한 결과다.

| 쓴 것 | `.ipriskignore` | workspace |
|---|---|---|
| `node_modules` | **안 거른다** | 오류 |
| `**/node_modules/**` | 안 거른다 | 오류 (선행 `/` 없음) |
| `*node_modules/*` | **거른다** | 오류 |
| `/**/node_modules/**` | 안 거른다 | **거른다** |

**두 곳 모두에서 동작하는 패턴 문자열이 하나도 없다.** 그리고 사람이 가장 자연스럽게 적을
`node_modules` 는 `.ipriskignore` 에서 오류도 없이 20,764 개를 그대로 통과시킨다.
workspace 쪽은 적어도 거부로 실패가 보인다.

검증한 두 목록(같은 집합을 거른다, 20,764 → 439)은 `SOURCE_MEASUREMENT.md` §1.5 에 있다.

## 1-A — 막혔다. 사람의 동작 둘이 필요하다

**(가) Drive 폴더를 서비스 계정에 뷰어로 공유해야 한다.**

```
iprisk-v2-worker@proj-aj22-211200020328.iam.gserviceaccount.com
```

**(나) `gcloud auth login`.** 지금 세션이 만료돼 서비스 계정 가장이 안 된다
(`Reauthentication failed. cannot prompt during non-interactive execution`).

탐침은 만들어 두었다 — `check` / `start` / `poll` 세 명령이고, 각 변경에 `removed` ·
`trashed` · `parents` 를 함께 찍어 **폴더 밖으로 나간 것이 `removed` 로 오는지 아니면
`parents` 만 바뀐 평범한 변경으로 오는지**를 구별한다. 둘은 처리가 전혀 다르다. 자격증명은
파일로 두지 않고 호출마다 가장으로 받는다. 위 둘이 풀리면 10 분이면 답이 나온다.

## 다른 세션이 알아야 할 것

**메인에게** — 위 매처 건은 결함으로 올릴 만하다고 본다. `.ipriskignore` 가 잘못된 패턴에
오류를 내지 않고 0 개를 거르는 것은 §8.1 이 말한 "조용한" 실패와 같은 종류이고, 방향이
반대다(위험을 놓치는 쪽이 아니라 **한도를 태우는 쪽**). `SOURCE_MEASUREMENT.md` §1.4 에
재현 코드가 있다. 다만 `connectors/**` 는 메인 것이라 나는 건드리지 않았다.

명세에 채울 칸도 둘 있다 — §10 의 "초기 스캔 KIPRIS"(상한은 위 표, 실호출 비율은 아직
미측정)와 §13-4 "기본 제외 목록의 내용"(§1.5 의 검증된 목록). 명세는 메인 것이므로 옮기는
것은 맡긴다.

**Fork D 에게** — 1-A 가 `gcloud` 재인증과 폴더 공유를 기다린다. 배포 세션이 GCP 를 쥐고
있으니, 재인증하는 김에 서비스 계정 공유 대상 주소가 위의 것이 맞는지 확인해 주면 좋겠다.
`iprisk-v2-api` 가 아니라 **`iprisk-v2-worker`** 로 잡았는데, Drive 폴링이 Worker 에서
도는 전제였다. 아니면 알려 달라.

**모두에게** — 소스 코드를 특허 경로에 넣을지가 비용의 88% 를 가른다. 근거가 §1.2 (B) 에
없다(그 논거는 기획 문서를 가리킨다). 이건 실측이 답할 수 있는 것이 아니라 **정하는
문제**라 사용자에게 올렸다.
