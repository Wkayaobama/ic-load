"""
Stage: ASSOC_VALIDATE
Hook:  run_bridge (PipelineHooks.association_runner)

What it does
------------
Executes sql/{entity}/09_association_bridge.sql via sql_file_runner. The
SQL implements the two-pass resolution pattern defined in
IC_Load_Production_Plan.md §6.1:

    Pass A — StackSync UUID preferred:
        JOIN on stacksync_record_id_* columns (high-fidelity, requires
        StackSync to have propagated post-gold).

    Pass B — legacy ID fallback:
        JOIN on icalps_{entity}_id columns when UUIDs are still NULL
        (works immediately after gold upsert, before StackSync cycles).

Association type IDs are read from GomplateRepoMix/schema_context.yaml
(NOT from this hook directly — the existing load_schema_context() loader
in context/config.py handles the read).

Upstream assumptions
--------------------
- GOLD_UPSERT → records exist in hubspot.{entity}
- STACKSYNC_SYNC → coverage logged (non-blocking; low coverage OK here
  because pass B handles the fallback)

Writes / side effects
---------------------
- INSERT into hubspot.associations_* tables.
- Transaction: single sql_file_runner invocation wraps both passes.
- Updates transition details: pass_a_inserted, pass_b_inserted, total.

Common failure modes and diagnosis
----------------------------------
- pass_a_inserted == 0 and pass_b_inserted > 0
    → Normal immediately post-gold. StackSync hasn't populated UUIDs
      yet; pass B covered everything via legacy IDs. Re-run --assoc-only
      after StackSync cycles to promote legacy-ID associations to UUIDs.

- "no association type defined for {source}→{target}"
    → The association typeId is missing from schema_context.yaml. Check
      §6.2 in the plan for the full list; if a new entity pair is
      introduced, register it in schema_context.yaml and re-run.

- Both passes insert 0 rows
    → Either (a) no records exist in hubspot.{entity} to associate from,
      (b) the SQL's WHERE clause over-filters. Inspect by running the
      SQL file directly against a dev database.

- WARNING if coverage < threshold
    → threshold defined in context.config.load_thresholds(entity). The
      SQL should report coverage; a coverage below the entity's
      association threshold transitions to WARNING, not FAILED.

Re-running
----------
Idempotent. INSERT statements use ON CONFLICT DO NOTHING or include
NOT EXISTS guards. Safe to re-invoke; safe to use as --assoc-only gate
after StackSync propagates.

Phase 1 notes
-------------
Existing pipeline.associations.AssociationBridgeExecutor already wraps
the SQL execution and reads schema_context.yaml. Phase 2 thins this hook
to a direct delegation.
"""
from __future__ import annotations

from typing import Any


def run_bridge(entity: str, dry_run: bool = False) -> dict[str, Any]:
    """Execute sql/{entity}/09_association_bridge.sql (two-pass).

    Phase 2 implementation sketch:
        1. Resolve path from MANIFEST.yaml:entities.{entity}.sql_files.association_bridge.
        2. Load schema_context.yaml (association typeIds) via context.config.
        3. Call _primitives.run_sql_file with typeIds as parameters.
        4. Return {"mode": "live", "pass_a_inserted": ..., "pass_b_inserted": ...,
           "statements": [..]}.
    """
    raise NotImplementedError(
        f"pipeline.hooks.associations.run_bridge — Phase 1 scaffolding. "
        f"Called for entity={entity!r}. "
        f"Phase 2: delegate to pipeline.associations.AssociationBridgeExecutor.execute()."
    )
