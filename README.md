# Code Supplement: Layered Pre-Experimental Verification for Low-Data Science

This supplement provides a self-contained, domain-portable implementation of the
four-layer verification architecture described in the paper, instantiated for a
**rare-earth and transition-metal heterogeneous catalysis** dataset. It is
intended to accompany journal submission as a reproducibility and generalisability
demonstration.

The catalysis domain was selected as a held-out testbed: it shares the low-data,
multi-evidence-lane structure of the primary domain (structured experimental
records + external literature) while differing entirely in schema, terminology,
and identifier conventions. No catalysis data was used during system development.

---

## Contents

```
supplement/
├── agent/
│   ├── prompts/
│   │   ├── plan_request.md       # Request planner system prompt (catalysis)
│   │   ├── synthesize_answer.md  # Synthesis LLM system prompt
│   │   └── verifier_prompt.md    # Claim-level verifier system prompt (catalysis examples)
│   ├── guidance/database/
│   │   ├── database_identifier_formats.json  # Catalyst ID pattern recognition
│   │   ├── database_terms.json               # Natural-language → column mapping
│   │   └── request_planner_terms.json        # Field-bundle vocabulary
│   ├── request_plan.py           # Validated request-planning schema (Pydantic)
│   ├── schemas.py                # Core agent schemas: evidence, synthesis, verification
│   ├── state.py                  # AgentState: shared graph node state
│   └── verifier_terminal.py     # Deterministic abstention renderer
├── infrastructure/
│   ├── build_index.py            # One-time indexer: embeds chunks → data/embeddings.npz
│   ├── lancedb_retrieval.py      # Vector retrieval (fastembed + cosine search)
│   ├── mock_database.py          # SQLite-backed structured-data retrieval mock
│   └── mock_retrieval.py         # Keyword-scored retrieval (baseline / offline use)
├── data/
│   ├── catalysis_runs.json       # 30 synthetic catalyst performance records
│   └── literature_chunks.json    # 14 literature and internal-document chunks
├── demo.py                       # End-to-end runnable pipeline demo
├── eval_retrieval.py             # Retrieval evaluation: P@k, R@k, NDCG@k, MRR
├── requirements.txt
└── .env.example
```

---

## Architecture

The pipeline has four layers, each independently evaluable:

```
User query
    │
    ▼
[1] Request planner      — Claude structured-JSON output; routes to evidence lanes
    │
    ▼
[2] Evidence retrieval   — Structured data (SQLite mock) + Vector document retrieval
    │
    ▼
[3] Synthesis            — Claude converts evidence packet → cited answer prose
    │
    ▼
[4] Claim-level verifier — Claude Haiku checks each proposition against evidence
    │
    ▼
Final verified answer (or controlled abstention / retry)
```

**Infrastructure mocks replace production services** so the supplement runs
without cloud credentials. In the primary system:

| Supplement component | Production replacement |
|---|---|
| `infrastructure/mock_database.py` | BigQuery + LangChain database agent |
| `infrastructure/lancedb_retrieval.py` (fastembed + numpy) | LanceDB dense vector search (Cloud Run service) |
| `data/embeddings.npz` (14-chunk numpy index) | LanceDB table populated from GCS-stored chunk embeddings |

The LLM calls (planning, synthesis, verification) use the real Anthropic API;
only an `ANTHROPIC_API_KEY` is required.

---

## Setup

**Requirements:** Python 3.11+, an Anthropic API key.

```bash
# 1. Create an isolated environment
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. Install dependencies (~150 MB; no torch or CUDA required)
pip install -r requirements.txt

# 3. Configure your API key
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
# Optionally set ANTHROPIC_MODEL=claude-haiku-4-5-20251001 to minimise credit usage

# 4. Build the vector index (one-time; downloads ~25 MB ONNX model on first run)
python infrastructure/build_index.py

# 5. Run the demo
python demo.py

# 6. Run a custom query
python demo.py "Which catalysts have TOF above 0.5 s-1 and what does the literature say about their stability?"
```

The demo prints each pipeline stage and produces a verified, cited answer.

