# v3 개발 추적 기록

이 문서는 **개발 세션이 쌓는 커밋을 따라가며** 잠재적 오류 위험과 개선 방향을
적어 두는 곳이다. 고치는 것은 개발 세션의 몫이므로, 여기에는 무엇이 왜 위험한지와
**확인 방법**까지 적는다.

관련 문서

* `docs/INTEGRATION_V1_CROSSCHECK.md` — v1(`origin/integration`)이 실측으로 겪은
  결함을 v3 와 맞댄 기록
* `docs/GITHUB_LOCAL_DESKTOP_PLAN.md` — 개발 세션이 소유하는 진행 계획

판정 표기는 crosscheck 문서와 같다. **코드를 열어 본 것만 확인으로 적는다.**

---

## 2026-08-22 · `78a6490` → `e7440ab`

배포된 리비전(`78a6490`, API `00037-6zz` / Worker `00037-tq6`) 이후 쌓인 커밋을
검토했다.

| 커밋 | 내용 |
|---|---|
| `93a11b4` / `1a0361a` | 점검용 저장소 `2HyN/sample_github` 를 작업 트리 밖으로 |
| `79207f2` | GitHub 으로 돌아가지 않고 다른 저장소를 마운트 |
| `eb28c7c` | 하위 폴더 게이트 실패와 v1 에서 가져올 것을 기록 |
| `e7440ab` | 하위 폴더 불일치 수정 + 저장소 선택기를 실제 동선에 + oauth state 안내 |

### 검토 결과

#### [중간] 하위 폴더 파일의 표시 이름이 첫 push 이후 바뀐다

`e7440ab` 는 **어댑터와 게이트**를 맞췄다. 그런데 같은 artifact 에 이름을 붙이는
곳이 하나 더 있고, 그쪽은 아직 어긋나 있다.

| 어디서 | `display_name` | `path_hint` |
|---|---|---|
| 마운트 (`github/adapter.py:225` `initial_changes`) | `file.path` 의 **마지막 조각** | 전체 경로 |
| push (`github/webhook_processor.py:158`) | `file.filename` = **전체 경로** | 전체 경로 |

GitHub push 페이로드의 `filename` 은 저장소 루트 기준 전체 경로다. 그래서
`docs/design.md` 는 마운트 때 `design.md` 로, push 때 `docs/design.md` 로 등록된다.

**실패하지는 않는다.** 확인한 근거는 두 가지다.

* 등록이 기존 artifact 의 이름을 갱신한다 — `process_change/service.py:412` 의
  `replace(existing, display_name=current_ref.display_name, ...)`.
* `display_name` 은 불변 조건에 없다 — `core_firestore/repositories.py:503-512` 는
  source workspace 와 source 정체성만 막는다.

그래서 게이트의 `snapshot.display_name != artifact.display_name`
(`security_gate/service.py:442`) 검사는 **이벤트마다 자기정합적**이라 통과한다.

**증상은 표시다.** 하위 폴더에 있는 파일의 이름이 첫 push 이후 `design.md` 에서
`docs/design.md` 로 바뀐다. 루트 파일은 두 값이 같아 바뀌지 않는다. 같은 화면에
루트 파일과 하위 폴더 파일이 섞이면 표기 규칙이 달라 보인다.

`logical_path` 는 양쪽 다 `alias/docs/design.md` 로 **안정적이다**
(`process_change/service.py:359` 가 `path_hint` 를 우선한다). 근거의 reference 와
Risk 정체성은 영향을 받지 않는다.

**확인 방법** — `sample_github` 의 `docs/` 아래 파일을 push 로 수정하고, Sources
화면의 artifact 이름이 바뀌는지 본다. push 경로는 아직 한 번도 돌지 않았으므로
이번 검증에서 자연히 지나가는 자리다.

