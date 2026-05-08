"""Phase F: HubSpot custom-property deletion.

Reads ``properties_manifest.json`` (committed, reviewable). Loops the names
for the requested object_type, calls ``DELETE /crm/v3/properties/{type}/{name}``
once per property, records per-property outcome.

The three join keys for the library_files mart are held back in
``join_keys_held_back`` and require explicit operator opt-in to delete.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

from pipeline.library_files.client import HubSpotClient

from .ledger import CleanupLedger


_MANIFEST_PATH = Path(__file__).parent / "properties_manifest.json"


class JoinKeyGuardError(RuntimeError):
    """Raised when an operator tries to delete the library_files join keys
    without explicitly opting in to BOTH safety flags."""


def load_manifest(path: Path = _MANIFEST_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_property_list(
    manifest: dict,
    *,
    object_type: str,
    include_join_keys: bool,
    library_migration_complete: bool,
) -> list[str]:
    """Combine the standard list with the optional join-key list.

    Refuses to surface the join keys unless the operator passes BOTH
    --include-join-keys AND --library-migration-complete on the runner.
    """
    base = list(manifest.get(object_type, []))
    held = manifest.get("join_keys_held_back", {}).get(object_type, [])

    if not include_join_keys:
        return base

    if not library_migration_complete:
        raise JoinKeyGuardError(
            f"--include-join-keys was passed but --library-migration-complete "
            f"was not. Refusing to delete {held!r} because they are the join "
            f"keys for staging.fct_library_files. Verify that the library "
            f"files migration is at status='attached' for every row, then "
            f"pass --library-migration-complete explicitly."
        )

    return base + list(held)


def delete_properties(
    *,
    client: HubSpotClient,
    ledger: CleanupLedger,
    object_type: str,
    properties: list[str],
    live: bool,
) -> dict:
    skip = ledger.property_skip_set(object_type)
    pending = [name for name in properties if name not in skip]

    summary = {
        "object_type": object_type,
        "live":        live,
        "manifest":    len(properties),
        "already_done": len(skip),
        "attempted":   len(pending),
        "deleted":     0,
        "already_absent": 0,
        "failed":      0,
    }

    for name in pending:
        if not live:
            ledger.record_property(object_type=object_type, property_name=name, status="dry_run")
            summary["attempted"] = summary["attempted"]  # unchanged
            continue
        try:
            http_status = client.delete_property(object_type, name)
        except requests.HTTPError as exc:
            err = f"{exc.response.status_code} {exc.response.text[:300]}"
            ledger.record_property(
                object_type=object_type,
                property_name=name,
                status="failed",
                http_status=exc.response.status_code,
                error=err,
            )
            summary["failed"] += 1
            continue

        if http_status == 204:
            ledger.record_property(
                object_type=object_type, property_name=name,
                status="deleted", http_status=204,
            )
            summary["deleted"] += 1
        elif http_status == 404:
            ledger.record_property(
                object_type=object_type, property_name=name,
                status="already_absent", http_status=404,
            )
            summary["already_absent"] += 1
        else:
            ledger.record_property(
                object_type=object_type, property_name=name,
                status="failed", http_status=http_status,
                error=f"unexpected status {http_status}",
            )
            summary["failed"] += 1

    return summary
