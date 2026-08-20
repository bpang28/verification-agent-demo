"""
Vector retrieval backed by a local LanceDB table.

Drop-in replacement for mock_retrieval.py — same retrieve() signature.
Requires build_index.py to have been run first.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_DB_PATH    = Path(__file__).parent.parent / "data" / "lancedb"
_MODEL_NAME = "all-MiniLM-L6-v2"
_DEFAULT_LIMIT = 10

# Lazy singletons — loaded on first retrieve() call.
_model = None
_table = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _get_table():
    global _table
    if _table is None:
        import lancedb
        db = lancedb.connect(str(_DB_PATH))
        _table = db.open_table("chunks")
    return _table


def retrieve(
    query: str,
    *,
    scope: str = "all",
    limit: int = _DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """
    Embed query and return top-k semantically similar chunks.

    scope: 'internal', 'external', or 'all'
    """
    model = _get_model()
    table = _get_table()

    q_vec = model.encode(query, normalize_embeddings=True).tolist()

    # Over-fetch so scope filtering still returns enough results.
    fetch = limit * 4 if scope != "all" else limit
    rows = table.search(q_vec).limit(fetch).to_list()

    if scope == "internal":
        rows = [r for r in rows if r["source_type"] == "internal_documents"]
    elif scope == "external":
        rows = [r for r in rows if r["source_type"] == "external_literature"]

    rows = rows[:limit]

    parcels = []
    for rank, row in enumerate(rows, start=1):
        # _distance is L2; we stored normalised vectors so cosine sim = 1 - dist/2
        dist = row.get("_distance", 0.0)
        score = round(max(0.0, 1.0 - dist / 2.0), 4)
        parcels.append({
            "evidence_id":      f"EV-D-{rank:03d}",
            "chunk_id":         row["chunk_id"],
            "rank":             rank,
            "retrieval_score":  score,
            "source_type":      row["source_type"],
            "title":            row["title"],
            "page":             row["page"] or None,
            "text":             row["text"],
            "citation":         row["title"],
        })

    return parcels
