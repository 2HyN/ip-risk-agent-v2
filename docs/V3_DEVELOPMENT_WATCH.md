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
