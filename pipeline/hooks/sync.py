"""
Stage: STACKSYNC_SYNC
Hook:  wait_for_sync (PipelineHooks.sync_waiter)

What it does
------------
Logs StackSync sync status but does NOT block the pipeline. StackSync is
a third-party bidirectional sync middleware between Postgres and HubSpot;
its propagation takes minutes and cannot be reliably awaited from the
pipeline. Instead, this hook:
    1. Measures current UUID coverage (% of hubspot.{entity} rows with
       stacksync_record_id_* populated).
    2. Writes the measurement to artifacts/stacksync_sync_log.md.
    3. Always returns SUCCESS (or SUCCESS with a low-coverage WARNING
       annotation). The downstream ASSOC_VALIDATE stage uses two-pass
       resolution to work around low initial UUID coverage.

This is the non-blocking contract referenced in IC_Load_Production_Plan.md
§6.4 and §12.

Upstream assumptions
--------------------
- GOLD_UPSERT → rows written to hubspot.{entity}

Writes / side effects
---------------------
- Reads: hubspot.{entity} to compute UUID coverage.
- Writes: artifacts/stacksync_sync_log.md (cumulative across runs).
- Never fails — reports status only.

Common failure modes and diagnosis
----------------------------------
This hook is intentionally failure-resilient. If the status query fails,
it returns {"mode": "error", "note": str(exc)} and the stage transitions
to WARNING — but the run continues.

If you see uuid_coverage=0.0% right after GOLD_UPSERT:
    → Expected. StackSync hasn't cycled yet. The ASSOC_VALIDATE stage
      will fall back to legacy-ID resolution (pass B of the two-pass
      pattern). Re-run --assoc-only later to pick up UUIDs.

If uuid_coverage stays < 50% for hours across runs:
    → StackSync job is stalled or misconfigured. Check the StackSync
      dashboard directly (outside this pipeline).

Re-running
----------
Idempotent. Each invocation appends a new row to the cumulative log;
the log is an audit trail, not pipeline state.

Phase 1 notes
-------------
Existing pipeline.sync.StackSyncCheckpoint already implements the wait()
method returning the coverage dict. Phase 2 delegates to it.
"""
from __future__ import annotations

from typing import Any


def wait_for_sync(entity: str, dry_run: bool = False) -> dict[str, Any]:
    """Check StackSync UUID coverage and append to cumulative log.

    Phase 2 implementation sketch:
        1. If dry_run: return {"mode": "dry_run", "synced": True}.
        2. Query hubspot.{entity} for COUNT(*) and
           COUNT(stacksync_record_id_*) to compute coverage.
        3. Append a line to artifacts/stacksync_sync_log.md.
        4. Return {"mode": "live", "synced": True, "uuid_coverage": pct}.
    """
    raise NotImplementedError(
        f"pipeline.hooks.sync.wait_for_sync — Phase 1 scaffolding. "
        f"Called for entity={entity!r}. "
        f"Phase 2: delegate to pipeline.sync.StackSyncCheckpoint.wait()."
    )
