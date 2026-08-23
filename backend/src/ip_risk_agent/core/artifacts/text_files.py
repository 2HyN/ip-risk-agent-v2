"""어떤 파일이 텍스트이고, 그것이 코드인가 문서인가.

## 왜 한 곳에 두는가

``dependency_files`` 와 같은 이유다. 이 판단을 **네 곳**이 각자 필요로 한다.

* 세 커넥터가 아티팩트 종류를 정할 때 (그 종류가 License·Patent 경로를 가른다)
* Security Gate 가 이 파일을 읽어도 되는지 정할 때

각자 들고 있으면 어긋난다. 실제로 어긋나 있었다.

* GitHub 과 Local 이 **같은 표를 각각 복사**해 들고 있었다. 지금은 값이 같지만
  한쪽만 고치면 조용히 갈라진다 — 의존성 표가 정확히 그렇게 갈라졌었다.
* Drive 에는 표가 아예 없어서, 의존성이 아닌 것은 **전부 문서**로 봤다. 그래서 같은
  ``main.py`` 가 GitHub 에서는 소스 코드로, Drive 에서는 문서로 분석됐다.
* 게이트는 mime 만 보고 확장자를 보지 않았다. ``application/octet-stream`` 으로 온
  ``.md`` 가 거부됐다. GitHub 과 Local 은 mime 을 아예 넘기지 않으므로(``None``)
  이 판단이 소스마다 달랐다.

## 무엇을 텍스트로 보는가

**확장자만 본다.** 내용까지 확인하려면 파일을 먼저 받아야 하는데, 받을지 말지를 정하는
것이 이 판단이다. 확장자가 텍스트 계열인데 내용이 바이너리인 경우는 디코드가 실패하고,
그것은 정직한 "미지원" 으로 끝난다 (§6.2).

목록은 **넓게** 잡는다. 빠뜨리면 그 파일은 ``UNKNOWN`` 이 되어 어느 분석기도 맡지 않고
**조용히 사라진다.** 폴더를 통째로 마운트하면 (§6.1) 그 침묵이 그대로 누락이 된다.
"""

from __future__ import annotations

from iprisk_contracts.common import ArtifactKind

#: 소스 코드. 특허 경로로 간다.
CODE_EXTENSIONS = frozenset(
    {
        ".c", ".cc", ".cpp", ".cs", ".cxx", ".go", ".h", ".hpp", ".java", ".js",
        ".jsx", ".kt", ".kts", ".m", ".mjs", ".php", ".pl", ".py", ".pyi", ".r",
        ".rb", ".rs", ".scala", ".sh", ".sql", ".swift", ".ts", ".tsx", ".vue",
    }
)

#: 산문·설정·표. 특허 경로로 간다 — 설계 문서가 여기 들어 있기 때문이다.
#:
#: ``.json`` 과 ``.toml`` 도 여기 둔다. 의존성 선언인 것들은 그 전에
#: ``dependency_files`` 가 먼저 집어 가므로 여기까지 오지 않는다.
DOCUMENT_EXTENSIONS = frozenset(
    {
        ".adoc", ".cfg", ".conf", ".csv", ".env", ".ini", ".json", ".jsonl",
        ".log", ".md", ".markdown", ".org", ".properties", ".rst", ".text",
        ".toml", ".tsv", ".txt", ".xml", ".yaml", ".yml",
    }
)

#: 확장자가 없어도 텍스트인 관행적 이름.
_EXTENSIONLESS_TEXT = frozenset({"dockerfile", "makefile", "readme"})