**개선 방향** — 이름을 만드는 곳이 세 군데(마운트·push·스냅샷)라서 생긴 일이다.
`e7440ab` 가 스냅샷을 "등록이 적은 것을 되돌려준다" 로 정리했으니, 등록 쪽 두
곳도 한 규칙으로 모으는 것이 같은 결의 정리다. 어느 쪽으로 통일할지는 판단이
필요하다 — 전체 경로로 통일하면 화면에서 폴더가 보이고(v1 이 `b58b5f1` 에서 고른
방향), 마지막 조각으로 통일하면 이름이 짧다. `logical_path` 가 이미 폴더를 들고
있으므로 **화면에서 폴더를 보여 주는 데 `display_name` 이 꼭 필요하지는 않다.**

#### [낮음·기록 정정] 큐 재시도 창은 하루가 아니라 8 회

`eb28c7c` 는 v1 의 재시도 창 확대(`5e85440`)를 "이미 닫힌 항목 — v3 는 하루" 로
적었다. 배포된 큐를 읽어 확인한 값은 이렇다.

```
maxAttempts: 8
maxRetryDuration: 86400s
minBackoff: 5s   maxBackoff: 3600s   maxDoublings: 8
```

`maxRetryDuration` 은 하루가 맞지만 **`maxAttempts` 가 8 이다.** 두 한계 중 먼저
닿는 쪽에서 재시도가 끝난다. 백오프가 5 → 10 → 20 → 40 → 80 → 160 → 320 초로
늘어나므로 8 회는 대략 **10 분** 남짓이다. 하루가 아니다.

v1 이 창을 넓힌 이유는 "수정이 배포되기 전에 일감이 전부 폐기되는 창" 이었다. 이
저장소의 배포 한 바퀴는 빌드 약 2 분 + 배포 약 1 분이므로 10 분이 절망적이지는
않으나, 원인을 찾는 시간까지 넣으면 빠듯하다.

`bfc615d` 로 **급한 정도는 줄었다.** 큐가 포기한 뒤에도 사람이 화면에서 되살릴 수
있게 됐기 때문이다. 다만 그것은 사람이 알아차렸을 때의 이야기이고, 재시도가 조용히
끝나는 것 자체는 그대로다.

**정정만 해 두고 값은 건드리지 않았다.** 큐 설정 변경은 배포 영역이다.

### 확인했고 문제 없던 것

같은 자리를 다시 파지 않도록 남긴다.

* **하위 폴더 수정 자체는 정확하다.** 게이트는 두 가지를 따로 본다 —
  `snapshot.display_name == artifact.display_name`(442 행)과
  `hint 로 만든 경로 == artifact.logical_path`(458-463 행). 등록이
  `display_name=basename` + `path_hint=전체 경로` 이므로, 스냅샷이 등록의
  `display_name` 을 되돌려주면 두 검사가 모두 맞는다. 루트 파일이 우연히
  통과했다는 설명도 코드와 일치한다.
* **폴더가 artifact 이름에서 사라지지 않는다.** v1 의 `b58b5f1` 이 고친 문제는
  v3 에 없다 — `logical_path` 가 `path_hint` 를 우선하므로 폴더가 남는다. 같은
  이름의 파일이 다른 폴더에 있어도 `logical_path` 가 다르고, artifact 정체성은
  `(source_workspace_id, source_artifact_id)` 라 애초에 충돌하지 않는다.
* **새 라우트의 인가가 두 겹이다.** `source-mounts/{mount_id}/github/repositories`
  는 mount 인가를, `.../github/mounts` 는 mount 인가에 더해 대상 workspace 인가를
  받는다. 기본값도 `deny_all_authz` 다. Drive 의 mount 범위 라우트와 같은 모양이다.
* **oauth state 안내가 보강됐다.** crosscheck 문서 5 절에서 지적한 자리다. GitHub 과
  Drive 양쪽이 함께 바뀌었다.

### 배포 관점 메모

