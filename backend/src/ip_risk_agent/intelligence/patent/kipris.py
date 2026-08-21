"""KIPRIS Plus 접근 계층.

XML/HTTP 처리는 전부 이 파일에 가둔다 (Agent 3 Spec 14). Analyzer 는 특허를
:class:`PatentDocument` 로만 본다.

검색이 0건인 것과 호출이 실패한 것을 반드시 구분한다 (Agent 3 Spec 15).
0건은 "선행 특허가 없다"이고 실패는 "모른다"이다. 둘을 섞으면 장애가
위험 해소로 둔갑한다.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Protocol
from xml.etree.ElementTree import Element

import httpx
from defusedxml.ElementTree import ParseError, fromstring

from ..common.errors import FailureCategory, ProviderFailureError

BASE_URL = "https://plus.kipris.or.kr/openapi/rest"

# 세 서비스로 나뉘어 있다. 검색 응답에는 초록이 없어 따로 조회해야 한다.
SEARCH_PATH = "KpaGeneralSearchService/anySearch"
BIBLIOGRAPHIC_PATH = "KpaBibliographicService/bibliographicInfo"
KOREAN_ABSTRACT_PATH = "KorAbstractInfoService/korAbstractInfo"

PROVIDER = "KIPRIS"
_TIMEOUT_SECONDS = 20.0

# 출원번호는 하이픈 유무가 응답마다 다르다. 숫자만 남겨 하나로 본다.
_DIGITS = re.compile(r"\D+")


def normalize_application_number(raw: str) -> str:
    """중복 판정의 기준값. 같은 특허가 여러 검색어에서 나와도 하나로 합쳐진다."""
    return _DIGITS.sub("", raw or "")


@dataclass(frozen=True)
class PatentSearchHit:
    """검색 결과 한 건. 초록은 아직 없다."""

    application_number: str
    title: str
    query: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PatentDocument:
    """대조에 쓰는 특허 문서.

    청구항을 우선하되 KIPRIS 가 제공하는 범위는 초록이다 (Agent 3 Spec 17).
    """

    application_number: str
    title: str
    abstract: str = ""
    claims: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def has_content(self) -> bool:
        return bool(self.abstract or self.claims)


class PatentSearchProvider(Protocol):
    async def search(self, query: str, *, rows: int = 5) -> list[PatentSearchHit]:
        ...

    async def fetch_detail(self, application_number: str) -> PatentDocument:
        ...


def _require_successful_result(root: Element) -> None:
    """오류 본문을 "결과 0건" 으로 넘기지 않는다.

    KIPRIS 는 인증/등록 실패도 **HTTP 200** 으로 돌려주고 본문에만 사유를 남긴다.

        <resultCode>30</resultCode>
        <resultMsg>AccessKey&ServiceID Is Not Registerd Error</resultMsg>

    이것을 그대로 파싱하면 ``searchResult`` 가 0 개라 "검색은 정상이고 결과가
    없었다" 로 처리된다. 그러면 특허 분석이 coverage=COMPLETE 로 끝나며 **없는
    권위를 주장한다.** 운영에서 실제로 그랬다 — 모든 질의가 hit_total=0,
    search_failures=0 이었고 실은 한 번도 검색되지 않았다.

    성공 응답의 정확한 코드 값은 문서화되어 있지 않으므로 ``resultMsg`` 가 비어
    있지 않으면 실패로 본다. 판정이 한쪽으로 틀린다면 **거짓 실패**여야 한다.
    거짓 성공은 "Risk 없음" 으로 읽히고, 거짓 실패는 coverage 를 낮출 뿐이다.
    """
    # 두 값은 <header> 아래에 중첩되어 온다. 직계 자식만 보면 놓친다.
    message = (root.findtext(".//resultMsg") or "").strip()
    if not message:
        return
    code = (root.findtext(".//resultCode") or "").strip()
    lowered = message.casefold()
    category = (
        FailureCategory.AUTH
        if any(token in lowered for token in ("accesskey", "serviceid", "not registerd", "unauthorized"))
        else FailureCategory.UNAVAILABLE
    )
    raise ProviderFailureError(
        PROVIDER,
        category,
        f"KIPRIS rejected the request (resultCode={code or 'unknown'})",
    )


def _text(element: Element, tag: str) -> str:
    return (element.findtext(tag) or "").strip()


class KiprisClient:
    """실제 KIPRIS Plus 호출.

    ``searchAny`` 는 넣은 단어를 **모두** 포함하는 문서만 찾는다. 그래서 검색어가
    길면 결과가 0건이 된다. 검색어를 2~3 단어로 제한하는 이유가 이것이다.
    """

    def __init__(
        self,
        access_key: str,
        *,
        base_url: str = BASE_URL,
        timeout_seconds: float = _TIMEOUT_SECONDS,
        max_concurrency: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._access_key = access_key
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds,
            headers={"User-Agent": "ip-risk-agent/1.0"},
        )
        # 공공 API 는 동시 호출에 민감하다. 스스로 조인다.
        self._gate = asyncio.Semaphore(max_concurrency)

    async def aclose(self) -> None:
        """직접 만든 연결만 닫는다. 주입받은 것은 호출자 소유다."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "KiprisClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def search(self, query: str, *, rows: int = 5) -> list[PatentSearchHit]:
        root = await self._get(
            SEARCH_PATH,
            {"searchAny": query, "docsCount": str(rows), "currentPage": "1"},
        )
        hits: list[PatentSearchHit] = []
        # 실제 응답 기준. 항목 태그는 <item> 이 아니라 <searchResult> 이고,
        # 필드도 applicationNumber/inventionTitle 이 아니라 아래 이름을 쓴다.
        for element in root.iter("searchResult"):
            number = normalize_application_number(_text(element, "applicationNo"))
            if not number:
                continue
            hits.append(
                PatentSearchHit(
                    application_number=number,
                    title=_text(element, "inventionName"),
                    query=query,
                    metadata={
                        "applicationDate": _text(element, "applicationDate"),
                        "registerDate": _text(element, "registerDate"),
                        "ipc": _text(element, "ipc"),
                    },
                )
            )
        return hits

    async def fetch_detail(self, application_number: str) -> PatentDocument:
        """서지 정보와 국문 초록을 합친다.

        검사 대상 문서는 대개 한국어다. 국문 초록이 있으면 그것을 대조에 쓰고,
        없을 때만 영문 초록을 쓴다. 언어가 다르면 겹치는 표현을 찾기 어렵다.
        """
        bibliographic = await self._get(
            BIBLIOGRAPHIC_PATH, {"applicationNumber": application_number}
        )
        english_abstract = (bibliographic.findtext(".//astrtCont") or "").strip()
        english_title = (bibliographic.findtext(".//inventionTitle") or "").strip()

        korean_abstract = korean_title = ""
        try:
            korean = await self._get(
                KOREAN_ABSTRACT_PATH, {"applicationNumber": application_number}
            )
            korean_abstract = (korean.findtext(".//korAbstract") or "").strip()
            korean_title = (korean.findtext(".//inventionName") or "").strip()
        except ProviderFailureError:
            # 국문 조회는 보조 경로다. 실패해도 영문으로 대조할 수 있다.
            pass

        abstract = korean_abstract or english_abstract
        return PatentDocument(
            application_number=application_number,
            title=korean_title or english_title,
            abstract=abstract,
            metadata={
                "abstract_language": "ko" if korean_abstract else "en",
                "english_title": english_title,
            },
        )

    # ------------------------------------------------------------ 내부

    async def _get(self, path: str, params: dict[str, str]) -> Element:
        url = f"{self._base_url}/{path}"
        async with self._gate:
            try:
                response = await self._client.get(
                    url, params={**params, "accessKey": self._access_key}
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                category = {
                    401: FailureCategory.AUTH,
                    403: FailureCategory.AUTH,
                    429: FailureCategory.RATE_LIMITED,
                }.get(status, FailureCategory.UNAVAILABLE)
                raise ProviderFailureError(PROVIDER, category, f"HTTP {status}") from exc
            except httpx.TimeoutException as exc:
                raise ProviderFailureError(
                    PROVIDER, FailureCategory.TIMEOUT, "request timed out"
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderFailureError(
                    PROVIDER, FailureCategory.UNAVAILABLE, type(exc).__name__
                ) from exc

        # 외부에서 받은 XML 이다. 엔티티 확장 공격을 막는 파서를 쓴다.
        try:
            root = fromstring(response.content)
        except ParseError as exc:
            raise ProviderFailureError(
                PROVIDER, FailureCategory.MALFORMED_OUTPUT, "response was not valid XML"
            ) from exc
        _require_successful_result(root)
        return root


class StaticPatentSearchProvider:
    """테스트용. 검색어별 결과와 실패를 지정한다."""

    def __init__(
        self,
        results: dict[str, list[PatentSearchHit]] | None = None,
        documents: dict[str, PatentDocument] | None = None,
        *,
        failing_queries: set[str] | None = None,
        failing_details: set[str] | None = None,
    ) -> None:
        self._results = results or {}
        self._documents = documents or {}
        self._failing_queries = failing_queries or set()
        self._failing_details = failing_details or set()

    async def search(self, query: str, *, rows: int = 5) -> list[PatentSearchHit]:
        if query in self._failing_queries:
            raise ProviderFailureError(PROVIDER, FailureCategory.TIMEOUT, "request timed out")
        return list(self._results.get(query, []))[:rows]

    async def fetch_detail(self, application_number: str) -> PatentDocument:
        if application_number in self._failing_details:
            raise ProviderFailureError(
                PROVIDER, FailureCategory.UNAVAILABLE, "detail service unavailable"
            )
        document = self._documents.get(application_number)
        if document is None:
            raise ProviderFailureError(PROVIDER, FailureCategory.NOT_FOUND, "not found")
        return document
