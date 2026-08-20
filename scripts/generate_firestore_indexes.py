"""코드의 index manifest 를 배포 가능한 firestore.indexes.json 으로 바꾼다.

``REQUIRED_COMPOSITE_INDEXES`` 는 query 가 요구하는 필드 조합이지 배포 파일
형식이 아니다. 손으로 옮겨 적으면 코드가 바뀔 때 조용히 어긋난다. 그래서
생성한다.

실행:

    python scripts/generate_firestore_indexes.py            # deploy/ 에 기록
    python scripts/generate_firestore_indexes.py --check    # 최신인지 확인만

``--check`` 는 CI 에서 쓴다. 코드가 바뀌었는데 배포 파일을 다시 만들지 않았으면
0 이 아닌 코드로 끝난다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "deploy" / "firestore" / "firestore.indexes.json"

sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "shared" / "contracts" / "python"))

from ip_risk_agent.persistence.core_firestore.schema import (  # noqa: E402
    REQUIRED_COMPOSITE_INDEXES,
)


def build_document() -> dict:
    """gcloud 가 그대로 먹는 형식으로 만든다.

    모든 필드는 equality/IN lookup 에 쓰이므로 ASCENDING 이면 충분하다.
    정렬은 현재 application 메모리에서 deterministic 하게 수행한다.
    """
    indexes = [
        {
            "collectionGroup": index.collection,
            "queryScope": "COLLECTION",
            "fields": [
                {"fieldPath": field, "order": "ASCENDING"} for field in index.fields
            ],
        }
        for index in REQUIRED_COMPOSITE_INDEXES
    ]
    return {"indexes": indexes, "fieldOverrides": []}


def render() -> str:
    return json.dumps(build_document(), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="파일을 쓰지 않고 최신 상태인지만 확인한다",
    )
    args = parser.parse_args()

    rendered = render()
    if args.check:
        if not OUTPUT.exists():
            print(f"missing: {OUTPUT.relative_to(ROOT)}", file=sys.stderr)
            return 1
        if OUTPUT.read_text(encoding="utf-8") != rendered:
            print(
                f"stale: {OUTPUT.relative_to(ROOT)} — "
                "python scripts/generate_firestore_indexes.py 를 실행하세요",
                file=sys.stderr,
            )
            return 1
        print(f"up to date: {len(REQUIRED_COMPOSITE_INDEXES)} indexes")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(REQUIRED_COMPOSITE_INDEXES)} indexes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
