"""임계값 교정을 위한 라벨 수집 도구.

## 왜 필요한가

지금 검토 우선도는 이산 규칙이 정한다. 임계값 두 개로 전환하려면 **사람이 매긴
정답**이 있어야 한다. 라벨 없이 고른 임계값은 숫자만 있고 근거가 없다
(``docs/PATENT_PRIORITY_DESIGN_NOTE.md`` §5).

## 점수를 가린다

라벨을 매길 때 파생 점수나 시스템 등급을 보여 주면, 사람이 그것을 확인하는 방향으로
매기게 된다. 그러면 그 라벨로 고른 임계값은 **자기 자신을 검증하는 것**이 되어
아무것도 말해 주지 않는다. 그래서 화면에는 문서 조각과 특허 근거만 보여 준다.

## 쓰는 법

    python scripts/label_patent_candidates.py collect --corpus   # 합성 코퍼스
    python scripts/label_patent_candidates.py collect            # 실제 KIPRIS
    python scripts/label_patent_candidates.py label
    python scripts/label_patent_candidates.py report

합성 코퍼스로 매긴 라벨은 **임계값 근거로 쓰지 않는다** — 본문이 합성이라 사람의
판단도 합성 텍스트에 대한 것이 된다. 도구를 검증하는 용도다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from iprisk_contracts import AnalysisArtifact
from iprisk_contracts.analysis_artifact import AnalysisSecurityContext
from iprisk_contracts.common import AnalysisType, ArtifactKind, ContentScope

from ip_risk_agent.connectors.common.segmentation import split_document
from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient
from ip_risk_agent.intelligence.patent.analyzer import PatentAnalyzer

ROOT = Path(__file__).resolve().parents[1]
GRADES = {"1": "HIGH", "2": "MEDIUM", "3": "LOW"}


def _artifact(path: Path) -> AnalysisArtifact:
    body = path.read_text(encoding="utf-8")
    return AnalysisArtifact(
        contract_version="1",
        analysis_job_id="label:" + path.stem,
        risk_workspace_id="label-vws",
        mount_id="label-mount",
        artifact_id="label-artifact:" + path.stem,
        logical_path="/label/" + path.name,
        revision="rev-1",
        artifact_kind=ArtifactKind.DOCUMENT_TEXT,
        mime_type="text/markdown",
        requested_analyzers=[AnalysisType.PATENT],
        content_scope=ContentScope.FULL_TEXT,
        text_segments=split_document(body),
        security_context=AnalysisSecurityContext(
            approved=True,
            policy_version="label",
            redaction_count=0,
            original_checksum="sha256:label",
            analysis_input_checksum="sha256:label:" + path.stem,
        ),
        created_at=datetime.now(timezone.utc),
    )


def _model() -> GoogleGenAIClient:
    return GoogleGenAIClient(
        os.environ["GEMINI_MODEL_ID"],
        vertex_config={
            "vertexai": True,
            "project": os.environ["GCP_PROJECT_ID"],
            "location": os.environ.get("VERTEX_LOCATION", "global"),
        },
    )


async def _collect(documents, corpus_path):
    if corpus_path is not None:
        from ip_risk_agent.intelligence.patent.offline_corpus import (
            load_corpus,
            offline_kipris_client,
        )

        corpus = load_corpus(corpus_path, acknowledge_synthetic=True)
        provider = offline_kipris_client(corpus, acknowledge_synthetic=True)
        synthetic = True
    else:
        from ip_risk_agent.intelligence.patent.kipris import KiprisClient

        provider = KiprisClient(os.environ["KIPRIS_KEY"])
        synthetic = False

    analyzer = PatentAnalyzer(provider, _model(), candidate_cap=6)
    rows = []
    for path in documents:
        artifact = _artifact(path)
        result = await analyzer.analyze(artifact)
        segments = {item.segment_id: item.text for item in artifact.text_segments}
        evidence = {item.evidence_id: item for item in result.evidence}
        for candidate in result.candidates:
            rows.append(
                {
                    "document": path.name,
                    "application_number": candidate.normalized_application_number,
                    "patent_title": candidate.title,
                    "matched_elements": list(candidate.matched_elements),
                    "document_excerpts": [
                        segments.get(eid[len("src:") :], "")
                        for eid in candidate.evidence_ids
                        if eid.startswith("src:")
                    ],
                    "patent_excerpts": [
                        evidence[eid].excerpt
                        for eid in candidate.evidence_ids
                        if eid in evidence and not eid.startswith("src:")
                    ],
                    # 라벨을 매길 때 보여 주지 않는다. 분포를 볼 때만 쓴다.
                    "_system_priority": candidate.suggested_review_priority.value,
                    "_evidence_strength": candidate.provider_metadata_safe.get(
                        "evidence_strength"
                    ),
                    "synthetic": synthetic,
                    "label": None,
                }
            )
    close = getattr(provider, "aclose", None)
    if close is not None:
        await close()
    return rows


def _write(pool: Path, rows: list[dict]) -> None:
    pool.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    pool.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read(pool: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in pool.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _show(row: dict, index: int, total: int) -> None:
    print()
    print("=" * 72)
    print("[" + str(index) + "/" + str(total) + "] " + row["document"])
    print("특허: " + row["patent_title"] + "  (" + row["application_number"] + ")")
    if row["synthetic"]:
        print("※ 합성 코퍼스입니다. 이 라벨은 임계값 근거로 쓰지 않습니다.")
    print()
    print("-- 문서 --")
    for text in row["document_excerpts"][:2]:
        print("  " + text[:400])
    print()
    print("-- 특허 근거 --")
    for text in row["patent_excerpts"][:2]:
        print("  " + text[:400])
    print()
    print("-- 겹친다고 본 구성 --")
    for element in row["matched_elements"][:5]:
        print("  - " + element)


def _label(pool: Path) -> int:
    rows = _read(pool)
    pending = [row for row in rows if row.get("label") is None]
    if not pending:
        print("매길 것이 남아 있지 않습니다.")
        return 0
    print(str(len(pending)) + " 건이 남았습니다. 1=상 2=중 3=하 s=건너뜀 q=저장하고 끝")
    for position, row in enumerate(pending, start=1):
        _show(row, position, len(pending))
        while True:
            choice = input("\n등급 [1/2/3/s/q] > ").strip().lower()
            if choice == "q":
                _write(pool, rows)
                print("저장했습니다.")
                return 0
            if choice == "s":
                break
            if choice in GRADES:
                row["label"] = GRADES[choice]
                break
            print("1, 2, 3, s, q 중에서 고르세요.")
    _write(pool, rows)
    print("전부 매겼습니다.")
    return 0


def _report(pool: Path) -> int:
    rows = _read(pool)
    labelled = [row for row in rows if row.get("label")]
    print("후보 " + str(len(rows)) + " 건 - 라벨 " + str(len(labelled)) + " 건")
    if not labelled:
        return 0
    if any(row["synthetic"] for row in labelled):
        print("※ 합성 코퍼스가 섞여 있습니다. 임계값 근거로 쓰지 마세요.")
    agreement: Counter = Counter()
    for row in labelled:
        agreement[(row["label"], row["_system_priority"])] += 1
    print()
    print("사람 라벨 x 시스템 등급")
    for (human, system), count in sorted(agreement.items()):
        mark = "  " if human == system else " <>"
        print("  " + human.ljust(6) + " x " + system.ljust(6) + mark + " " + str(count))
    scored = [row for row in labelled if row.get("_evidence_strength") is not None]
    if not scored:
        return 0
    print()
    print("라벨별 근거 강도 (임계값을 고를 분포)")
    for grade in ("HIGH", "MEDIUM", "LOW"):
        values = sorted(
            float(row["_evidence_strength"]) for row in scored if row["label"] == grade
        )
        if values:
            print(
                "  "
                + grade.ljust(6)
                + " n="
                + str(len(values)).ljust(3)
                + " min="
                + format(values[0], ".3f")
                + " 중앙="
                + format(values[len(values) // 2], ".3f")
                + " max="
                + format(values[-1], ".3f")
            )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="후보를 모은다")
    collect.add_argument("--documents", default=str(ROOT / "samples" / "patent"))
    collect.add_argument("--out", default=str(ROOT / "labels" / "pool.jsonl"))
    collect.add_argument(
        "--corpus",
        nargs="?",
        const=str(ROOT / "tests" / "fixtures" / "kipris" / "corpus.json"),
        help="합성 코퍼스로 모은다. 도구 검증용이며 임계값 근거가 아니다",
    )

    for name, help_text in (("label", "사람이 매긴다"), ("report", "분포를 본다")):
        item = sub.add_parser(name, help=help_text)
        item.add_argument("--pool", default=str(ROOT / "labels" / "pool.jsonl"))

    args = parser.parse_args()
    if args.command == "collect":
        target = Path(args.documents)
        documents = sorted(target.glob("*.md")) if target.is_dir() else [target]
        rows = asyncio.run(
            _collect(documents, Path(args.corpus) if args.corpus else None)
        )
        out = Path(args.out)
        _write(out, rows)
        print("후보 " + str(len(rows)) + " 건을 " + str(out) + " 에 모았습니다.")
        return 0

    pool = Path(args.pool)
    if not pool.exists():
        print("pool 이 없습니다: " + str(pool), file=sys.stderr)
        return 2
    return _label(pool) if args.command == "label" else _report(pool)


if __name__ == "__main__":
    raise SystemExit(main())
