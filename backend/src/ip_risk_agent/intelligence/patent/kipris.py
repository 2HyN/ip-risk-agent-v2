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

# 실측으로 확정한 경로다. 이전 값(`/openapi/rest/KpaGeneralSearchService/anySearch`)
# 은 이 access key 로 `AccessKey&ServiceID Is Not Registerd Error` 를 돌려주었고,
# 그 응답이 HTTP 200 이라 검색이 조용히 0 건으로 처리됐다.
BASE_URL = "https://plus.kipris.or.kr/kipo-api/kipi"

SEARCH_PATH = "patUtiModInfoSearchSevice/getWordSearch"
# 항목별검색. getWordSearch 는 **전문(full-text) AND + 불투명한 정렬**이라
# 2단어 질의에 수천 건이 걸리고 원하는 문헌이 상위에 올 근거가 없다 — 골든셋
# 실측: "셔터 연동" 이 전문 8,166건(인용 문헌 60위 밖) vs 제목 19건(4위),
# 초록 394건(9위). 필드를 좁히는 것이 곧 순위를 만드는 것이다.
ADVANCED_SEARCH_PATH = "patUtiModInfoSearchSevice/getAdvancedSearch"
DETAIL_PATH = "patUtiModInfoSearchSevice/getBibliographyDetailInfoSearch"

# 이 base 는 키 파라미터 이름이 `ServiceKey` 다. `accessKey` 는 인증되지 않는다.
KEY_PARAM = "ServiceKey"

# 실측한 성공 응답의 코드. 오류는 30(등록/키), 11(필수 파라미터) 등이다.
SUCCESS_RESULT_CODE = "00"

#: 실측한 KIPRIS 오류 코드. 코드가 곧 분류다.
#:
#: 셋 다 **다시 걸어도 결과가 같다.** 그래서 어느 것도 재시도 대상이 아니다.
#: 메시지로 추정하면 이 구분이 흐려져 재시도가 상황을 악화시킨다 — 22 를
#: UNAVAILABLE 로 분류했을 때 실제로 그랬다.
#:
#: * 22 호출 한도 초과. 재시도가 한도를 더 쓴다
#: * 30 키가 발급 대장에 없다. 서비스 미신청이면 30 이 아니라 31 이 온다
#: * 31 신청은 했으나 이용기간이 끝났다. 갱신 전에는 계속 같다
#:
#: 30 과 31 은 실측으로 갈랐다. 같은 키로 특허는 22, 상표·디자인은 31 이 왔고,
#: 다른 키는 세 서비스 모두 30 이었다.
_RESULT_CODE_CATEGORIES = {
    "22": FailureCategory.RATE_LIMITED,
    "30": FailureCategory.AUTH,
    "31": FailureCategory.AUTH,
}

PROVIDER = "KIPRIS"
_TIMEOUT_SECONDS = 20.0

# 검색 다섯 건이 한꺼번에 타임아웃해 분석 전체가 실패한 적이 있다. 개별 요청의
# 문제가 아니라 그 시점 KIPRIS 가 느렸던 것이므로 짧게 한 번 더 시도한다.
# GET 이라 재시도가 안전하다. 최악 지연은 두 배가 되지만 (검색 120s + 대조)
# worker 요청 예산 300 초 안에 든다.
_RETRY_ATTEMPTS = 2
_RETRY_BACKOFF_SECONDS = 1.0

