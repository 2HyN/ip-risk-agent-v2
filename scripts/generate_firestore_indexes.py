"""코드의 index manifest 를 배포 가능한 형태로 바꾼다.

``REQUIRED_COMPOSITE_INDEXES`` 는 query 가 요구하는 필드 조합이지 배포 파일
형식이 아니다. 손으로 옮겨 적으면 코드가 바뀔 때 조용히 어긋난다. 그래서
생성한다.

두 가지를 만든다. 도구마다 형식이 다르기 때문이다.

- ``firestore.indexes.json`` — Firebase CLI (``firebase deploy``) 형식
- ``create-indexes.sh`` — gcloud 형식. gcloud 는 인덱스를 하나씩 개별 플래그로
  받으므로 파일을 통째로 넘길 수 없다

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
SCRIPT_OUTPUT = ROOT / "deploy" / "firestore" / "create-indexes.sh"

sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "shared" / "contracts" / "python"))

from ip_risk_agent.persistence.core_firestore.schema import (  # noqa: E402
    REQUIRED_COMPOSITE_INDEXES,
)


def build_document() -> dict:
    """Firebase CLI 가 그대로 먹는 형식.

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


def render_json() -> str:
    return json.dumps(build_document(), indent=2, ensure_ascii=False) + "\n"


def render_script() -> str:
    """gcloud 로 바로 실행할 수 있는 형태."""
    lines = [
        "#!/usr/bin/env bash",
        "# 코드의 REQUIRED_COMPOSITE_INDEXES 에서 생성됨. 손으로 고치지 않는다.",
        "# 다시 만들려면: python scripts/generate_firestore_indexes.py",
        "#",
        "# 이미 존재하는 인덱스는 ALREADY_EXISTS 로 실패한다. 정상이며 무시해도 된다.",
        "# 그래서 하나가 실패해도 나머지를 계속 시도하도록 set -e 를 쓰지 않는다.",
        "set -uo pipefail",
        "",
        'DATABASE="${FIRESTORE_DATABASE:-(default)}"',
        "",
    ]
    for index in REQUIRED_COMPOSITE_INDEXES:
        parts = [
            "gcloud firestore indexes composite create \\",
            '    --database="$DATABASE" \\',
            f"    --collection-group={index.collection} \\",
        ]
        configs = [
            f"    --field-config=field-path={field},order=ascending"
            for field in index.fields
        ]
        # 마지막 줄에는 줄바꿈 이스케이프를 붙이지 않는다.
        configs = [line + " \\" for line in configs[:-1]] + [configs[-1]]
        lines.extend(parts + configs)
        lines.append("")

    lines.extend(
        [
            f'echo "요청한 인덱스 {len(REQUIRED_COMPOSITE_INDEXES)}개."',
            'echo "생성 상태 확인:"',
            "echo \"  gcloud firestore indexes composite list "
            '--format=\'table(name.basename(),state)\'"',
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="파일을 쓰지 않고 최신 상태인지만 확인한다",
    )
    args = parser.parse_args()

    targets = ((OUTPUT, render_json()), (SCRIPT_OUTPUT, render_script()))

    if args.check:
        for path, expected in targets:
            if not path.exists():
                print(f"missing: {path.relative_to(ROOT)}", file=sys.stderr)
                return 1
            if path.read_text(encoding="utf-8") != expected:
                print(
                    f"stale: {path.relative_to(ROOT)} — "
                    "python scripts/generate_firestore_indexes.py 를 실행하세요",
                    file=sys.stderr,
                )
                return 1
        print(f"up to date: {len(REQUIRED_COMPOSITE_INDEXES)} indexes")
        return 0

    for path, content in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")
    print(f"{len(REQUIRED_COMPOSITE_INDEXES)} indexes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
