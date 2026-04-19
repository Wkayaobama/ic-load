"""
Stage: GOLD_UPSERT  (GOLD_VALIDATE is inline in runner, no hook — gate only)
Hook:  upsert (PipelineHooks.gold_upserter)

What it does
------------
Renders and executes the gold-upsert SQL for the entity. For company,
contact, opportunity, case: renders `upsert_{entity}.sql` via the Gomplate
template (sql.render.render_entity_upsert). For communication: renders
four engagement upserts (calls, tasks, notes, meetings). Each rendered
SQL is executed in a fresh Postgres transaction via _primitives.run_sql_text.

The SQL uses INSERT ... ON CONFLICT (icalps_{entity}_id) DO UPDATE so
running this hook twice against the same silver data is a no-op.

GOLD_VALIDATE gate
------------------
The preceding GOLD_VALIDATE stage is inline in the runner and NOT a hook.
It checks that the operator passed --approve-gold. Without approval, the
run fails BEFORE this stage executes.

Upstream assumptions
--------------------
- ENTITY_POSTPROCESS_PRE → silver normalised tables ready
- GOLD_VALIDATE → --approve-gold set by operator (human gate)

Writes / side effects
---------------------
- Renders SQL to SQL_RENDERED_DIR (for audit / dry-run inspection).
- INSERT/UPDATE into hubspot.{entity} (Postgres) — one fresh transaction
  per rendered statement (Contract B).
- Updates transition details: mode, statements, rows_affected per statement.

Common failure modes and diagnosis
----------------------------------
- "duplicate key value violates unique constraint ..."
    → Reconciliation key (icalps_{entity}_id) has duplicates in silver.
      Inspect staging.fct_{entity}_silver GROUP BY icalps_{entity}_id
      HAVING COUNT(*) > 1. Upstream dedupe failure — fix in silver.

- "null value in column "..." violates not-null constraint"
    → Silver emitted NULL for a required HubSpot column. Most common
      cause: an fn_map_* function returned NULL for an unmapped source
      value. Check staging.fct_{entity}_silver for the specific column;
      add the missing enum value to the seed or fn_map_* body.

- "permission denied for schema hubspot"
    → Postgres role lacks INSERT on hubspot.*. Not a pipeline bug —
      contact DBA.

- "foreign key violation"
    → An FK column references a record that doesn't exist in the parent
      table. Usually: contact references a company_id that failed to land
      in hubspot.companies. Fix by re-running company entity before
      contact (import order enforced by orchestrator).

Re-running
----------
Idempotent by virtue of ON CONFLICT. Safe to resume from this stage after
fixing upstream data:
    python -m pipeline.runner --entity {X} --resume-from GOLD_UPSERT
"""
from __future__ import annotations

from typing import Any

from pipeline.gold import GoldUpsertExecutor
from pipeline.hooks._primitives import run_sql_text


def upsert(entity: str, dry_run: bool = False) -> dict[str, Any]:
    """Render and execute the gold upsert SQL for entity.

    Fresh GoldUpsertExecutor instance per call (Contract B: no state reuse).
    For dry_run, skips execution but still renders SQL to SQL_RENDERED_DIR
    so the output can be inspected.
    """
    executor = GoldUpsertExecutor()
    if dry_run:
        return executor.execute(entity, dry_run=True)

    # run_sql_text opens, commits, and closes its own transaction per call.
    return executor.execute(entity, dry_run=False, execute_sql=run_sql_text)
