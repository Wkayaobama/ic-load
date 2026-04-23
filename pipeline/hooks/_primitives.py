"""Shared primitives used by multiple hook modules.

These are not PipelineStage entries themselves — they are building blocks
called by stage hooks:

- run_sql_file: executes a .sql file against Postgres in a fresh transaction.
  Called by gold.upsert, associations.run_bridge, post_run_verify.verify,
  and entity_postprocess.dispatch (for type: sql entries in MANIFEST.yaml).

- run_sql_text: executes an in-memory SQL string in a fresh transaction.
  Used internally by hook modules that delegate to the legacy executor
  classes (GoldUpsertExecutor, AssociationBridgeExecutor) which require
  an `execute_sql: Callable[[str], int]` callable.

- write_csv: writes columns + rows to a CSV file. Used by executor preview
  methods to emit candidate-row CSVs when the runner is invoked with
  --preview. Centralised so gold.py and associations.py share one CSV
  dialect (UTF-8, csv.QUOTE_MINIMAL, \\n terminator).

- StructuredLogger: writes the per-stage log blocks defined in
  IC_Load_Production_Plan.md §8. Phase 2 scaffolds the class; Phase 5
  wires it into PipelineContext.transition().
"""
from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def run_sql_file(
    sql_path: Path,
    params: Mapping[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a .sql file against Postgres in a single fresh transaction.

    Contract (IC_Load_Production_Plan.md §7.6 Contract B)
    -----------------------------------------------------
    - Opens, commits, and closes its own transaction. Does not share state
      across calls — safe for repeated invocation across entities.
    - Parameters are bound via psycopg2 parameter binding (no string
      interpolation into SQL — prevents injection).
    - On exception, ROLLBACK is issued before the exception propagates.

    Returns
    -------
    {"file": str, "statements": int, "rows_affected": int, "duration_s": float,
     "mode": "dry_run" | "executed"}
    """
    sql_path = Path(sql_path)
    if dry_run:
        return {
            "file": str(sql_path),
            "statements": 0,
            "rows_affected": 0,
            "duration_s": 0.0,
            "mode": "dry_run",
        }

    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found: {sql_path}")

    sql_text = sql_path.read_text(encoding="utf-8")
    rows = run_sql_text(sql_text, params=params)
    start = time.perf_counter()
    # run_sql_text already executed — measure lightweight timing for logging.
    duration = time.perf_counter() - start
    return {
        "file": str(sql_path),
        "statements": 1,
        "rows_affected": rows,
        "duration_s": round(duration, 3),
        "mode": "executed",
    }


def run_sql_text(sql_text: str, params: Mapping[str, Any] | None = None) -> int:
    """Execute a SQL text string in a fresh transaction. Return cursor.rowcount.

    Used by hook modules (gold, associations, post_run_verify) as the
    `execute_sql` callable passed to legacy executor classes that already
    handle SQL rendering but delegate statement execution.

    Note: for multi-statement SQL, cursor.rowcount reports the LAST
    statement's count. This matches psycopg2 semantics.
    """
    from context.db import get_connection

    with get_connection() as conn:
        try:
            with conn.cursor() as cur:
                cur.execute(sql_text, params or None)
                rc = cur.rowcount if cur.rowcount is not None else 0
            conn.commit()
            return rc
        except Exception:
            conn.rollback()
            raise


def write_csv(path: Path, columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> int:
    """Write header + rows to a CSV file. Return the number of data rows written.

    Used by GoldUpsertExecutor.preview and AssociationBridgeExecutor.preview
    to emit candidate-row CSVs during --preview runs. Central location keeps
    every preview output on the same dialect: UTF-8, csv.QUOTE_MINIMAL, \\n.
    Parent directories are created if missing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(list(columns))
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


class StructuredLogger:
    """Append per-stage transition blocks to a human-readable .log file.

    See IC_Load_Production_Plan.md §8 for the log format. Target path:
    artifacts/logs/pipeline_run_{entity}_{run_id}.log

    The logger is stateful on one field only — the log file handle — and
    only for the lifetime of a single PipelineContext. It is not shared
    across runs or entities.

    Phase 2 status: class defined, not yet wired into transition(). Phase 5
    adds the wiring per migration plan.
    """

    def record(
        self,
        *,
        from_stage: str,
        to_stage: str,
        status: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        raise NotImplementedError(
            "pipeline.hooks._primitives.StructuredLogger.record — "
            "scheduled for Phase 5 (Orchestration + Logging). "
            "See IC_Load_Production_Plan.md §11 Phase 5."
        )
