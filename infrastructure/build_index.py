"""
One-time script: embed all chunks and save to data/embeddings.npz.

Run once before using lancedb_retrieval.py:
    python infrastructure/build_index.py

Uses fastembed (ONNX, no torch required, ~25 MB model download on first run).
In production this step writes to a LanceDB Cloud Run service instead.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

CHUNKS_PATH = Path(__file__).parent.parent / "data" / "literature_chunks.json"
INDEX_PATH  = Path(__file__).parent.parent / "data" / "embeddings.npz"
MODEL_NAME  = "BAAI/bge-small-en-v1.5"


def build() -> None:
    from fastembed import TextEmbedding

    print(f"Loading {MODEL_NAME!r} (downloads ~25 MB on first run)...")
    model = TextEmbedding(model_name=MODEL_NAME)

    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))["chunks"]
    texts  = [c["title"] + " " + c["text"] for c in chunks]

    print(f"Embedding {len(chunks)} chunks...")
    vectors = np.array(list(model.embed(texts)), dtype=np.float32)  # (N, D)

    # Normalise so cosine similarity = dot product.
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors = vectors / np.maximum(norms, 1e-9)

    chunk_ids    = np.array([c["chunk_id"]                    for c in chunks])
    source_types = np.array([c.get("source_type", "unknown")  for c in chunks])
    titles       = np.array([c["title"]                       for c in chunks])
    texts_arr    = np.array([c["text"]                        for c in chunks])
    pages        = np.array([str(c.get("page") or "")         for c in chunks])

    np.savez_compressed(
        INDEX_PATH,
        vectors=vectors,
        chunk_ids=chunk_ids,
        source_types=source_types,
        titles=titles,
        texts=texts_arr,
        pages=pages,
    )

    n_ext = sum(1 for c in chunks if c.get("source_type") == "external_literature")
    n_int = sum(1 for c in chunks if c.get("source_type") == "internal_documents")
    print(f"Saved {len(chunks)} embeddings → {INDEX_PATH}")
    print(f"  External: {n_ext}  |  Internal: {n_int}  |  dim: {vectors.shape[1]}")


if __name__ == "__main__":
    build()