---

## Example queries

The following queries exercise different pipeline paths:

**Structured data only:**
```
For catalyst CER-003, return TOF, conversion, and stability hours.
```

**Database + literature:**
```
Compare CER-001 and CER-003 on activity and stability, and use literature to explain the La promotion effect.
```

**Literature only:**
```
Summarise what is known about coke resistance in Ni/La2O3 catalysts for dry reforming.
```

**Hypothesis generation:**
```
Use our experimental records and relevant literature to propose a testable explanation for why ALD-prepared Pd/CeO2 outperforms wet-impregnated samples.
```

---

## Retrieval evaluation

`eval_retrieval.py` evaluates the document retrieval layer against a
hand-labelled relevance set (graded: primary source = 2, supporting = 1).
Run without an API key:

```bash
python eval_retrieval.py
```

Results against the 14-chunk corpus (10 external queries, 4 internal queries)
using `BAAI/bge-small-en-v1.5` embeddings:

| Split | MRR | NDCG@1 | NDCG@3 | NDCG@5 |
|---|---|---|---|---|
| External literature (10 chunks) | 1.00 | 0.900 | 0.967 | 0.967 |
| Internal documents (4 chunks) | 1.00 | 1.000 | 0.940 | 0.981 |

MRR = 1.00 across both splits means the primary relevant chunk ranked first for
every query. The two NDCG@1 misses on external queries occur on paired chunks
(e.g. LIT-007 / LIT-008) that share vocabulary, causing the secondary chunk to
occasionally score higher than the primary at rank 1; both are retrieved within
the top 2.

---

## Example output

The following is an abridged trace from the hypothesis-generation query, run on
the held-out catalysis domain. It demonstrates all four pipeline layers operating
together and grounding a novel mechanistic claim in both structured experimental
records and peer-reviewed literature.

**Query:**
> Use our experimental records and relevant literature to propose a testable
> explanation for why ALD-prepared Pd/CeO2 outperforms wet-impregnated samples.

**Pipeline trace:**
```
[1/4] Planning request...
  status=ready  tasks=['lookup', 'generate_hypothesis']
  sources=['structured_data', 'external_literature', 'general_knowledge']

[2/4] Retrieving evidence...
  [db]  4 rows returned  (PDC-003 ALD, CER-001/002/003 wet impregnation)
  [lit] 5 chunks retrieved  (Spezzati et al. 2017; Choi et al. 2021)

[3/4] Synthesising answer...
  confidence=medium  citations=[EV-S-001..004, EV-D-001, EV-D-002]

[4/4] Verifying claims...
  outcome=passed  action=allow
```

**Answer (abridged):**

The database records show that at matched 1 wt% Pd loading and identical BET
surface area (~113 m²/g), ALD-prepared PDC-003 achieves dispersion = 88.4%,
TOF = 0.91 s⁻¹, and stability = 350 h, versus 54.2%, 0.48 s⁻¹, and 120 h for
wet-impregnated CER-001 — a 90% TOF gain and 3× longer stability with no
textural advantage [EV-S-001, EV-S-004].

The proposed mechanism: ALD's self-limiting vapour-phase deposition
preferentially generates isolated, atomically dispersed PdOx sites anchored to
CeO2 surface oxygen positions. Literature confirms that atomically dispersed
PdO/PdO2 on CeO2(111) are the active phase for low-temperature CO oxidation
(ΔEact = 29 kJ/mol via Mars–van Krevelen), while metallic Pd clusters are
inactive due to CO poisoning [EV-D-002]. Higher dispersion in ALD samples
approaches the single-atom/sub-nm regime, consistent with the Choi et al. result
that increasing Pd dispersion on CeO2 from ~45.6% to 75.1% (via hydrothermal
redispersion) directly improves activity [EV-D-001].

**Testable predictions generated:**
1. HAADF-STEM / XANES — ALD PDC-003 should show Pd²⁺/Pd⁴⁺ oxidation state
   (PdOx), CER-001 a higher fraction of metallic Pd nanoparticles.
