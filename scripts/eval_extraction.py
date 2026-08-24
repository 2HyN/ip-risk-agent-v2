"""TechnicalExtraction 회귀 평가 — 모델 티어링 결정을 정성 판단에서 숫자로 옮긴다.

## 왜 필요한가

``compare_quality.py`` 는 사람이 눈으로 읽고 판단하는 정성 비교다. 그것으로
"lite 도 괜찮아 보인다" 까지는 말할 수 있어도 "N/N 정확히 일치했다" 는 말할 수
없다. 여기서는 ``samples/patent`` 의 정답을 미리 고정해 두고, 모델이 그 정답과
같은지를 자동으로 채점한다. 팀이 이미 쓰는 패턴이다(P-01~P-03, ``is_technical``
분류 정확성).

## 정답을 어떻게 정했는가

파일 이름과 내용을 보고 사람이 미리 판단했다 — 4편은 구체적 처리 방식·구조·
알고리즘이 서술된 기술 문서, 1편(``negative-weekly-meeting-notes.md``)은
회의록이라 비기술 문서다. 이 판단 기준은 ``patent_extract`` 프롬프트의
``is_technical`` 정의(§7.1)와 같다.

## 실행

    python scripts/eval_extraction.py --models gemini-3.6-flash,gemini-3.5-flash-lite

모델을 콤마로 여러 개 넘기면 한 번에 비교표가 나온다. ``--runs`` 로 반복하면
같은 모델 안에서의 흔들림(비결정성)도 같이 본다.
"""

from __future__ import annotations

import _repo_path  # noqa: F401  -- 저장소 코드를 먼저 경로에 올린다

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient, PromptLibrary
from ip_risk_agent.intelligence.gemini.schemas import TechnicalExtraction

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = REPO_ROOT / "samples" / "patent"

#: 파일 이름 → 정답(is_technical). 새 샘플을 추가하면 여기도 같이 채운다 —
#: 정답 없는 문서는 채점하지 않고 건너뛴다(누락을 "틀림"으로 세지 않는다).
GROUND_TRUTH: dict[str, bool] = {
    "battery-thermal-runaway-detection-design.md": True,
    "negative-weekly-meeting-notes.md": False,
    "s5-replacement-warehouse-picking.md": True,
    "speaker-diarization-recording-analysis.md": True,
    "voice-phishing-detection-design.md": True,
}

DEFAULT_DOC_CHARS = 6000


async def _evaluate(model: str, run: int, doc_chars: int) -> list[dict]:
    client = GoogleGenAIClient(model, api_key=os.environ["GEMINI_API_KEY"])
    prompt = PromptLibrary().get("patent_extract_v2")
    rows = []
    for filename, expected in sorted(GROUND_TRUTH.items()):
        path = SAMPLES / filename
        if not path.is_file():
            print(f"  건너뜀 (파일 없음): {filename}")
            continue
        text = path.read_text(encoding="utf-8")[:doc_chars]
        segments = f"[seg-1]\n{text}"
        try:
            result: TechnicalExtraction = await client.generate(
                prompt.render(segments=segments), TechnicalExtraction
            )
        except Exception as exc:  # noqa: BLE001 - 평가는 계속한다
            print(f"  {filename}: 호출 실패 ({type(exc).__name__})")
            rows.append({
                "model": model, "run": run, "file": filename,
                "expected": expected, "actual": None, "pass": False,
                "query_count": 0,
            })
            continue
        passed = result.is_technical == expected
        mark = "PASS" if passed else "FAIL"
        print(
            f"  [{mark}] {filename}: expected={expected} actual={result.is_technical}"
            f" queries={len(result.search_queries)}"
        )
        rows.append({
            "model": model, "run": run, "file": filename,
            "expected": expected, "actual": result.is_technical, "pass": passed,
            "query_count": len(result.search_queries),
        })
    return rows


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--models", required=True, help="콤마로 구분한 모델 ID 목록")
    parser.add_argument("--runs", type=int, default=1, help="모델당 반복 횟수 (비결정성 확인용)")
    parser.add_argument("--doc-chars", type=int, default=DEFAULT_DOC_CHARS)
    parser.add_argument("--out", default="extraction-eval.jsonl")
    args = parser.parse_args()

    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY 가 없습니다.")
        return 1

    all_rows: list[dict] = []
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        for run in range(1, args.runs + 1):
            print(f"\n== {model} (run {run}/{args.runs}) ==")
            all_rows += await _evaluate(model, run, args.doc_chars)

    with open(args.out, "a", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\n{'=' * 60}\n## 모델별 정확도\n")
    by_model: dict[str, list[dict]] = {}
    for row in all_rows:
        by_model.setdefault(row["model"], []).append(row)

    overall_ok = True
    for model, rows in sorted(by_model.items()):
        total = len(rows)
        correct = sum(1 for r in rows if r["pass"])
        accuracy = correct / total * 100 if total else 0.0
        print(f"{model}: {correct}/{total} ({accuracy:.0f}%)")
        if correct < total:
            overall_ok = False
            for r in rows:
                if not r["pass"]:
                    print(f"    불일치: {r['file']} expected={r['expected']} actual={r['actual']}")

    print(f"\n결과 파일: {args.out}")
    if overall_ok:
        print("모든 모델이 정답과 100% 일치했습니다.")
    else:
        print("일부 모델에서 불일치가 있습니다 — 위 목록을 확인하세요.")
    return 0 if overall_ok else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
