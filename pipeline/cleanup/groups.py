"""Group salvation — load + apply 'Group' rename PATCHes for preserved
conglomerate anchors.

Two responsibilities:
  - load_groups_from_csv(): bulk-UPSERT operator-curated rows into
    staging.fct_cleanup_groups. CSV schema:
        object_type, hubspot_id, original_name, target_name, reason
    `source` is set per-import (tag).
  - apply_group_renames(): pending rows -> PATCH /crm/v3/objects/{type}/{id}
    with {"name": target_name}. Records pre-PATCH state via the table's
    `original_name` column if not already set, so revert is possible.

Both gated by separate env vars for explicit operator opt-in.
"""
from __future__ import annotations

import csv
from pathlib import Path

import psycopg2  # type: ignore[import-not-found]
import requests
from psycopg2.extras import execute_values  # type: ignore[import-not-found]

from pipeline.library_files.client import HubSpotClient

from .ledger import CleanupLedger


_REQUIRED_COLUMNS = ("object_type", "hubspot_id", "target_name")


def _iter_rows(csv_path: Path, source: str):
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
            target_name = (row.get("target_name") or "").strip()
            if not (object_type and hubspot_id and target_name):
                continue
            yield (
                object_type,
                hubspot_id,
                (row.get("original_name") or "").strip() or None,
                target_name,
                "pending",
                None,
                source,
            )


def load_groups_from_csv(dsn: str, csv_path: Path, source: str, *, schema: str = "staging") -> int:
    """Bulk-UPSERT rows from CSV into {schema}.fct_cleanup_groups.

    Returns the number of rows imported (input row count; UPSERT means new +
    updated are both counted).
    """
    rows = list(_iter_rows(csv_path, source))
    if not rows:
        return 0
    sql = f"""
        INSERT INTO {schema}.fct_cleanup_groups
            (object_type, hubspot_id, original_name, target_name, status, error, source)
        VALUES %s
        ON CONFLICT (object_type, hubspot_id) DO UPDATE SET
            -- preserve original_name once captured (don't overwrite mid-flight)
            original_name = COALESCE({schema}.fct_cleanup_groups.original_name, EXCLUDED.original_name),
            target_name   = EXCLUDED.target_name,
            source        = EXCLUDED.source,
            added_at      = now()
    """
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        execute_values(cur, sql, rows, page_size=500)
        conn.commit()
    return len(rows)


def apply_group_renames(
    *,
    client: HubSpotClient,
    dsn: str,
    object_type: str,
    live: bool,
    schema: str = "staging",
) -> dict:
    """PATCH name for every pending fct_cleanup_groups row of object_type.

    Idempotent: rows already at status='applied' are skipped.
    Records original_name pre-PATCH (if missing) so revert is possible later.
    """
    summary = {
        "object_type": object_type, "live": live,
        "pending": 0, "applied": 0, "failed": 0, "skipped_already_applied": 0,
    }

    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT hubspot_id, original_name, target_name
            FROM {schema}.fct_cleanup_groups
            WHERE object_type = %s AND status IN ('pending', 'failed')
            ORDER BY hubspot_id
            """,
            (object_type,),
        )
        rows = cur.fetchall()
        summary["pending"] = len(rows)

        for hid, orig, target in rows:
            # If original_name not yet captured, GET it now so revert is possible.
            if not orig and object_type == "companies":
                if not live:
                    summary["skipped_already_applied"] += 0  # noop
                    continue
                try:
                    pre = client.get_company(hid, properties=["name"])
                    orig = pre.get("properties", {}).get("name") or ""
                    cur.execute(
                        f"UPDATE {schema}.fct_cleanup_groups SET original_name = %s "
                        f"WHERE object_type = %s AND hubspot_id = %s",
                        (orig, object_type, hid),
                    )
                    conn.commit()
                except requests.HTTPError as exc:
                    cur.execute(
                        f"UPDATE {schema}.fct_cleanup_groups SET status = 'failed', "
                        f"error = %s, last_attempt_at = now() "
                        f"WHERE object_type = %s AND hubspot_id = %s",
                        (f"GET failed: {exc.response.status_code} {exc.response.text[:200]}",
                         object_type, hid),
                    )
                    conn.commit()
                    summary["failed"] += 1
                    continue

            if not live:
                continue

            # PATCH
            try:
                if object_type == "companies":
                    client.patch_company(hid, {"name": target})
                else:
                    # Future extensibility: per-object-type PATCH paths.
                    raise NotImplementedError(f"apply_group_renames: object_type={object_type!r} not wired yet")
                cur.execute(
                    f"UPDATE {schema}.fct_cleanup_groups SET status = 'applied', "
                    f"error = NULL, last_attempt_at = now() "
                    f"WHERE object_type = %s AND hubspot_id = %s",
                    (object_type, hid),
                )
                conn.commit()
                summary["applied"] += 1
            except (requests.HTTPError, NotImplementedError) as exc:
                err_text = (
                    f"{exc.response.status_code} {exc.response.text[:200]}"
                    if isinstance(exc, requests.HTTPError)
                    else str(exc)
                )
                cur.execute(
                    f"UPDATE {schema}.fct_cleanup_groups SET status = 'failed', "
                    f"error = %s, last_attempt_at = now() "
                    f"WHERE object_type = %s AND hubspot_id = %s",
                    (err_text, object_type, hid),
                )
                conn.commit()
                summary["failed"] += 1

    return summary
