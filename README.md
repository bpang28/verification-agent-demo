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
│   ├── mock_database.py          # SQLite-backed structured-data retrieval mock
│   └── mock_retrieval.py         # Keyword-scored in-memory document retrieval mock
├── data/
│   ├── catalysis_runs.json       # 30 synthetic catalyst performance records
│   └── literature_chunks.json    # 20 synthetic literature and internal-document chunks
├── demo.py                       # End-to-end runnable pipeline demo
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
[2] Evidence retrieval   — Structured data (SQLite mock) + Document retrieval mock
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

| Mock (supplement)              | Production replacement             |
|--------------------------------|------------------------------------|
| `infrastructure/mock_database` | BigQuery + LangChain database agent |
| `infrastructure/mock_retrieval`| LanceDB dense + BM25 hybrid search  |

The LLM calls (planning, synthesis, verification) use the real Anthropic API;
only an `ANTHROPIC_API_KEY` is required.

---

## Setup

**Requirements:** Python 3.11+, an Anthropic API key.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure your API key
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...

# 3. Run the demo
python demo.py

# 4. Try a custom query
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
Technology, Nature Communications), plus four internal-document chunks (`INT-001` through `INT-004`). `INT-001`
through `INT-003` are characterisation-report excerpts whose numerical data are
drawn from real open-access publications (same sources as LIT-*), presented in
the style of an internal lab record; `INT-004` is a synthetic stability-protocol
description. Access notes within each chunk flag values not independently
verifiable from open-access text.

---

## Mapping to paper sections

| Paper section | Supplement component |
|---|---|
| §2.1 Request planner | `agent/prompts/plan_request.md`, `agent/request_plan.py` |
| §2.2 Hybrid retrieval | `infrastructure/mock_retrieval.py` (keyword proxy) |
| §2.3 Database retrieval | `infrastructure/mock_database.py` (SQLite proxy) |
| §2.4 Synthesis | `agent/prompts/synthesize_answer.md`, `demo.py::_synthesize` |
| §2.5 Claim verifier | `agent/prompts/verifier_prompt.md`, `demo.py::_verify` |
| §3 Evidence schemas | `agent/schemas.py` |
| §4 State model | `agent/state.py` |

---

## Licence

Code is released under the MIT licence. Synthetic data files (`data/`) are
released under CC0 (no rights reserved).
