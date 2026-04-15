"""
Stage: ASSOC_VALIDATE
Hook:  run_bridge (PipelineHooks.association_runner)

What it does
------------
Renders and executes association-bridge SQL via the existing
`pipeline.associations.AssociationBridgeExecutor`. The executor reads
GomplateRepoMix/schema_context.yaml to discover supported patterns
(comm_type × target pairs), renders the two-pass resolution SQL via
`sql.render.render_association_bridge`, writes each rendered .sql to
SQL_RENDERED_DIR, then executes via the injected `execute_sql` callable.

Two-pass resolution (§6.1)
--------------------------
    Pass A — StackSync UUID preferred:
        JOIN on stacksync_record_id_* columns (high-fidelity, requires
        StackSync to have propagated post-gold).

    Pass B — legacy ID fallback:
        JOIN on icalps_{entity}_id columns when UUIDs are still NULL
        (works immediately after gold upsert, before StackSync cycles).

Current scope: communication only
---------------------------------
The existing AssociationBridgeExecutor returns `mode="not_applicable"`
for non-communication entities. Phase 3 of the migration plan extends
coverage to company/contact/opportunity/case bridges.

Upstream assumptions
--------------------
- GOLD_UPSERT → records exist in hubspot.{entity}
- STACKSYNC_SYNC → coverage logged (non-blocking; low coverage is OK
  because pass B handles the fallback)

Writes / side effects
---------------------
- Reads: GomplateRepoMix/schema_context.yaml.
- Writes: rendered SQL files to SQL_RENDERED_DIR (for audit).
- INSERT into hubspot.associations_* tables — one fresh transaction
  per rendered statement (Contract B, via run_sql_text).
- Updates transition details: mode, statements list.

Common failure modes and diagnosis
----------------------------------
- "no association type defined for {source}→{target}"
    → typeId missing from schema_context.yaml. Check §6.2 in the plan
      for the full list. If a new entity pair is introduced, register
      it in schema_context.yaml and re-run.

- Both passes insert 0 rows
    → Either (a) no records exist in hubspot.{entity} to associate from,
      (b) the SQL's WHERE clause over-filters. Inspect by running the
      rendered .sql file from SQL_RENDERED_DIR directly against a dev db.

- WARNING mode="not_applicable"
    → Current implementation only handles communication. Expected for
      company / contact / opportunity / case until Phase 3.

Re-running
----------
Idempotent. The rendered SQL uses ON CONFLICT DO NOTHING / NOT EXISTS
guards. Safe to re-invoke; safe to use as --assoc-only gate after
StackSync propagates.
"""
from __future__ import annotations

from typing import Any

from pipeline.associations import AssociationBridgeExecutor
from pipeline.hooks._primitives import run_sql_text


def run_bridge(entity: str, dry_run: bool = False) -> dict[str, Any]:
    """Render and execute association bridge SQL for entity.

    Fresh executor instance per call (Contract B).
    """
    executor = AssociationBridgeExecutor()
    if dry_run:
        return executor.execute(entity, dry_run=True)

    return executor.execute(entity, dry_run=False, execute_sql=run_sql_text)
