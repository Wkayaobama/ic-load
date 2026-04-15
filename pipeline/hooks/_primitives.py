"""Shared primitives used by multiple hook modules.

These are not PipelineStage entries themselves — they are building blocks
called by stage hooks:

- run_sql_file: executes a .sql file against Postgres in a fresh transaction.
  Called by gold.upsert, associations.run_bridge, post_run_verify.verify,
  and entity_postprocess.dispatch (for type: sql entries in MANIFEST.yaml).

- StructuredLogger: writes the per-stage log blocks defined in
  IC_Load_Production_Plan.md §8. Injected into PipelineContext at
  construction; state.transition() calls .record() on every transition.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


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

    Returns
    -------
    {"file": str, "statements": int, "rows_affected": int, "duration_s": float}

    Raises
    ------
    NotImplementedError — Phase 1 scaffolding. Implement in Phase 2 by
    wrapping context.db.get_connection() in a context manager that opens
    a cursor, executes the file contents, commits, and returns counts.
    """
    raise NotImplementedError(
        f"pipeline.hooks._primitives.run_sql_file — Phase 1 scaffolding. "
        f"Target: {sql_path.name}. "
        f"See IC_Load_Production_Plan.md §11 Phase 2."
    )


class StructuredLogger:
    """Append per-stage transition blocks to a human-readable .log file.

    See IC_Load_Production_Plan.md §8 for the log format. Target path:
    artifacts/logs/pipeline_run_{entity}_{run_id}.log

    The logger is stateful on one field only — the log file handle — and
    only for the lifetime of a single PipelineContext. It is not shared
    across runs or entities.
    """

    def record(
        self,
        *,
        from_stage: str,
        to_stage: str,
        status: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Append one formatted block to the log.

        Format (see §8.2):
            [YYYY-MM-DD HH:MM:SS] STEP {NN} — {STAGE_NAME}
              status: {STATUS}
              {key}: {value}
              ...
        """
        raise NotImplementedError(
            "pipeline.hooks._primitives.StructuredLogger.record — "
            "Phase 1 scaffolding. See IC_Load_Production_Plan.md §11 Phase 5."
        )