* 이번 배포에는 **프론트 변경이 포함된다**(`AddSourceChooser.tsx`,
  `SourcePanel.tsx`, `connectionClient.ts`). `index.html` 은
  `Cache-Control: no-cache` 라 옛 화면이 남지는 않는다
  (`composition/frontend_hosting.py:22`).
* `sample_github` 는 파일 수와 비용을 미리 정해 만든 저장소다. **다른 저장소를
  붙일 때는** crosscheck 문서 5 절의 초기 스캔 비용 표를 먼저 볼 것 —
  `.ipriskignore`·`global_ignore_text`·`include/exclude` 세 수단이 모두 비어 있으면
  마운트 한 번으로 KIPRIS 월 한도를 넘길 수 있다.

### 아직 열려 있는 것

crosscheck 문서의 잠재 문제 중 이번 커밋들이 다루지 않은 것.

| 항목 | 상태 |
|---|---|
| 감시 재개해도 Risk 가 되살아나지 않는다 | 그대로 |
| Drive mime 허용 목록이 좁다 | 그대로 |
| 좀비 실행을 화면에서 되살릴 수 없다 | **닫힘** — `bfc615d` 가 "진행 중" 의 뜻을 상태가 아니라 **lease 생존**으로 바꿨다. 점유(claim)가 이미 그 뜻으로 쓰고 있었으므로 두 경로가 어긋나지 않는다. 읽을 수 없는 lease 는 살아 있는 것으로 세는 것도 점유 쪽과 같다. 되살린 좀비의 옛 시도가 새 시도를 덮지 않는 근거는 결과 수락이 `started_at` 으로 시도를 구분한다는 것이다 |
| 게이트가 `/` 선행 경로를 내보낸다 | 그대로 (구조) |

---

## 2026-08-23 · 라이선스·RAG 경로 결함 조사

RAG 개선안을 논의하려고 라이선스 경로를 훑다가 나온 것들이다. **개선안의 방향에 따라
일부는 고칠 필요가 없어질 수 있으므로** 여기에는 기록만 하고 수정은 하지 않았다.

전부 이 저장소의 venv 로 **직접 재현했다.** 아래 재현 명령을 그대로 실행하면 같은 값이 나온다.

### 요약

| # | 결함 | 성격 |
|---|---|---|
| 1 | 조각화가 의존성 파일 파싱을 부순다 | **데이터 파괴** — 위험을 "해소" 로 오보 |
| 2 | 게이트가 판정을 이끈 식별자가 아니라 표현식 전체를 본다 | 틀린 근거 노출 |
| 3 | 미상 식별자가 저장 전에 `UNKNOWN` 으로 소거된다 | 확장 불가의 근본 원인 |
| 4 | `WITH` 예외를 읽지 않는다 / `OR` 선택이 기록되지 않는다 | 오탐·무기록 |
| 5 | `PARTIAL` 이 결정론적 판정까지 폐기한다 | 조용한 감시 중단 |
| 6 | 라이선스가 바뀌면 Risk 링크가 끊긴다 | 제품 핵심 값의 실패 지점 |

### 1. [데이터 파괴] 조각화가 의존성 파일 파싱을 부순다

`split_document` 가 artifact 종류를 가리지 않고 적용되고, `LicenseAnalyzer` 가 조각마다
파서를 부른다. JSON·TOML 은 조각내면 파싱이 깨진다.

```
python -c "
from ip_risk_agent.connectors.common.segmentation import split_document
from ip_risk_agent.intelligence.license.analyzer import _select_parser
import pathlib
for p in ('pyproject.toml','package.json'):
    t = pathlib.Path(p).read_text(encoding='utf-8'); f = _select_parser(p)
    segs = split_document(t)
    per = sum(len(f(s.text, p)) for s in segs if _try(s))
    print(p, len(f(t,p)), '->', per)"
```

| 파일 | 통짜 | 조각 경유 |
|---|---|---|
| `pyproject.toml` | 20 | **3** |
| `package.json` | 1 | **0** |
| `samples/license/package.json` (351B) | 4 | 4 |
| `samples/license/requirements.txt` | 6 | 6 |