2. CO-IR — PDC-003 should show isolated Pd²⁺–CO bands (>2100 cm⁻¹), not
   bridging/linear CO on Pd⁰ clusters.
3. Post-reaction dispersion — PDC-003 should retain dispersion better after
   350 h than CER-001 after 120 h, confirming stronger site-anchoring.
4. Temperature-matched TOF — retesting PDC-003 at 100 °C (matching CER-001)
   expected to widen the TOF gap further.

*Confidence: medium — direct spectroscopic characterisation of PDC-003 Pd
speciation not yet in the evidence base. Verification: passed.*

---

## Domain adaptation: what changes between domains

The table below maps each production component to its catalysis-domain
equivalent, showing exactly what a researcher would modify to instantiate the
framework in a new domain.

| Component | Primary domain | Catalysis supplement |
|---|---|---|
| Database schema | ~20 CVD process columns | ~19 catalysis columns (TOF, conversion, support, etc.) |
| Identifier patterns | Sample IDs (GLCT_NNNN), reactor IDs | Catalyst IDs (CER-001, PDC-042) |
| Database vocabulary | Growth rate, chamber pressure, etc. | TOF, conversion, BET surface area, etc. |
| Planner prompt examples | CVD reactor queries | Catalyst performance queries |
| Verifier prompt examples | Growth rate, nitrogen enrichment | TOF, Pd dispersion, La promotion |
| Retrieval corpus | Internal CVD reports + materials PDFs | Internal catalyst reports + catalysis literature |

The LLM prompts for synthesis and verification are **structurally identical**
across domains; only the domain-specific examples differ.

---

## Data

`data/catalysis_runs.json` contains **30 synthetic catalyst performance records**.
Values are chosen to be realistic in magnitude but do not represent any real
catalyst or run. The synthetic dataset covers:

- Six support materials: CeO2, Al2O3, ZrO2, TiO2, La2O3, SiO2
- Six active metals: Pd, Pt, Rh, Ru, Ni, Au, Cu
- Five promoters: La, Ba, K, Ce, Fe
- Four reactions: CO oxidation, dry reforming, WGS, CO2 hydrogenation
- Four synthesis methods: wet impregnation, coprecipitation, sol-gel, ALD
- Performance metrics: TOF (s⁻¹), conversion (%), selectivity (%), stability (h), BET (m²/g), dispersion (%)

`data/literature_chunks.json` contains ten literature chunks (`LIT-001` through
`LIT-010`) with passages extracted or closely paraphrased from real,
peer-reviewed publications (ACS Catalysis, RSC Advances, Catalysis Science &
Technology, Nature Communications), plus four internal-document chunks
(`INT-001` through `INT-004`). `INT-001` through `INT-003` are
characterisation-report excerpts whose numerical data are drawn from the same
real open-access sources; `INT-004` is a synthetic stability-protocol
description. Access notes within each chunk flag values not independently
verifiable from open-access text.

`data/embeddings.npz` is generated by `infrastructure/build_index.py` and is
not committed to the repository.

---

## Mapping to paper sections

| Paper section | Supplement component |
|---|---|
| §2.1 Request planner | `agent/prompts/plan_request.md`, `agent/request_plan.py` |
| §2.2 Hybrid retrieval | `infrastructure/lancedb_retrieval.py`, `infrastructure/build_index.py` |
| §2.3 Database retrieval | `infrastructure/mock_database.py` (SQLite proxy) |
| §2.4 Synthesis | `agent/prompts/synthesize_answer.md`, `demo.py::_synthesize` |
| §2.5 Claim verifier | `agent/prompts/verifier_prompt.md`, `demo.py::_verify` |
| §3 Evidence schemas | `agent/schemas.py` |
| §4 State model | `agent/state.py` |

---

## Licence

Code is released under the MIT licence. Synthetic data in `data/catalysis_runs.json`
is released under CC0 (no rights reserved). Passages in `data/literature_chunks.json`
are excerpts from published works cited within each chunk and reproduced here for
non-commercial research and reproducibility purposes.
