# Fork D — 빌드·배포

빌드와 배포를 전담한다. **다른 세션은 빌드 중 쓰기를 멈춘다.**

## 쥐고 있는 파일

```
deploy/**
docs/GCP_INTERNAL_DEPLOYMENT.md
scripts/validate_gcp_deployment.py  ← IAM 구역만. 아래를 보라
```

## Fork A 에게 — 같은 파일을 쓴다

`scripts/validate_gcp_deployment.py` 를 **내가 이미 고쳤다** (`dc10f4a`). 고친 자리는
`dynamicCredentialPermissions` 를 검사하는 IAM 구역 하나뿐이고, 네가 풀어야 할 corpus
하드코딩(`corpus_version` 과 소스 3 건, 그리고 `CORPUS_SUBJECT_COVERAGE` 교차검증)과는
멀리 떨어져 있다.

**그 파일을 열기 전에 `dc10f4a` 를 pull 해 달라.** 내용이 겹치지는 않지만 각자 통째로
쓰면 한쪽이 사라진다. 앞으로 그 파일에서 내가 건드리는 곳은 IAM 구역뿐이다.

## 결함 23 — 계약은 고쳤고, 운영은 아직이다

**계약에 `deleter` 를 넣었다** (`dc10f4a`). `dynamicCredentialPermissions.deleter` 로
API SA 하나에 `secretmanager.secrets.delete` 를, `versions.*` 와 같은
`iprisk-v2-cred-` prefix 조건으로 준다. worker 는 넣지 않았다 — 삭제 경로가
`api/workspaces/router.py:314` 하나뿐이라 worker 는 이 길을 타지 않는다. `creator` 가
API 전용인 것과 같은 이유다. 검증기도 이 항목을 기대하도록 함께 고쳤다.

**왜 prefix 조건이 여기서는 걸리는가** — `secrets.create` 는 새 secret 이 아니라 project
parent 에 대해 평가되어 조건을 걸 수 없다는 제약이 `GCP_INTERNAL_DEPLOYMENT.md` 에 적혀
있는데, **삭제는 이미 존재하는 secret resource 에 평가되므로 그 제약이 적용되지 않는다.**

**이걸로 운영이 고쳐지지 않는다.** 검증기는 **계약 파일만** 읽고 실제 IAM 정책은 보지
않는다. §9.4 의 네 걸음 중 ③ 만 끝났다.

| | | |
|---|---|---|
| ① | 실제 정책에 이 binding 이 있는지 확인 | **막힘** |
| ② | 없으면 조건부 binding 실제 부여 | **막힘** |
| ③ | 계약 파일과 검증기 갱신 | 끝남 (`dc10f4a`) |
| ④ | 자격증명이 붙은 workspace 를 실제로 지워 확인 | **막힘** |

## 막힌 것 — gcloud 재인증

```
ERROR: Reauthentication failed. cannot prompt during non-interactive execution.
```

토큰이 만료됐고 재인증은 대화형이라 세션 안에서 못 한다. 사용자에게 `gcloud auth login`
을 요청해 두었다. 풀리면 ①②④ 와 아래 리비전 확인을 이어서 한다.

## 배포 리비전 — 아직 답을 못 줬다

`00037`(`78a6490`) 대 `00038`(`79207f2`) 은 **같은 인증 문제로 막혀 있다.** 저장소에서
확인한 것은 하나뿐이다 — `79207f2` 가 `78a6490` **보다 나중 커밋**이므로 명세 머리말 쪽이
낡았을 가능성이 높다. 다만 실제로 무엇이 떠 있는지는 `gcloud run services describe` 를
봐야 알 수 있어 아직 단정하지 않는다.

## 빌드·배포 — 지금은 할 것이 없다

마지막 세 커밋이 문서와 계약 파일이라 **실행 이미지가 바뀌지 않았다.** 결함 23 의 IAM 도
`gcloud` 조작이지 배포가 아니다.

**메인 세션에게** — 묶음 2 가 커밋되면 이 파일에 적어 달라. 그때 첫 빌드를 돌린다.
빌드가 시작되면 **모든 세션이 쓰기를 멈춰야 하므로** 미리 알아야 한다. 지금 작업트리에
`risk_reconcile/service.py`, `core/risk/transitions.py`, `core/risk/__init__.py`,
`intelligence/license/analyzer.py` 네 개가 미커밋으로 보인다 — 빌드는 이것들이 커밋된
뒤다.
