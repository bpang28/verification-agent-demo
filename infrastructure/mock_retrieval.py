"""
In-memory mock of the hybrid retrieval pipeline (dense + BM25 + reranking).

Replaces LanceDB / BM25 / cross-encoder for self-contained execution.
Retrieval uses keyword overlap scoring as a reproducible stand-in.
In production, swap for the real embedding + reranking stack.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).parent.parent / "data" / "literature_chunks.json"
_DEFAULT_LIMIT = 10


def _load_chunks() -> list[dict]:
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))["chunks"]


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))


def _bm25_score(query_tokens: set[str], chunk_text: str) -> float:
    chunk_tokens = _tokenize(chunk_text)
    if not chunk_tokens:
        return 0.0
    overlap = query_tokens & chunk_tokens
    return len(overlap) / (len(chunk_tokens) ** 0.5)


def retrieve(
    query: str,
    *,
    scope: str = "all",
    limit: int = _DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """
    Score literature chunks against the query by keyword overlap and return
    the top-k results as evidence parcels for the synthesis pipeline.

    scope: 'internal', 'external', or 'all'
    """
    chunks = _load_chunks()

    if scope == "internal":
        chunks = [c for c in chunks if c.get("source_type") == "internal_documents"]
    elif scope == "external":
        chunks = [c for c in chunks if c.get("source_type") == "external_literature"]

    query_tokens = _tokenize(query)
    scored = [
        (chunk, _bm25_score(query_tokens, chunk["title"] + " " + chunk["text"]))
        for chunk in chunks
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:limit]

    evidence_parcels = []
    for rank, (chunk, score) in enumerate(top, start=1):
        parcel_id = f"EV-D-{int(chunk['chunk_id'].split('-')[1]):03d}"
        evidence_parcels.append({
            "evidence_id": parcel_id,
            "chunk_id": chunk["chunk_id"],
            "rank": rank,
            "retrieval_score": round(score, 4),
            "source_type": chunk["source_type"],
            "title": chunk["title"],
            "page": chunk.get("page"),
            "text": chunk["text"],
            "citation": f"{chunk['title']}, p. {chunk.get('page', '?')}",
        })

    return evidence_parcels
