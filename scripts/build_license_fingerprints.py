"""SPDX 전문 corpus → 라이선스 원문 대조 지문 (1-L1).

rag-corpus 의 라이선스 전문(OSS_LICENSE_TEXT, 672편)에서 정규화 해시 +
minhash 지문을 만들어 wheel 에 실리는
``backend/src/ip_risk_agent/intelligence/license/license_fingerprints.json``
을 생성한다. 해설(OBLIGATION_GUIDE) 3편은 전문이 아니므로 대조 기준에서
제외한다.

    python scripts/build_license_fingerprints.py            # 생성
    python scripts/build_license_fingerprints.py --check    # 드리프트 검사만

corpus 판본이 지문 파일에 스탬프되므로, corpus 를 갱신하면 이 스크립트도
다시 돌려 함께 커밋한다 (`--check` 가 CI 후보).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

import yaml

from ip_risk_agent.intelligence.license.text_match import (
    FINGERPRINT_VERSION,
    NUM_PERMUTATIONS,
    SHINGLE_SIZE,
    exact_digest,
    minhash_signature,
    normalize_license_tokens,
    pack_signature,
)

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "rag-corpus"
OUTPUT = (
    ROOT
    / "backend"
    / "src"
    / "ip_risk_agent"
    / "intelligence"
    / "license"
    / "license_fingerprints.json"
)

#: corpus 문서는 "한국어 머리말 + --- + 원문 그대로" 형식이다. 지문은 원문
#: 부분에서만 만든다 — 머리말은 우리가 붙인 것이지 라이선스가 아니다.
_BODY_SEPARATOR = "\n---\n"


def _license_body(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    head, separator, body = raw.partition(_BODY_SEPARATOR)
    if not separator:
        raise SystemExit(f"corpus 문서에 본문 구분선이 없다: {path}")
    return body


def build_payload() -> dict:
    manifest = yaml.safe_load((CORPUS / "manifest.yaml").read_text(encoding="utf-8"))
    entries = []
    skipped_short = []
    for source in manifest["sources"]:
        if source.get("source_type") != "OSS_LICENSE_TEXT":
            continue
        body = _license_body(CORPUS / source["path"])
        tokens = normalize_license_tokens(body)
        signature = minhash_signature(tokens)
        if signature is None:
            skipped_short.append(source["source_id"])
            continue
        entries.append(
            {
                "source_id": source["source_id"],
                "covers": sorted(source.get("covers") or []),
                "token_count": len(tokens),
                "exact_sha256": exact_digest(tokens),
                "minhash": pack_signature(signature),
            }
        )
    entries.sort(key=lambda entry: entry["source_id"])
    if skipped_short:
        print(
            f"경고: shingle 을 만들 수 없을 만큼 짧아 제외한 문서 "
            f"{len(skipped_short)}편: {skipped_short[:5]}",
            file=sys.stderr,
        )
    return {
        "fingerprint_version": FINGERPRINT_VERSION,
        "corpus_version": manifest["corpus_version"],
        "shingle_size": SHINGLE_SIZE,
        "num_permutations": NUM_PERMUTATIONS,
        "entry_count": len(entries),
        "entries": entries,
    }


def render(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=1, sort_keys=True) + "\n"


def main() -> int:
    # Windows 콘솔(cp949)에서 한국어 출력이 깨지지 않게 한다.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="드리프트 검사만 한다")
    args = parser.parse_args()

    rendered = render(build_payload())
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print(
                "license fingerprints drift: corpus 또는 산식이 바뀌었다 — "
                "python scripts/build_license_fingerprints.py 를 돌려 커밋하라",
                file=sys.stderr,
            )
            return 1
        print("license fingerprints clean")
        return 0

    OUTPUT.write_text(rendered, encoding="utf-8", newline="\n")
    payload = json.loads(rendered)
    print(
        f"wrote {OUTPUT.relative_to(ROOT)} — {payload['entry_count']}편, "
        f"corpus {payload['corpus_version']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
