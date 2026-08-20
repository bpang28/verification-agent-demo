"""
One-time script: embed all chunks and write a LanceDB table.

Run once before using lancedb_retrieval.py:
    python infrastructure/build_index.py

Writes to data/lancedb/. Safe to re-run — overwrites the existing table.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

CHUNKS_PATH = Path(__file__).parent.parent / "data" / "literature_chunks.json"
DB_PATH     = Path(__file__).parent.parent / "data" / "lancedb"
MODEL_NAME  = "all-MiniLM-L6-v2"


def build() -> None:
    from sentence_transformers import SentenceTransformer
    import lancedb

    print(f"Loading embedding model {MODEL_NAME!r}...")
    model = SentenceTransformer(MODEL_NAME)

    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))["chunks"]
    print(f"Embedding {len(chunks)} chunks...")

    records = []
    for chunk in chunks:
        embed_text = chunk["title"] + " " + chunk["text"]
        vector = model.encode(embed_text, normalize_embeddings=True).tolist()
        records.append({
            "chunk_id":    chunk["chunk_id"],
            "source_type": chunk.get("source_type", "unknown"),
            "title":       chunk["title"],
            "text":        chunk["text"],
            "page":        str(chunk.get("page") or ""),
            "vector":      vector,
        })

    DB_PATH.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(str(DB_PATH))
    table = db.create_table("chunks", data=records, mode="overwrite")
    print(f"Indexed {len(records)} chunks → {DB_PATH}")
    print(f"  External: {sum(1 for r in records if r['source_type'] == 'external_literature')}")
    print(f"  Internal: {sum(1 for r in records if r['source_type'] == 'internal_documents')}")


if __name__ == "__main__":
    build()
