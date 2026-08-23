"""데스크톱 워처가 쓰는 표를 서버 표에서 만들어 낸다.

## 왜 생성하는가

같은 판단을 두 언어가 각자 적고 있었다. 그리고 **이미 크게 어긋나 있었다** —
서버가 코드 확장자 29 · 문서 21 · 제외 폴더 23 을 아는 동안 데스크톱은 9 · 3 · 6 이었고,
`requirements.lock` · `constraints.txt` · `requirements/base.txt` 를 감시하지 않았다.
0-J 가 되살려 낸 이름들이다.

**감시가 먼저 거른다.** 서버 표를 아무리 넓혀도 데스크톱이 안 보내면 그 파일은 Local
마운트에서 존재하지 않는다. 그래서 서버만 고치는 것은 Local 에 대해 아무것도 고치지
않는 것이었다.

`filters.ts` 의 주석이 이 실패를 두 줄 위에서 예언해 두었다 — "이름 목록으로 두면
어긋난다" — 그리고 바로 아래에서 이름 목록을 썼다. 사람이 두 곳을 맞추는 규율에
기대는 대신 한쪽에서 만든다.

계약(`generate_contracts.py`)과 corpus 색인(`build_rag_corpus.py`)이 이미 같은 방식이다.

    python scripts/generate_source_filters.py
    git diff --exit-code -- apps/desktop/watcher/generated-filters.ts
"""

from __future__ import annotations

import json
from pathlib import Path

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from ip_risk_agent.core.artifacts import dependency_files, text_files
from ip_risk_agent.core.security.ignore_patterns import DEFAULT_IGNORE_PATTERNS

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "apps" / "desktop" / "watcher" / "generated-filters.ts"

HEADER = """// 생성된 파일이다. 손으로 고치지 않는다.
//
//     python scripts/generate_source_filters.py
//
// 원본은 `backend/src/ip_risk_agent/core/artifacts/` 와 `core/security/` 의 표다.
// 같은 판단을 두 언어가 각자 적으면 어긋나고, 감시가 먼저 거르므로 그 어긋남은
// **Local 마운트에서 조용한 누락**이 된다.
"""


def _skip_directories() -> tuple[str, ...]:
    """공용 제외 목록에서 **폴더 이름**만 뽑는다.

    워처는 경로 패턴이 아니라 디렉터리 이름으로 가지치기를 한다. 끝이 ``/`` 이고
    글롭 문자가 없는 것만 폴더 이름으로 쓸 수 있다.
    """
    found = []
    for pattern in DEFAULT_IGNORE_PATTERNS:
        if not pattern.endswith("/"):
            continue
        name = pattern.rstrip("/")
        if any(character in name for character in "*?/"):
            continue
        found.append(name)
    return tuple(sorted(found))


def _dependency_exact_names() -> tuple[str, ...]:
    return tuple(sorted(name for name, _ in dependency_files._EXACT_NAMES))


def render() -> str:
    def const(name: str, values) -> str:
        body = json.dumps(sorted(values), ensure_ascii=False, indent=2)
        return f"export const {name}: readonly string[] = {body};\n"

    parts = [
        HEADER,
        "",
        const("CODE_EXTENSIONS", text_files.CODE_EXTENSIONS),
        "",
        const("DOCUMENT_EXTENSIONS", text_files.DOCUMENT_EXTENSIONS),
        "",
        "// 확장자가 없어도 텍스트인 관행적 이름.",
        const("EXTENSIONLESS_TEXT", text_files._EXTENSIONLESS_TEXT),
        "",
        "// 라이선스 전문 파일. 어느 분석기도 맡지 않으므로 감시해도 거부된 artifact 만",
        "// 남는다 (결함 26).",
        const("LICENCE_STEMS", text_files._LICENSE_FILE_STEMS),
        "",
        "// 의존성 선언. 이름이 정확히 맞아야 하는 것들.",
        const("DEPENDENCY_EXACT_NAMES", _dependency_exact_names()),
        "",
        "// `requirements` 로 시작하면 같은 형식이다. `requirements-dev.txt` ·",
        "// `requirements.in` 처럼 쓰는 관행이 넓다.",
        f'export const DEPENDENCY_PREFIX = "{dependency_files._REQUIREMENTS_PREFIX}";\n',
        "",
        "// `requirements/base.txt` 처럼 폴더가 형식을 말해 주는 관행.",
        'export const DEPENDENCY_DIRECTORY = "requirements";\n',
        "",
        "// 빌드 산출물과 의존성 트리. 워처가 가지치기에 쓴다.",
        const("SKIP_DIRECTORIES", _skip_directories()),
    ]
    return "\n".join(parts)


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
