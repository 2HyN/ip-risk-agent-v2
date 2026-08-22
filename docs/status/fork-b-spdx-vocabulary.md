# Fork B — SPDX 어휘와 예외 표

`DEVELOPMENT_SPEC.md` 의 2-A · 2-B 를 맡는다.

## 쥐고 있는 파일

```
backend/src/ip_risk_agent/intelligence/license/spdx.py
backend/src/ip_risk_agent/intelligence/license/policy.py
그리고 그 시험
```

`analyzer.py` 와 `package_metadata.py` 는 **메인 세션 것**이다.

## 할 일

1. **어휘를 SPDX 전체로 넓힌다.** 지금 `spdx._CANONICAL` 과 `policy._OUTCOME_BY_ID` 가
   각각 42 개이고 **양방향 차집합이 공집합**이다. 시험이 그것을 고정하고 있으므로 두
   표를 **함께** 넓혀야 한다.
2. **`WITH` 예외를 평가에 반영한다.** 파서는 예외를 제대로 읽어 `LicenseNode.exception`
   에 담는데(`spdx.py:227`) 정책이 그 필드를 **한 번도 보지 않는다**(`policy.py:90-92`).
3. **예외 식별자를 검증한다.** 지금은 `MIT WITH totally-made-up` 이 그냥 통과한다.
   목록에 없으면 완화하지 않고 `UNKNOWN` 으로 다룬다.
4. **`OR` 이 어느 쪽을 택했는지 기록한다.** 지금은 조용히 최소 심각도를 고르고 그 선택이
   원장에 남지 않는다.

## 완료 조건

`DEVELOPMENT_SPEC.md` §5.3 의 표 다섯 줄이 전부 의도한 값이 된다.

| 표현식 | 지금 | 되어야 할 것 |
|---|---|---|
| `GPL-2.0-only WITH Classpath-exception-2.0` | `POLICY_CONFLICT` | 예외가 완화한다 |
| `MIT WITH totally-made-up` | `NOTICE_REQUIRED` | 날조된 예외는 완화 못 얻는다 |
| `AGPL-3.0-only OR MIT` | `NOTICE_REQUIRED` | 값은 같아도 **선택이 기록된다** |

## 알아 둘 것

**예외가 의무를 완화하는 표는 SPDX 가 주지 않는다.** 목록만 준다. Classpath · GCC · LLVM
처럼 널리 쓰이는 것부터 손으로 채우게 되고, 분류 하나하나가 법적 판단이라 **근거를 함께
남겨야 한다.** 근거 없는 완화는 나중에 되짚을 수 없다.

정책 표 밖 식별자는 `UNKNOWN` 이되, 메인이 0-F 로 **원문자열을 보존**하면 표가 넓어질 때
재평가로 구제된다. 그 전까지는 표를 넓혀도 이미 저장된 `UNKNOWN` 은 살아나지 않는다.

## 현황

<!-- 여기에 적는다 -->
