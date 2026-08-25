"""라이선스 원문 대조 CLI (1-L1 데모·수동 검증용).

    python scripts/match_license_text.py <파일> [--declared MIT] [--top 3]

파일의 텍스트를 SPDX 전문 지문 672편과 대조해 최근접 후보와 점수를 보여 준다.
``--declared`` 를 주면 선언된 식별자와 원문 최근접이 갈리는지도 말한다 —
판정이 아니라 관측이다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from ip_risk_agent.intelligence.license.text_match import LicenseTextMatcher


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="대조할 라이선스 텍스트 파일")
    parser.add_argument("--declared", help="레지스트리/저장소가 선언한 SPDX 식별자")
    parser.add_argument("--top", type=int, default=3)
    args = parser.parse_args()

    text = Path(args.path).read_text(encoding="utf-8", errors="replace")
    matcher = LicenseTextMatcher.load_bundled()
    matches = matcher.match(text, top_k=args.top)

    print(f"corpus {matcher.corpus_version} · 후보 {args.top}개")
    if not matches:
        print("대조 불가 — 텍스트가 너무 짧다 (5어절 미만)")
        return 0
    for match in matches:
        covered = ", ".join(match.covers[:4]) + ("…" if len(match.covers) > 4 else "")
        marker = "정규화 동일" if match.exact else f"{match.score:.2%}"
        print(f"  {match.source_id:34} {marker:>10}  [{covered}]")

    if args.declared:
        best = matches[0]
        if args.declared in best.covers:
            state = "일치" if best.exact else f"일치하나 변형 의심 ({best.score:.2%})"
        else:
            state = f"불일치 — 원문 최근접은 {best.source_id}"
        print(f"선언 {args.declared!r} vs 원문: {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
