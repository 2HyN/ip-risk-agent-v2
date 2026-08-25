"""질의 생성 개선의 천장 측정 — 놓친 인용에 "어떤 질의였다면 닿았는가".

## 질문

fielded_v3 는 심사관 인용 83건 중 13건(16%)을 판정 대상까지 데려온다. 손실
회계(계획 문서 §7.2)는 남은 손실의 78%가 **검색 폭**(풀 미진입)이라고 가리킨다.
그러면 다음 처방은 질의 생성(동의어·상위개념 계열)인데, **만들기 전에 천장을
알아야 한다** — 동의어 확장으로 회수 가능한 인용이 5건이면 안 만드는 것이 맞고
30건이면 최우선이다.

정답 문서를 이미 알고 있으므로 역산할 수 있다. 이 스크립트가 그 역산이다.
"어떤 질의를 던졌어야 이 인용이 나왔을까" 를 정답 쪽에서 되짚는다.

## 3층

* **Layer A (서지 캐시만, Gemini 0회)** — 출원 초록의 어휘로 만든 2단어 조합
  중 인용 문헌의 제목·초록에 AND-매치하는 것이 있는가?

  - 있으면 ``LEXICAL_REACHABLE`` — 동의어 없이 **질의 선택만 고쳐도** 닿는다.
  - 없으면 ``SYNONYM_ZONE`` — 표면 어휘가 안 겹친다. 동의어·상위개념 영역.

* **Layer B (``--probe``)** — Layer A 가 찾은 조합을 실제 KIPRIS 로 친다.
  "매치한다" 와 "실제로 상위 rows 안에 들어온다" 는 다르다 — 결과 2,769건짜리
  광역 조합은 매치해도 순위에서 다시 밀린다. 결과집합 크기와 인용의 실제
  순위를 재서 Layer A 의 상한을 실측으로 깎는다.

* **Layer C (``--synonym``)** — SYNONYM_ZONE 인용에 대해, 원문과 인용이 같은
  개념을 다른 어휘로 쓰는지 Gemini 에게 묻고 대응 어휘쌍을 받는다. 동의어
  확장으로 회수 가능한 몫의 추정치이자, 프롬프트에 넣을 실제 재료다.

## 근사의 한계 — 왜 Layer B 가 필요한가

AND 매치를 부분문자열 포함으로 근사한다 (KIPRIS 색인의 형태소 처리와 다르다).
그래서 Layer A 는 낙관적 **상한**이다. 반대로 조사 제거는 어간만 남기므로
질의가 어간으로 나오고 인용 본문은 원문 그대로인 실제 조건에 가까워진다.

입력 문서는 골든셋 관례대로 출원 **초록**이다. 운영의 실제 입력(기획서·설계
문서)은 더 길므로, 여기서 나온 천장은 운영 천장의 하한이다.

## 비용

Layer A 인용 1건당 KIPRIS <=3회(번호 해석 + 서지), 전부 파일 캐시. Gemini 0회.
Layer B 인용 1건당 <= ``--probe-top`` 회. Layer C 인용 1건당 Gemini 1회.

    PYTHONIOENCODING=utf-8 KIPRIS_ACCESS_KEY=... GOLDEN_DIR=... \
      python scripts/probe_query_ceiling.py --probe
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import math
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from defusedxml.ElementTree import fromstring
from pydantic import BaseModel, ConfigDict, Field

import diagnose_golden_misses as diag
from ip_risk_agent.intelligence.patent.kipris import (
    ADVANCED_SEARCH_PATH,
    BASE_URL,
    normalize_application_number,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "labels" / "query-ceiling"  # labels/ 는 gitignore

#: KIPRIS 호출 간격. **공용 키 수칙: 1인당 최소 0.7초(초당 1회 이하).**
#: 같은 키를 여러 사람이 동시에 쓰므로 내 몫만 지켜도 합계는 그 배수가 된다.
#: 0.25초 연속 호출은 서버가 연결을 끊는 것이 실측으로 확인됐다.
_CALL_INTERVAL = 0.7
_last_call = 0.0

#: 조사 근사 목록. 긴 것부터 벗긴다 — "으로부터" 를 "부터" 로 자르면 안 된다.
_PARTICLES = tuple(
    sorted(
        (
            "으로부터", "로부터", "에서의", "에게서", "이라는", "으로써", "으로서",
            "에서", "에게", "부터", "까지", "으로", "이나", "에는", "와의", "과의",
            "들의", "라는", "이며", "이고",
            "의", "을", "를", "이", "가", "은", "는", "에", "와", "과", "로", "도",
            "만", "나", "랑", "께", "들",
        ),
        key=len,
        reverse=True,
    )
)


class SynonymJudgement(BaseModel):
    """Layer C — 원문과 인용 문헌이 같은 개념을 다른 말로 쓰는가."""

    model_config = ConfigDict(extra="forbid")

    same_domain: bool = Field(description="두 문서가 같은 기술 영역을 다루는가")
    recoverable: bool = Field(
        description="원문 어휘를 동의어나 상위개념으로 한 단계 바꾸면 인용 문헌을 "
        "AND 검색으로 데려올 수 있겠는가"
    )
    term_pairs: list[str] = Field(
        default_factory=list,
        description="대응 어휘쌍을 '원문어휘 -> 인용어휘' 형식으로. 최대 6개",
    )
    suggested_queries: list[str] = Field(
        default_factory=list,
        description="인용 문헌을 데려올 2단어 한국어 검색어. 최대 4개",
    )


def _throttle() -> None:
    global _last_call
    wait = _CALL_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


class KiprisError(RuntimeError):
    """KIPRIS 가 200 으로 돌려준 오류 응답."""


class KeysExhausted(RuntimeError):
    """쓸 수 있는 ServiceKey 가 남지 않았다."""


#: 이 응답들은 그 키가 더는 못 쓴다는 뜻이다. 기다려도 풀리지 않는다 —
#: 총량 소진은 초당 제한과 달리 2초 후 재시도도 같은 오류였다(실측).
_KEY_DEAD = (
    "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
    "DEADLINE_HAS_EXPIRED_ERROR",
    "SERVICE_ACCESS_DENIED_ERROR",
)

_OK = {"NORMAL SERVICE.", "NORMAL SERVICE", ""}


def _result_message(xml_text: str) -> str:
    found = re.search(r"<resultMsg>(.*?)</resultMsg>", xml_text)
    return found.group(1).strip() if found else ""


class KeyPool:
    """ServiceKey 를 순서대로 쓰고, 소진되면 다음으로 넘어간다.

    무료 키에는 총량 한도가 있다. 측정 한 번이 수백 호출이라 도중에 소진되는
    것이 정상 경로이고, 그때 **측정 전체가 죽으면 안 된다** — 여기까지 받아
    캐시한 것은 남기고, 무엇이 남았는지 말하고 멈추는 것이 옳다.
    """

    def __init__(self, keys: list[str]) -> None:
        self._keys = [key for key in keys if key]
        self._index = 0
        self.calls = 0
        self.retired: list[str] = []

    @property
    def alive(self) -> bool:
        return self._index < len(self._keys)

    def current(self) -> str:
        if not self.alive:
            raise KeysExhausted(f"키 {len(self._keys)}개가 모두 소진됐다")
        return self._keys[self._index]

    def retire(self, reason: str) -> None:
        dead = self._keys[self._index]
        self.retired.append(f"...{dead[-6:]}: {reason}")
        print(f"    키 ...{dead[-6:]} 소진 ({reason}) — 다음 키로")
        self._index += 1

    def get(self, path: str, params: dict) -> str:
        """호출 1회. 소진 응답이면 키를 갈고 같은 요청을 다시 보낸다."""
        while True:
            key = self.current()
            _throttle()
            response = httpx.get(
                f"{BASE_URL}/{path}",
                params={**params, "ServiceKey": key},
                timeout=30.0,
            )
            response.raise_for_status()
            self.calls += 1
            message = _result_message(response.text)
            if message.upper() in _KEY_DEAD:
                self.retire(message)
                continue
            if message.upper() not in _OK:
                # 키 문제가 아닌 오류다. 빈 결과로 읽고 캐시하면 "모른다" 가
                # "없다" 로 굳는다 (녹화-재생 규율, 계획 문서 §4).
                raise KiprisError(message)
            return response.text


def _detail_xml(number: str, pool: KeyPool, cache: Path) -> str:
    """서지 상세. 성공한 응답만 캐시한다."""
    path = cache / f"biblio-{number}.xml"
    if path.exists():
        return path.read_text(encoding="utf-8")
    text = pool.get(diag.DETAIL_PATH, {"applicationNumber": number})
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


#: 인용 번호가 올 수 있는 번호 체계. 13자리는 공개번호가 유력하고(실측),
#: 짧은 것은 등록번호다. 어느 쪽도 아닐 때를 위해 나머지도 순서대로 시도한다.
_NUMBER_FIELDS_LONG = ("openNumber", "applicationNumber", "publicationNumber", "registerNumber")
_NUMBER_FIELDS_SHORT = ("registerNumber", "publicationNumber", "openNumber", "applicationNumber")


def _resolve_citation(digits: str, pool: KeyPool, cache: Path) -> str | None:
    """공보 번호 -> 출원번호. 해석 실패는 캐시하지 않는다.

    ``diag._resolve_citation`` 과 같은 일을 하되 두 가지가 다르다 — 오류
    응답을 빈 결과로 읽지 않고, 못 찾은 결과를 파일에 굳히지 않는다. 못 찾은
    것은 다음 실행에서 다시 시도해야 하는 상태다.
    """
    path = cache / f"resolve-{digits}.json"
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8")).get("application_number")
        if cached:
            return cached
    normalized = re.sub(r"\D", "", digits)
    fields = _NUMBER_FIELDS_LONG if len(normalized) >= 12 else _NUMBER_FIELDS_SHORT
    resolved = None
    for field in fields:
        root = fromstring(
            pool.get(
                ADVANCED_SEARCH_PATH,
                {
                    field: normalized,
                    "patent": "true",
                    "utility": "true",
                    "pageNo": "1",
                    "numOfRows": "3",
                },
            )
        )
        item = next(root.iter("item"), None)
        if item is not None:
            resolved = normalize_application_number(
                item.findtext("applicationNumber") or ""
            )
            if resolved:
                break
    if resolved:
        cache.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"citation": digits, "application_number": resolved}),
            encoding="utf-8",
        )
    return resolved


def _stem(word: str) -> str:
    """조사 근사 제거. 어간이 2글자 미만으로 줄면 벗기지 않는다."""
    if not re.fullmatch(r"[가-힣]+", word):
        return word
    for particle in _PARTICLES:
        if word.endswith(particle) and len(word) - len(particle) >= 2:
            return word[: -len(particle)]
    return word


def _vocab(text: str) -> list[str]:
    """실질 어휘 어간 집합. 순서는 결정론을 위해 정렬한다."""
    return sorted({_stem(word) for word in diag._tokens(text) if len(_stem(word)) >= 2})


def _corpus_df(cache: Path) -> tuple[Counter[str], int]:
    """캐시된 서지 전량을 코퍼스로 문서빈도를 센다 — 조합 특이도의 자.

    조합을 고를 때 무엇이 흔한 말인지 알아야 한다. "시스템 방법" 조합은
    매치해도 결과가 수만 건이라 쓸모가 없고, "셔터 연동" 은 19건이다. 골든셋이
    이미 받아 둔 서지 수백 건이 그 판별의 무료 코퍼스다.
    """
    path = cache / "corpus-df.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        return Counter(payload["df"]), payload["documents"]
    df: Counter[str] = Counter()
    documents = 0
    for xml_path in sorted(diag.RAW_DIR.glob("biblio-*.xml")):
        try:
            fields = diag._biblio_fields(xml_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- 깨진 캐시 1건이 측정을 막지 않는다
            continue
        text = f"{fields['title']} {fields['abstract']}"
        if not text.strip():
            continue
        documents += 1
        df.update(set(_vocab(text)))
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"documents": documents, "df": dict(df)}, ensure_ascii=False),
        encoding="utf-8",
    )
    return df, documents


def _idf(word: str, df: Counter[str], documents: int) -> float:
    frequency = df.get(word, 0)
    return math.log(1.0 + (documents - frequency + 0.5) / (frequency + 0.5))


def _combos(
    vocab: list[str],
    cited: dict,
    df: Counter[str],
    documents: int,
    *,
    limit: int,
    words: int = 2,
) -> list[dict]:
    """원문 어휘 2단어 조합 중 인용 문헌에 AND-매치하는 것을 특이도 순으로.

    제목 매치를 초록 매치보다 앞에 둔다 — 제목 필드 검색이 정밀하다는 것은
    이미 실측이다 (제목 4위 vs 초록 9위, 계획 문서 §7.2).
    """
    title = cited["title"]
    abstract = cited["abstract"]
    found: list[dict] = []
    for group in itertools.combinations(vocab, words):
        in_title = all(word in title for word in group)
        in_abstract = all(word in abstract for word in group)
        if not (in_title or in_abstract):
            continue
        found.append(
            {
                "query": " ".join(group),
                "field": "inventionTitle" if in_title else "astrtCont",
                "in_title": in_title,
                "in_abstract": in_abstract,
                "idf": round(sum(_idf(word, df, documents) for word in group), 4),
            }
        )
    found.sort(key=lambda row: (not row["in_title"], -row["idf"], row["query"]))
    return found[:limit]


def _probe(query: str, field: str, pool: KeyPool, rows: int, cache: Path) -> dict:
    """조합 하나를 실제로 검색한다. 결과집합 크기와 반환된 출원번호 순서."""
    digest = hashlib.sha1(f"{field}|{query}|{rows}".encode()).hexdigest()[:12]
    path = cache / f"probe-{digest}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    root = fromstring(
        pool.get(
            ADVANCED_SEARCH_PATH,
            {
                field: query,
                "patent": "true",
                "utility": "true",
                "pageNo": "1",
                "numOfRows": str(rows),
            },
        )
    )
    total = (root.findtext(".//totalCount") or "").strip()
    numbers = [
        normalize_application_number(item.findtext("applicationNumber") or "")
        for item in root.iter("item")
    ]
    result = {
        "query": query,
        "field": field,
        "rows": rows,
        "total": int(total) if total.isdigit() else None,
        "numbers": [n for n in numbers if n],
    }
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def _probe_combos(
    combos: list[dict], target: str, pool: KeyPool, rows: int, cache: Path
) -> tuple[str, list[dict]]:
    """조합들을 실제로 쳐서 인용이 rows 안에 들어오는지 본다.

    * ``PROBE_HIT`` — 하나라도 인용을 rows 안에 데려온다. 질의 생성만 고치면
      실제로 회수되는 인용이다. 이것이 진짜 천장이다.
    * ``PROBE_DEEP`` — 결과집합에는 있으나(total>0) 반환 rows 안에 없다.
      질의를 고쳐도 깊이·순위가 함께 가야 한다.
    * ``PROBE_MISS`` — 실제로는 안 나온다. 부분문자열 근사의 오차.
    """
    evidence: list[dict] = []
    verdict = "PROBE_MISS"
    for combo in combos:
        result = _probe(combo["query"], combo["field"], pool, rows, cache)
        rank = (
            result["numbers"].index(target) + 1
            if target in result["numbers"]
            else None
        )
        evidence.append(
            {
                "query": combo["query"],
                "field": combo["field"],
                "total": result["total"],
                "returned": len(result["numbers"]),
                "rank": rank,
            }
        )
        if rank is not None:
            verdict = "PROBE_HIT"
        elif verdict == "PROBE_MISS" and result["total"]:
            verdict = "PROBE_DEEP"
    return verdict, evidence


_SYNONYM_PROMPT = """당신은 한국 특허 검색 전문가다.

