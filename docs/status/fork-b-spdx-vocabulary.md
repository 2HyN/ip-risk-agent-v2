# Fork B — SPDX 어휘와 예외 표

`DEVELOPMENT_SPEC.md` 의 2-A · 2-B 를 맡는다.

## 쥐고 있는 파일

```
backend/src/ip_risk_agent/intelligence/license/spdx.py
backend/src/ip_risk_agent/intelligence/license/policy.py
backend/src/ip_risk_agent/intelligence/license/spdx_data.py   (생성물)
scripts/generate_spdx_data.py
tests/intelligence/test_spdx_vocabulary.py
tests/intelligence/test_license_exceptions.py
```

`analyzer.py` 와 `package_metadata.py` 는 **메인 세션 것**이다.
`reference_gate.py` 도 내 것이 아니다 — 아래 "Fork A 에게" 를 보라.

## 현황 — 2-A · 2-B 끝났다 (`d4d14d0`)

어휘가 SPDX **3.28.0 전체 727 개**다. 예외 84 개도 함께 들어왔다. 정책 표는 **158 개만**
분류했고 나머지는 `UNKNOWN` 이다.

`WITH` 예외가 평가에 반영된다. 완화는 `POLICY_CONFLICT → REVIEW_REQUIRED` 한 칸에서
멈춘다 — 예외가 붙이는 조건(수정 여부·링크 방식·무엇을 배포하는가)은 코드가 확인할 수
없으므로 사람이 볼 자리까지만 내린다.

§5.3 표의 다섯 줄이 전부 의도한 값이 됐다. 시험 65 건으로 고정했다.

## 브리핑의 전제 하나가 틀렸다

> "두 표의 양방향 차집합이 공집합이고 **시험이 그것을 고정하고 있으므로** 두 표를 함께
> 넓혀야 한다"

**그런 시험은 없었다.** 저장소 전체에서 `_CANONICAL` 과 `_OUTCOME_BY_ID` 를 참조하는 곳은
두 모듈 자신뿐이었다. 42 = 42 는 실측이었지 강제된 불변조건이 아니었다.

그리고 **같게 맞추는 것이 목표가 되면 안 된다.** 같게 맞추려면 727 개를 전부 분류해야
하고, 그것은 근거 없는 법적 단정을 700 개쯤 만드는 일이다. 어휘(등록된 식별자인가)와
판단(어느 등급인가)을 갈랐다.

대신 **방향이 있는 불변조건**을 시험으로 새로 걸었다 — 정책 표의 모든 식별자는 실재하는
SPDX 식별자여야 한다. 반대는 요구하지 않는다. 정책 표의 오타는 그냥 두면 **영원히
`UNKNOWN`** 으로 나타나 아무도 못 알아챈다.

## 메인 세션에게

**1. 0-G 가 쓸 API 가 준비됐다.** `policy.evaluate(expression)` 이
`Evaluation(outcome, leading, all_leaves, notes)` 를 준다.

* `leading` — 판정을 이끈 leaf. AND 면 가장 무거운 것, OR 이면 택한 것. §5.5 의 게이트가
  "표현식의 모든 leaf" 대신 이것을 보면 반대 근거 부착이 닫힌다.
* `notes` — OR 이 무엇을 버렸는지, 예외가 무엇을 완화했는지, 등록되지 않은 예외가
  달려 있는지. §7.3 의 "보이는 하향" 재료다.

`evaluate_expression()` 은 그대로 `LicensePolicyOutcome` 만 준다. 기존 호출부
(`analyzer.py:149`)는 고치지 않아도 된다.

**2. `POLICY_VERSION` 이 `global-license-policy-2026-08-23.1` 로 올라갔다.** 저장된 판정과
비교하면 전부 다르게 나온다. §7.4 의 "우리 지식" 원인으로 잡힐 것이고, 그것이 맞다.

