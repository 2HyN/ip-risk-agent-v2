"""골든 데이터셋 수집 — 심사 이력을 라벨로 바꾼다.

## 무엇을 만드는가

특허 파이프라인의 신뢰도를 재기 위한 (출원 문서, 심사 결과 라벨) 쌍이다.
심사관이 실제로 내린 판단을 정답으로 빌린다 — 우리에게 없는 특허 전문성을
사람 라벨링 없이 확보하는 유일한 길이다.

    라벨 0  의견제출통지서 없음        심사관이 인용할 것을 찾지 못했다
    라벨 1  통지서 있음, 거절결정 없음   선행문헌이 있었으나 극복했다
    라벨 2  거절결정 있음              선행문헌을 넘지 못했다

라벨 0 은 심사청구가 있었던 출원에서만 의미가 있다. 심사 자체가 없었으면
"통지서 없음" 은 음성이 아니라 무정보다 — 수집할 때 등록/거절까지 간 출원만
넣는 이유다.

## 호출 예산

무료 한도는 **월 1,000 회이고 운영 분석과 공유**한다. 그래서:

* 모든 호출을 세고, ``--max-calls`` (기본 60) 에서 멈춘다
* 받은 응답은 전부 ``labels/golden/raw/`` 에 저장한다 — 같은 것을 두 번
  묻지 않는다. 재실행하면 저장분을 먼저 쓴다
* ``resultCode=22`` (한도 초과) 가 오면 즉시 전체를 멈춘다

## 지금 비어 있는 것 — 실행 전에 채워야 한다

서비스 루트는 상품 페이지에서 실측했지만 **오퍼레이션 이름**(요청 URL 의
마지막 조각)은 로그인한 화면의 오퍼레이션 상세에만 보인다. 아래
``SERVICE_URLS`` 의 ``None`` 을 그 요청 URL 로 채운 뒤 ``probe`` 로 검증한다.
경로를 추측해서 넣지 않는다 — 잘못된 경로도 HTTP 200 으로 "등록 안 됨" 을
돌려줘서 (kipris.py 의 BASE_URL 주석 참조) 조용히 0 건이 된다.

## 쓰는 법

    # 1) 엔드포인트 검증 (2~4 회 소비). 30/31 이 오면 상품이 키에 안 붙은 것
    .venv/Scripts/python scripts/collect_golden_pairs.py probe

    # 2) 수집 — 출원번호 목록 파일 (한 줄에 하나, 하이픈 유무 무관)
    .venv/Scripts/python scripts/collect_golden_pairs.py collect --applications apps.txt

키는 환경변수 ``KIPRIS_ACCESS_KEY`` 로 받는다. 값은 어디에도 출력하지 않는다.
산출물은 ``labels/`` 아래이고 이 디렉터리는 gitignore 되어 있다 — 실제 공보
본문이 담기므로 저장소에 커밋하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from defusedxml.ElementTree import fromstring

from ip_risk_agent.intelligence.patent.kipris import (
    BASE_URL,
    DETAIL_PATH,
    SEARCH_PATH,
    SUCCESS_RESULT_CODE,
    normalize_application_number,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "labels" / "golden"
RAW_DIR = OUT_DIR / "raw"

# ── 상품 페이지의 오퍼레이션 상세에서 채울 곳 ────────────────────────
# 이 두 상품은 운영 코드의 kipo-api 베이스가 아니라 **구형 openapi/rest 베이스**다
# (상품 페이지의 요청 URL 에서 실측). 서비스 루트는 확정, 오퍼레이션 이름
# (요청 URL 마지막 조각 / "오퍼레이션 명" 칸의 영문)만 채우면 된다.
OPINION_SERVICE = "http://plus.kipris.or.kr/openapi/rest/IntermediateDocumentOPService"
REJECTION_SERVICE = "http://plus.kipris.or.kr/openapi/rest/IntermediateDocumentREService"

SERVICE_URLS: dict[str, str | None] = {
    # 라벨 1 판정 — 출원번호로 통지서 발송 이력 조회 (오퍼레이션 명세 실측).
    "opinion_notice": f"{OPINION_SERVICE}/bibliographicInfo",
    # 심사관 대비 본문 — rejectDecisionInfo. 출력값에 rejectionContentDetail ·
    # lawContent 등 **본문 텍스트 필드가 XML 로 있다** (명세 실측). PDF 불필요.
    "opinion_content": f"{OPINION_SERVICE}/rejectDecisionInfo",
    # 라벨 2 판정. 거절결정서 상품도 같은 오퍼레이션 구성을 쓴다 (상품 페이지의
    # 오퍼레이션 목록이 동일) — 서비스 루트만 RE 다.
    "rejection_decision": f"{REJECTION_SERVICE}/bibliographicInfo",
    # recall 채점용 후보 목록 (인용문헌V3). 상품 미신청 — 신청하면 채운다.
    "citations": None,
}

# 파라미터 이름도 오퍼레이션 상세의 입력값(Request Parameter) 표 확인 대상이다.
APPLICATION_PARAM = "applicationNumber"

# 이 상품들의 입력값 샘플이 `accessKey=` 를 쓴다 (명세 실측). kipo-api 베이스의
# 공보 상세는 `ServiceKey` 이므로 (kipris.py 실측) 후보를 순서대로 시도해
# 베이스마다 동작하는 쪽을 기억한다.
KEY_PARAM_CANDIDATES = ("accessKey", "ServiceKey")


class QuotaExhausted(RuntimeError):
    """resultCode=22 — 이번 달 한도가 끝났다. 더 걸면 운영 몫만 축낸다."""


@dataclass
class Budget:
    limit: int
    spent: int = 0
    log: list[str] = field(default_factory=list)

    def charge(self, what: str) -> None:
        if self.spent >= self.limit:
            raise SystemExit(
                f"호출 예산 {self.limit}회 소진 — 여기서 멈춘다. 지금까지: {self.log}"
            )
        self.spent += 1
        self.log.append(what)


def _client() -> httpx.Client:
    return httpx.Client(timeout=20.0)


# 첫 성공에서 판명된 키 파라미터 이름. 서비스 베이스마다 다를 수 있어 베이스별로 든다.
_WORKING_KEY_PARAM: dict[str, str] = {}


def _base_of(url: str) -> str:
    return url.split("/rest/")[0] if "/rest/" in url else url.rsplit("/", 1)[0]


# 운영 베이스(kipo-api)는 ServiceKey 가 실측 확정 (kipris.py) — 헛시도를 막는다.
_WORKING_KEY_PARAM[_base_of(f"{BASE_URL}/{DETAIL_PATH}")] = "ServiceKey"


def _get(
    client: httpx.Client,
    budget: Budget,
    url: str,
    params: dict[str, str],
    *,
    cache_name: str,
) -> str:
    """호출 1 회. 같은 요청의 응답이 raw/ 에 있으면 호출하지 않는다.

    키 파라미터 이름이 베이스마다 다르다(ServiceKey vs accessKey). 어느 쪽인지
    모르는 베이스는 후보를 순서대로 시도하고, 성공한 이름을 기억해 다음부터
    한 번에 간다 — 실패 시도도 호출로 세는 것이 보수적으로 맞다.
    """
    cache = RAW_DIR / f"{cache_name}.xml"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    key = os.environ.get("KIPRIS_ACCESS_KEY", "").strip()
    if not key:
        raise SystemExit(
            "KIPRIS_ACCESS_KEY 가 비어 있다. v1 의 .env 값을 환경변수로 넘겨라 —"
            " 값을 파일이나 화면에 옮겨 적지 말 것."
        )
    base = _base_of(url)
    candidates = (
        (_WORKING_KEY_PARAM[base],)
        if base in _WORKING_KEY_PARAM
        else KEY_PARAM_CANDIDATES
    )
    body = ""
    for key_param in candidates:
        budget.charge(f"{url}?{APPLICATION_PARAM}={params.get(APPLICATION_PARAM, '')}")
        response = client.get(url, params={**params, key_param: key})
        response.raise_for_status()
        body = response.text
        code = (fromstring(body).findtext(".//resultCode") or "").strip()
        if code == "22":
            raise QuotaExhausted("KIPRIS 월 한도 초과 (resultCode=22) — 전체 중단")
        if code in {"30", "31"} or "Not Register" in body:
            # 30: 키 미등록 / 31: 이용기간 밖 / 구형 베이스는 문구로 온다.
            # 다른 키 파라미터 이름을 마저 시도한다.
            continue
        _WORKING_KEY_PARAM[base] = key_param
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(body, encoding="utf-8")
        return body
    raise SystemExit(
        f"{url}: 어떤 키 파라미터로도 인증되지 않았다"
        f" (시도: {candidates}). 상품 신청 상태를 확인할 것. 마지막 응답 일부:"
        f" {body[:200]}"
    )


def _require_paths(*names: str) -> None:
    missing = [name for name in names if SERVICE_URLS[name] is None]
    if missing:
        raise SystemExit(
            f"SERVICE_URLS 미기입: {missing} — 상품 페이지 오퍼레이션 상세의"
            " 요청 URL 을 채운 뒤 다시 실행할 것. 추측으로 채우지 말 것."
        )


def probe(budget: Budget) -> None:
    """엔드포인트가 살아 있고 키에 붙어 있는지 최소 호출로 확인한다."""
    _require_paths("opinion_notice", "rejection_decision")
    # 통지 1건 + 거절결정 2건이 실측으로 확인된 출원 — '있음' 이 나와야 정상이라
    # 빈 응답과 경로 오류를 구별할 수 있다.
    sample = "1020200157175"
    with _client() as client:
        for name, url in SERVICE_URLS.items():
            if url is None:
                print(f"  {name:20s} (미기입 — 건너뜀)")
                continue
            body = _get(
                client,
                budget,
                url,
                {APPLICATION_PARAM: sample},
                cache_name=f"probe-{name}-{sample}",
            )
            found = _has_items(body)
            print(
                f"  {name:20s} 항목 {'있음' if found else '없음'}"
                f" · 키 파라미터 {_WORKING_KEY_PARAM.get(_base_of(url), '?')}"
            )
    print(f"소비 {budget.spent}회. 응답 원문: {RAW_DIR} — 직접 열어 확인할 것")


def collect(budget: Budget, applications_file: Path) -> None:
    """출원번호마다 문서·라벨 재료를 모아 pairs.jsonl 로 남긴다."""
    _require_paths("opinion_notice", "rejection_decision")
    numbers = [
        normalize_application_number(line)
        for line in applications_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "pairs.jsonl"
    written = 0
    with _client() as client, out.open("a", encoding="utf-8") as sink:
        for number in numbers:
            try:
                record = _collect_one(client, budget, number)
            except QuotaExhausted as reason:
                print(f"중단: {reason}")
                break
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1
            print(
                f"  {number}: label={record['label']}"
                f" citations={len(record['citation_numbers'])}"
            )
    print(f"기록 {written}건 → {out} · 소비 {budget.spent}회")


def _collect_one(client: httpx.Client, budget: Budget, number: str) -> dict:
    # 입력 문서(초록)와 등록상태의 원전. 운영과 같은 공보 상세를 쓴다.
    _get(
        client,
        budget,
        f"{BASE_URL}/{DETAIL_PATH}",
        {APPLICATION_PARAM: number},
        cache_name=f"biblio-{number}",
    )
    notice_url = SERVICE_URLS["opinion_notice"]
    decision_url = SERVICE_URLS["rejection_decision"]
    assert notice_url and decision_url
    notice = _get(
        client, budget, notice_url, {APPLICATION_PARAM: number},
        cache_name=f"notice-{number}",
    )
    has_notice = _has_items(notice)
    # 통지서가 없으면 거절결정도 없다 — 절차상 통지 없이 거절할 수 없으므로
    # 호출 하나를 아낀다.
    has_decision = False
    cited: list[str] = []
    content_filled = False
    if has_notice:
        decision = _get(
            client, budget, decision_url, {APPLICATION_PARAM: number},
            cache_name=f"decision-{number}",
        )
        has_decision = _has_items(decision)
        content_url = SERVICE_URLS["opinion_content"]
        assert content_url
        content = _get(
            client, budget, content_url, {APPLICATION_PARAM: number},
            cache_name=f"content-{number}",
        )
        cited = _attachment_citations(content)
        content_filled = _content_detail_filled(content)
    citations_url = SERVICE_URLS["citations"]
    citation_numbers: list[str] = []
    if citations_url is not None:
        citations = _get(
            client, budget, citations_url, {APPLICATION_PARAM: number},
            cache_name=f"citations-{number}",
        )
        citation_numbers = _citation_numbers(citations)
    return {
        "application_number": number,
        "label": 2 if has_decision else 1 if has_notice else 0,
        # 라벨 0 의 유효성(심사청구·등록 여부)은 서지 XML 로 검증한다.
        # 필드 이름이 명세서 확인 전이라 원문 경로만 남긴다.
        "biblio_raw": f"raw/biblio-{number}.xml",
        "notice_raw": f"raw/notice-{number}.xml",
        # 통지서 PDF 링크(fileToss.jsp). 3층 평가(겹침 지점 채점)에서
        # 거절결정내용 오퍼레이션이 본문을 못 줄 때의 대안 경로다.
        "notice_pdf_urls": _file_paths(notice),
        # 심사관이 통지서에 첨부한 선행문헌 번호 — recall 채점의 정답.
        # 인용문헌 상품 없이도 여기서 나온다 (probe 실측).
        "examiner_cited": cited,
        # rejectionContentDetail 이 채워져 있는가. 3층 평가 가능 여부의 표지.
        "content_detail_filled": content_filled,
        "citation_numbers": citation_numbers,
    }


# 첨부 목록의 공보 번호. "등록특허공보 제10-1582254호" / "공개특허공보
# 제10-2012-0106424호" 형태를 실측했다 (probe-opinion_content-*.xml).
_ATTACHMENT_NUMBER = re.compile(r"제\s*(\d{2}-\d{4,7}(?:-\d{7})?)\s*호")


def _attachment_citations(body: str) -> list[str]:
    root = fromstring(body)
    numbers: list[str] = []
    for node in root.iter("attachmentfileContent"):
        for match in _ATTACHMENT_NUMBER.finditer(node.text or ""):
            digits = normalize_application_number(match.group(1))
            if digits and digits not in numbers:
                numbers.append(digits)
    return numbers


def _content_detail_filled(body: str) -> bool:
    root = fromstring(body)
    return any(
        (node.text or "").strip()
        for node in root.iter("rejectionContentDetail")
    )


def _file_paths(body: str) -> list[str]:
    root = fromstring(body)
    return [
        (node.text or "").strip()
        for node in root.iter("filePath")
        if (node.text or "").strip()
    ]


def _has_items(body: str) -> bool:
    """응답에 실제 항목이 있는가.

    실측: 의견제출통지서 서비스는 **성공 시 resultCode 가 빈 값**이다
    (공보 서비스의 성공 코드 00 과 다르다). 그래서 코드로 성공을 판정하지
    않는다 — 오류 코드(22/30/31 등)가 아닌 한, body/items 아래에 항목
    요소가 있는지로 '있음' 을 판정한다.
    """
    root = fromstring(body)
    code = (root.findtext(".//resultCode") or "").strip()
    if code and code != SUCCESS_RESULT_CODE:
        return False
    items = next(root.iter("items"), None)
    if items is None:
        items = next(root.iter("body"), None)
    if items is None:
        return False
    # totCnt/docsStart 같은 집계 요소는 항목이 아니다.
    return any(len(list(child)) > 0 for child in items)


def _citation_numbers(body: str) -> list[str]:
    """인용문헌 응답에서 문헌번호를 뽑는다. 요소 이름은 명세서 확인 후 조정."""
    root = fromstring(body)
    numbers = {
        normalize_application_number(node.text or "")
        for node in root.iter()
        if node.tag.lower().endswith("documentnumber") and (node.text or "").strip()
    }
    return sorted(number for number in numbers if number)


def collect_negatives(budget: Budget, queries: list[str], target: int) -> None:
    """라벨 0 표본 — 통지서 없이 등록된 출원.

    검색으로 후보를 모으고, 공보 상세에서 **등록 + 심사청구** 를 확인한 뒤,
    통지서 부재를 확인한 것만 라벨 0 으로 남긴다. 순서가 비용을 정한다:
    등록 여부(공보 1회)를 먼저 보고 탈락시키면 통지서 조회를 아낀다.

    "등록 + 통지서 없음" 은 일발등록 — 심사관이 선행문헌을 찾아봤는데 인용할
    것이 없었다는 뜻이라 꽤 깨끗한 음성이다. "등록 + 통지서 있음" 은 라벨 1 로
    이미 수집되는 부류이니 여기서는 버린다.
    """
    _require_paths("opinion_notice")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "pairs.jsonl"
    seen = {
        json.loads(line)["application_number"]
        for line in out.read_text(encoding="utf-8").splitlines()
        if line.strip()
    } if out.exists() else set()
    found = 0
    with _client() as client, out.open("a", encoding="utf-8") as sink:
        for query in queries:
            if found >= target:
                break
            search = _get(
                client,
                budget,
                f"{BASE_URL}/{SEARCH_PATH}",
                {
                    "word": query,
                    "year": "0",
                    "patent": "true",
                    "utility": "true",
                    "docsStart": "1",
                    "docsCount": "30",
                },
                cache_name=f"search-{query}",
            )
            root = fromstring(search)
            numbers = [
                normalize_application_number(node.findtext("applicationNumber") or "")
                for node in root.iter("item")
            ]
            for number in numbers:
                if found >= target:
                    break
                if not number or number in seen:
                    continue
                seen.add(number)
                try:
                    record = _try_negative(client, budget, number)
                except QuotaExhausted as reason:
                    print(f"중단: {reason}")
                    return
                if record is None:
                    continue
                sink.write(json.dumps(record, ensure_ascii=False) + chr(10))
                found += 1
                print(f"  {number}: label=0 ({record['register_status']})")
    print(f"라벨 0 {found}건 추가 · 소비 {budget.spent}회")


def _try_negative(client: httpx.Client, budget: Budget, number: str) -> dict | None:
    biblio = _get(
        client,
        budget,
        f"{BASE_URL}/{DETAIL_PATH}",
        {APPLICATION_PARAM: number},
        cache_name=f"biblio-{number}",
    )
    root = fromstring(biblio)
    status = (next(root.iter("registerStatus"), None) is not None
              and (next(root.iter("registerStatus")).text or "").strip()) or ""
    requested = ((next(root.iter("originalExaminationRequestFlag"), None) is not None
                  and (next(root.iter("originalExaminationRequestFlag")).text or "").strip()) or "")
    # 등록이 아니면 음성 후보가 아니다. 심사청구 표시가 없으면 "통지서 없음" 이
    # 무정보라 역시 버린다 (모듈 docstring 의 라벨 0 조건).
    if status != "등록" or requested != "Y":
        return None
    notice = _get(
        client, budget, SERVICE_URLS["opinion_notice"] or "",
        {APPLICATION_PARAM: number},
        cache_name=f"notice-{number}",
    )
    if _has_items(notice):
        return None  # 통지서를 받고 극복한 등록 — 라벨 1 부류라 여기서는 버린다
    return {
        "application_number": number,
        "label": 0,
        "register_status": status,
        "biblio_raw": f"raw/biblio-{number}.xml",
        "notice_raw": f"raw/notice-{number}.xml",
        "notice_pdf_urls": [],
        "examiner_cited": [],
        "content_detail_filled": False,
        "citation_numbers": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["probe", "collect", "label0"])
    parser.add_argument("--applications", type=Path, help="출원번호 목록 파일")
    parser.add_argument("--queries", nargs="*", help="label0: 후보를 찾을 검색어들")
    parser.add_argument("--target", type=int, default=20, help="label0: 목표 건수")
    parser.add_argument("--max-calls", type=int, default=60)
    args = parser.parse_args()
    budget = Budget(limit=args.max_calls)
    if args.mode == "probe":
        probe(budget)
        return
    if args.mode == "label0":
        if not args.queries:
            parser.error("label0 에는 --queries 가 필요하다")
        collect_negatives(budget, args.queries, args.target)
        return
    if args.applications is None:
        parser.error("collect 에는 --applications 가 필요하다")
    collect(budget, args.applications)


if __name__ == "__main__":
    main()
