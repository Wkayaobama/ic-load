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
import sys
from pathlib import Path

from .client import HubSpotClient
from .config import Settings
from .overrides import SandboxOverrideMap
from .sources import CsvLibraryReader, LibraryRecord, PostgresLibraryReader
from .uploader import HubSpotFileUploader, LibraryFileRow
from .walker import build_rows


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
                note_body=f"Legacy migrated file: {rec.legacy_file_name}",
                target_associations=targets,
            )
        )
    return rows


def cmd_migrate(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    client = HubSpotClient.from_settings(settings)
    uploader = HubSpotFileUploader(client)

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

    ledger = uploader.upload_phase(rows)
    ledger = uploader.attach_phase(rows, ledger)
    json.dump(ledger, sys.stdout, indent=2, default=str)
    print()
    return 1 if any(e["status"] in ("failed", "partial") for e in ledger) else 0


def cmd_walk(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    client = HubSpotClient.from_settings(settings)
    uploader = HubSpotFileUploader(client)

    root = Path(args.library_base_dir).resolve()
    if not root.is_dir():
        print(f"library_base_dir does not exist: {root}", file=sys.stderr)
        return 2

    targets = [(args.sandbox_target_type, args.sandbox_target_id)]
    rows = build_rows(root, target_associations=targets)
    if not rows:
        print(f"no non-image files under {root}", file=sys.stderr)
        return 1

    ledger = uploader.upload_phase(rows)
    ledger = uploader.attach_phase(rows, ledger)

    json.dump(ledger, sys.stdout, indent=2, default=str)
    print()
    failed = [e for e in ledger if e["status"] in ("failed", "partial")]
    return 1 if failed else 0


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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
