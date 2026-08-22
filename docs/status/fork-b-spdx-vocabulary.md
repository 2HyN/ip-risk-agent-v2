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

`analyzer.py` · `package_metadata.py` · `reference_gate.py` 는 **메인 세션 것**이다.

## 현황 — 2-A · 2-B 끝났고, 분류를 넓혔다

| 커밋 | 무엇 |
|---|---|
| `d4d14d0` | 어휘 42 → **727** (SPDX 3.28.0), `WITH` 예외 평가, 미등록 예외 거부, `OR` 선택 기록 |
| `5cb8c87` | 정책 분류 158 → **226** (OSI 승인 라이선스) |

미분류 OSI 는 74 → **19** 이고, 그중 폐기 표기 매핑으로도 안 덮이는 것은 **6 개**뿐이다 —
`ALGLIB-Documentation` · `Frameworx-1.0` · `OCLC-2.0` · `OLFL-1.3` · `OSC-1.0` · `UCL-1.0`.
**일부러 남겼다.** 전문을 제대로 읽지 않고는 무엇을 요구하는지 정할 수 없었고, 찍어서
분류하면 §1.3 이 경고한 "근거 없는 판정이 기록으로 굳는" 것이 된다. `UNKNOWN` 은 이미
"사람이 보라" 는 뜻이므로 남기는 것이 답이지 구멍이 아니다.

나머지 미분류 OSI 는 폐기 표기라 조회 전에 현행 표기로 바뀐다.

## Fork A 에게 — corpus 에 43 편이 더 필요하다

corpus 가 `needs_review` 대상을 따라가고 있어(현재 70 편, 초과분 0 편) 정책 표를 넓힌
만큼 대상도 늘었다. 지금 **113 편이 필요한데 70 편이 있다.**

없는 43 편에서 두 덩어리가 눈에 띈다.

**(1) `-or-later` 변형이 통째로 없다.** `GPL-2.0-or-later` · `GPL-3.0-or-later` ·
`LGPL-2.1-or-later` · `AGPL-3.0-or-later` · `GFDL-*-or-later` 가 전부 빠져 있다.
**이건 내 확장과 무관하게 원래 있던 구멍이다** — `-or-later` 는 실제 패키지 메타데이터에
`-only` 만큼 흔하다. 전문은 `-only` 와 같으므로 같은 파일을 가리키게 해도 되고, 그 편이
번역·검토 몫을 늘리지 않는다.

**(2) 이번에 새로 분류된 것들** — `APSL-1.0/1.1/1.2`, `SPL-1.0`, `CUA-OPL-1.0`,
`Motosoto`, `Nokia`, `OSET-PL-2.1`, `CATOSL-1.1`, `LPL-1.0/1.02`, `RSCPL`, `APL-1.0`,
`LiLiQ-R-1.1`, `LiLiQ-Rplus-1.1`, `CPAL-1.0`, `RPSL-1.0`, `CAL-1.0`,
`CAL-1.0-Combined-Work-Exception`, `CERN-OHL-S-2.0`, `CERN-OHL-W-2.0`, `NGPL`,
`SimPL-2.0`, `Watcom-1.0`, `OGTSL`, `LPPL-1.3a/1.3c`, `IPA`, `Artistic-1.0-cl8`,
`OFL-1.1-RFN`, `OFL-1.1-no-RFN`, `MPL-2.0-no-copyleft-exception`.

목록은 이 명령으로 언제든 다시 뽑을 수 있다.

```
python - <<'PY'
import sys, os, glob
sys.path.insert(0, "backend/src"); sys.path.insert(0, "shared/contracts/python")
from ip_risk_agent.intelligence.license import policy
need = {i for i, o in policy._OUTCOME_BY_ID.items() if policy.needs_review(o)}
have = {os.path.basename(p)[5:-3] for p in glob.glob("rag-corpus/licenses/spdx-*.md")}
print(sorted(i for i in need if i.lower() not in have))
PY
```

**서두를 것은 아니다.** TRACKING 이 적재를 0-G 뒤로 묶어 두었으니 전문이 늘어도 지금은
올라가지 않는다. 다만 43 편이 비어 있는 채로 적재하면 그 라이선스들은 근거 없이 판정된다.

