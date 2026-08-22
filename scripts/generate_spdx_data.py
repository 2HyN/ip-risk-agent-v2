"""SPDX 식별자 목록을 코드로 굳힌다.

## 왜 생성물인가

식별자 727 개와 예외 84 개를 손으로 적으면 반드시 어긋난다. 그리고 어긋난 것이 조용히
`UNKNOWN` 으로 나타나 **라이선스를 모른다는 뜻과 구별되지 않는다.**

그래서 SPDX 공식 목록에서 생성한다. 산출물
(``backend/src/ip_risk_agent/intelligence/license/spdx_data.py``)은 손으로 고치지 않는다.

## 왜 데이터 파일이 아니라 파이썬 모듈인가

패키지 자료로 실으려면 ``pyproject.toml`` 의 ``package-data`` 를 건드려야 하고, 이미지에
들어가는지도 따로 확인해야 한다 (``rag-corpus/`` 가 이미지에 없다는 선례가 있다). 파이썬
모듈이면 패키지 코드라 그냥 실린다. 확인할 것이 하나 줄어든다.

## 쓰는 법

    python scripts/generate_spdx_data.py            # 기본 태그로 내려받아 생성
    python scripts/generate_spdx_data.py --version 3.28.0
    python scripts/generate_spdx_data.py --check    # 생성물이 최신인지만 확인

``--check`` 는 파일을 쓰지 않고 다르면 1 로 끝난다. 목록을 올릴 때 사람이 diff 를 보게
하려는 것이다 — 라이선스 목록이 바뀌면 판정이 바뀔 수 있으므로 조용히 따라가면 안 된다.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

#: 이 값을 올릴 때는 반드시 diff 를 사람이 본다. 목록이 바뀌면 판정이 바뀔 수 있다.
DEFAULT_VERSION = "3.28.0"

_BASE = "https://raw.githubusercontent.com/spdx/license-list-data/v{version}/json/{name}.json"

_OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "src"
    / "ip_risk_agent"
    / "intelligence"
    / "license"
    / "spdx_data.py"
)

_HEADER = '''"""SPDX 라이선스·예외 식별자. **생성물이므로 손으로 고치지 않는다.**

``scripts/generate_spdx_data.py`` 가 SPDX 공식 목록 v{version} 에서 만든다. 목록을 올리려면
그 스크립트를 다시 돌리고 diff 를 사람이 본다.

여기에는 **어떤 판단도 없다.** "이것이 등록된 식별자인가" 만 담는다. 어느 검토 등급인가는
:mod:`ip_risk_agent.intelligence.license.policy` 가 따로 정한다. 둘을 섞지 않는 이유는
§5.2 가 말한 것과 같다 — 등록된 식별자를 `UNKNOWN` 으로 소거하면 원문이 사라져 나중에
정책 표를 넓혀도 구제할 수 없다. 어휘는 넓게, 판단은 좁게 간다.
"""

from __future__ import annotations

#: SPDX license list 태그. ``SPDX_SNAPSHOT_VERSION`` 이 이 값을 쓴다.
SPDX_LIST_VERSION = "{version}"
'''


def _fetch(name: str, version: str) -> dict:
    url = _BASE.format(version=version, name=name)
    with urllib.request.urlopen(url, timeout=90) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _tuple_literal(name: str, values: tuple[str, ...], doc: str) -> str:
    lines = [f"#: {doc}", f"{name}: tuple[str, ...] = ("]
    row: list[str] = []
    width = 0
    for value in values:
        item = f'"{value}",'
        if width + len(item) + 1 > 92:
            lines.append("    " + " ".join(row))
            row, width = [], 0
        row.append(item)
        width += len(item) + 1
    if row:
        lines.append("    " + " ".join(row))
    lines.append(")")
    return "\n".join(lines)


def render(version: str) -> str:
    licenses = _fetch("licenses", version)["licenses"]
    exceptions = _fetch("exceptions", version)["exceptions"]

    all_licenses = tuple(sorted(x["licenseId"] for x in licenses))
    deprecated_licenses = tuple(
        sorted(x["licenseId"] for x in licenses if x.get("isDeprecatedLicenseId"))
    )
    all_exceptions = tuple(sorted(x["licenseExceptionId"] for x in exceptions))
    deprecated_exceptions = tuple(
        sorted(
            x["licenseExceptionId"] for x in exceptions if x.get("isDeprecatedLicenseId")
        )
    )
    osi = tuple(sorted(x["licenseId"] for x in licenses if x.get("isOsiApproved")))

    parts = [
        _HEADER.format(version=version),
        _tuple_literal(
            "LICENSE_IDS",
            all_licenses,
            f"등록된 라이선스 식별자 전부 ({len(all_licenses)} 개). 정규 표기다.",
        ),
        _tuple_literal(
            "DEPRECATED_LICENSE_IDS",
            deprecated_licenses,
            "SPDX 가 폐기한 식별자. 여전히 유효한 표기이므로 소거하지 않는다.",
        ),
        _tuple_literal(
            "OSI_APPROVED_LICENSE_IDS",
            osi,
            "OSI 승인. 판단에 쓰지 않고 검토자에게 보이는 참고값이다.",
        ),
        _tuple_literal(
            "EXCEPTION_IDS",
            all_exceptions,
            f"등록된 예외 식별자 전부 ({len(all_exceptions)} 개).",
        ),
        _tuple_literal(
            "DEPRECATED_EXCEPTION_IDS",
            deprecated_exceptions,
            "SPDX 가 폐기한 예외 식별자.",
        ),
        '__all__ = [\n'
        '    "SPDX_LIST_VERSION",\n'
        '    "LICENSE_IDS",\n'
        '    "DEPRECATED_LICENSE_IDS",\n'
        '    "OSI_APPROVED_LICENSE_IDS",\n'
        '    "EXCEPTION_IDS",\n'
        '    "DEPRECATED_EXCEPTION_IDS",\n'
        ']',
    ]
    return "\n\n\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=DEFAULT_VERSION)
    parser.add_argument(
        "--check",
        action="store_true",
        help="쓰지 않고 최신인지만 본다. 다르면 1 로 끝난다.",
    )
    args = parser.parse_args()

    generated = render(args.version)
    if args.check:
        current = _OUTPUT.read_text("utf-8") if _OUTPUT.exists() else ""
        if current == generated:
            print(f"최신이다 (SPDX {args.version})")
            return 0
        print(f"{_OUTPUT} 가 SPDX {args.version} 과 다르다. 다시 생성해야 한다.")
        return 1

    _OUTPUT.write_text(generated, "utf-8")
    print(f"{_OUTPUT} 를 SPDX {args.version} 으로 썼다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
