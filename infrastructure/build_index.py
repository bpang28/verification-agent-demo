"""
One-time script: embed all chunks and write a LanceDB table.

Run once before using lancedb_retrieval.py:
    python infrastructure/build_index.py

Writes to data/lancedb/. Safe to re-run — overwrites the existing table.
Uses fastembed (ONNX, no torch/CUDA required, ~25 MB model download).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

CHUNKS_PATH = Path(__file__).parent.parent / "data" / "literature_chunks.json"
DB_PATH     = Path(__file__).parent.parent / "data" / "lancedb"
MODEL_NAME  = "BAAI/bge-small-en-v1.5"


def build() -> None:
    from fastembed import TextEmbedding
    import lancedb

    print(f"Loading embedding model {MODEL_NAME!r} (downloads ~25 MB on first run)...")
    model = TextEmbedding(model_name=MODEL_NAME)

    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))["chunks"]
    texts  = [c["title"] + " " + c["text"] for c in chunks]

    print(f"Embedding {len(chunks)} chunks...")
    vectors = list(model.embed(texts))   # generator → list of numpy arrays

    records = []
    for chunk, vec in zip(chunks, vectors):
        records.append({
            "chunk_id":    chunk["chunk_id"],
            "source_type": chunk.get("source_type", "unknown"),
            "title":       chunk["title"],
            "text":        chunk["text"],
            "page":        str(chunk.get("page") or ""),
            "vector":      vec.tolist(),
        })

    DB_PATH.mkdir(parents=True, exist_ok=True)
    db    = lancedb.connect(str(DB_PATH))
    table = db.create_table("chunks", data=records, mode="overwrite")
    print(f"Indexed {len(records)} chunks → {DB_PATH}")
    print(f"  External: {sum(1 for r in records if r['source_type'] == 'external_literature')}")
    print(f"  Internal: {sum(1 for r in records if r['source_type'] == 'internal_documents')}")


if __name__ == "__main__":
    build()
