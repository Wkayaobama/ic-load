"""
Stage: GOLD_UPSERT  (GOLD_VALIDATE is inline in runner, no hook — gate only)
Hook:  upsert (PipelineHooks.gold_upserter)

What it does
------------
Executes sql/{entity}/07_gold_upsert.sql via the shared sql_file_runner
primitive. The SQL performs INSERT ... ON CONFLICT (icalps_{entity}_id)
DO UPDATE against hubspot.{entity}. Rows land in the HubSpot-mirrored
Postgres tables, from which StackSync pushes them to the HubSpot portal.

GOLD_VALIDATE gate
------------------
The preceding GOLD_VALIDATE stage is inline in the runner and is NOT a
hook — it's a simple check that the operator passed --approve-gold.
Without explicit approval, the run fails BEFORE this stage executes.

Upstream assumptions
--------------------
- DBT_TEST_MARTS → fct_{entity}_silver materialized and passing tests
- GOLD_VALIDATE → --approve-gold set by operator (human gate)

Writes / side effects
---------------------
- INSERT/UPDATE into hubspot.{entity} (Postgres).
- Transaction scope: single transaction per sql_file_runner call.
- Updates transition details: mode, statements, rows_affected.

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
    → An FK column references a record that doesn't exist in the
      parent table. Usually: contact references a company_id that
      failed to land in hubspot.companies. Fix by re-running company
      entity before contact (import order enforced by orchestrator).

Re-running
----------
Idempotent by virtue of ON CONFLICT. Safe to resume from this stage
after fixing upstream data:
    python -m pipeline.runner --entity {X} --resume-from GOLD_UPSERT

Phase 1 notes
-------------
Existing pipeline.gold.GoldUpsertExecutor already exists and wraps the
SQL execution. Phase 2 will thin this hook to a direct delegation to
sql_file_runner; GoldUpsertExecutor can be deleted or repurposed.
"""
from __future__ import annotations

from typing import Any


def upsert(entity: str, dry_run: bool = False) -> dict[str, Any]:
    """Execute sql/{entity}/07_gold_upsert.sql.

    Phase 2 implementation sketch:
        1. Resolve sql path from MANIFEST.yaml:entities.{entity}.sql_files.gold_upsert.
        2. Call _primitives.run_sql_file(sql_path, dry_run=dry_run).
        3. Return the primitive's result dict verbatim:
           {"file": ..., "statements": ..., "rows_affected": ..., "duration_s": ...}.
    """
    raise NotImplementedError(
        f"pipeline.hooks.gold.upsert — Phase 1 scaffolding. Called for entity={entity!r}. "
        f"Phase 2: resolve MANIFEST.sql_files.gold_upsert path, call sql_file_runner."
    )