## 메인 세션에게

**1. 0-G 가 쓸 것이 이미 있다.** `policy.evaluate(expression)` 이
`Evaluation(outcome, leading, all_leaves, notes)` 를 준다.

* `leading` — 판정을 이끈 leaf (AND 면 가장 무거운 것, OR 이면 택한 것). `is_relevant` 가
  전체 leaf 대신 이것을 보면 §5.5 의 반대 근거 부착이 닫힌다.
* `notes` — OR 이 무엇을 버렸는지, 예외가 무엇을 완화했는지, **등록되지 않은 예외가
  달려 있는지**. §7.3 의 "보이는 하향" 재료다.

`evaluate_expression()` 은 그대로라 `analyzer.py` 를 고치지 않아도 된다.

**2. `POLICY_VERSION` 이 `global-license-policy-2026-08-23.1` 이다.** 저장된 판정과 전부
다르게 나오고, §7.4 의 "우리 지식" 원인으로 잡히는 것이 맞다.

**3. 이행(§11.6)에서 Risk 정체성이 움직인다.** `license_risk_key` 가
`normalized_license_expression` 을 포함하는데, `UNKNOWN` 으로 저장되던 것이 이제 제 이름으로
저장된다. 의도한 방향이지만 **그 Risk 에 붙은 사용자 처분은 따라오지 않는다.** 발견이
아니라 계산으로 처리해야 할 몫이다. `GPL-2.0-with-classpath-exception` 같은 폐기 합성
표기도 같은 이유로 key 가 움직인다.

## 커밋 규칙에 덧붙일 것 — `&&` 로는 안 막힌다

새 규칙이 `git add <경로들> && git commit` 또는 `git commit -- <경로들>` 둘 다 허용하는데,
**앞의 것은 막지 못한다.**

증거가 내 커밋이다. `366ffff` 는 `git add docs/status/fork-b-spdx-vocabulary.md && git
commit` 한 호출이었는데 **81 개 파일**이 담겼다. `git commit` 은 `--` 없이는 그 시점의
**인덱스 전체**를 담으므로, 다른 세션이 `git add` 를 끝낸 상태면 그것이 함께 간다. 틈이
아니라 인덱스가 공유 자원인 것이 원인이다.

**`git commit -- <경로들>` 만이 확실하다.** 인덱스에 무엇이 있든 그 경로만 담는다.
`5cb8c87` 을 그 형태로 했고 파일 1 개로 나왔다.

## 알아 둘 것 — 예외 표에서 정작 중요한 부분

완화하는 예외를 모으는 것보다 **완화처럼 보이지만 완화가 아닌 것**을 가려내는 쪽이
중요했다.

* **OpenSSL 예외 8 종** — GPL 과 OpenSSL 의 **비양립**을 푸는 장치다. 비공개 배포와는
  무관하다. 완화로 넣었다면 **거짓 하향**이 되고 거짓 하향은 알림 없이 사라진다.
* **Universal-FOSS · RRDtool-FLOSS · DigiRule-FOSS** — 결합물을 **오픈소스로 배포할
  때만** 쓸 수 있다.
* **GPL-CC-1.0** — 위반 시 유예를 주겠다는 약속이지 면제가 아니다.

완화는 `POLICY_CONFLICT → REVIEW_REQUIRED` 한 칸에서 멈춘다. 예외가 붙이는 조건(수정
여부·링크 방식·무엇을 배포하는가)은 코드가 확인할 수 없으므로, 확인하지 않은 것을
충족했다고 단정하지 않는다.

## 남은 것

* 예외 84 개 중 **53 개** 분류. 나머지는 "등록됐지만 아직 분류하지 않았다" 로 표시되고
  완화하지 않는다 — 안전한 방향이다.
* 라이선스 727 개 중 **226 개** 분류. 남은 501 개는 OSI 승인이 아니거나 폐기 표기이고,
  실사용에서 걸리는 것이 나오면 그때 채운다.
* 목록 갱신은 `python scripts/generate_spdx_data.py`, 확인만은 `--check`.
  **자동으로 따라가지 않는다** — 목록이 바뀌면 판정이 바뀔 수 있어 사람이 diff 를 본다.
