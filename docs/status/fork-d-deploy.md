# Fork D — 빌드·배포

빌드와 배포를 전담한다. **다른 세션은 빌드 중 쓰기를 멈춘다.**

## 쥐고 있는 파일

```
deploy/**
docs/GCP_INTERNAL_DEPLOYMENT.md
scripts/validate_gcp_deployment.py  ← IAM 구역만. 나머지는 Fork A 것
```

## 내가 저지른 것 — `5e83336` 이 Fork C 파일을 담아 갔다

`git add docs/status/fork-d-deploy.md` 로 내 것만 올렸는데도 `fork-c-measurement.md` 와
`fork-a-rag-corpus.md` 가 함께 들어갔다. **이미 스테이지에 있던 것이 `git commit` 에 그냥
딸려 간다.** 내 파일만 add 했다는 것은 아무 보호가 되지 않는다.

앞으로 `git commit -- <경로들>` 을 쓴다. 인덱스 상태와 무관하게 그 경로만 담긴다.
Fork C 가 `4c40ab7` 에서 지적한 그대로였다. 되돌리지는 않는다 — 내용은 온전하다.

## 결함 23 — 계약은 살아 있고, 운영은 아직이다

Fork A 가 같은 파일(`scripts/validate_gcp_deployment.py`)을 고친 뒤에도 내 변경이 그대로
있는 것을 확인했다 — 계약의 `deleter` 항목과 검증기의 기대 목록 둘 다. 배포 관련 시험
18 건 통과.

§9.4 의 네 걸음 중 ③ 만 끝났다. 검증기는 **계약 파일만** 읽고 실제 IAM 정책은 보지 않는다.

| | | |
|---|---|---|
| ① | 실제 정책에 binding 이 있는지 확인 | **막힘 — 재인증** |
| ② | 없으면 조건부 binding 부여 | **막힘 — 재인증** |
| ③ | 계약 파일과 검증기 갱신 | 끝남 (`dc10f4a`) |
| ④ | 자격증명 붙은 workspace 를 실제로 지워 확인 | **막힘 — 재인증** |

## 배포 직전에 반드시 할 것 — corpus 판본 맞추기

`TRACKING.md` 가 "코드가 잡아 주지 못한다" 고 적은 그것이다. 왜 못 잡는지 확인해
`GCP_INTERNAL_DEPLOYMENT.md` 에 절차로 세웠다.

**`RAG_CORPUS_VERSION` 은 `optionalEnvironment.worker` 라 이름만 저장소에 있고 값은 라이브
service 에만 산다.** 게다가 두 가지가 겹쳐 조용하다 — **worker 전용**이라 API 를 봐서는
모르고, **optional** 이라 값이 낡아도 배포가 실패하지 않는다.

지금 어긋나 있다. 매니페스트는 이미 `2026-08-23.3` 까지 올라갔고 배포 env 는
`2026-08-21.1` 이다. 한 번 맞추는 것으로는 안 된다 — corpus 가 아직 움직인다.

**순서는 적재 → 매니페스트 판본 읽기 → worker env 갱신 → 배포.** 값만 맞추면 라벨만
바뀌고 실제 corpus 는 그대로다. 확인 명령은 `GCP_INTERNAL_DEPLOYMENT.md` 에 있다.

**Fork A 에게** — 적재가 끝나 `corpus_version` 이 멎으면 이 파일에 적어 달라. 그때 값을
`canonicalEnvironment.worker` 로 옮겨 검증기가 매니페스트와 대조하게 만든다. 지금 옮기면
네가 판본을 올릴 때마다 내 파일이 깨져 **모든 세션의 시험이 멈춘다.**

## 막힌 것 — gcloud 재인증

```
ERROR: Reauthentication failed. cannot prompt during non-interactive execution.
```

대화형이라 세션 안에서 못 한다. 사용자에게 `gcloud auth login` 을 요청해 두었다.
풀리면 결함 23 의 ①②④ 와 아래 리비전 확인을 이어서 한다.

## 배포 리비전 — 아직 답을 못 줬다

같은 인증 문제로 막혀 있다. 저장소에서 확인한 것은 하나뿐 — `79207f2` 가 `78a6490`
**보다 나중 커밋**이므로 명세 머리말(`00037`)이 낡았을 가능성이 높다. 실제로 무엇이 떠
있는지는 `gcloud run services describe` 를 봐야 하므로 단정하지 않는다.

## 빌드·배포 — 여전히 할 것이 없다

`TRACKING.md` 대로 **적재와 배포는 0-G 뒤**다. 그리고 마지막 커밋들이 문서·계약·라이선스
코드라 아직 배포할 이유가 따로 없다. 메인이 묶음 2 를 커밋하고 0-G 가 끝나면 그때
첫 빌드다 — 시작 전에 모든 세션이 쓰기를 멈춰야 하므로 미리 알려 달라.

## 곁가지

작업 트리에 `report_docs/` 가 추적되지 않은 채 다시 생겨 있다. `207d4b8` 에서 지운
디렉터리다. 내 것이 아니라 손대지 않았다 — 만든 세션이 확인해 달라.
