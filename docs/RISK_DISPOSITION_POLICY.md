# Risk 처분 정책 — 사람의 판단과 외적 종료를 가른다

> 2026-08-22 결정. 이 문서는 `ReviewDisposition` 의 뜻을 고정한다.

## 1. 무엇을 가르는가

처분에는 성격이 다른 두 가지가 섞여 있었다.

* 사람이 **판단해서** 내리는 것 — 계속 지켜본다, 감수하기로 했다
* 추적이 **끊겨서** 더 이상 관리되지 않는 것 — 파일 추적 중단, mount 일시중지,
  workspace 삭제

둘을 같은 목록에서 사람이 고르게 두면 뜻이 흐려진다. 특히 추적이 이미 끊긴 Risk 를
두고 "계속 지켜볼까" 를 사람이 고르는 것은 물어볼 수 없는 질문이다. 지켜볼 대상이
없기 때문이다.

## 2. 값의 뜻

| 값 | 누가 붙이나 | 뜻 |
|---|---|---|
| `UNREVIEWED` | 시스템 | 아직 사람이 보지 않았다 |
| `MONITORING` | 사람 | 계속 지켜본다 |
| `ACCEPTED_RISK` | 사람 | **사람이 스스로 감시를 그만둔다.** 위험을 알고 감수한다 |
| `EXCLUDED` | **시스템만** | 사용자 판단 밖의 외적 요인으로 관리가 끝났다 |

`ACCEPTED_RISK` 가 "monitoring 중단" 에 해당하는 유일한 값이다. 사람이 감시를
그만두는 길은 이것 하나뿐이다.

## 3. 사람이 할 수 없는 것

`decide_user_review` 가 두 방향을 모두 막는다 (`core/risk/transitions.py`).

* `EXCLUDED` **로** 바꾸기 — 외적 종료를 사람이 흉내 낼 수 없다
* `EXCLUDED` **에서** 벗어나기 — 추적이 끊긴 Risk 를 사람이 되살릴 수 없다

두 번째가 중요하다. 다시 검토 대상이 되는 길은 **그 파일을 다시 추적하는 것**뿐이다.
사람이 처분만 바꿔 되살리면, 감시되지 않는 파일의 Risk 가 활성 목록에 앉아 추적되고
있는 것처럼 읽힌다.

이 규칙은 core 에 있으므로 어떤 API 를 거치든 우회할 수 없다. 위반은
`DomainInvariantError` 이고 API 에서 422 `DOMAIN_VALIDATION_FAILED` 가 된다.
화면에서도 선택지에서 빼고, 이미 제외된 Risk 에는 검토 카드 대신 설명을 보여준다.

## 4. 시스템이 `EXCLUDED` 를 붙이는 자리

`application/risk_exclusion.py` 한 곳에서만 붙인다.

| 계기 | 함수 | 범위 |
|---|---|---|
| 파일 추적 해제 | `exclude_artifact_risks` | 그 artifact 의 Risk |
| mount 일시중지 | `exclude_mount_risks` | 그 mount 의 모든 artifact |

> **[2026-08-23] 이 표에 세 줄이 더해진다** — `docs/DEVELOPMENT_SPEC.md` §7.1 의 1-D 가
> **파일 삭제 · 폴더 이탈 · 접근 상실**을 같은 경로로 보낸다. 지금은 셋 다 `EXCLUDED` 를
> 붙이지 않아 **지워진 파일의 Risk 가 활성 목록에 남는다.** 방아쇠가 넓어지면 §5 의
> 되살리기 규칙도 함께 바뀌므로 그쪽 표시를 같이 읽어야 한다.

전이는 `decide_exclusion` 이 정한다 — **`RESOLVED` + `EXCLUDED`**.

지우지 않는다. Risk 도 근거도 이력도 그대로 남는다. 남기는 이유는 감사다. "왜 그때
그렇게 판단했는가" 는 추적을 끊은 뒤에도 답할 수 있어야 한다.

`resolved_at` 은 `max(occurred_at, first_seen_at, last_seen_at)` 로 잡는다.
`Risk` 는 `resolved_at` 이 `first_seen_at` 보다 앞서는 것을 불변조건으로 막는다.

### review_version 을 반드시 올린다

저장소가 "처분이 바뀌면 `review_version` 이 정확히 하나 오른다" 를 강제한다
(`repositories/in_memory.py`). 시스템이 붙이는 처분도 예외가 아니다. 화면의 ETag 가
이 값으로 만들어지므로, 올리지 않으면 낡은 값이 계속 유효해 보인다.

