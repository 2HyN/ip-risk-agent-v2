"""이미 만들어진 Risk 에 설명과 권고를 붙인다.

설명은 분석 시점에 만들어지므로, 그 기능이 생기기 전에 만들어진 Risk 는 설명이
비어 있다. 다시 분석하면 붙지만 특허는 그때마다 KIPRIS 호출 한도를 쓴다.

이 도구는 **저장된 근거만** 본다. provider 는 Gemini 하나뿐이라 KIPRIS 한도와
무관하고, 라이선스든 특허든 종류를 가리지 않는다.

    python scripts/backfill_risk_explanations.py --workspace-id workspace-XXXX
    python scripts/backfill_risk_explanations.py --workspace-id workspace-XXXX --confirm

기본은 dry-run 이다. 설명이 이미 있는 Risk 는 건너뛴다 — 같은 근거로 다시 부르면
돈만 쓰고 문장만 흔들린다.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import _repo_path  # noqa: F401  -- 자기 저장소의 코드를 먼저 경로에 올린다

from ip_risk_agent.application.risk_explanation import RiskExplanationService
from ip_risk_agent.gcp_contract import FIRESTORE_DATABASE, PROJECT_ID
from ip_risk_agent.intelligence.explain import GeminiRiskExplainer
from ip_risk_agent.intelligence.gemini.client import GoogleGenAIClient
from ip_risk_agent.persistence.core_firestore import FirestoreControlUnitOfWorkFactory


def _client(database: str):
    from google.cloud import firestore  # noqa: PLC0415 - 지연 import

    return firestore.AsyncClient(project=PROJECT_ID, database=database)


async def _risk_ids(factory, workspace_id: str) -> list[str]:
    async with factory() as uow:
        risks = await uow.risks.list_for_workspace(workspace_id)
    return [risk.id for risk in risks if not risk.explanation_safe]


async def backfill(workspace_id: str, *, database: str, confirm: bool) -> dict[str, int]:
    client = _client(database)
    try:
        factory = FirestoreControlUnitOfWorkFactory.from_client(client)
        pending = await _risk_ids(factory, workspace_id)
        if not confirm:
            return {"would_explain": len(pending)}

        model = GoogleGenAIClient(
            os.environ["GEMINI_MODEL_ID"],
            vertex_config={
                "vertexai": True,
                "project": os.environ.get("GCP_PROJECT_ID", PROJECT_ID),
                "location": os.environ.get("VERTEX_LOCATION", "global"),
            },
        )
        service = RiskExplanationService(
            unit_of_work_factory=factory,
            explainer=GeminiRiskExplainer(model),
        )
        outcome = await service.explain_risks(tuple(pending))
        return {
            "explained": len(outcome.explained),
            "skipped": len(outcome.skipped),
            "failed": len(outcome.failed),
        }
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--database", default=FIRESTORE_DATABASE)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="실제로 모델을 부르고 저장한다. 없으면 대상 수만 센다.",
    )
    args = parser.parse_args()

    if args.database != FIRESTORE_DATABASE:
        print(f"STOP: refusing to touch database {args.database!r}", file=sys.stderr)
        return 2

    counts = asyncio.run(
        backfill(args.workspace_id, database=args.database, confirm=args.confirm)
    )
    for name, count in sorted(counts.items()):
        print(f"  {name:<16} {count}")
    if not args.confirm:
        print("re-run with --confirm to apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