# 다시 걸어볼 값어치가 있는 것만 재시도한다. 인증 실패는 다시 해도 같고,
# 호출량 초과는 재시도가 상황을 악화시킨다.
_RETRYABLE_CATEGORIES = frozenset({FailureCategory.TIMEOUT, FailureCategory.UNAVAILABLE})

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

    이것을 그대로 파싱하면 결과 항목이 0 개라 "검색은 정상이고 결과가 없었다" 로
    처리된다. 그러면 특허 분석이 coverage=COMPLETE 로 끝나며 **없는 권위를
    주장한다.** 운영에서 실제로 그랬다 — 모든 질의가 hit_total=0,
    search_failures=0 이었고 실은 한 번도 검색되지 않았다.

    실측한 성공 응답은 ``resultCode=00`` / ``resultMsg=NORMAL SERVICE.`` 다.
    메시지는 성공에도 채워지므로 **코드로 판정한다.**

    분류는 코드로 한다. 특히 한도 초과(22)를 ``UNAVAILABLE`` 로 두면 재시도가
    상황을 악화시킨다 — 이미 한도를 넘긴 키로 한 번 더 부를 뿐이다. 실측한 응답은
    ``resultCode=22`` / ``resultMsg=LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR``
    이고, ``RATE_LIMITED`` 는 ``_RETRYABLE_CATEGORIES`` 에 없으므로 즉시 실패한다.
    """
    code = (root.findtext(".//resultCode") or "").strip()
    if not code or code == SUCCESS_RESULT_CODE:
        return
    message = (root.findtext(".//resultMsg") or "").strip().casefold()
    category = _RESULT_CODE_CATEGORIES.get(code)
    if category is None:
        category = (
            FailureCategory.AUTH
            if any(
                token in message
                for token in ("accesskey", "serviceid", "not registerd", "unauthorized")
            )
            else FailureCategory.RATE_LIMITED
            if "limited_number" in message or "exceeds" in message
            else FailureCategory.AUTH
            if "expired" in message or "deadline" in message
            else FailureCategory.UNAVAILABLE
        )
    raise ProviderFailureError(
        PROVIDER, category, f"KIPRIS rejected the request (resultCode={code})"
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
        retry_attempts: int = _RETRY_ATTEMPTS,
        retry_backoff_seconds: float = _RETRY_BACKOFF_SECONDS,
        client: httpx.AsyncClient | None = None,
        search_fields: tuple[str, ...] | None = None,
    ) -> None:
        # None 이면 기존 getWordSearch(전문 검색). ("inventionTitle", "astrtCont")
        # 처럼 주면 항목별검색으로 필드마다 검색해 병합한다 — 상단
        # ADVANCED_SEARCH_PATH 주석의 실측이 근거다. 기본값은 기존 동작 유지.
        self._search_fields = search_fields
        self._access_key = access_key
        self._retry_attempts = max(1, retry_attempts)
        self._retry_backoff_seconds = retry_backoff_seconds
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
        if self._search_fields is not None:
            return await self._fielded_search(query, rows=rows)
        root = await self._get(
            SEARCH_PATH,
            {
                "word": query,
                "year": "0",
                "patent": "true",
                "utility": "true",
                "docsStart": "1",
                "docsCount": str(rows),
            },
        )
        return self._parse_hits(root, query)

    async def _fielded_search(self, query: str, *, rows: int) -> list[PatentSearchHit]:
        """항목별검색 — 필드마다 따로 검색해 병합한다.

        제목은 정밀하고(수십 건) 초록은 재현이 넓다(수백 건). 제목 결과를 앞에
        두고 초록 결과로 뒤를 채운다 — 인용 문헌이 제목 4위 / 초록 9위였던
        실측이 이 순서의 근거다. 필드 수만큼 호출이 늘어나는 것이 대가다.
        """
        merged: list[PatentSearchHit] = []
        seen: set[str] = set()
        for field in self._search_fields or ():
            root = await self._get(
                ADVANCED_SEARCH_PATH,
                {
                    field: query,
                    "patent": "true",
                    "utility": "true",
                    "docsStart": "1",
                    "docsCount": str(max(rows, 20)),
                },
            )
            for hit in self._parse_hits(root, query):
                if hit.application_number not in seen:
                    seen.add(hit.application_number)
                    merged.append(hit)
        return merged[: max(rows, 20)]

    def _parse_hits(self, root: Element, query: str) -> list[PatentSearchHit]:
        hits: list[PatentSearchHit] = []
        for element in root.iter("item"):
            number = normalize_application_number(_text(element, "applicationNumber"))
            if not number:
                continue
            hits.append(
                PatentSearchHit(
                    application_number=number,
                    title=_text(element, "inventionTitle"),
                    query=query,
                    metadata={
                        "applicationDate": _text(element, "applicationDate"),
                        "openDate": _text(element, "openDate"),
                        "ipc": _text(element, "ipcNumber"),
                    },
                )
            )
        return hits

    async def fetch_detail(self, application_number: str) -> PatentDocument:
        """서지·초록·청구항을 한 번에 가져온다.

        이전 구현은 서지와 국문 초록을 각각 다른 서비스에서 조회했다. 현재 경로는
        한 응답에 모두 담겨 있고 **청구항도 포함한다** — 초록만 제공된다는 기존
        제약(Agent 3 Spec 17)은 이 경로에서는 사실이 아니다. 청구항이 있으면
        대조 근거의 질이 올라간다.
        """
        root = await self._get(DETAIL_PATH, {"applicationNumber": application_number})

        title = ""
        summary = next(root.iter("biblioSummaryInfo"), None)
        if summary is not None:
            title = _text(summary, "inventionTitle") or _text(summary, "inventionTitleEng")

        abstract = ""
        for node in root.iter("abstractInfo"):
            abstract = _text(node, "astrtCont")
            if abstract:
                break

        claims = [
            text
            for node in root.iter("claimInfo")
            for text in (_text(node, "claim"),)
            if text
        ]

        return PatentDocument(
            application_number=application_number,
            title=title,
            abstract=abstract,
            claims=claims,
            metadata={"claim_count": str(len(claims))},
        )

    # ------------------------------------------------------------ 내부

    async def _get(self, path: str, params: dict[str, str]) -> Element:
        for attempt in range(1, self._retry_attempts + 1):
            try:
                return await self._get_once(path, params)
            except ProviderFailureError as exc:
                last = exc
                if (
                    attempt == self._retry_attempts
                    or exc.category not in _RETRYABLE_CATEGORIES
                ):
                    raise
            await asyncio.sleep(self._retry_backoff_seconds * attempt)
        raise last  # pragma: no cover - 위 루프가 항상 반환하거나 올린다

    async def _get_once(self, path: str, params: dict[str, str]) -> Element:
        url = f"{self._base_url}/{path}"
        async with self._gate:
            try:
                response = await self._client.get(
                    url, params={**params, KEY_PARAM: self._access_key}
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
