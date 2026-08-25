"""재료 데이터(patent_goldsets/negativePairs)의 가공 — 요청서 v2 의 "이쪽 소관".

입력: 팀원이 수집한 재료 3종 (출원별 청구항 / 인용 전문 / 출원↔인용 매핑,
도메인 태그·인용 출원번호 선해석 포함).

  --fetch   원 출원 206건의 서지(IPC·초록·출원일)와, (51) 줄이 없는 인용의
            서지를 KIPRIS 로 수집·캐시 (labels/goldset2/). 공용 키 규칙
            (호출 0.7초 간격) 준수.
  --build   파생 3종 생성:
            1. 안전 음성 쌍 — IPC 서브클래스 서로소 교차 (시드 고정,
               출원당 2쌍), labels/goldset2/safe_negative_pairs.csv
            2. 양성 쌍 — 출원 청구항 ↔ 확정 인용 전문 (대조 재현율 확장),
               labels/goldset2/positive_pairs.csv
            3. 검색 평가 명세 — pairs2.jsonl (출원·초록 유무·인용 출원번호·
               컷오프·도메인), Layer R 확장의 입력

    PYTHONIOENCODING=utf-8 KIPRIS_ACCESS_KEY=... GOLDEN2_SRC=... \
      .venv/Scripts/python scripts/build_goldset2.py --fetch
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import _repo_path  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(os.environ.get("GOLDEN2_SRC") or (ROOT.parent / "patent_goldsets" / "negativePairs"))
OUT = ROOT / "labels" / "goldset2"
CALL_SLEEP = 0.75  # 공용 키 — 1인당 0.7초/호출 이상

_IPC_SUBCLASS = re.compile(r"([A-H]\s?\d{2}\s?[A-Z])")
_IPC_51 = re.compile(r"\(51\)[^(]{0,200}")

csv.field_size_limit(10**8)


def _rows(name: str) -> list[dict]:
    with (SRC / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _subclasses(text: str) -> list[str]:
    return sorted({m.replace(" ", "") for m in _IPC_SUBCLASS.findall(text or "")})


def _fetch_biblio(number: str, key: str) -> str:
    import httpx
    from ip_risk_agent.intelligence.patent.kipris import BASE_URL, DETAIL_PATH

    path = OUT / "raw" / f"biblio-{number}.xml"
    if path.exists():
        return path.read_text(encoding="utf-8")
    response = httpx.get(
        f"{BASE_URL}/{DETAIL_PATH}",
        params={"applicationNumber": number, "ServiceKey": key},
        timeout=25.0,
    )
    response.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response.text, encoding="utf-8")
    time.sleep(CALL_SLEEP)
    return response.text


def _biblio_fields(xml_text: str) -> dict:
    from defusedxml.ElementTree import fromstring

    root = fromstring(xml_text)
    summary = next(root.iter("biblioSummaryInfo"), None)
    title = (summary.findtext("inventionTitle") or "").strip() if summary is not None else ""
    abstract = next((n.text for n in root.iter("astrtCont") if n.text), "") or ""
    date = re.sub(r"\D", "", next((n.text for n in root.iter("applicationDate") if n.text), "") or "")[:8]
    ipcs = sorted({
        s for n in root.iter("ipcNumber") for s in _subclasses(n.text or "")
    })
    return {"title": title, "abstract": abstract.strip(), "date": date, "ipcs": ipcs}


def fetch() -> int:
    key = os.environ.get("KIPRIS_ACCESS_KEY", "").strip()
    if not key:
        raise SystemExit("KIPRIS_ACCESS_KEY 필요")
    claims = _rows("gold_target_claims_all.csv")
    cited = _rows("gold_cited_fulltext_all.csv")
    manifest = {}
    for index, row in enumerate(claims):
        number = row["applicationNumber"].strip()
        try:
            manifest[number] = _biblio_fields(_fetch_biblio(number, key))
        except Exception as exc:  # noqa: BLE001
            print(f"  {number}: 서지 실패 {type(exc).__name__}")
        if index % 25 == 0:
            print(f"  원 출원 서지 {index + 1}/{len(claims)}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "source_biblio.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    # 인용 IPC — (51) 줄 우선, 없으면 서지 조회 (출원번호 선해석분만)
    cited_ipcs = {}
    fetched = 0
    for row in cited:
        ident = row["식별자"]
        appno = (row.get("applicationNumber") or "").strip()
        block = _IPC_51.search(row["원문텍스트"] or "")
        subclasses = _subclasses(block.group(0)) if block else []
        if not subclasses and appno:
            try:
                subclasses = _biblio_fields(_fetch_biblio(appno, key))["ipcs"]
                fetched += 1
            except Exception:  # noqa: BLE001
                subclasses = []
        cited_ipcs[ident] = {"applicationNumber": appno, "ipcs": subclasses}
    (OUT / "cited_ipcs.json").write_text(
        json.dumps(cited_ipcs, ensure_ascii=False), encoding="utf-8"
    )
    no_ipc = sum(1 for v in cited_ipcs.values() if not v["ipcs"])
    print(f"완료 — 원 출원 {len(manifest)}건 · 인용 IPC {len(cited_ipcs)}건"
          f" (서지 보충 {fetched}, IPC 미상 {no_ipc})")
    return 0


def build() -> int:
    random.seed(42)
    claims_rows = {r["applicationNumber"].strip(): r["claims"] for r in _rows("gold_target_claims_all.csv")}
    cited_rows = {r["식별자"]: r for r in _rows("gold_cited_fulltext_all.csv")}
    reject_rows = _rows("gold_reject_decisions_all.csv")
    source = json.loads((OUT / "source_biblio.json").read_text(encoding="utf-8"))
    cited_ipcs = json.loads((OUT / "cited_ipcs.json").read_text(encoding="utf-8"))

    true_map: dict[str, set[str]] = {}
    domain: dict[str, str] = {}
    for row in reject_rows:
        appno = row["applicationNumber"].strip()
        domain[appno] = (row.get("domain") or "").strip()
        try:
            lst = ast.literal_eval(row["kr_citations"])
        except Exception:  # noqa: BLE001
            continue
        true_map.setdefault(appno, set()).update(
            c["식별자"] for c in lst if isinstance(c, dict) and "식별자" in c
        )

    # ── 1. 양성 쌍 (대조 재현율 확장)
    positives = []
    for appno, idents in sorted(true_map.items()):
        claims = claims_rows.get(appno)
        if not claims:
            continue
        for ident in sorted(idents):
            crow = cited_rows.get(ident)
            if not crow:
                continue
            positives.append({
                "applicationNumber": appno,
                "sendNumber": "",
                "target_claims": claims,
                "cited_식별자": ident,
                "cited_fulltext": crow["원문텍스트"],
                "citedApplicationNumber": (crow.get("applicationNumber") or "").strip(),
                "pair_label": "1",
                "negative_basis": "",
                "domain": domain.get(appno, ""),
            })

    # ── 2. 안전 음성 쌍 — IPC 서브클래스 서로소 교차, 출원당 2쌍
    negatives = []
    all_idents = sorted(cited_rows)
    for appno in sorted(true_map):
        claims = claims_rows.get(appno)
        src_ipcs = set(source.get(appno, {}).get("ipcs") or [])
        if not claims or not src_ipcs:
            continue
        pool = []
        for ident in all_idents:
            if ident in true_map[appno]:
                continue
            info = cited_ipcs.get(ident) or {}
            c_ipcs = set(info.get("ipcs") or [])
            if not c_ipcs or (src_ipcs & c_ipcs):
                continue  # IPC 미상·겹침은 안전 음성이 아니다
            pool.append(ident)
        for ident in random.sample(pool, min(2, len(pool))):
            crow = cited_rows[ident]
            negatives.append({
                "applicationNumber": appno,
                "sendNumber": "",
                "target_claims": claims,
                "cited_식별자": ident,
                "cited_fulltext": crow["원문텍스트"],
                "citedApplicationNumber": (crow.get("applicationNumber") or "").strip(),
                "pair_label": "0",
                "negative_basis": "ipc-disjoint("
                + ",".join(sorted(src_ipcs)[:3]) + " vs "
                + ",".join(sorted(set(cited_ipcs[ident]["ipcs"]))[:3]) + ")",
                "domain": domain.get(appno, ""),
            })

    fields = ["applicationNumber", "sendNumber", "target_claims", "cited_식별자",
              "cited_fulltext", "citedApplicationNumber", "pair_label",
              "negative_basis", "domain"]
    for name, rows in (("positive_pairs.csv", positives),
                       ("safe_negative_pairs.csv", negatives)):
        with (OUT / name).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"{name}: {len(rows)}쌍")

    # ── 3. 검색 평가 명세 (Layer R 확장 입력)
    with (OUT / "pairs2.jsonl").open("w", encoding="utf-8") as handle:
        for appno in sorted(true_map):
            info = source.get(appno) or {}
            cited_apps = sorted({
                (cited_ipcs.get(i) or {}).get("applicationNumber", "")
                for i in true_map[appno]
            } - {""})
            handle.write(json.dumps({
                "application_number": appno,
                "domain": domain.get(appno, ""),
                "has_abstract": bool(info.get("abstract")),
                "cutoff": info.get("date", ""),
                "cited_applications": cited_apps,
            }, ensure_ascii=False) + "\n")
    print(f"pairs2.jsonl: 출원 {len(true_map)}건")
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.fetch:
        sys.exit(fetch())
    if args.build:
        sys.exit(build())
    parser.error("--fetch / --build")


if __name__ == "__main__":
    main()