아래 [원문]은 어떤 출원의 초록이고, [인용]은 심사관이 그 출원의 선행기술로
인용한 특허다. 우리 검색기는 원문에서 뽑은 단어들을 KIPRIS 에 AND 검색으로
넣는데, 이 인용 문헌을 데려오지 못했다. 두 문서가 표면 어휘를 공유하지 않기
때문이다.

물어볼 것은 하나다: 원문의 어휘를 동의어나 한 단계 상위개념으로 바꾸면 이
인용 문헌에 닿을 수 있었는가?

닿을 수 있다면 어떤 어휘 대응인지, 그리고 실제로 던졌어야 할 2단어 검색어가
무엇인지 알려 달라. 검색어의 두 단어는 반드시 [인용]의 제목이나 초록에
그대로 나타나는 표현이어야 한다 — AND 검색이라 하나라도 없으면 빈다.

두 문서가 애초에 다른 기술이면 recoverable 을 false 로 두라. 억지로 만들지
않는 것이 이 측정의 목적이다.

[원문]
{source}

[인용] {cited_title}
{cited_abstract}
"""


async def _judge_synonym(model, source: str, cited: dict, cache: Path) -> dict | None:
    digest = hashlib.sha1(
        f"{source[:200]}|{cited['title']}".encode()
    ).hexdigest()[:12]
    path = cache / f"synonym-{digest}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    prompt = _SYNONYM_PROMPT.format(
        source=source[:3000],
        cited_title=cited["title"],
        cited_abstract=cited["abstract"][:3000],
    )
    try:
        judgement = await model.generate(prompt, SynonymJudgement)
    except Exception as error:  # noqa: BLE001 -- 1건 실패가 측정을 막지 않는다
        print(f"    동의어 판정 실패: {type(error).__name__}")
        return None
    payload = judgement.model_dump()
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def _report(counts: Counter, rows: list[dict], args) -> None:
    skipped = {"UNRESOLVED", "NO_CITED_TEXT"}
    scored = [r for r in rows if r.get("category") not in skipped]
    total = len(scored)
    print("\n" + "=" * 62)
    print(f"판정 대상 인용 {total}건 (자기 출원·해석실패 제외)")
    print("=" * 62)
    for name in (
        "PROBE_HIT", "PROBE_DEEP", "PROBE_MISS", "LEXICAL_REACHABLE",
        "SYNONYM_RECOVERABLE", "SYNONYM_ZONE",
    ):
        if counts.get(name):
            share = counts[name] / total * 100 if total else 0.0
            print(f"  {name:22} {counts[name]:3}건  ({share:4.1f}%)")
    for name in ("UNRESOLVED", "NO_CITED_TEXT", "SELF"):
        if counts.get(name):
            print(f"  ({name} {counts[name]}건 — 채점 제외)")

    if args.probe:
        hits = [r for r in rows if r.get("category") == "PROBE_HIT"]
        print(f"\n실측 회수 가능 인용 {len(hits)}건 — 질의 생성 개선의 천장")
        for row in hits[:12]:
            best = min(
                (p for p in row.get("probe", []) if p["rank"]),
                key=lambda p: (p["rank"], p["total"] or 10**9),
                default=None,
            )
            if best:
                print(
                    f"    {row['cited_application']} <- '{best['query']}'"
                    f" [{best['field']}] 결과 {best['total']}건 중 {best['rank']}위"
                )
        if len(hits) > 12:
            print(f"    ... 외 {len(hits) - 12}건")

    if args.synonym:
        recoverable = [r for r in rows if r.get("category") == "SYNONYM_RECOVERABLE"]
        print(f"\n동의어 한 단계로 도달 가능 {len(recoverable)}건 — 어휘 대응 예시")
        for row in recoverable[:8]:
            pairs = " · ".join(row["synonym"].get("term_pairs", [])[:3])
            print(f"    {row['cited_application']}: {pairs}")


def _key_pool() -> KeyPool:
    """``KIPRIS_ACCESS_KEY`` 는 쉼표로 여러 개를 받는다.

    무료 키의 총량 한도가 측정 한 번보다 작다. 키를 여러 개 이어 붙일 수
    있어야 한 번에 끝난다.
    """
    raw = os.environ.get("KIPRIS_ACCESS_KEYS") or os.environ.get("KIPRIS_ACCESS_KEY", "")
    keys = [part.strip() for part in raw.split(",") if part.strip()]
    if not keys:
        raise SystemExit("KIPRIS_ACCESS_KEY 가 필요하다 (쉼표로 여러 개 가능)")
    return KeyPool(keys)


async def _one_citation(
    *,
    record: dict,
    citation: str,
    vocab: list[str],
    abstract: str,
    pool: KeyPool,
    df: Counter[str],
    documents: int,
    model,
    args,
) -> dict | None:
    """인용 1건을 분류한다. ``None`` 이면 채점에서 빠진다(자기 출원)."""
    number = record["application_number"]
    resolved = _resolve_citation(citation, pool, OUT_DIR)
    if not resolved:
        return {"application": number, "citation": citation, "category": "UNRESOLVED"}
    if resolved == number:
        # 자기 출원 인용은 채점에서 뺀다 (계획 문서 §4 규율).
        return None
    cited = diag._biblio_fields(_detail_xml(resolved, pool, OUT_DIR))
    row = {
        "application": number,
        "citation": citation,
        "cited_application": resolved,
        "cited_title": cited["title"],
    }
    if not (cited["title"] or cited["abstract"]):
        row["category"] = "NO_CITED_TEXT"
        return row

    combos = _combos(
        vocab, cited, df, documents, limit=args.combo_limit, words=args.words
    )
    row.update(
        source_vocab_size=len(vocab),
        combo_count=len(combos),
        combos=combos[: args.probe_top],
    )

    if combos:
        category = "LEXICAL_REACHABLE"
        if args.probe:
            category, evidence = _probe_combos(
                combos[: args.probe_top], resolved, pool, args.rows, OUT_DIR
            )
            row["probe"] = evidence
    else:
        category = "SYNONYM_ZONE"
        if args.synonym and model is not None:
            judgement = await _judge_synonym(model, abstract, cited, OUT_DIR)
            if judgement:
                row["synonym"] = judgement
                if judgement.get("recoverable"):
                    category = "SYNONYM_RECOVERABLE"
    row["category"] = category
    return row


def _key_pool() -> KeyPool:
    """``KIPRIS_ACCESS_KEY`` 는 쉼표로 여러 개를 받는다.

    무료 키의 총량 한도가 측정 한 번보다 작다. 키를 여러 개 이어 붙일 수
    있어야 한 번에 끝난다.
    """
    raw = os.environ.get("KIPRIS_ACCESS_KEYS") or os.environ.get("KIPRIS_ACCESS_KEY", "")
    keys = [part.strip() for part in raw.split(",") if part.strip()]
    if not keys:
        raise SystemExit("KIPRIS_ACCESS_KEY 가 필요하다 (쉼표로 여러 개 가능)")
    return KeyPool(keys)


async def run(args) -> int:
    pool = _key_pool()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pairs_path = diag.GOLDEN / "pairs.jsonl"
    if not pairs_path.exists():
        raise SystemExit(f"{pairs_path} 가 없다 — GOLDEN_DIR 을 확인하라")
    records = [
        json.loads(line)
        for line in pairs_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    records = [r for r in records if r.get("examiner_cited")]
    if args.limit:
        records = records[: args.limit]
    citations = sum(len(r["examiner_cited"]) for r in records)
    print(f"인용 있는 출원 {len(records)}건 · 인용 {citations}건")

    df, documents = _corpus_df(OUT_DIR)
    print(f"특이도 코퍼스: 서지 {documents}건 · 어휘 {len(df)}종\n")

    model = diag._model_client() if args.synonym else None

    rows: list[dict] = []
    counts: Counter[str] = Counter()
    seen_citations = 0
    exhausted = ""

    try:
        for record in records:
            number = record["application_number"]
            try:
                source = diag._biblio_fields(_detail_xml(number, pool, diag.RAW_DIR))
            except KeysExhausted:
                raise
            except Exception as error:  # noqa: BLE001 -- 1건 실패가 측정을 막지 않는다
                print(f"  {number}: 서지 실패 {type(error).__name__} — 건너뜀")
                continue
            abstract = source["abstract"]
            if not abstract:
                print(f"  {number}: 출원 초록 없음 — 건너뜀")
                continue
            vocab = _vocab(abstract)

            for citation in record["examiner_cited"]:
                row = await _one_citation(
                    record=record,
                    citation=citation,
                    vocab=vocab,
                    abstract=abstract,
                    pool=pool,
                    df=df,
                    documents=documents,
                    model=model,
                    args=args,
                )
                seen_citations += 1
                if row is None:
                    counts["SELF"] += 1
                    continue
                counts[row["category"]] += 1
                rows.append(row)
                head = row.get("combos") or []
                print(
                    f"  {number} -> {citation}: {row['category']}"
                    f" (조합 {row.get('combo_count', 0)}"
                    f" · 최선 '{head[0]['query'] if head else '-'}')"
                )
    except KeysExhausted as error:
        # 키가 떨어진 것은 실패가 아니라 **중단**이다. 받아 둔 것은 캐시에
        # 남아 있으므로, 새 키로 같은 명령을 다시 부르면 여기서 이어진다.
        exhausted = str(error)
        print(f"\n!! {error} — 여기까지 저장하고 멈춘다")

    payload = {
        "golden_dir": str(diag.GOLDEN),
        "corpus_documents": documents,
        "complete": not exhausted,
        "exhausted": exhausted,
        "citations_seen": seen_citations,
        "citations_total": citations,
        "kipris_calls": pool.calls,
        "retired_keys": pool.retired,
        "options": {
            "probe": args.probe,
            "synonym": args.synonym,
            "rows": args.rows,
            "probe_top": args.probe_top,
            "words": args.words,
        },
        "counts": dict(counts),
        "rows": rows,
    }
    out_name = "ceiling.json" if args.words == 2 else f"ceiling-w{args.words}.json"
    (OUT_DIR / out_name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    _report(counts, rows, args)
    print(f"\nKIPRIS 호출 {pool.calls}회 · 인용 {seen_citations}/{citations} 처리")
    if exhausted:
        print("미완 — 새 KIPRIS 키로 같은 명령을 다시 부르면 캐시에서 이어진다.")
    print(f"세부 -> {OUT_DIR / out_name}")
    return 1 if exhausted else 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true",
                        help="Layer B — 조합을 실제 KIPRIS 로 검증한다")
    parser.add_argument("--synonym", action="store_true",
                        help="Layer C — SYNONYM_ZONE 을 Gemini 로 판정한다")
    parser.add_argument("--rows", type=int, default=60,
                        help="probe 시 받을 건수 (운영 fielded_v2/v3 와 같은 60)")
    parser.add_argument("--probe-top", type=int, default=3,
                        help="인용 1건당 실제로 칠 조합 수")
    parser.add_argument("--combo-limit", type=int, default=40,
                        help="특이도 상위 몇 개 조합까지 보관할지")
    parser.add_argument("--limit", type=int, default=0,
                        help="출원 수 제한 (시험용)")
    parser.add_argument("--words", type=int, default=2,
                        help="질의 단어 수. 3 이면 3단어 AND 질의를 역산한다")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
