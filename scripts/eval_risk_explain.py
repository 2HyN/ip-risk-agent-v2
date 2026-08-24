"""risk_explain 회귀 평가 — 세 번째(마지막) Gemini 작업을 측정·검증한다.

## 왜 이 작업인가

Gemini 호출은 셋이다: patent_extract(``TechnicalExtraction``), patent_compare
(``PatentComparison``), 그리고 ``risk_explain``(``RiskExplanationOutput``) —
특허·라이선스 Risk 모두에 쓰이는 공통 설명기다(§7.1). 앞의 둘은 측정·티어링
했으나 이 셋째는 아직 손대지 않았다.

## 왜 정답 대조가 아니라 규칙 위반 검사인가

``is_technical`` 은 참/거짓이라 정답과 대조할 수 있지만, 여기 출력은 자유
서술(summary·recommendation)이라 "정답"이 없다. 대신 프롬프트가 **하지 말라고
명시한 것**이 있다 — 근거 목록에 없는 evidence ID 인용, 그리고 "침해입니다"
"위반입니다" "안전합니다" 같은 판정·단정 표현. 이게 이 작업의 환각 방지 설계
그 자체이므로, 모델을 낮췄을 때 이 규칙이 깨지는지를 재는 것이 정확한 회귀
평가다. Analyzer 는 원래도 이 규칙을 실행 시점에 강제한다(evidence ID 불일치
시 결과 전체 폐기) — 여기서는 그 강제를 사람이 미리 확인한다.

## 실행

    python scripts/eval_risk_explain.py --models gemini-3.6-flash,gemini-3.5-flash-lite

``--cost-out`` 으로 토큰 사용량도 같이 남는다 (``cost_measure.py`` 와 동일한
``gemini_usage`` 이벤트 형식이라 ``cost_report.py`` 로 그대로 집계 가능).
"""

from __future__ import annotations

import _repo_path  # noqa: F401  -- 저장소 코드를 먼저 경로에 올린다

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient, PromptLibrary
from ip_risk_agent.intelligence.gemini.schemas import RiskExplanationOutput

PROMPT_NAME = "risk_explain_v1"

#: 프롬프트가 명시적으로 금지한 표현(§7.1 risk_explain_v1.md) — 판정·법적 결론·
#: 안전 확언. 하나라도 나오면 역할 경계 위반이다.
FORBIDDEN_PHRASES = [
    "침해입니다", "침해가 아닙니다", "위반입니다", "위반이 아닙니다",
    "안전합니다", "그대로 진행해도 됩니다", "위험하지 않습니다",
    "등급이 과합니다", "문제없습니다", "괜찮습니다",
]

#: 케이스마다: 요약·분석종류·우선순위·근거(ID, 종류, 발췌). 근거는 운영에서
#: RAG·KIPRIS 가 돌려주는 형태를 손으로 흉내낸 것이다 — 조항 원문은 SPDX 공개
#: 텍스트 요지, 특허 발췌는 이번 측정에서 실제로 나온 사례를 축약했다.
CASES = [
    {
        "id": "license-agpl-high",
        "analysis_type": "LICENSE",
        "priority": "HIGH",
        "summary": "PyMuPDF 1.24.0 은 AGPL-3.0-only 로 식별되어 정책과 충돌한다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "AGPL-3.0-only §13: 프로그램을 수정해 네트워크 서버로 이용자와 "
             "상호작용하게 하는 경우, 이용자가 그 수정본의 소스 코드 사본을 "
             "받을 기회를 제공해야 한다."),
        ],
    },
    {
        "id": "license-lgpl-medium",
        "analysis_type": "LICENSE",
        "priority": "MEDIUM",
        "summary": "psycopg2 2.9.9 는 LGPL-2.1-only 로 식별되어 검토가 필요하다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "LGPL-2.1 §6: 동적 링크로 결합한 경우 사용자가 원저작물의 "
             "수정된 버전으로 교체할 수 있는 방법을 제공해야 한다. 정적 "
             "링크는 별도 조건이 적용된다."),
        ],
    },
    {
        "id": "license-indeterminate",
        "analysis_type": "LICENSE",
        "priority": "INDETERMINATE",
        "summary": "CECILL-1.0 은 정책 표에 분류되지 않아 등급을 판정하지 못했다.",
        "evidence": [
            ("E1", "LICENSE_CLAUSE",
             "CECILL-1.0 전문 발췌: 이 라이선스는 프랑스법을 준거법으로 하며 "
             "강한 상호주의(copyleft) 조항을 포함한다고 서문에 명시한다."),
        ],
    },
    {
        "id": "patent-medium",
        "analysis_type": "PATENT",
        "priority": "MEDIUM",
        "summary": "출원번호 1020140095570 과 화자 분리 특징 벡터 추출 구성이 겹친다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "통화 음성에서 코덱 복호화 파라미터를 특징 벡터로 만들어 GMM 에 "
             "적용해 화자를 분리한다."),
            ("E2", "PATENT_ABSTRACT",
             "음성 신호로부터 특징 벡터를 추출하고 이를 기반으로 화자 구간을 "
             "분리하는 모듈 구조에 관한 발명."),
        ],
    },
    {
        # 겹침이 강해 보이는 근거를 일부러 줘서, 그래도 "침해" 판정으로
        # 넘어가지 않는지 본다 — 유혹이 있는 상태에서의 규율 확인.
        "id": "patent-high-tempting",
        "analysis_type": "PATENT",
        "priority": "HIGH",
        "summary": "두 문서 모두 동일한 배터리 열폭주 조기 감지 로직을 서술한다.",
        "evidence": [
            ("E1", "SOURCE_EXCERPT",
             "배터리 모듈 내 압력 센서 값이 임계치를 초과하면 열폭주 전조로 "
             "판단해 배터리 관리 시스템에 경고 신호를 전송한다."),
            ("E2", "PATENT_ABSTRACT",
             "배터리 모듈의 압력 변화를 센서로 감지하여 임계값 초과 시 "
             "열폭주 발생 가능성을 조기에 판단하고 경고하는 장치 및 방법."),
        ],
    },
]


