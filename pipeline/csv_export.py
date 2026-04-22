"""CSV export utilities for --silver-only --csv and --gold-only --csv modes.

These functions are read-only SELECT queries — no INSERT, UPDATE, or DDL.
They use the same DB connection pattern as pipeline/hooks/_primitives.py.
"""
from __future__ import annotations

import csv
from pathlib import Path


def export_silver_normalised(entity: str, run_id: str, artifacts_dir: Path) -> Path:
    """SELECT * FROM staging.stg_{entity}_normalised → CSV.

    Returns the Path of the written CSV file.
    """
    from context.db import get_connection

    table = f"staging.stg_{entity}_normalised"
    out_path = artifacts_dir / f"{entity}_silver_{run_id}.csv"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT * FROM {table}")
            headers = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    return out_path


def export_gold_preview(entity: str, run_id: str, artifacts_dir: Path) -> list[Path]:
    """Export what would be upserted at gold, without any DB writes.

    For company/contact/opportunity:
      SELECT * FROM staging.stg_{entity}_normalised WHERE _load_status IN ('NEW','MODIFIED')
      → one CSV: artifacts/{entity}_gold_preview_{run_id}.csv

    For communication:
      The gold upsert reads from four bridge tables populated by PG UDF
      silver.fn_build_communication_hierarchy (run during ENTITY_POSTPROCESS_PRE).
      No _load_status filter — uses NOT EXISTS idempotency guard instead.
      Export: SELECT * FROM {bridge_table} WHERE icalps_communication_id IS NOT NULL
      → up to four CSVs: artifacts/communication_gold_preview_{type}_{run_id}.csv
      Missing bridge tables are skipped with a printed warning.

    Returns list of Paths written.
    """
    from context.config import load_schema_context
    from context.db import get_connection

    out_paths: list[Path] = []
    out_path_base = artifacts_dir
    out_path_base.mkdir(parents=True, exist_ok=True)

    if entity.lower() == "communication":
        schema = load_schema_context()
        comm_cfg = schema.get("entities", {}).get("Communication", {})
        bridge_tables: dict[str, str] = comm_cfg.get("bridge_tables", {})
        # Meetings is not in schema_context.yaml; use the same fallback as render.py
        all_types = ["Calls", "Notes", "Tasks", "Meetings"]
        for comm_type in all_types:
            table = bridge_tables.get(comm_type, f"staging.fct_communication_{comm_type.lower()}")
            out_path = out_path_base / f"communication_gold_preview_{comm_type.lower()}_{run_id}.csv"
            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"SELECT * FROM {table} WHERE icalps_communication_id IS NOT NULL"
                        )
                        headers = [desc[0] for desc in cur.description]
                        rows = cur.fetchall()
                with open(out_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                    writer.writerows(rows)
                out_paths.append(out_path)
            except Exception as exc:
                print(f"  [WARNING]  gold_only: skipping {comm_type} — {exc}")
    else:
        _ENTITY_KEY = {"company": "Company", "contact": "Person", "opportunity": "Opportunity"}
        schema_key = _ENTITY_KEY.get(entity.lower())
        if schema_key is None:
            raise ValueError(f"export_gold_preview: unsupported entity {entity!r}")

        schema = load_schema_context()
        cfg = schema["entities"][schema_key]
        silver_table = cfg["silver_table"]
        load_status_col = cfg["upsert"]["load_status_column"]
        out_path = out_path_base / f"{entity}_gold_preview_{run_id}.csv"

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM {silver_table}"
                    f" WHERE {load_status_col} IN ('NEW', 'MODIFIED')"
                )
                headers = [desc[0] for desc in cur.description]
                rows = cur.fetchall()

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

        out_paths.append(out_path)

    return out_paths
