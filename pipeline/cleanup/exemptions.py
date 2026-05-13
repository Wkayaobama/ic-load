"""Bulk-load exemption rows from CSV into staging.fct_cleanup_exemptions.

CSV schema (header row required):
    object_type, hubspot_id, legacy_id, label, reason

`source` is supplied by the caller (one value per import — typically a tag like
'blast_radius_v1' or 'manual_<date>'). Rows are UPSERTed on (object_type,
hubspot_id) so re-imports are idempotent and operator-curated edits (changed
reason/label) are picked up on re-run.

Bulk path uses psycopg2.extras.execute_values — important for the ~10k+ row
imports we expect from the SEALSQ-IC'ALPS blast-radius closure (row-by-row
would inherit the same slowness flagged earlier for record_archive).
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

import psycopg2  # type: ignore[import-not-found]
from psycopg2.extras import execute_values  # type: ignore[import-not-found]


_REQUIRED_COLUMNS = ("object_type", "hubspot_id")
_OPTIONAL_COLUMNS = ("legacy_id", "label", "reason")


def _iter_rows(csv_path: Path, source: str) -> Iterable[tuple]:
    with csv_path.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        missing = [c for c in _REQUIRED_COLUMNS if c not in (reader.fieldnames or ())]
        if missing:
            raise ValueError(
                f"CSV {csv_path} missing required columns: {missing}. "
                f"Got headers: {reader.fieldnames}"
            )
        for row in reader:
            object_type = (row.get("object_type") or "").strip()
            hubspot_id  = (row.get("hubspot_id") or "").strip()
            if not object_type or not hubspot_id:
                continue
            yield (
                object_type,
                hubspot_id,
                (row.get("legacy_id") or "").strip() or None,
                (row.get("label") or "").strip() or None,
                (row.get("reason") or "").strip() or None,
                source,
            )


def load_exemptions_from_csv(dsn: str, csv_path: Path, source: str, *, schema: str = "staging") -> int:
    """Bulk-UPSERT rows from CSV into {schema}.fct_cleanup_exemptions.

    Returns the number of rows imported (input row count; UPSERT means
    new + updated are both counted)."""
    rows = list(_iter_rows(csv_path, source))
    if not rows:
        return 0
    sql = f"""
        INSERT INTO {schema}.fct_cleanup_exemptions
            (object_type, hubspot_id, legacy_id, label, reason, source)
        VALUES %s
        ON CONFLICT (object_type, hubspot_id) DO UPDATE SET
            legacy_id = EXCLUDED.legacy_id,
            label     = EXCLUDED.label,
            reason    = EXCLUDED.reason,
            source    = EXCLUDED.source,
            added_at  = now()
    """
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        execute_values(cur, sql, rows, page_size=500)
        conn.commit()
    return len(rows)
