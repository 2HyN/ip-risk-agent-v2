"""SPDX 라이선스 전문으로 RAG corpus 를 만든다.

## 왜 전문인가

파이프라인 3 단계는 **조회**다 (`DEVELOPMENT_SPEC.md` §5.1). 식별자를 이미 알고
있으므로 임베딩으로 찾지 않는다 — `AGPL-3.0-only` 와 `GPL-3.0-only` 를 헷갈리면
정반대의 근거가 붙는다. 4 단계가 그 전문 **안에서** 배포 형태에 걸리는 조항을 찾는다.
그래서 corpus 에 들어가야 하는 것은 해설이 아니라 라이선스 본문이다.

SPDX license-list-data 는 CC0 이라 자유롭게 쓸 수 있다.

## 무엇을 넣는가

`needs_review` 가 참인 식별자만 넣는다. 나머지는 정책 표가 이미 결론을 내므로 RAG 를
부르지 않고, 넣어 봤자 **오부착 원천만 늘린다** (§5.5). 정책 표가 넓어지면 이 스크립트를
다시 돌리면 되고, 그때 대상도 함께 넓어진다.

## 왜 스크립트인가

손으로 만들면 다음 사람이 같은 corpus 를 다시 만들 수 없다. 그러면 `rag_corpus_version`
이 내용을 설명하지 못한다 — 판정이 왜 달라졌는지 되짚는 §7.4 의 전제가 무너진다.

받은 것을 그대로 쓰지 않고 **본문이 같은 식별자를 한 문서로 묶는다.** `GPL-3.0-only` 와
`GPL-3.0-or-later` 는 같은 글이고, 따로 넣으면 4 단계 검색이 같은 조항을 두 번 돌려준다.

사용법::

    python scripts/build_rag_corpus.py            # 만들고 매니페스트를 다시 쓴다
    python scripts/build_rag_corpus.py --check    # 다시 만들면 달라지는지만 본다
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "rag-corpus"
LICENSE_DIR = CORPUS / "licenses"
MANIFEST = CORPUS / "manifest.yaml"

#: 게이트가 읽을 커버리지 색인. `rag-corpus/` 는 런타임 이미지에 실리지 않으므로
#: (Dockerfile 이 복사하지 않는다) 표만 wheel 에 실어 보낸다. 자리를 패키지 안에 두는
#: 이유가 그것이다.
COVERAGE_INDEX = (
    ROOT
    / "backend"
    / "src"
    / "ip_risk_agent"
    / "intelligence"
    / "license"
    / "corpus_coverage.json"
)

SPDX_RAW = "https://raw.githubusercontent.com/spdx/license-list-data/main/json"
SPDX_INDEX = f"{SPDX_RAW}/licenses.json"

#: 손으로 쓴 의무 해설. 라이선스 전문과 성격이 다르므로 이 스크립트가 건드리지 않고
#: 매니페스트에서 그대로 옮긴다.
GUIDE_SOURCE_TYPE = "OBLIGATION_GUIDE"

#: 전문 문서의 종류. `corpus_manifest.ALLOWED_SOURCE_TYPES` 에 이미 있는 값이다.
TEXT_SOURCE_TYPE = "OSS_LICENSE_TEXT"


def _fetch(url: str, cache: Path) -> bytes:
    """받아서 캐시에 둔다. 같은 판을 여러 번 받지 않기 위해서다."""
    key = cache / (hashlib.sha256(url.encode()).hexdigest() + ".json")
    if key.is_file():
        return key.read_bytes()
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = response.read()
    cache.mkdir(parents=True, exist_ok=True)
    key.write_bytes(payload)
    return payload


def _needs_review_identifiers() -> list[str]:
    """RAG 를 실제로 부르는 식별자.

    정책 표에서 읽는다. 여기에 목록을 다시 적으면 표가 넓어질 때 조용히 어긋난다.
    """
    sys.path.insert(0, str(ROOT / "backend" / "src"))
    sys.path.insert(0, str(ROOT / "shared" / "contracts" / "python"))
    from ip_risk_agent.intelligence.license import policy

    return sorted(
        identifier
        for identifier, outcome in policy._OUTCOME_BY_ID.items()
        if policy.needs_review(outcome)
    )


def corpus_checksum(text: str) -> str:
    """``intelligence.rag.ingestion.checksum`` 과 같은 규칙 — ``strip()`` 후 해시."""
    return "sha256:" + hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _slug(identifiers: list[str]) -> str:
    """묶인 식별자들의 파일 이름. 가장 짧은 것이 대표다."""
    return min(identifiers, key=lambda value: (len(value), value)).lower()


def _document(identifiers: list[str], detail: dict, list_version: str) -> str:
    """라이선스 한 편. 머리말은 우리 것이고 본문은 손대지 않는다."""
    name = detail.get("name", identifiers[0])
    primary = identifiers[0]
    joined = ", ".join(f"`{value}`" for value in identifiers)
    deprecated = [
        value for value in identifiers if detail.get("isDeprecatedLicenseId") is True
    ]
    lines = [
        f"# {name}",
        "",
        f"SPDX 식별자 — {joined}",
        f"SPDX license list — `{list_version}`",
        f"원본 — <https://spdx.org/licenses/{primary}.html>",
    ]
    if deprecated:
        lines.append("")
        lines.append(
            "이 식별자는 SPDX 에서 **폐기 표시**가 되어 있다. 옛 선언에 남아 있으므로 "
            "읽기는 하되, 새 선언에 권하지 않는다."
        )
    lines += [
        "",
        "아래는 라이선스 **전문**이다. 해설이 아니므로 한 글자도 고치지 않는다. "
        "배포 형태별 의무 해설은 `sources/` 의 별도 문서가 담는다.",
        "",
        "---",
        "",
        detail["licenseText"].strip(),
        "",
    ]
    return "\n".join(lines)


def _next_version(current: str | None) -> str:
    """오늘 날짜로 판본을 올린다. 같은 날 두 번째면 ``.2`` 가 된다.

    내용이 바뀌었는데 판본이 그대로면 `rag_corpus_version` 이 판정을 설명하지 못한다.
    그것이 §5.6 이 적은 결함이므로 여기서 자동으로 올린다.
    """
    from datetime import date

    today = date.today().isoformat()
    if current and current.startswith(today + "."):
        try:
            return f"{today}.{int(current.rsplit('.', 1)[1]) + 1}"
        except ValueError:
            pass
    return f"{today}.1"


def build(*, check: bool, version: str | None = None) -> int:
    cache = ROOT / ".rag-corpus-cache"
    index = json.loads(_fetch(SPDX_INDEX, cache))
    list_version = index.get("licenseListVersion", "unknown")
    known = {entry["licenseId"] for entry in index["licenses"]}

    targets = _needs_review_identifiers()
    missing = [value for value in targets if value not in known]
    if missing:
        print("SPDX 목록에 없는 식별자: " + ", ".join(missing), file=sys.stderr)
        return 1

    # 본문이 같은 식별자를 한 문서로 묶는다.
    details: dict[str, dict] = {}
    by_text: dict[str, list[str]] = defaultdict(list)
    for identifier in targets:
        detail = json.loads(_fetch(f"{SPDX_RAW}/details/{identifier}.json", cache))
        text = detail["licenseText"].strip()
        details[identifier] = detail
        by_text[text].append(identifier)

    document = yaml.safe_load(MANIFEST.read_text("utf-8")) or {}
    guides = [
        source
        for source in document.get("sources", ())
        if source.get("source_type") == GUIDE_SOURCE_TYPE
    ]

    written: list[dict] = []
    changed = False
    LICENSE_DIR.mkdir(parents=True, exist_ok=True)
    for text, identifiers in sorted(by_text.items(), key=lambda item: item[1][0]):
        identifiers = sorted(identifiers)
        slug = _slug(identifiers)
        # 파일 이름이 곧 source_id 다. RAG 가 검색 결과에 `sourceDisplayName` 으로
        # 무엇을 돌려주든 — source_id 든 파일명이든 — 게이트가 표에서 찾을 수 있어야
        # 한다. 둘이 다르면 전문이 붙어도 게이트가 "관련 없음" 으로 버린다.
        source_id = f"spdx-{slug}"
        path = LICENSE_DIR / f"{source_id}.md"
        body = _document(identifiers, details[identifiers[0]], list_version)
        if not path.is_file() or path.read_text("utf-8") != body:
            changed = True
            if not check:
                path.write_text(body, encoding="utf-8", newline="\n")
        written.append(
            {
                "source_id": source_id,
                "version": list_version,
                "source_type": TEXT_SOURCE_TYPE,
                "canonical_reference": (
                    f"https://spdx.org/licenses/{identifiers[0]}.html"
                ),
                "checksum": corpus_checksum(body),
                "path": f"licenses/{source_id}.md",
                "tags": ["license", "full-text", "spdx"],
                "approved_for_rag": True,
                "covers": identifiers,
            }
        )

    stale = {
        item.name for item in LICENSE_DIR.glob("*.md")
    } - {Path(entry["path"]).name for entry in written}
    for name in sorted(stale):
        changed = True
        if not check:
            (LICENSE_DIR / name).unlink()
        print(f"  버림  licenses/{name}")

    previous = document.get("corpus_version")
    document["sources"] = guides + written
    document["description"] = (
        "라이선스 의무사항 참조 지식. 공개 자료만 포함한다. "
        "전문은 SPDX license-list-data(CC0)에서 스크립트로 받는다."
    )

    def render(corpus_version: str | None) -> str:
        document["corpus_version"] = corpus_version
        # corpus_version 이 먼저 오도록 다시 세운다 — 사람이 가장 먼저 볼 값이다.
        ordered = {"corpus_version": document["corpus_version"]}
        ordered.update({k: v for k, v in document.items() if k != "corpus_version"})
        return yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False, width=100)

    # 판본은 **corpus 내용이 달라졌을 때만** 올린다. 아래 커버리지 색인은 매니페스트에서
    # 뽑아낸 파생물이라 그것만 달라진 것은 corpus 가 달라진 것이 아니다.
    if MANIFEST.read_text("utf-8") != render(previous):
        changed = True
        if not check:
            bumped = version or _next_version(previous)
            MANIFEST.write_text(render(bumped), encoding="utf-8", newline="\n")
            print(f"corpus_version     {previous} → {bumped}")
    elif version and not check:
        MANIFEST.write_text(render(version), encoding="utf-8", newline="\n")

    # 커버리지 색인. 게이트가 "이 문서가 이 판정을 다루는가" 를 물을 때 보는 표이고,
    # 지금은 `reference_gate.CORPUS_SUBJECT_COVERAGE` 에 손으로 적혀 있다. 매니페스트가
    # 이미 `covers` 로 같은 것을 말하므로 여기서 뽑아 **데이터로** 싣는다 — 그래야
    # 문서를 늘릴 때 코드를 고치지 않는다 (DEVELOPMENT_SPEC §5.5, 항목 2-D).
    coverage = {
        entry["source_id"]: sorted(entry["covers"])
        for entry in (guides + written)
        if entry.get("approved_for_rag")
    }
    index_body = json.dumps(coverage, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if not COVERAGE_INDEX.is_file() or COVERAGE_INDEX.read_text("utf-8") != index_body:
        changed = True
        if not check:
            COVERAGE_INDEX.write_text(index_body, encoding="utf-8", newline="\n")

    covered = sorted({value for entry in written for value in entry["covers"]})
    print(f"SPDX license list  {list_version}")
    print(f"라이선스 문서      {len(written)} 편 (식별자 {len(covered)} 종)")
    print(f"의무 해설          {len(guides)} 편")
    if check:
        print("다시 만들면 달라진다" if changed else "다시 만들어도 같다")
        return 1 if changed else 0
    print("매니페스트를 다시 썼다" if changed else "바뀐 것이 없다")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="파일을 쓰지 않고 다시 만들면 달라지는지만 본다",
    )
    parser.add_argument(
        "--corpus-version",
        help="쓸 판본. 없으면 오늘 날짜로 올린다 (YYYY-MM-DD.N)",
    )
    arguments = parser.parse_args()
    return build(check=arguments.check, version=arguments.corpus_version)


if __name__ == "__main__":
    raise SystemExit(main())