## 5. 다시 추적하면 되살아난다

> **[2026-08-23] 이 절의 규칙은 `docs/DEVELOPMENT_SPEC.md` §7.1 이 개정한다.** 아래
> "제외되어 있던 동안의 판단은 더 이상 유효하지 않으므로 처음 본 것처럼 다시 시작한다" 는
> 방아쇠가 **수동 "추적 해제" 하나뿐일 때** 옳았다 — 사용자가 스스로 그만둔 것이므로 다시
> 시작하는 것이 맞다. 1-D 가 방아쇠를 삭제 · 폴더 이탈 · 접근 상실로 넓히면 전제가 깨진다.
> 파일을 잠깐 옮겼다 되돌리는 흔한 일에 **사람이 검토해 수용한 판단이 지워진다.**
>
> 개정 내용 — **판본이 같으면 이전 처분을 복원하고, 다르면 지금처럼 `NEW`/`UNREVIEWED`
> 로 시작한다.** "제외되어 있던 동안 세상이 달라졌다" 는 근거는 판본이 달라진 경우에만
> 성립하므로, 규칙을 판본에 걸면 원래 의도가 그대로 유지된다.
>
> 아래 문장이 말하지 않는 것이 하나 더 있다 — `should_revive` 는
> `risk_reconcile/service.py` 의 `_reconcile` 안, 권위 게이트 **뒤**에서만 불린다.
> 그래서 "분석 없이 되살리기" 에는 **새 경로가 필요하다.** 1-D 는 기존 코드에 계기만
> 붙이는 일이 아니다.

같은 workspace 의 같은 파일이 다시 추적 대상이 되면 **이전 Risk 를 되살린다.**
새로 만들지 않는다 — 그 파일의 이력이 한 줄로 이어져야 한다.

`should_revive` 가 `EXCLUDED` 일 때만 참이고, 수용 경로가 그때
**`NEW` / `UNREVIEWED`** 로 되돌린다 (`risk_reconcile/service.py`).

제외되어 있던 동안의 판단은 더 이상 유효하지 않으므로 처음 본 것처럼 다시 시작한다.
반대로 `ACCEPTED_RISK` 같은 **사람의 처분은 재분석이 덮지 않는다.** 되살리기는
`EXCLUDED` 에만 적용된다.

되살리기가 성립하려면 artifact id 가 재추적 뒤에도 같아야 한다. mount 는 계정 단위로
안정적이고 (`vws:{...}|scope:drive-account:{...}`), 일시중지된 mount 는 다시 mount
할 때 같은 것이 활성화된다. 그래서 artifact id 와 risk key 가 보존된다.

## 6. 추적 해제의 두 부분

canonical 상태와 provider 감시는 다른 것이라 나눠서 처리한다.

| 부분 | 어디 | 하는 일 |
|---|---|---|
| canonical | `ControlPlaneFacade.untrack_artifact` | artifact 를 `ARCHIVED` 로, Risk 를 `EXCLUDED` 로 |
| provider 감시 | Drive connector 라우터 | 추적 범위에서 file id 제거 |

순서는 **canonical 이 먼저**다. 뒤집으면 canonical 이 실패했을 때 감시만 끊긴 채
Risk 가 활성으로 남는다. 이 순서라면 반대로 감시가 남아 다음 변경에 Risk 가
되살아나므로 사용자가 다시 시도할 수 있다. 조용히 잘못되기보다 눈에 보이게 실패한다.

추적 범위는 source 종류마다 모양이 다르고 canonical 상태가 아니다. 그래서 facade 가
`source_artifact_id` 를 돌려주고 connector 가 그것으로 감시를 끊는다. 지금은 Drive
에만 구현되어 있다 — GitHub·Local 은 각자의 범위 표현이 생길 때 같은 자리에 붙인다.

## 7. 아직 하지 않은 것

* **workspace 삭제** 는 아직 이 정책을 쓰지 않는다. 제품 경로의 삭제는 `DELETING`
  상태로 두는 soft delete 이고, 삭제 정책 자체가 정해지지 않았다. 정해질 때
  `exclude_mount_risks` 를 workspace 범위로 부르면 된다
* **GitHub·Local 의 파일 단위 추적 해제** — canonical 쪽은 이미 source 종류와
  무관하므로 connector 라우터만 붙이면 된다

