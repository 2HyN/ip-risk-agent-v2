"""라이선스 원문 대조(1-L1) 회귀 테스트.

지문 파일은 커밋된 실물을 쓴다 (wheel package-data 와 같은 경로). corpus
전체를 재생성하는 것은 분 단위라 여기서 하지 않고, 대표 문서 3편의 지문만
재계산해 커밋본과 대조한다 — 정규화·산식 드리프트를 몇 초에 잡는다.
"""

from __future__ import annotations

import json
from pathlib import Path

from ip_risk_agent.intelligence.license.text_match import (
    LicenseTextMatcher,
    exact_digest,
    minhash_signature,
    normalize_license_tokens,
    pack_signature,
)

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "rag-corpus" / "licenses"
FINGERPRINTS = (
    ROOT
    / "backend"
    / "src"
    / "ip_risk_agent"
    / "intelligence"
    / "license"
    / "license_fingerprints.json"
)


def corpus_body(name: str) -> str:
    raw = (CORPUS / name).read_text(encoding="utf-8")
    return raw.partition("\n---\n")[2]


def matcher() -> LicenseTextMatcher:
    return LicenseTextMatcher(json.loads(FINGERPRINTS.read_text(encoding="utf-8")))


# ------------------------------------------------------------ 정규화


def test_copyright_lines_do_not_change_the_fingerprint():
    body = corpus_body("spdx-mit.md")
    personalized = body.replace(
        "Copyright (c) <year> <copyright holders>",
        "Copyright (c) 2026 홍길동",
    )
    assert exact_digest(normalize_license_tokens(body)) == exact_digest(
        normalize_license_tokens(personalized)
    )


def test_whitespace_and_case_do_not_change_the_fingerprint():
    # 저작권 줄 제거가 줄 단위이므로 줄 구조는 유지한 채 대소문자·줄 안 공백만
    # 흔든다 — 실제 변형(들여쓰기·재줄바꿈 없는 재타이핑)의 모양이다.
    body = corpus_body("spdx-mit.md")
    reflowed = "\n".join(
        "  " + " ".join(line.upper().split()) for line in body.splitlines()
    )
    assert exact_digest(normalize_license_tokens(body)) == exact_digest(
        normalize_license_tokens(reflowed)
    )


def test_signature_is_deterministic():
    tokens = normalize_license_tokens(corpus_body("spdx-apache-2.0.md"))
    assert minhash_signature(tokens) == minhash_signature(tokens)


# ------------------------------------------------------------ 대조


def test_verbatim_text_is_an_exact_match():
    (best, *_rest) = matcher().match(corpus_body("spdx-mit.md"))
    assert best.source_id == "spdx-mit"
    assert best.exact
    assert best.score == 1.0
    assert "MIT" in best.covers


def test_variant_with_an_extra_clause_stays_closest_but_not_exact():
    """"표준 라이선스를 조금 고쳐 조항이 하나 더 붙은" 사례 — §12.4 가 감수하던
    바로 그 위험이 관측 가능해진다."""
    variant = corpus_body("spdx-mit.md") + (
        "\n\nAdditional Clause. Redistribution in any commercial product "
        "requires prior written approval from the original vendor and a "
        "separate commercial agreement covering each distributed unit."
    )
    (best, *_rest) = matcher().match(variant)
    assert best.source_id == "spdx-mit"
    assert not best.exact
    assert 0.55 <= best.score < 1.0


def test_unrelated_license_is_not_the_nearest():
    matches = matcher().match(corpus_body("spdx-apache-2.0.md"), top_k=5)
    assert matches[0].source_id == "spdx-apache-2.0"
    assert matches[0].exact
    mit_scores = [m.score for m in matches if m.source_id == "spdx-mit"]
    assert not mit_scores or mit_scores[0] < 0.3


def test_too_short_text_returns_nothing_instead_of_guessing():
    assert matcher().match("MIT License") == []


# ------------------------------------------------------------ 지문 파일 신선도


def test_bundled_fingerprints_match_recomputation_for_known_documents():
    payload = json.loads(FINGERPRINTS.read_text(encoding="utf-8"))
    by_id = {entry["source_id"]: entry for entry in payload["entries"]}
    assert payload["entry_count"] == len(payload["entries"]) >= 600
    for name in ("spdx-mit.md", "spdx-apache-2.0.md", "spdx-gpl-3.0-only.md"):
        source_id = name.removesuffix(".md")
        tokens = normalize_license_tokens(corpus_body(name))
        entry = by_id[source_id]
        assert entry["exact_sha256"] == exact_digest(tokens), source_id
        assert entry["minhash"] == pack_signature(minhash_signature(tokens)), source_id


def test_bundled_loader_reads_the_packaged_file():
    bundled = LicenseTextMatcher.load_bundled()
    assert bundled.corpus_version == matcher().corpus_version
