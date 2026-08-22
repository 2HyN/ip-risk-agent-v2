# 메인 세션 — 0 단계 오답 제거

`DEVELOPMENT_SPEC.md` §11 의 0 단계 전부와, 그 뒤 1·3 단계를 맡는다.

## 쥐고 있는 파일

건드리지 말아 주기 바란다.

```
backend/src/ip_risk_agent/core/risk/**
backend/src/ip_risk_agent/core/artifacts/**
backend/src/ip_risk_agent/application/risk_reconcile/**
backend/src/ip_risk_agent/application/security_gate/**
backend/src/ip_risk_agent/application/process_change/**
backend/src/ip_risk_agent/connectors/**
backend/src/ip_risk_agent/intelligence/license/analyzer.py
backend/src/ip_risk_agent/intelligence/license/package_metadata.py
backend/src/ip_risk_agent/intelligence/license/manifests.py
backend/src/ip_risk_agent/intelligence/license/lockfiles.py
tests/control/**  tests/connectors/**  tests/intelligence/test_license.py
```

`spdx.py` 와 `policy.py` 는 **Fork B 것**이라 건드리지 않는다. `rag-corpus/**` 와
`scripts/**` 는 **Fork A 것**이다.

**`reference_gate.py` 는 지금 둘이 겹친다.** Fork A 가 2-D(커버리지 표를 데이터로)를
하면서 이 파일의 **불러오는 쪽**을 이미 고쳤다. 나는 0-G 에서 **거르는 쪽**(`is_relevant`
가 판정을 이끈 leaf 만 보게 하는 것)이 필요하다. 겹치지 않게 **Fork A 의 변경이 커밋된
뒤에** 0-G 를 시작한다. 그전까지 이 파일에 손대지 않는다.

## 끝난 것

**묶음 1 — 잘못된 해소를 멈춘다.**

* **0-L 1 걸음** — 의존성 파일에서 후보가 0 건인 결과는 해소 권한을 갖지 못한다.
  `core/risk/transitions.py` 의 `absence_can_resolve()` 가 규칙이고,
  `risk_reconcile/service.py` 의 해소 루프가 그 앞에서 멈춘다. 막힐 때
  `risk_resolution_withheld` 를 남긴다.
  선언이 하나라도 나왔으면 막지 않는다 — 그건 사람이 의존성을 지운 것이다.
  특허 경로에는 걸지 않는다.
* **0-I** — 라이선스 경로에 진단 로그가 생겼다. `license_analysis_diagnostic` 이
  조각 수·선언 수·후보 수·형식·coverage 를 함께 남긴다. **패키지 이름과 파일 경로는
  넣지 않는다** — 되짚는 수단은 `artifact_id` 와 `revision` 이다.

## 다음

**묶음 2 — 손실 경로 넷.** 0-A 통짜 분석 · 0-B redaction · 0-C 파서 실패 구분 ·
0-D `content_scope`, 그리고 짝인 0-E `PARTIAL` 좁히기. 0-C 가 끝나면 0-L 2 걸음(정상
제거는 다시 해소되게)을 붙인다.

## 다른 세션이 알아야 할 것

**Fork A 에게** — `reference_gate.py` 의 불러오는 쪽을 이미 고친 것을 봤다. 좋다.
다만 지금 `tests/integration/test_deployment_assets.py` 두 건이 실패한다 —
`corpus_coverage.json` 이 wheel 에 선언되지 않았다(`[tool.setuptools.package-data]`).
**그 변경을 커밋해 달라.** 커밋된 뒤에 내가 같은 파일의 `is_relevant` 를 0-G 로 고친다.
동시에 쓰면 서로의 앵커가 깨진다.

**Fork B 에게** — 0-F(원문자열 보존)는 `package_metadata.py` 세 곳을 고치는 일이고
`spdx.py` 의 `canonicalize` 자체는 건드리지 않을 생각이다. 어휘를 넓힐 때
`_CANONICAL` 과 `policy._OUTCOME_BY_ID` 가 **정확히 같은 집합**이어야 한다는 시험이
이미 있다 (양방향 차집합이 공집합).

**Fork D 에게** — 결함 23 이 급하다. 런타임 SA 에 `secrets.delete` 가 없어 자격증명이
붙은 workspace 가 `DELETING` 에서 영영 끝나지 않는다. `DEVELOPMENT_SPEC.md` §9.4 에
확인 순서를 적어 두었다.

**모두에게** — 배포 리비전이 문서마다 다르다. 명세 머리말은 `00037`(`78a6490`),
`GITHUB_LOCAL_DESKTOP_PLAN.md` 는 `00038`(`79207f2`)이고 후자가 나중 커밋이다. 실제로
무엇이 떠 있는지는 Fork D 가 확인해 주기 바란다.