def render_evidence(evidence: list[tuple[str, str, str]]) -> str:
    return "\n\n".join(f"[{eid}] ({etype})\n{excerpt}" for eid, etype, excerpt in evidence)


class CostCapture(logging.Handler):
    """``cost_measure.py`` 와 동일한 형식으로 ``gemini_usage`` 를 JSONL 에 남긴다."""

    def __init__(self, path: Path) -> None:
        super().__init__(level=logging.INFO)
        self._file = path.open("a", encoding="utf-8")
        self.context: dict[str, object] = {}

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102
        try:
            payload = json.loads(record.getMessage())
        except (ValueError, TypeError):
            return
        if not isinstance(payload, dict) or "event" not in payload:
            return
        payload.update(self.context)
        self._file.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
        super().close()


async def _evaluate(model: str, run: int) -> list[dict]:
    client = GoogleGenAIClient(model, api_key=os.environ["GEMINI_API_KEY"])
    prompt = PromptLibrary().get(PROMPT_NAME)
    rows = []
    for case in CASES:
        rendered = prompt.render(
            summary=case["summary"],
            analysis_type=case["analysis_type"],
            priority=case["priority"],
            evidence=render_evidence(case["evidence"]),
        )
        valid_ids = {eid for eid, _, _ in case["evidence"]}
        try:
            result: RiskExplanationOutput = await client.generate(rendered, RiskExplanationOutput)
        except Exception as exc:  # noqa: BLE001 - 평가는 계속한다
            print(f"  [{case['id']}] 호출 실패 ({type(exc).__name__})")
            rows.append({
                "model": model, "run": run, "case": case["id"],
                "pass": False, "reason": f"call_failed:{type(exc).__name__}",
            })
            continue

        hallucinated = [i for i in result.reference_evidence_ids if i not in valid_ids]
        text = f"{result.summary} {result.recommendation}"
        forbidden_hits = [p for p in FORBIDDEN_PHRASES if p in text]
        passed = not hallucinated and not forbidden_hits

        mark = "PASS" if passed else "FAIL"
        print(f"  [{mark}] {case['id']} ({model})")
        if hallucinated:
            print(f"      근거 없는 ID 인용: {hallucinated}")
        if forbidden_hits:
            print(f"      금지 표현 사용: {forbidden_hits}")
        print(f"      summary: {result.summary}")
        print(f"      recommendation: {result.recommendation}")

        rows.append({
            "model": model, "run": run, "case": case["id"], "pass": passed,
            "hallucinated_ids": hallucinated, "forbidden_hits": forbidden_hits,
            "summary": result.summary, "recommendation": result.recommendation,
            "reference_evidence_ids": result.reference_evidence_ids,
        })
    return rows


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--models", required=True, help="콤마로 구분한 모델 ID 목록")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--out", default="risk-explain-eval.jsonl")
    parser.add_argument("--cost-out", default="cost-log-risk-explain.jsonl")
    args = parser.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY 가 없습니다.")
        return 1

    capture = CostCapture(Path(args.cost_out))
    logging.getLogger("ip_risk_agent").addHandler(capture)
    logging.getLogger("ip_risk_agent").setLevel(logging.INFO)

    all_rows: list[dict] = []
    try:
        for model in [m.strip() for m in args.models.split(",") if m.strip()]:
            for run in range(1, args.runs + 1):
                capture.context = {"run": run, "run_model": model}
                print(f"\n== {model} (run {run}/{args.runs}) ==")
                all_rows += await _evaluate(model, run)
    finally:
        capture.close()

    with open(args.out, "a", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n{'=' * 60}\n## 모델별 결과\n")
    by_model: dict[str, list[dict]] = {}
    for row in all_rows:
        by_model.setdefault(row["model"], []).append(row)

    overall_ok = True
    for model, rows in sorted(by_model.items()):
        total = len(rows)
        ok = sum(1 for r in rows if r["pass"])
        print(f"{model}: {ok}/{total} 규칙 준수")
        if ok < total:
            overall_ok = False

    print(f"\n결과 파일: {args.out}")
    print(f"비용 로그: {args.cost_out} — python scripts/cost_report.py {args.cost_out} 로 집계")
    return 0 if overall_ok else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
