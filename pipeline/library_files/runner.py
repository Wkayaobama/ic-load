"""Standalone CLI entry point for the library_files module.

Sub-commands:
  walk    — Iterate a folder and upload+attach every non-image file to a single
            sandbox target record. No postgres lookup; the target id is supplied
            on the command line.

Unit 3 scope. Unit 4 will add a `migrate` sub-command that resolves targets via
postgres + sandbox-id override map.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .client import HubSpotClient
from .config import Settings
from .ledger import PostgresLedger
from .overrides import SandboxOverrideMap
from .sources import CsvLibraryReader, LibraryRecord, PostgresLibraryReader
from .uploader import HubSpotFileUploader, LibraryFileRow
from .walker import build_rows


# Approval gates — env vars must be explicitly set to "1" to enable each phase's
# REST writes. Default is DRY-RUN: enumerate + resolve, no POST.
APPROVE_FILES_UPLOAD_ENV = "ICALPS_APPROVE_FILES_UPLOAD"
APPROVE_FILE_NOTES_POST_ENV = "ICALPS_APPROVE_FILE_NOTES_POST"
# Rollback gate — protects the `unmigrate` subcommand. Set to "1" to actually
# delete previously-attached notes from HubSpot. Default unset = DRY-RUN that
# only enumerates what *would* be deleted.
APPROVE_UNMIGRATE_ENV = "ICALPS_APPROVE_UNMIGRATE"


def _read_approval_gates() -> tuple[bool, bool]:
    """Returns (upload_live, attach_live). Both default to False (dry-run)."""
    upload_live = os.environ.get(APPROVE_FILES_UPLOAD_ENV, "").strip() == "1"
    attach_live = os.environ.get(APPROVE_FILE_NOTES_POST_ENV, "").strip() == "1"
    return upload_live, attach_live


def _print_gate_banner(upload_live: bool, attach_live: bool, *, stream=sys.stderr) -> None:
    print("library_files runner — approval gates:", file=stream)
    print(
        f"  Phase 1 (file upload):  {'LIVE' if upload_live else 'DRY'}"
        f"   ({APPROVE_FILES_UPLOAD_ENV}={'1' if upload_live else 'unset'})",
        file=stream,
    )
    print(
        f"  Phase 2 (note + assoc): {'LIVE' if attach_live else 'DRY'}"
        f"   ({APPROVE_FILE_NOTES_POST_ENV}={'1' if attach_live else 'unset'})",
        file=stream,
    )
    if attach_live and not upload_live:
        print(
            "  WARN: Phase 2 gate is set but Phase 1 is not — Phase 2 cannot "
            "attach files that were never uploaded. Phase 2 will run but "
            "produce zero attachments unless previous live runs already wrote "
            "to the ledger.",
            file=stream,
        )
    print(file=stream)


def _records_to_rows(
    records: list[LibraryRecord],
    *,
    library_base_dir: Path,
    overrides: SandboxOverrideMap,
) -> list[LibraryFileRow]:
    rows: list[LibraryFileRow] = []
    for rec in records:
        targets = overrides.resolve(
            legacy_company_id=rec.legacy_company_id,
            legacy_contact_id=rec.legacy_contact_id,
            legacy_deal_id=rec.legacy_deal_id,
        )
        if not targets:
            # Skip rows with no resolvable sandbox target — caller can inspect
            # source records vs override map to fill gaps.
            continue
        rows.append(
            LibraryFileRow(
                legacy_id=rec.legacy_library_id,
                file_path=library_base_dir / rec.legacy_file_path / rec.legacy_file_name,
                note_body="File",
                target_associations=targets,
            )
        )
    return rows


def cmd_migrate(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    client = HubSpotClient.from_settings(settings)

    # Wire the postgres-backed idempotency ledger from Phase 5. Re-runs of the
    # same legacy_library_id skip the actual REST calls when the ledger shows
    # a prior 'uploaded' / 'attached' status. Tables are created on first use.
    ledger_obj: PostgresLedger | None = None
    if settings.prod_postgres_dsn:
        ledger_obj = PostgresLedger(settings.prod_postgres_dsn)
        ledger_obj.bootstrap()
    uploader = HubSpotFileUploader(client, ledger=ledger_obj)

    upload_live, attach_live = _read_approval_gates()
    _print_gate_banner(upload_live, attach_live)

    library_base_dir = Path(args.library_base_dir).resolve()
    overrides = SandboxOverrideMap.from_json(Path(args.overrides_json))

    if args.source == "csv":
        reader = CsvLibraryReader(Path(args.csv_path))
    else:
        if not settings.prod_postgres_dsn:
            print("PROD_POSTGRES_DSN not set", file=sys.stderr)
            return 2
        reader = PostgresLibraryReader(settings.prod_postgres_dsn, args.query)

    records = list(reader.fetch_rows())
    rows = _records_to_rows(records, library_base_dir=library_base_dir, overrides=overrides)
    if not rows:
        print("no rows resolved against override map", file=sys.stderr)
        return 1

    ledger = uploader.upload_phase(rows, live=upload_live)
    ledger = uploader.attach_phase(rows, ledger, live=attach_live)
    json.dump(ledger, sys.stdout, indent=2, default=str)
    print()
    return 1 if any(e["status"] in ("failed", "partial") for e in ledger) else 0


def cmd_walk(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    client = HubSpotClient.from_settings(settings)
    uploader = HubSpotFileUploader(client)

    upload_live, attach_live = _read_approval_gates()
    _print_gate_banner(upload_live, attach_live)

    root = Path(args.library_base_dir).resolve()
    if not root.is_dir():
        print(f"library_base_dir does not exist: {root}", file=sys.stderr)
        return 2

    targets = [(args.sandbox_target_type, args.sandbox_target_id)]
    rows = build_rows(root, target_associations=targets)
    if not rows:
        print(f"no non-image files under {root}", file=sys.stderr)
        return 1

    ledger = uploader.upload_phase(rows, live=upload_live)
    ledger = uploader.attach_phase(rows, ledger, live=attach_live)

    json.dump(ledger, sys.stdout, indent=2, default=str)
    print()
    failed = [e for e in ledger if e["status"] in ("failed", "partial")]
    return 1 if failed else 0


def cmd_unmigrate(args: argparse.Namespace) -> int:
    """Rollback subcommand — delete previously-attached library file notes.

    Uses the ledger as the rollback index: SELECTs every row in
    `staging.fct_file_notes_posted` with status='attached', then calls
    `client.delete_note(hs_note_id)` per row. On success the ledger row is
    flipped to 'unattached_via_unmigrate', so a second invocation is a no-op
    (same idempotency property as forward migrate).

    Default is DRY-RUN: enumerate what would be deleted, no API calls,
    no ledger writes. Set ICALPS_APPROVE_UNMIGRATE=1 to perform live DELETEs.
    """
    del args  # no per-command args yet
    settings = Settings.from_env()
    if not settings.prod_postgres_dsn:
        print("PROD_POSTGRES_DSN not set", file=sys.stderr)
        return 2

    ledger = PostgresLedger(settings.prod_postgres_dsn)
    ledger.bootstrap()
    client = HubSpotClient.from_settings(settings)

    live = os.environ.get(APPROVE_UNMIGRATE_ENV, "").strip() == "1"
    print(
        f"library_files runner — unmigrate gate: "
        f"{'LIVE' if live else 'DRY'} "
        f"({APPROVE_UNMIGRATE_ENV}={'1' if live else 'unset'})",
        file=sys.stderr,
    )

    rows = ledger.load_attached_rows()
    if not rows:
        print("no attached rows in ledger — nothing to unmigrate", file=sys.stderr)
        json.dump([], sys.stdout, indent=2)
        print()
        return 0

    results: list[dict] = []
    for entry in rows:
        legacy_id = entry["legacy_library_id"]
        hs_note_id = entry["hs_note_id"]
        if not live:
            results.append({
                "legacy_id": legacy_id,
                "hs_note_id": hs_note_id,
                "status": "would_unattach",
                "error": None,
            })
            continue
        try:
            client.delete_note(hs_note_id)
            status, error = "unattached_via_unmigrate", None
        except Exception as exc:
            status, error = "unattach_failed", str(exc)
        ledger.record_unattach(legacy_id, status, error)
        results.append({
            "legacy_id": legacy_id,
            "hs_note_id": hs_note_id,
            "status": status,
            "error": error,
        })

    json.dump(results, sys.stdout, indent=2)
    print()
    return 1 if any(r["status"] == "unattach_failed" for r in results) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.library_files.runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    walk = sub.add_parser("walk", help="Walk a folder and upload+attach to one target.")
    walk.add_argument("--library-base-dir", required=True)
    walk.add_argument("--sandbox-target-id", required=True)
    walk.add_argument("--sandbox-target-type", default="company")
    walk.set_defaults(func=cmd_walk)

    migrate = sub.add_parser(
        "migrate",
        help="Read source records (csv|postgres), resolve sandbox targets via "
        "override map, upload+attach.",
    )
    migrate.add_argument("--library-base-dir", required=True)
    migrate.add_argument("--overrides-json", required=True)
    migrate.add_argument("--source", choices=["csv", "postgres"], default="csv")
    migrate.add_argument("--csv-path")
    migrate.add_argument("--query", help="Override SQL for postgres source.")
    migrate.set_defaults(func=cmd_migrate)

    unmigrate = sub.add_parser(
        "unmigrate",
        help="Delete previously-attached library file notes from HubSpot, "
        "using the ledger as the rollback index. "
        "Gated by ICALPS_APPROVE_UNMIGRATE (default DRY-RUN).",
    )
    unmigrate.set_defaults(func=cmd_unmigrate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
