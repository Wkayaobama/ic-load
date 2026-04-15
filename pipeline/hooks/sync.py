"""
Stage: STACKSYNC_SYNC
Hook:  wait_for_sync (PipelineHooks.sync_waiter)

What it does
------------
Logs StackSync sync status but does NOT block the pipeline. StackSync is
a third-party bidirectional sync middleware between Postgres and HubSpot;
its propagation takes minutes and cannot be reliably awaited from the
pipeline.

This hook delegates to `pipeline.sync.StackSyncCheckpoint.wait()` which:
  - Returns {"mode": "dry_run", "synced": False} for dry_run invocations.
  - Returns {"mode": "assumed", "synced": True} when
    ICALPS_ASSUME_STACKSYNC_SYNC=1 is set (probe-only runs).
  - Raises RuntimeError if neither is configured and no poller is injected.

The non-blocking contract is implemented in the runner's _run_stacksync_sync
(not here) — this hook returns status; the runner decides to transition
SUCCESS even when synced=False.

Upstream assumptions
--------------------
- GOLD_UPSERT → rows written to hubspot.{entity}

Writes / side effects
---------------------
- Reads: env variables ICALPS_ASSUME_STACKSYNC_SYNC or injected poller.
- Does NOT query Postgres itself (that's the poller's job if injected).
- Appends entry to artifacts/stacksync_sync_log.md (via runner log block).

Common failure modes and diagnosis
----------------------------------
- "StackSync sync checkpoint is not configured"
    → Neither dry_run, ICALPS_ASSUME_STACKSYNC_SYNC, nor an injected
      poller is set. For probe-only runs: export ICALPS_ASSUME_STACKSYNC_SYNC=1.
      For production runs: inject a poller hook that queries hubspot.{entity}
      for stacksync_record_id_* coverage.

- uuid_coverage stays low across multiple runs
    → StackSync job is stalled or misconfigured. Check the StackSync
      dashboard directly (outside this pipeline). ASSOC_VALIDATE will use
      legacy-ID fallback (pass B) in the meantime.

Re-running
----------
Idempotent. The hook itself is read-only; log appends are audit trail.
"""
from __future__ import annotations

from typing import Any

from pipeline.sync import StackSyncCheckpoint


def wait_for_sync(entity: str, dry_run: bool = False) -> dict[str, Any]:
    """Check StackSync sync status for entity.

    Fresh checkpoint per call (Contract B — no state reuse across entities).
    """
    checkpoint = StackSyncCheckpoint()
    return checkpoint.wait(entity, dry_run=dry_run)
