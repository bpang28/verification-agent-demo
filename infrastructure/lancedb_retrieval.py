"""
Vector retrieval backed by a numpy index built by build_index.py.

Drop-in replacement for mock_retrieval.py — same retrieve() signature.
Uses fastembed for query embedding and cosine similarity over the full index.
In production this is a LanceDB Cloud Run service; the interface is identical.

Requires build_index.py to have been run first.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

_INDEX_PATH = Path(__file__).parent.parent / "data" / "embeddings.npz"
_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_DEFAULT_LIMIT = 10

_model = None
_index: dict | None = None


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=_MODEL_NAME)
    return _model


def _get_index() -> dict:
    global _index
    if _index is None:
        if not _INDEX_PATH.exists():
            raise FileNotFoundError(
                f"Index not found at {_INDEX_PATH}. "
                "Run: python infrastructure/build_index.py"
            )
        data = np.load(_INDEX_PATH, allow_pickle=False)
        _index = {k: data[k] for k in data.files}
    return _index


def retrieve(
    query: str,
    *,
    scope: str = "all",
    limit: int = _DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """
    Embed query and return top-k chunks by cosine similarity.

    scope: 'internal', 'external', or 'all'
    """
    model = _get_model()
    idx   = _get_index()

    q_vec = np.array(list(model.embed([query]))[0], dtype=np.float32)
    q_vec /= max(np.linalg.norm(q_vec), 1e-9)

    scores = idx["vectors"] @ q_vec  # (N,) cosine similarities

    # Mask out chunks outside the requested scope.
    if scope == "internal":
        mask = idx["source_types"] == "internal_documents"
    elif scope == "external":
        mask = idx["source_types"] == "external_literature"
    else:
        mask = np.ones(len(scores), dtype=bool)

    scores[~mask] = -2.0  # push out-of-scope chunks below all in-scope ones

    top_indices = np.argsort(scores)[::-1][:limit]

    parcels = []
    for rank, i in enumerate(top_indices, start=1):
        if scores[i] < -1.5:
            break  # no more in-scope results
        parcels.append({
            "evidence_id":     f"EV-D-{rank:03d}",
            "chunk_id":        str(idx["chunk_ids"][i]),
            "rank":            rank,
            "retrieval_score": round(float(scores[i]), 4),
            "source_type":     str(idx["source_types"][i]),
            "title":           str(idx["titles"][i]),
            "page":            str(idx["pages"][i]) or None,
            "text":            str(idx["texts"][i]),
            "citation":        str(idx["titles"][i]),
        })

    return parcels
