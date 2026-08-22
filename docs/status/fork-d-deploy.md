# Fork D — 빌드·배포

빌드와 배포를 전담한다. **다른 세션은 빌드 중 쓰기를 멈춘다.**

## 쥐고 있는 파일

```
deploy/**
```

## 지금 가장 급한 것 — 결함 23

**런타임 SA 에 `secrets.delete` 가 없어 workspace 삭제가 끝나지 못한다.**
`deploy/iam-policy-contract.yaml` 이 주는 Secret 권한은 셋뿐이고(`secrets.create`,
`versions.add`, `versions.access`) `secrets.delete` 가 **0 건**이다. 그런데
`gcp/secret_vault.py` 의 `delete()` 는 `delete_secret` 을 부르고 `NotFound` 만 잡으며,
`gcp/operational_eraser.py:90-99` 는 그 실패를 **일부러 올린다.** 그래서 자격증명이 붙은
workspace 는 `DELETING` 에서 영영 재시도만 한다.

순서는 `DEVELOPMENT_SPEC.md` §9.4 에 있다.

1. **실제 IAM 에 무엇이 붙어 있는지 먼저 확인한다.** 계약 파일과 실제 정책이 다를 수 있다.
2. 없으면 `secretmanager.secrets.delete` 를 `iprisk-v2-cred-` prefix 조건으로 붙인다.
   `secrets.create` 와 달리 **삭제는 존재하는 secret 에 평가되므로 prefix 조건이 실제로
   걸린다.**
3. `deploy/iam-policy-contract.yaml` 의 표와 custom role 을 함께 고친다.
4. **자격증명이 붙은 workspace 를 실제로 지워** 끝나는지 본다. 계약 파일만 고치면 그대로다.

## 확인해 줄 것

**배포 리비전이 문서마다 다르다.** `DEVELOPMENT_SPEC.md` 머리말은 `00037`(`78a6490`),
`GITHUB_LOCAL_DESKTOP_PLAN.md` 는 `00038`(`79207f2`) 인데 후자가 나중 커밋이다. 실제로
무엇이 떠 있는지 확인해 이 파일에 적어 달라 — 어느 세션이 배포할지에 직결된다.

## 알아 둘 것

Fork A 가 corpus 를 넓히면 `scripts/validate_gcp_deployment.py` 가 막는다
(`corpus_version` 과 소스 3 건이 하드코딩). 그 수정은 Fork A 가 한다. 배포는 그 뒤다.

## 현황

<!-- 여기에 적는다 -->
