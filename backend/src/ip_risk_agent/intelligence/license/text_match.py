"""LICENSE 원문 대조 (T2 유예 해제 — `docs/FINAL_ENHANCEMENT_IDEAS.md` 1-L1).

레지스트리가 준 **이름**을 믿는 현행 파이프라인의 감수 위험(§12.4)은 "표준
라이선스를 조금 고쳐 조항이 하나 더 붙은" 변형과 "사내 라이선스에 비슷한
이름을 붙인" 사칭을 못 본다는 것이다. 이 모듈은 라이선스 **원문**을 SPDX 전문
672편의 지문과 대조해 "이 텍스트는 실제로 무엇에 가장 가깝고, 얼마나 같은가"를
계산한다.

## 판정하지 않는다

대조 결과는 점수와 후보일 뿐이다. 등급·판정은 여전히 규칙 엔진(policy)이
이름 기반으로 한다 — 원문 대조는 "선언과 원문이 다르다"는 **관측 신호**를
만들 뿐이다 (T3 규율: 올릴 수만 있고, 여기서는 그마저도 아직 안 한다 —
파이프라인 편입은 별도 결정).

## 왜 지문(minhash)인가

corpus 전문 11.8MB 는 wheel 에 싣지 않는다(rag-corpus 는 이미지 밖 — 결정
기록 있음). 대조에 필요한 것은 전문이 아니라 **유사도**이므로, 빌드 시점에
문서당 고정 크기 지문(정규화 해시 + 5-gram shingle 의 minhash 128슬롯)을 만들어
`license_fingerprints.json` 으로 싣는다 (~1MB). minhash 슬롯 일치율이 Jaccard
유사도의 불편추정이라, 변형("조항 하나 추가")은 1.0 미만의 높은 점수로,
무관한 라이선스는 낮은 점수로 갈린다.

## 결정론

정규화·shingle·해시·치환 계수가 전부 고정 상수에서 파생된다. 같은 텍스트는
언제나 같은 지문이다. 계수를 바꾸면 지문 파일과 호환이 깨지므로
``FINGERPRINT_VERSION`` 을 함께 올리고 재생성한다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import struct
from dataclasses import dataclass
from importlib import resources

#: 지문 산식의 판본. 정규화·shingle·치환 계수가 바뀌면 올린다.
FINGERPRINT_VERSION = "license_text_match_v1"

SHINGLE_SIZE = 5
NUM_PERMUTATIONS = 128

_MASK64 = (1 << 64) - 1
#: 64비트 곱셈 해시용 메르센 소수.
_PRIME = (1 << 61) - 1

_WORD = re.compile(r"[a-z0-9]+")

#: 저작권 표시 줄은 라이선스의 본문이 아니라 **사용자의 기입란**이다.
#: "Copyright (c) 2026 홍길동" 이 다르다고 다른 라이선스가 되면 안 되므로
#: 정규화에서 걷어낸다.
_COPYRIGHT_LINE = re.compile(
    r"^\s*(?:copyright\b|\(c\)\s|©|all rights reserved)", re.IGNORECASE
)


def _permutation_coefficients() -> list[tuple[int, int]]:
    """치환 계수 (a, b) 128쌍. 난수가 아니라 해시에서 파생해 영원히 고정한다."""
    coefficients: list[tuple[int, int]] = []
    for index in range(NUM_PERMUTATIONS):
        digest = hashlib.sha256(
            f"iprisk-license-minhash:{FINGERPRINT_VERSION}:{index}".encode()
        ).digest()
        a = (int.from_bytes(digest[:8], "big") | 1) % _PRIME  # 홀수 보장
        b = int.from_bytes(digest[8:16], "big") % _PRIME
        coefficients.append((a or 1, b))
    return coefficients


_COEFFICIENTS = _permutation_coefficients()


def normalize_license_tokens(text: str) -> list[str]:
    """대조용 토큰열. 저작권 줄 제거 → 소문자 → 영숫자 어절."""
    kept_lines = [
        line for line in text.splitlines() if not _COPYRIGHT_LINE.match(line)
    ]
    return _WORD.findall("\n".join(kept_lines).lower())


def _shingles(tokens: list[str]) -> set[int]:
    if len(tokens) < SHINGLE_SIZE:
        return set()
    out: set[int] = set()
    for start in range(len(tokens) - SHINGLE_SIZE + 1):
        shingle = " ".join(tokens[start : start + SHINGLE_SIZE])
        digest = hashlib.blake2b(shingle.encode(), digest_size=8).digest()
        out.add(int.from_bytes(digest, "big"))
    return out


def exact_digest(tokens: list[str]) -> str:
    return hashlib.sha256(" ".join(tokens).encode()).hexdigest()


def minhash_signature(tokens: list[str]) -> list[int] | None:
    """minhash 128슬롯. shingle 을 만들 수 없을 만큼 짧으면 ``None``."""
    shingles = _shingles(tokens)
    if not shingles:
        return None
    signature: list[int] = []
    for a, b in _COEFFICIENTS:
        best = _MASK64
        for value in shingles:
            candidate = (a * value + b) % _PRIME
            if candidate < best:
                best = candidate
        signature.append(best)
    return signature


def pack_signature(signature: list[int]) -> str:
    return base64.b64encode(
        struct.pack(f">{len(signature)}Q", *signature)
    ).decode("ascii")


def unpack_signature(packed: str) -> list[int]:
    raw = base64.b64decode(packed.encode("ascii"))
    return list(struct.unpack(f">{len(raw) // 8}Q", raw))


@dataclass(frozen=True)
class LicenseTextMatch:
    """대조 결과 한 건. 점수는 Jaccard 추정치(0~1), exact 는 정규화 동일."""

    source_id: str
    covers: tuple[str, ...]
    score: float
    exact: bool


class LicenseTextMatcher:
    """지문 묶음을 들고 입력 텍스트의 최근접 라이선스를 찾는다."""

    def __init__(self, payload: dict) -> None:
        if payload.get("fingerprint_version") != FINGERPRINT_VERSION:
            raise ValueError(
                "license fingerprint file was built with "
                f"{payload.get('fingerprint_version')!r}; this code expects "
                f"{FINGERPRINT_VERSION!r} — rebuild with "
                "scripts/build_license_fingerprints.py"
            )
        self.corpus_version: str = payload["corpus_version"]
        self._entries = [
            (
                entry["source_id"],
                tuple(entry["covers"]),
                entry["exact_sha256"],
                unpack_signature(entry["minhash"]),
            )
            for entry in payload["entries"]
        ]

    @classmethod
    def load_bundled(cls) -> "LicenseTextMatcher":
        """wheel 에 실린 지문 파일을 읽는다 (package-data ``license/*.json``)."""
        with (
            resources.files("ip_risk_agent.intelligence.license")
            .joinpath("license_fingerprints.json")
            .open("r", encoding="utf-8")
        ) as handle:
            return cls(json.load(handle))

    def match(self, text: str, *, top_k: int = 3) -> list[LicenseTextMatch]:
        """가장 가까운 라이선스 후보. 대조 불가(너무 짧음)면 빈 목록."""
        tokens = normalize_license_tokens(text)
        signature = minhash_signature(tokens)
        if signature is None:
            return []
        digest = exact_digest(tokens)

        scored: list[LicenseTextMatch] = []
        for source_id, covers, entry_digest, entry_signature in self._entries:
            equal_slots = sum(
                1 for mine, theirs in zip(signature, entry_signature) if mine == theirs
            )
            scored.append(
                LicenseTextMatch(
                    source_id=source_id,
                    covers=covers,
                    score=round(equal_slots / NUM_PERMUTATIONS, 4),
                    exact=digest == entry_digest,
                )
            )
        # 정렬은 완전 결정론 — 점수 → exact → source_id.
        scored.sort(key=lambda m: (-m.score, not m.exact, m.source_id))
        return scored[:top_k]


__all__ = [
    "FINGERPRINT_VERSION",
    "LicenseTextMatch",
    "LicenseTextMatcher",
    "NUM_PERMUTATIONS",
    "SHINGLE_SIZE",
    "exact_digest",
    "minhash_signature",
    "normalize_license_tokens",
    "pack_signature",
    "unpack_signature",
]