#: 라이선스 전문 파일. **일부러 분석하지 않는다.**
#:
#: 이 파일들은 코드도 산문도 아니다. 라이선스 전문이고, 그것을 원문 대조로 판정하는
#: 것은 유예했다 (§5.9) — 대신 의존성 선언에서 레지스트리로 간다. 그런데 종류를
#: 정하지 않으면 확장자에 끌려간다. ``LICENSE`` 는 확장자가 없어 ``UNKNOWN`` 이 되고
#: ``LICENSE.txt`` 는 ``.txt`` 라 **문서로 분류되어 특허 경로**를 탄다. 같은 파일이
#: 이름 하나 차이로 KIPRIS 를 11 회쯤 쓰고, 나오는 것은 라이선스 전문에서 찾은
#: 특허 유사도다 (결함 26).
#:
#: 그래서 여기서 먼저 집어 낸다. 전문 대조를 하기로 하면 이 표가 그 입구가 된다.
_LICENSE_FILE_STEMS = frozenset(
    {"license", "licence", "licenses", "licences", "copying", "notice", "unlicense"}
)


def _name_and_suffix(logical_path: str) -> tuple[str, str]:
    name = logical_path.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    dot = name.rfind(".")
    # 맨 앞의 점은 확장자가 아니다 — `.env` 는 이름이 `.env` 이고 확장자가 없다.
    suffix = name[dot:] if dot > 0 else ""
    return name, suffix


def text_kind(logical_path: str) -> ArtifactKind | None:
    """이 이름이 코드인가 문서인가. 텍스트가 아니면 ``None``.

    의존성 선언은 여기서 판정하지 않는다. 호출부가 ``dependency_files`` 를 **먼저**
    묻는다 — 같은 ``pyproject.toml`` 이 문서로 분류되면 License 검사를 못 받는다.
    """
    name, suffix = _name_and_suffix(logical_path)
    stem = name[: -len(suffix)] if suffix else name
    if stem in _LICENSE_FILE_STEMS:
        # 라이선스 전문이다. 확장자가 무엇이든 분석하지 않는다 — 위 표를 보라.
        return None
    if suffix in CODE_EXTENSIONS:
        return ArtifactKind.SOURCE_CODE
    if suffix in DOCUMENT_EXTENSIONS:
        return ArtifactKind.DOCUMENT_TEXT
    if name in _EXTENSIONLESS_TEXT:
        return ArtifactKind.DOCUMENT_TEXT
    # `.env.production` 처럼 뒤에 무언가 붙는 관행.
    if name.startswith(".env"):
        return ArtifactKind.DOCUMENT_TEXT
    return None


def is_text_like(logical_path: str) -> bool:
    """이름만 보고 읽어 볼 만한 파일인가.

    게이트가 mime 을 믿을 수 없을 때 쓴다. mime 이 없거나(``None`` — GitHub 과
    Local 이 그렇다) 뭉뚱그려 왔을 때(``application/octet-stream``) 이름이 유일한
    단서다.
    """
    return text_kind(logical_path) is not None


#: "이것이 무엇인지 말하지 않겠다" 는 mime. 이때만 파일 이름이 판단을 대신한다.
#:
#: **적극적으로 무엇이라고 말하는 mime 은 뒤집지 않는다.** ``image/png`` 은 판단을
#: 미룬 것이 아니라 이미지라고 주장하는 것이고, 그것을 파일 이름 추측으로 덮으면
#: 확장자만 바꿔 게이트를 지나갈 수 있게 된다.
NON_COMMITTAL_MIME_TYPES = frozenset(
    {"application/octet-stream", "binary/octet-stream"}
)


def mime_is_textual(mime_type: str | None) -> bool:
    """mime 이 스스로 텍스트라고 말하는가.

    ``text/`` 로 시작하면 그렇다 — ``text/x-python`` · ``text/csv`` · ``text/yaml``
    처럼 목록으로는 다 셀 수 없는 것들이 여기 들어온다. 실제로 Drive 가 네 가지
    고정 목록만 통과시켜 이것들을 전부 떨어뜨렸다.
    """
    if not mime_type:
        return False
    return mime_type.split(";", 1)[0].strip().casefold().startswith("text/")


__all__ = [
    "CODE_EXTENSIONS",
    "DOCUMENT_EXTENSIONS",
    "NON_COMMITTAL_MIME_TYPES",
    "is_text_like",
    "mime_is_textual",
    "text_kind",
]
