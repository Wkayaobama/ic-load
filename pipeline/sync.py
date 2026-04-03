from __future__ import annotations

from typing import Any, Callable

from context.config import stacksync_sync_assumed


class StackSyncCheckpoint:
    def wait(
        self,
        entity: str,
        *,
        dry_run: bool = False,
        poller: Callable[[str], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if dry_run:
            return {"entity": entity, "synced": False, "mode": "dry_run"}
        if poller is not None:
            result = poller(entity)
            result.setdefault("entity", entity)
            return result
        if stacksync_sync_assumed():
            return {"entity": entity, "synced": True, "mode": "assumed"}
        raise RuntimeError(
            "StackSync sync checkpoint is not configured. Set ICALPS_ASSUME_STACKSYNC_SYNC=1 for probe-only runs or inject a poller hook."
        )
