"""KIPRIS 없이 특허 파이프라인을 끝까지 돌리기 위한 고정 코퍼스 provider.

## 프로덕션에 배선하지 않는다

이 모듈은 시험과 `scripts/` 에서만 만들어진다. 여기서 나온 특허 본문은 **합성**이고
실제 공보가 아니므로, 이것으로 만들어진 근거는 실제 IP 판단에 쓸 수 없다.
`tests/intelligence/test_patent.py` 가 production 조립이 이 모듈을 참조하지 않는지
확인한다.

## 왜 대역이 아니라 XML 인가

``StaticPatentSearchProvider`` 처럼 파이썬 객체를 바로 돌려주면 **파싱 경로가
검증되지 않는다.** 실제로 이 프로젝트에서 가장 오래 걸린 결함 둘이 파싱과 응답
해석에 있었다 — 오류 본문을 "결과 0 건" 으로 넘긴 것과, 서비스 경로가 달라
인증되지 않은 것. 그래서 코퍼스를 **실제 응답과 같은 XML** 로 만들어
``KiprisClient`` 에 물린다.

## 검색 의미

KIPRIS 의 단어 검색은 넣은 단어를 **모두** 포함하는 문서를 찾는다 (AND).
코퍼스도 같게 동작한다 — 질의의 모든 토큰이 특허의 키워드에 있어야 적중이다.
그래서 검색어가 길수록 결과가 줄고, 그 성질이 `clamp_queries` 의 이유다.
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape

import httpx

from .kipris import KiprisClient

#: 실제 성공 응답과 같은 헤더. 값은 실측이다.
_HEADER = "<header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>"


def load_corpus(path: Path) -> dict[str, dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _search_xml(corpus: dict[str, dict], query: str, rows: int) -> bytes:
    tokens = [token for token in query.split() if token]
    items: list[str] = []
    for application_number, entry in sorted(corpus.items()):
        keywords = entry.get("keywords") or []
        haystack = " ".join([*keywords, entry.get("title", "")])
        if tokens and all(token in haystack for token in tokens):
            items.append(
                "<item>"
                f"<applicationNumber>{escape(application_number)}</applicationNumber>"
                f"<inventionTitle>{escape(entry['title'])}</inventionTitle>"
                f"<ipcNumber>{escape(entry.get('ipc', 'G10L 25/00'))}</ipcNumber>"
                f"<applicationDate>{escape(entry.get('application_date', '20240101'))}</applicationDate>"
                "<openDate></openDate>"
                "</item>"
            )
    body = "".join(items[:rows])
    return (
        f"<response>{_HEADER}<body><totalSearchCount>{len(items)}</totalSearchCount>"
        f"<items>{body}</items></body></response>"
    ).encode("utf-8")


def _detail_xml(corpus: dict[str, dict], application_number: str) -> bytes:
    entry = corpus.get(application_number)
    if entry is None:
        # 실제 KIPRIS 도 없는 번호에 대해 200 과 빈 본문을 돌려준다.
        return f"<response>{_HEADER}<body></body></response>".encode("utf-8")
    claims = "".join(
        f"<claimInfo><claim>{escape(claim)}</claim></claimInfo>"
        for claim in entry.get("claims") or []
    )
    return (
        f"<response>{_HEADER}<body>"
        f"<biblioSummaryInfo><inventionTitle>{escape(entry['title'])}</inventionTitle>"
        f"<applicationNumber>{escape(application_number)}</applicationNumber></biblioSummaryInfo>"
        f"<abstractInfo><astrtCont>{escape(entry.get('abstract', ''))}</astrtCont></abstractInfo>"
        f"{claims}"
        "</body></response>"
    ).encode("utf-8")


def offline_kipris_client(corpus: dict[str, dict], **kwargs) -> KiprisClient:
    """코퍼스를 실제 응답 모양의 XML 로 내주는 ``KiprisClient``.

    호출 횟수를 세고 싶으면 ``client.offline_calls`` 를 본다.
    """
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append(path)
        params = dict(request.url.params)
        if path.endswith("getWordSearch"):
            rows = int(params.get("docsCount") or 5)
            return httpx.Response(200, content=_search_xml(corpus, params.get("word", ""), rows))
        if path.endswith("getBibliographyDetailInfoSearch"):
            return httpx.Response(
                200, content=_detail_xml(corpus, params.get("applicationNumber", ""))
            )
        return httpx.Response(404, content=b"<response/>")

    client = KiprisClient(
        "offline-corpus",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        **kwargs,
    )
    client.offline_calls = calls  # type: ignore[attr-defined]
    return client


__all__ = ["load_corpus", "offline_kipris_client"]
