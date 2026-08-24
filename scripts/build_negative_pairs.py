import ast, random
from pathlib import Path
import pandas as pd

random.seed(42)

BASE = Path("samples/patent")
claims_df = pd.read_csv(BASE / "gold_target_claims_all.csv", encoding="utf-8-sig")
cited_df = pd.read_csv(BASE / "gold_cited_fulltext_all.csv", encoding="utf-8-sig")
reject_df = pd.read_csv(BASE / "gold_reject_decisions_all.csv", encoding="utf-8-sig")

claims_map = dict(zip(claims_df["applicationNumber"], claims_df["claims"]))
fulltext_map = {
    k: v for k, v in zip(cited_df["식별자"], cited_df["원문텍스트"])
    if isinstance(v, str) and v.strip()
}
all_ids = list(fulltext_map.keys())

def parse_kr_citations(raw):
    try:
        lst = ast.literal_eval(raw)
    except Exception:
        return set()
    return {c["식별자"] for c in lst if "식별자" in c}

reject_df["kr_citation_ids"] = reject_df["kr_citations"].apply(parse_kr_citations)
true_citations = dict(zip(reject_df["applicationNumber"], reject_df["kr_citation_ids"]))

N_PER_APP = 2
rows = []
for app_no, claims in claims_map.items():
    cited_ids = true_citations.get(app_no, set())
    candidates = [i for i in all_ids if i not in cited_ids]
    if not candidates:
        continue
    for cid in random.sample(candidates, min(N_PER_APP, len(candidates))):
        rows.append({
            "applicationNumber": app_no,
            "target_claims": claims,
            "cited_식별자": cid,
            "cited_fulltext": fulltext_map[cid],
            "label": "negative",
        })

pd.DataFrame(rows).to_csv(BASE / "negative_pairs.csv", index=False, encoding="utf-8-sig")
print(f"negative pairs: {len(rows)}")
