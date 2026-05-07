"""Two-phase HubSpot file uploader.

Phase 1 — `upload_phase`: POST /files/v3/files for each row, persist hs_file_id.
Phase 2 — `attach_phase`: POST /crm/v3/objects/notes (with hs_attachment_ids)
          followed by N x PUT /crm/v4/objects/note/.../associations/default/...

Why two phases:
- Phase 1 yields hs_file_ids that survive a Phase 2 failure. On retry we attach
  the already-uploaded file rather than orphaning it in HubSpot.
- Idempotency lives on our ledger keyed by legacy_id, not on HubSpot.

Retry/backoff lives here, not in HubSpotClient: the client stays a thin wrapper.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

import requests

from .client import HubSpotClient


@dataclass
class LibraryFileRow:
    legacy_id: str
    file_path: Path
    note_body: str
    # [(object_type, object_id)] e.g. [("company", "123"), ("contact", "456")]
    target_associations: list[tuple[str, str]] = field(default_factory=list)


# Status values the ledger walks through.
STATUS_PENDING = "pending"
STATUS_UPLOADED = "uploaded"
STATUS_ATTACHED = "attached"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"


def _is_retryable(exc: Exception) -> bool:
    """429 or 5xx HTTP errors, plus transport errors, are retryable."""
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else 0
        return status == 429 or 500 <= status < 600
    return isinstance(exc, (requests.ConnectionError, requests.Timeout))


def _retry_after_seconds(exc: Exception) -> float | None:
    """Honor the Retry-After header if HubSpot supplies one."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        ra = exc.response.headers.get("Retry-After")
        if ra:
            try:
                return float(ra)
            except ValueError:
                return None
    return None


class HubSpotFileUploader:
    def __init__(
        self,
        client: HubSpotClient,
        *,
        backoff_schedule: Sequence[float] = (1.0, 2.0, 4.0, 8.0, 16.0),
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self._backoff = tuple(backoff_schedule)
        self._sleep = sleep_fn

    def _retry(self, fn: Callable[[], dict]) -> dict:
        last_exc: Exception | None = None
        for attempt, delay in enumerate((0.0, *self._backoff)):
            if delay:
                self._sleep(delay)
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if not _is_retryable(exc):
                    raise
                ra = _retry_after_seconds(exc)
                if ra is not None and attempt < len(self._backoff):
                    self._sleep(min(ra, 60.0))
        assert last_exc is not None
        raise last_exc

    # -- Phase 1 -------------------------------------------------------------

    def upload_phase(self, rows: Iterable[LibraryFileRow]) -> list[dict]:
        ledger: list[dict] = []
        for row in rows:
            entry = {
                "legacy_id": row.legacy_id,
                "hs_file_id": None,
                "hs_note_id": None,
                "status": STATUS_PENDING,
                "error": None,
                "attempts": 0,
            }
            if not row.file_path.is_file():
                entry["status"] = STATUS_FAILED
                entry["error"] = "file_not_found"
                ledger.append(entry)
                continue
            try:
                resp = self._retry(lambda: self.client.upload_file(row.file_path))
                entry["hs_file_id"] = resp["id"]
                entry["status"] = STATUS_UPLOADED
            except Exception as exc:
                entry["status"] = STATUS_FAILED
                entry["error"] = f"upload_error: {exc}"
            ledger.append(entry)
        return ledger

    # -- Phase 2 -------------------------------------------------------------

    def attach_phase(
        self, rows: Iterable[LibraryFileRow], ledger: list[dict]
    ) -> list[dict]:
        by_legacy = {e["legacy_id"]: e for e in ledger}
        for row in rows:
            entry = by_legacy.get(row.legacy_id)
            if entry is None or entry["status"] != STATUS_UPLOADED:
                continue
            if not row.target_associations:
                entry["status"] = STATUS_FAILED
                entry["error"] = "no_target_associations"
                continue
            # Note creation
            try:
                note = self._retry(
                    lambda: self.client.create_note(
                        hs_note_body=row.note_body,
                        hs_attachment_ids=[entry["hs_file_id"]],
                    )
                )
                entry["hs_note_id"] = note["id"]
            except Exception as exc:
                entry["status"] = STATUS_FAILED
                entry["error"] = f"note_create_error: {exc}"
                continue
            # Associations — best-effort per target
            failed_targets: list[str] = []
            for to_type, to_id in row.target_associations:
                try:
                    self._retry(
                        lambda t=to_type, i=to_id: self.client.associate_default(
                            "note", entry["hs_note_id"], t, i
                        )
                    )
                except Exception as exc:
                    failed_targets.append(f"{to_type}:{to_id} ({exc})")
            if failed_targets:
                entry["status"] = STATUS_PARTIAL
                entry["error"] = "association_failed: " + "; ".join(failed_targets)
            else:
                entry["status"] = STATUS_ATTACHED
        return ledger

    def run(self, rows: list[LibraryFileRow]) -> list[dict]:
        return self.attach_phase(rows, self.upload_phase(rows))