**E2E 샘플이 통과한 이유가 이것이다** — 351 바이트라 조각이 1 개였고, `requirements.txt` 는
줄 지향이라 우연히 살아남았다. 운영에서 LICENSE Risk 10 건이 정상으로 보인 것도 같은 이유다.

그리고 뒤가 더 나쁘다. 확인한 연쇄:

```
package.json → 조각 → 의존성 0건
  → analyzer.py: succeeded([])   coverage 미지정
  → common/analyzer.py:143  coverage 는 실패 유무로 정해짐 → 실패 없으면 COMPLETE
  → core/risk/transitions.py:50  analysis_is_authoritative(SUCCEEDED, COMPLETE) = True
  → risk_reconcile/service.py:196  _reconcile 실행, 후보 0건
  → 기존 라이선스 Risk 전부 RESOLVED
```

**위험을 놓치는 것이 아니라 "위험이 해소되었다" 고 적극적으로 오보한다.** 제품의 첫 번째
값인 지속 추적을 정면으로 부순다.

**원인 귀속** — 이 회귀는 `split_document` 를 세 커넥터에 넣으면서 들어왔다. 특허 쪽의 줄
범위·인용 구간을 위한 변경이었는데, 의존성 파일에도 함께 적용됐다. 시험은 통과한다.
`samples/license/**` 만 검증에 쓰였고 그 둘은 위 표대로 손실이 0 이다.

### 2. [틀린 근거] 게이트가 판정을 이끈 식별자를 보지 않는다

`reference_gate.is_relevant` 가 **표현식의 모든 leaf** 를 본다. 판정을 이끈 leaf 가 아니다.

```
python -c "
from ip_risk_agent.intelligence.license import policy, reference_gate
from ip_risk_agent.intelligence.license.reference_gate import CORPUS_SUBJECT_COVERAGE
e='Apache-2.0 AND GPL-3.0-only'
print(policy.evaluate_expression(e).value,
      [s for s in CORPUS_SUBJECT_COVERAGE if reference_gate.is_relevant(s,e)])"
→ POLICY_CONFLICT ['permissive-notice']
```

`rag-corpus/sources/permissive-notice.md` 본문은 **"소스코드 공개 의무는 없다"** 이다.
즉 "결합 저작물 전체의 소스 공개를 요구한다" 고 판정해 놓고 그 반대를 근거로 붙인다.
`reference_gate` 가 막으려고 만들어진 바로 그 오류를 그 게이트가 통과시킨다.

단일 식별자(`GPL-3.0-only`)는 통과 문서가 0 개라 조용히 끝난다. **복합 표현식에서만 터진다.**

부수 사실 — `permissive-notice` 가 덮는 MIT·BSD·Apache·ISC 는 전부 `needs_review=False` 라
**자기가 판정을 이끈 경로에서는 검색되지 않는다.** 이 문서가 근거로 붙는 모든 경로가
오부착 경로다.

### 3. [근본] 미상 식별자가 저장 전에 소거된다

```
spdx.normalize('BUSL-1.1')          → 'UNKNOWN'
spdx.normalize('Elastic-2.0')       → 'UNKNOWN'
spdx.normalize('LicenseRef-Acme')   → 'UNKNOWN'
spdx.normalize('MIT AND BUSL-1.1')  → 'MIT AND UNKNOWN'      ← 부분 소거
len(spdx._CANONICAL) == len(policy._OUTCOME_BY_ID) == 42, 차집합 양방향 공집합
SPDX_SNAPSHOT_VERSION == 'spdx-3.24-subset'
```

치환이 `package_metadata.py` 의 fact 생성 시점, 즉 **저장 경계보다 앞**에 있다. 원문자열이
어디에도 남지 않는다.

귀결 셋:

* **정책 표에 행을 추가하는 것은 무효과다.** 그 문자열이 조회에 도달하지 못한다.
* **저장된 표현식으로 다시 계산하는 방식은 UNKNOWN 을 하나도 못 고친다.** 저장값이
  `"UNKNOWN"` 이다.
* `BUSL-1.1 → Elastic-2.0` 같은 **라이선스 변경을 구분할 수 없다.** 양쪽 다 `"UNKNOWN"` 이다.

따라서 **UNKNOWN 은 "정책 없음" 이 아니라 언제나 "식별 실패"** 다. 병목은 정책이 아니라 어휘다.

### 4. [오탐·무기록] `WITH` 예외와 `OR` 선택

```
'GPL-2.0-only WITH Classpath-exception-2.0'  → POLICY_CONFLICT   (맨 GPL 과 동일)
'0BSD OR GPL-3.0-only'                       → NO_ACTION → LOW → Risk 미생성
```

`policy._evaluate` 가 `LicenseNode.exception` 을 한 번도 읽지 않는다. OpenJDK 계열과
libstdc++ 로 링크되는 C++ 바이너리가 최고 등급 오탐이 된다.

`OR` 은 도구가 가장 가벼운 쪽을 조용히 고르는데 **그 선택이 원장에 남지 않는다.** 사람이
"우리는 어느 쪽을 택했나" 를 되짚을 수 없다.

### 5. [조용한 중단] `PARTIAL` 이 결정론적 판정까지 폐기한다

`_attach_reference_evidence` 는 RAG 예외에서 `record_failure` 후 `True` 를 돌려 coverage 를
PARTIAL 로 낮춘다. 그런데 `risk_reconcile/service.py:196` 이
`analysis_is_authoritative(SUCCEEDED, COMPLETE)` 안에서만 `_reconcile` 을 부른다.

**RAG 가 죽으면 표가 낸 판정도 함께 버려진다.** `explanation.py` 머리말의 "두 기능이 모두
실패해도 정책 결과는 그대로 남는다" 는 canonical 계층에서 사실이 아니다.

장애가 길어지면 모든 라이선스 분석이 폐기되어 Risk 가 갱신되지 않는데, 화면에서 "위험 없음"
과 "아무것도 모름" 이 구분되지 않는다.

같은 자리에서 `rag_corpus_version` 도 **조각이 실제로 붙었을 때만** 기록된다. corpus 갱신이
가장 크게 바꿀 판정들이 정확히 "어떤 지식으로 답했는지" 가 빈 채로 남는다.

### 6. [핵심 값 실패] 라이선스가 바뀌면 Risk 링크가 끊긴다

`license_risk_key` 가 `normalized_license_expression` 을 포함한다. 라이선스가 바뀌면 key 가
바뀌어 옛 Risk 는 후보 부재로 `RESOLVED`, 새 key 는 `DETECTED` 가 된다. 둘을 잇는 링크가
없고, 사용자가 걸어 둔 `MONITORING`·`ACCEPTED_RISK` 처분도 옛 Risk 에 남는다.

`RiskEventType` 에 `LICENSE_CHANGED` 가 없고, `NotificationType` 에 **해소도 등급 하향도
없다.** 즉 "당신이 검토해서 받아들인 그 패키지가 라이선스를 바꿨다" 는, 이 제품이 만들 수
있는 가장 값진 알림이 지금 구조에서 성립하지 않는다.

### 위험의 비대칭

이 결함들이 한 방향으로 쏠려 있다는 점이 중요하다.

* 틀린 **상향** — 검토자 시간을 쓴다. 화면에 보인다.
* 틀린 **하향** — 알림 0 건, `RESOLVED` 이력이 `evidence_refs=()` 로 근거 없이 남고,
  `NO_ACTION` 은 Risk 자체가 만들어지지 않는다. **소리 없이 사라진다.**

1·4·5 가 전부 하향 쪽이다. 개선안에서 무엇을 먼저 할지 정할 때 이 비대칭이 기준이 되어야 한다.