**3. 이행(§11.6)에서 조심할 것 — Risk 정체성이 움직인다.**

어휘가 넓어져 `BUSL-1.1` 이 이제 `UNKNOWN` 이 아니라 `BUSL-1.1` 로 저장된다. 그런데
`license_risk_key` 가 `normalized_license_expression` 을 포함하므로
(`risk_reconcile/service.py`), **그런 Risk 는 key 가 바뀌어 다른 Risk 가 된다.**

D10(§7.5)은 "정체성 현행 유지" 라고 했고 그 근거가 마이그레이션 위험이었다. 이 변경은
의도한 것이지만(§5.2 가 요구한 방향이다) **사용자가 그 Risk 에 붙인 처분은 따라오지
않는다.** 0-F 와 함께 이행을 계획할 때 이 몫을 세어야 한다. 지금 저장된 데이터가 적어
실제 피해는 작을 수 있으나, 세어 보지 않고 넘어갈 일은 아니다.

**4. 폐기 표기가 다르게 정규화된다.** `GPL-2.0-with-classpath-exception` 이 예전에는 맨
`UNKNOWN` 이었고 지금은 `GPL-2.0-only WITH Classpath-exception-2.0` 이다. 같은 이유로 key
가 움직인다.

## Fork A 에게

`backend/src/ip_risk_agent/intelligence/license/reference_gate.py` 를 고치고 있는데,
그 파일은 **메인 세션 몫**으로 배분됐다 (0-G 게이트 로직). 커버리지 색인을 **데이터로만**
내놓기로 했던 경계다. `corpus_coverage.json` 을 읽는 코드까지 필요했다면 메인과 먼저
맞추는 편이 안전하다 — 0-G 가 같은 함수(`is_relevant`)를 판정 leaf 기준으로 다시 쓴다.

그리고 지금 `tests/integration/test_deployment_assets.py::test_rag_ingestion_dry_run_is_manifest_bounded_and_write_free`
가 실패한다 (`spdx-epl-1.0` vs `spdx-elastic-2.0`). 작업 중 상태로 보이지만, 전체 시험을
돌리는 다른 세션에게는 내 변경으로 보일 수 있어 적어 둔다.

## 알아 둘 것 — 표에서 가장 중요한 부분

완화하는 예외를 모으는 것보다 **완화처럼 보이지만 완화가 아닌 것**을 가려내는 쪽이
중요했다.

* **OpenSSL 예외들**(openvpn · vsftpd · kvirc · stunnel · cryptsetup · x11vnc ·
  sqlitestudio · libpri) — GPL 과 OpenSSL 의 **비양립**을 푸는 장치다. 우리의 비공개
  배포와는 무관하다. 완화로 분류했다면 **거짓 하향**이 되고, 거짓 하향은 알림 없이
  사라진다 (§7.3 의 비대칭).
* **Universal-FOSS-exception-1.0 · RRDtool-FLOSS · DigiRule-FOSS** — 결합물을
  **오픈소스로 배포할 때만** 쓸 수 있다.
* **GPL-CC-1.0** — 위반 시 유예를 주겠다는 약속이지 의무의 면제가 아니다.

분류마다 근거 문자열을 함께 저장한다. 시험이 빈 근거를 막는다.

## 남은 것

* 예외 84 개 중 **53 개만** 효과를 분류했다. 나머지는 "등록됐지만 아직 분류하지 않았다"
  로 표시되고 완화하지 않는다 — 안전한 방향이다. 실사용에서 걸리는 것이 나오면 그때 채운다.
* 라이선스 727 개 중 **158 개만** 분류했다. 같은 이유로 넓히는 것은 수요를 보고 한다.
* 목록 갱신은 `python scripts/generate_spdx_data.py` 이고 `--check` 로 최신인지만 볼 수
  있다. **자동으로 따라가지 않는다** — 목록이 바뀌면 판정이 바뀔 수 있어 사람이 diff 를
  본다.
