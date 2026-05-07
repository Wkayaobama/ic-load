"""Schema + row-count probe for pre/post dbt validation.

Dumps information_schema for every staging table that matters (pre-gold silver
tables + communication dbt marts + custom-object marts) to a CSV. Run once
BEFORE dbt and once AFTER; diff the CSVs to see schema/row changes.

Usage
-----
    python scripts/probe_schemas.py --output artifacts/probe_pre_dbt.csv
    # ... run dbt build ...
    python scripts/probe_schemas.py --output artifacts/probe_post_dbt.csv
    diff artifacts/probe_pre_dbt.csv artifacts/probe_post_dbt.csv

Exit codes
----------
    0 — probe completed (some tables may be not_found; that is allowed)
    2 — DB connection failed or no tables could be inspected
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow `python scripts/probe_schemas.py` from the ic-load root without relying on PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from context.db import get_connection, is_postgres_configured, postgres_config  # noqa: E402


PROBE_TARGETS: list[tuple[str, str, str | None]] = [
    # (schema, table, primary_key_column_or_None)
    ("staging", "stg_company_normalised",       "icalps_company_id"),
    ("staging", "stg_contact_normalised",       "icalps_contact_id"),
    ("staging", "stg_opportunity_normalised",   "icalps_deal_id"),
    ("staging", "stg_communication_normalised", "comm_communicationid"),
    ("staging", "stg_case_v2",                  "icalps_ticket_id"),
    ("staging", "fct_communication_calls",      "icalps_communication_id"),
    ("staging", "fct_communication_notes",      "icalps_communication_id"),
    ("staging", "fct_communication_tasks",      "icalps_communication_id"),
    ("staging", "fct_communication_meetings",   "icalps_communication_id"),
    ("staging", "fct_communication_bridge",     None),  # aggregate table, no single PK
    ("staging", "fct_communication_email_meetings", "icalps_communication_id"),
    ("staging", "fct_communication_rank",       None),
    ("staging", "fct_custom_object_tasks",      None),
    ("staging", "stg_custom_object_tasks",      None),
]


CSV_HEADER = [
    "schema", "table", "column", "data_type", "is_nullable", "ordinal_position",
    "row_count", "distinct_pk_count", "null_pk_count", "status",
]


def _fetch_columns(cur, schema: str, table: str) -> list[tuple]:
    cur.execute(
        """
        SELECT column_name, data_type, is_nullable, ordinal_position
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    )
    return cur.fetchall()


def _fetch_counts(cur, schema: str, table: str, pk: str | None) -> tuple[int, int | None, int | None]:
    cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"')
    row_count = cur.fetchone()[0]

    if pk is None:
        return row_count, None, None

    cur.execute(
        f'SELECT COUNT(DISTINCT "{pk}"), COUNT(*) FILTER (WHERE "{pk}" IS NULL) '
        f'FROM "{schema}"."{table}"'
    )
    distinct_pk, null_pk = cur.fetchone()
    return row_count, distinct_pk, null_pk


def _probe(schema: str, table: str, pk: str | None, cur) -> list[list]:
    try:
        columns = _fetch_columns(cur, schema, table)
    except Exception as exc:
        return [[schema, table, "", "", "", "", "", "", "", f"error: {exc}"]]

    if not columns:
        return [[schema, table, "", "", "", "", "", "", "", "not_found"]]

    try:
        row_count, distinct_pk, null_pk = _fetch_counts(cur, schema, table, pk)
    except Exception as exc:
        row_count, distinct_pk, null_pk = "error", "", ""
        status_prefix = f"count_error: {exc}"
    else:
        status_prefix = "ok"

    rows: list[list] = []
    for (col, dtype, nullable, ordinal) in columns:
        rows.append([
            schema, table, col, dtype, nullable, ordinal,
            row_count, distinct_pk if distinct_pk is not None else "",
            null_pk if null_pk is not None else "",
            status_prefix,
        ])
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump schema + row counts for staging tables to CSV.")
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="CSV destination (default: artifacts/probe_schemas_<UTC>.csv)",
    )
    args = parser.parse_args()

    output_path = args.output or (
        Path("artifacts") / f"probe_schemas_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not is_postgres_configured(postgres_config()):
        print("ERROR: Postgres connection is not configured. Set ICALPS_PG* or PG* env vars.", file=sys.stderr)
        return 2

    all_rows: list[list] = []
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                for schema, table, pk in PROBE_TARGETS:
                    all_rows.extend(_probe(schema, table, pk, cur))
    except Exception as exc:
        print(f"ERROR: database connection failed: {exc}", file=sys.stderr)
        return 2

    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_HEADER)
        writer.writerows(all_rows)

    found = sum(1 for r in all_rows if r[-1].startswith("ok"))
    not_found = sum(1 for r in all_rows if r[-1] == "not_found")
    errors = sum(1 for r in all_rows if r[-1].startswith("error") or r[-1].startswith("count_error"))

    print(f"Wrote {output_path} — {len(all_rows)} rows ({found} ok columns, {not_found} not_found, {errors} errors)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
