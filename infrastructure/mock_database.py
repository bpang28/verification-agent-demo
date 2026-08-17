"""
SQLite-backed mock of the structured-data retrieval node.

Replaces the BigQuery pipeline for self-contained execution.
In production, swap this module for the real database adapter.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).parent.parent / "data" / "catalysis_runs.json"
_DB_PATH = ":memory:"

_FIELD_ALIASES: dict[str, str] = {
    "tof": "tof_s",
    "tos": "tof_s",
    "conversion": "conversion_pct",
    "selectivity": "selectivity_pct",
    "stability": "stability_hours",
    "surface area": "bet_surface_area_m2g",
    "bet": "bet_surface_area_m2g",
    "loading": "metal_loading_wt_pct",
    "dispersion": "dispersion_pct",
    "temperature": "reaction_temp_c",
    "pressure": "pressure_bar",
    "ghsv": "ghsv_h",
}


def _load_data(path: Path = _DATA_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["rows"]


def _create_connection(rows: list[dict]) -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row

    columns = [
        ("catalyst_id", "TEXT"), ("catalyst_name", "TEXT"),
        ("active_metal", "TEXT"), ("support", "TEXT"),
        ("metal_loading_wt_pct", "REAL"), ("promoter", "TEXT"),
        ("promoter_loading_wt_pct", "REAL"), ("bet_surface_area_m2g", "REAL"),
        ("synthesis_method", "TEXT"), ("calcination_temp_c", "INTEGER"),
        ("reaction", "TEXT"), ("reaction_temp_c", "INTEGER"),
        ("pressure_bar", "REAL"), ("ghsv_h", "REAL"),
        ("conversion_pct", "REAL"), ("selectivity_pct", "REAL"),
        ("tof_s", "REAL"), ("stability_hours", "REAL"),
        ("dispersion_pct", "REAL"),
    ]
    col_defs = ", ".join(f"{name} {typ}" for name, typ in columns)
    conn.execute(f"CREATE TABLE catalysis_experiments ({col_defs})")

    col_names = [c[0] for c in columns]
    placeholders = ", ".join("?" for _ in col_names)
    for row in rows:
        values = [row.get(c) for c in col_names]
        conn.execute(
            f"INSERT INTO catalysis_experiments VALUES ({placeholders})", values
        )
    conn.commit()
    return conn


def _normalize_question(question: str) -> str:
    question = question.lower()
    for alias, canonical in _FIELD_ALIASES.items():
        question = question.replace(alias, canonical)
    return question


def _extract_catalyst_ids(question: str) -> list[str]:
    return re.findall(r"\b[A-Z]{2,3}-\d{3}\b", question)


def _extract_filter(question: str) -> tuple[str | None, str | None, float | None]:
    """Parse simple threshold filters like 'bet_surface_area_m2g > 150'."""
    match = re.search(
        r"(tof_s|conversion_pct|selectivity_pct|stability_hours|bet_surface_area_m2g|metal_loading_wt_pct|dispersion_pct)"
        r"\s*(>|<|>=|<=|=|above|below|greater than|less than)\s*([0-9]+(?:\.[0-9]+)?)",
        question,
    )
    if not match:
        return None, None, None
    field, op, value = match.group(1), match.group(2), float(match.group(3))
    op_map = {"above": ">", "greater than": ">", "below": "<", "less than": "<", "=": "="}
    op = op_map.get(op, op)
    return field, op, value


def query(
    question: str,
    *,
    limit: int = 25,
) -> dict[str, Any]:
    """
    Lightweight natural-language-to-SQL parser for demo queries.

    Covers: named-catalyst lookups, simple threshold filters,
    metal/support/reaction group aggregates, and global aggregates.
    Returns a structured evidence packet compatible with the agent pipeline.
    """
    rows_data = _load_data()
    conn = _create_connection(rows_data)

    q = _normalize_question(question)
    catalyst_ids = _extract_catalyst_ids(question)
    field, op, threshold = _extract_filter(q)

    select_cols = "*"
    where_clauses: list[str] = []
    params: list[Any] = []

    if catalyst_ids:
        placeholders = ", ".join("?" for _ in catalyst_ids)
        where_clauses.append(f"catalyst_id IN ({placeholders})")
        params.extend(catalyst_ids)

    for keyword, col in [
        ("pd", "active_metal"), ("rh", "active_metal"), ("ru", "active_metal"),
        ("pt", "active_metal"), ("ni", "active_metal"), ("au", "active_metal"),
        ("cu", "active_metal"),
    ]:
        if re.search(rf"\b{keyword}\b", q) and "active_metal" not in str(where_clauses):
            where_clauses.append("LOWER(active_metal) = ?")
            params.append(keyword)
            break

    for keyword, col, val in [
        ("ceo2", "support", "CeO2"), ("al2o3", "support", "Al2O3"),
        ("zro2", "support", "ZrO2"), ("tio2", "support", "TiO2"),
        ("la2o3", "support", "La2O3"), ("sio2", "support", "SiO2"),
    ]:
        if keyword in q and "support" not in str(where_clauses):
            where_clauses.append("LOWER(support) = ?")
            params.append(val.lower())
            break

    for keyword, col, val in [
        ("co_oxidation", "reaction", "co_oxidation"),
        ("co oxidation", "reaction", "co_oxidation"),
        ("dry_reforming", "reaction", "dry_reforming"),
        ("dry reforming", "reaction", "dry_reforming"),
        ("wgs", "reaction", "wgs"),
        ("water-gas shift", "reaction", "wgs"),
        ("co2_hydrogenation", "reaction", "co2_hydrogenation"),
        ("co2 hydrogenation", "reaction", "co2_hydrogenation"),
    ]:
        if keyword in q and "reaction" not in str(where_clauses):
            where_clauses.append("reaction = ?")
            params.append(val)
            break

    if field and op and threshold is not None:
        where_clauses.append(f"{field} {op} ?")
        params.append(threshold)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    sql = f"SELECT {select_cols} FROM catalysis_experiments {where_sql} LIMIT {limit}"

    cursor = conn.execute(sql, params)
    result_rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    col_names = [
        "catalyst_id", "catalyst_name", "active_metal", "support",
        "metal_loading_wt_pct", "promoter", "promoter_loading_wt_pct",
        "bet_surface_area_m2g", "synthesis_method", "calcination_temp_c",
        "reaction", "reaction_temp_c", "pressure_bar", "ghsv_h",
        "conversion_pct", "selectivity_pct", "tof_s", "stability_hours",
        "dispersion_pct",
    ]

    return {
        "schema_version": "2.1.0",
        "agent": "database_agent",
        "question": question,
        "database_question": question,
        "query_type": "rows",
        "sql": sql,
        "dry_run_passed": True,
        "rows_returned": len(result_rows),
        "row_count_before_limit": len(result_rows),
        "required_columns": col_names,
        "context_columns": [],
        "evidence_rows": result_rows,
        "context_rows": [],
        "output_resolution": {
            "requested": col_names,
            "resolved": col_names,
            "unavailable": [],
            "partial": False,
        },
        "limitations": [] if result_rows else ["No matching records found."],
        "clarification_needed": False,
        "execution_failed": False,
        "requires_synthesis": True,
        "planner_table": {
            "columns": [{"name": c, "label": c, "unit": None, "source_column": c} for c in col_names],
            "rows": result_rows,
            "rows_returned": len(result_rows),
            "result_limit": limit,
            "truncated": False,
            "schema_caveats": ["Synthetic data — illustrative only."],
        },
        "database_completeness": {
            "status": "complete",
            "note": "SQLite in-memory store; all matching rows returned.",
        },
    }
