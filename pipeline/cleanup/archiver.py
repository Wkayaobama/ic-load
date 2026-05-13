"""Phase E (batch archive) and Phase E2 (GDPR-delete contacts) orchestration.

Reads target ids from staging.fct_cleanup_manifest, batches into 100-id
chunks, calls HubSpot, records per-id outcomes. Idempotent: re-runs skip ids
already at status='archived' / status='purged'.
"""
from __future__ import annotations

import time
from typing import Iterable, Iterator

import requests

from pipeline.library_files.client import HubSpotClient

from .ledger import CleanupLedger


HUBSPOT_BATCH_LIMIT = 100  # HubSpot's documented cap on batch/archive inputs


def _chunk(ids: list[str], n: int) -> Iterator[list[str]]:
    for i in range(0, len(ids), n):
        yield ids[i : i + n]


def archive(
    *,
    client: HubSpotClient,
    ledger: CleanupLedger,
    object_type: str,
    live: bool,
    sleep_between_batches_s: float = 1.0,
) -> dict:
    """Archive every manifest row for ``object_type`` not already archived.

    Returns a summary dict for stdout/JSON dump:
        {object_type, attempted, batches, dry_run, succeeded, failed}
    """
    manifest = ledger.manifest_ids(object_type)
    skip = ledger.archive_skip_set(object_type)
    exempt = ledger.exemption_set(object_type)

    pending: list[str] = []
    excluded_now: list[str] = []
    for hid, _legacy, _label in manifest:
        if hid in skip:
            continue
        if hid in exempt:
            excluded_now.append(hid)
            continue
        pending.append(hid)

    # Audit trail: record an 'excluded' row per blocked id so status_summary
    # reports it. Idempotent on re-run (UPSERT on PK).
    for hid in excluded_now:
        ledger.record_archive(
            object_type=object_type, hubspot_id=hid,
            status="excluded", error="in_fct_cleanup_exemptions",
        )

    summary = {
        "object_type":      object_type,
        "live":             live,
        "manifest":         len(manifest),
        "already_archived": len(skip),
        "excluded":         len(excluded_now),
        "attempted":        len(pending),
        "batches":          0,
        "succeeded":        0,
        "failed":           0,
    }

    for batch in _chunk(pending, HUBSPOT_BATCH_LIMIT):
        summary["batches"] += 1
        if not live:
            for hid in batch:
                ledger.record_archive(object_type=object_type, hubspot_id=hid, status="dry_run")
                summary["succeeded"] += 1
            continue
        try:
            client.batch_archive_objects(object_type, batch)
        except requests.HTTPError as exc:
            err = f"{exc.response.status_code} {exc.response.text[:300]}"
            for hid in batch:
                ledger.record_archive(object_type=object_type, hubspot_id=hid, status="failed", error=err)
                summary["failed"] += 1
            # don't raise — operator can re-run after triage
            continue
        for hid in batch:
            ledger.record_archive(object_type=object_type, hubspot_id=hid, status="archived")
            summary["succeeded"] += 1
        if sleep_between_batches_s > 0:
            time.sleep(sleep_between_batches_s)

    return summary


def gdpr_delete_contacts(
    *,
    client: HubSpotClient,
    ledger: CleanupLedger,
    live: bool,
    sleep_between_calls_s: float = 0.2,
) -> dict:
    """Permanently purge contacts already at archive status='archived'.

    HubSpot does not expose a batch endpoint for GDPR-delete; one POST per
    contact. Slow but irreversible — operator opts in via gate.
    """
    archived_contacts = ledger.archive_skip_set("contacts")
    already_purged    = ledger.gdpr_skip_set("contacts")
    exempt            = ledger.exemption_set("contacts")
    pending = sorted(archived_contacts - already_purged - exempt)

    summary = {
        "object_type":     "contacts",
        "live":            live,
        "eligible":        len(archived_contacts),
        "already_purged":  len(already_purged),
        "excluded":        len(archived_contacts & exempt),
        "attempted":       len(pending),
        "succeeded":       0,
        "failed":          0,
    }

    for hid in pending:
        if not live:
            ledger.record_gdpr(object_type="contacts", hubspot_id=hid, status="dry_run")
            summary["succeeded"] += 1
            continue
        try:
            client.gdpr_delete_contact(contact_id=hid)
        except requests.HTTPError as exc:
            err = f"{exc.response.status_code} {exc.response.text[:300]}"
            ledger.record_gdpr(object_type="contacts", hubspot_id=hid, status="failed", error=err)
            summary["failed"] += 1
            continue
        ledger.record_gdpr(object_type="contacts", hubspot_id=hid, status="purged")
        summary["succeeded"] += 1
        if sleep_between_calls_s > 0:
            time.sleep(sleep_between_calls_s)

    return summary
