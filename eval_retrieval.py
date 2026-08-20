"""
Retrieval evaluation for infrastructure/mock_retrieval.py.

Computes P@k, R@k, NDCG@k, and MRR against a hand-labelled relevance set
derived from the chunk corpus in data/literature_chunks.json.

Run:
    python eval_retrieval.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from infrastructure.mock_retrieval import retrieve

# ---------------------------------------------------------------------------
# Ground truth
# Grade 2 = primary source for the query, grade 1 = supporting, omit = 0.
# ---------------------------------------------------------------------------

EXTERNAL_QRELS = [
    {
        "query": "atomically dispersed Pd CeO2 CO oxidation low temperature activity",
        "relevant": {"LIT-001": 2, "LIT-002": 1},
    },
    {
        "query": "Pd sintering redispersion hydrothermal treatment CeO2 bimetallic",
        "relevant": {"LIT-002": 2, "LIT-001": 1},
    },
    {
        "query": "Ni La2O3 dry reforming methane promoter alkali conversion",
        "relevant": {"LIT-003": 2, "LIT-004": 1},
    },
    {
        "query": "coke resistance stability coking La2O3 dry reforming Boudouard",
        "relevant": {"LIT-004": 2, "LIT-003": 1, "LIT-006": 1},
    },
    {
        "query": "single atom Rh Al2O3 exsolution dry reforming optimal loading",
        "relevant": {"LIT-005": 2, "LIT-006": 1},
    },
    {
        "query": "methane pretreatment carbon deposition Rh DRM coking poisoning",
        "relevant": {"LIT-006": 2, "LIT-005": 1},
    },
    {
        "query": "Cu CeO2 ZrO2 water gas shift TOF activation energy support composition",
        "relevant": {"LIT-007": 2, "LIT-008": 1},
    },
    {
        "query": "H2-TPR hydrogen consumption CeO2 ZrO2 reducibility Cu catalyst",
        "relevant": {"LIT-008": 2, "LIT-007": 1},
    },
    {
        "query": "Ru TiO2 CO2 hydrogenation rutile anatase selectivity methane air annealing",
        "relevant": {"LIT-009": 2, "LIT-010": 1},
    },
    {
        "query": "activation energy Ru oxidation state XPS CO2 methanation metal support",
        "relevant": {"LIT-010": 2, "LIT-009": 1},
    },
]

INTERNAL_QRELS = [
    {
        "query": "Pd CeO2 preparation ball milling XPS oxidation state T50 light-off",
        "relevant": {"INT-001": 2, "INT-003": 1},
    },
    {
        "query": "CuO La2O3 WGS Cu dispersion crystallite sintering stability",
        "relevant": {"INT-002": 2, "INT-004": 1},
    },
    {
        "query": "Fe CeO2 support BET surface area particle size flame spray",
        "relevant": {"INT-003": 2, "INT-001": 1},
    },
    {
        "query": "stability protocol CO oxidation WGS GHSV fixed bed test conditions",
        "relevant": {"INT-004": 2, "INT-002": 1},
    },
]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _dcg(grades: list[float], k: int) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(grades[:k]))


def _ndcg(retrieved: list[str], relevant: dict[str, int], k: int) -> float:
    ret_grades = [relevant.get(cid, 0) for cid in retrieved]
    ideal_grades = sorted(relevant.values(), reverse=True)
    idcg = _dcg(ideal_grades, k)
    return _dcg(ret_grades, k) / idcg if idcg > 0 else 0.0


def _evaluate_one(qrel: dict, scope: str, ks: tuple[int, ...]) -> dict:
    relevant = qrel["relevant"]
    hits = retrieve(qrel["query"], scope=scope, limit=max(ks))
    hit_ids = [h["chunk_id"] for h in hits]

    rr = next(
        (1.0 / rank for rank, cid in enumerate(hit_ids, 1) if relevant.get(cid, 0) >= 1),
        0.0,
    )

    row: dict = {"query": qrel["query"], "rr": rr, "retrieved": hit_ids}
    for k in ks:
        hits_at_k = [cid for cid in hit_ids[:k] if relevant.get(cid, 0) >= 1]
        row[f"P@{k}"] = len(hits_at_k) / k
        row[f"R@{k}"] = len(hits_at_k) / len(relevant)
        row[f"NDCG@{k}"] = _ndcg(hit_ids, relevant, k)
    return row


def evaluate(qrels: list[dict], scope: str, ks: tuple[int, ...] = (1, 3, 5)) -> dict:
    rows = [_evaluate_one(q, scope, ks) for q in qrels]
    n = len(rows)
    agg: dict = {"MRR": sum(r["rr"] for r in rows) / n}
    for k in ks:
        agg[f"P@{k}"]    = sum(r[f"P@{k}"]    for r in rows) / n
        agg[f"R@{k}"]    = sum(r[f"R@{k}"]    for r in rows) / n
        agg[f"NDCG@{k}"] = sum(r[f"NDCG@{k}"] for r in rows) / n
    return {"rows": rows, "agg": agg}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _w(s: str, n: int) -> str:
    return s[:n].ljust(n)


def print_results(label: str, results: dict, ks: tuple[int, ...]) -> None:
    W = 52
    col = 7

    header = f"  {'Query':<{W}}  RR   " + "  ".join(f"N@{k}".rjust(col) for k in ks)
    sep    = f"  {'-'*W}  ----   " + "  ".join("-"*col for _ in ks)

    print(f"\n{'='*80}")
    print(f"  {label}")
    print(f"{'='*80}")
    print(header)
    print(sep)

    for r in results["rows"]:
        ndcg_str = "  ".join(f"{r[f'NDCG@{k}']:>{col}.3f}" for k in ks)
        print(f"  {_w(r['query'], W)}  {r['rr']:.2f}   {ndcg_str}")

    agg = results["agg"]
    ndcg_str = "  ".join(f"{agg[f'NDCG@{k}']:>{col}.3f}" for k in ks)
    print(sep)
    print(f"  {'MEAN':<{W}}  {agg['MRR']:.2f}   {ndcg_str}")

    print(f"\n  Summary  " + "".join(f"  {'@'+str(k):>8}" for k in ks))
    print(f"  -------" + "".join("  --------" for _ in ks))
    for metric in ("P", "R", "NDCG"):
        vals = "".join(f"  {agg[f'{metric}@{k}']:8.3f}" for k in ks)
        print(f"  {metric+'@k':<7}{vals}")
    print(f"  {'MRR':<7}  {agg['MRR']:8.3f}")


def print_per_query_hits(label: str, results: dict, qrels: list[dict]) -> None:
    print(f"\n--- Top-3 retrieved ({label}) ---")
    for r, q in zip(results["rows"], qrels):
        relevant = q["relevant"]
        tag = lambda cid: "+" if relevant.get(cid, 0) >= 1 else " "
        hits_str = "  ".join(f"{tag(cid)}{cid}" for cid in r["retrieved"][:3])
        print(f"  RR={r['rr']:.2f}  {hits_str}   | {r['query'][:55]}")


if __name__ == "__main__":
    ks: tuple[int, ...] = (1, 3, 5)

    ext  = evaluate(EXTERNAL_QRELS, scope="external", ks=ks)
    int_ = evaluate(INTERNAL_QRELS, scope="internal", ks=ks)

    print_results("EXTERNAL LITERATURE  (10 chunks, 10 queries)", ext, ks)
    print_results("INTERNAL DOCUMENTS   (4 chunks,  4 queries)",  int_, ks)

    print_per_query_hits("external", ext, EXTERNAL_QRELS)
    print_per_query_hits("internal", int_, INTERNAL_QRELS)
