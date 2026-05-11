"""Standalone CLI for the cleanup pipeline.

Sub-commands:
  snapshot              — populate staging.fct_cleanup_manifest
  check-overlap         — abort if cleanup targets collide with library_files notes
  archive               — batch-archive HubSpot records (gated)
  gdpr-delete-contacts  — irreversible purge of contacts (gated separately)
  delete-properties     — drop HubSpot custom properties (gated separately)
  status                — print ledger summary

Default for every write is DRY-RUN. Three independent gates:
    ICALPS_APPROVE_ARCHIVE       — Phase E
    ICALPS_APPROVE_GDPR_DELETE   — Phase E2
    ICALPS_APPROVE_PROP_DELETE   — Phase F

All three default unset. Each is opted into separately because the
irreversibility tier escalates: archive → restorable for 90d; gdpr-delete →
permanent contact purge; property-delete → permanent schema change.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import psycopg2  # type: ignore[import-not-found]

from pipeline.library_files.client import HubSpotClient
from pipeline.library_files.config import Settings

from .archiver import archive, gdpr_delete_contacts
from .ledger import CleanupLedger
from .properties import (
    JoinKeyGuardError,
    delete_properties,
    load_manifest,
    resolve_property_list,
)
from .selection import (
    SUPPORTED_OBJECTS,
    execute_plan,
    plan_from_view,
    plan_from_where,
)


APPROVE_ARCHIVE_ENV     = "ICALPS_APPROVE_ARCHIVE"
APPROVE_GDPR_ENV        = "ICALPS_APPROVE_GDPR_DELETE"
APPROVE_PROPERTIES_ENV  = "ICALPS_APPROVE_PROP_DELETE"
TOKEN_ENV               = "HUBSPOT_PROD_TOKEN"


def _gate(env_var: str) -> bool:
    return os.environ.get(env_var, "").strip() == "1"


def _print_banner(scope: str, *, archive_live: bool, gdpr_live: bool, prop_live: bool) -> None:
    print("cleanup runner — approval gates:", file=sys.stderr)
    print(
        f"  Phase E  (batch archive):     {'LIVE' if archive_live else 'DRY'}   "
        f"({APPROVE_ARCHIVE_ENV}={'1' if archive_live else 'unset'})",
        file=sys.stderr,
    )
    print(
        f"  Phase E2 (gdpr delete):       {'LIVE' if gdpr_live else 'DRY'}   "
        f"({APPROVE_GDPR_ENV}={'1' if gdpr_live else 'unset'})",
        file=sys.stderr,
    )
    print(
        f"  Phase F  (property delete):   {'LIVE' if prop_live else 'DRY'}   "
        f"({APPROVE_PROPERTIES_ENV}={'1' if prop_live else 'unset'})",
        file=sys.stderr,
    )
    print(f"  scope: {scope}", file=sys.stderr)
    print(file=sys.stderr)


def _settings_or_die() -> Settings:
    settings = Settings.from_env(token_var=TOKEN_ENV)
    if not settings.prod_postgres_dsn:
        print("PROD_POSTGRES_DSN not set", file=sys.stderr)
        sys.exit(2)
    return settings


# -- snapshot ----------------------------------------------------------------

def cmd_snapshot(args: argparse.Namespace) -> int:
    settings = _settings_or_die()
    ledger = CleanupLedger(settings.prod_postgres_dsn)
    ledger.bootstrap()

    if args.source_view:
        plan = plan_from_view(args.object, args.source_view)
    else:
        plan = plan_from_where(args.object, args.where)

    print(f"snapshot plan: {plan.description}", file=sys.stderr)
    n = ledger.upsert_manifest_rows(execute_plan(settings.prod_postgres_dsn, plan))
    print(f"snapshot: {n} rows upserted into staging.fct_cleanup_manifest "
          f"({plan.object_type})", file=sys.stderr)
    return 0


# -- overlap check -----------------------------------------------------------

def cmd_check_overlap(args: argparse.Namespace) -> int:
    settings = _settings_or_die()

    sql = """
        SELECT m.object_type, COUNT(*) AS overlap
        FROM staging.fct_cleanup_manifest m
        JOIN staging.fct_file_notes_posted n
          ON n.legacy_library_id IS NOT NULL
         AND n.status = 'attached'
         AND (
              (m.object_type = 'companies' AND m.legacy_id IN (
                  SELECT legacy_company_id::text FROM staging.fct_library_files
                  WHERE legacy_library_id = n.legacy_library_id))
           OR (m.object_type = 'contacts'  AND m.legacy_id IN (
                  SELECT legacy_contact_id::text FROM staging.fct_library_files
                  WHERE legacy_library_id = n.legacy_library_id))
           OR (m.object_type = 'deals'     AND m.legacy_id IN (
                  SELECT legacy_deal_id::text FROM staging.fct_library_files
                  WHERE legacy_library_id = n.legacy_library_id))
         )
        GROUP BY m.object_type
        ORDER BY m.object_type;
    """
    with psycopg2.connect(settings.prod_postgres_dsn) as conn, conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    if not rows:
        print("overlap check: 0 rows in cleanup manifest also have an attached "
              "library Note. Safe to proceed.", file=sys.stderr)
        return 0

    print("overlap check: cleanup targets COLLIDE with library_files notes:", file=sys.stderr)
    for object_type, overlap in rows:
        print(f"  {object_type}: {overlap}", file=sys.stderr)
    if args.allow_overlap:
        print("--allow-overlap supplied — continuing despite collision.", file=sys.stderr)
        return 0
    print("Re-run with --allow-overlap if this is intentional, or narrow the "
          "snapshot predicate.", file=sys.stderr)
    return 1


# -- archive ----------------------------------------------------------------

def cmd_archive(args: argparse.Namespace) -> int:
    settings = _settings_or_die()
    archive_live = _gate(APPROVE_ARCHIVE_ENV)
    _print_banner(
        scope=f"archive {args.object}",
        archive_live=archive_live,
        gdpr_live=_gate(APPROVE_GDPR_ENV),
        prop_live=_gate(APPROVE_PROPERTIES_ENV),
    )

    client = HubSpotClient.from_settings(settings)
    ledger = CleanupLedger(settings.prod_postgres_dsn)
    ledger.bootstrap()

    summary = archive(
        client=client, ledger=ledger,
        object_type=args.object, live=archive_live,
        sleep_between_batches_s=args.sleep,
    )
    json.dump(summary, sys.stdout, indent=2)
    print()
    return 1 if summary["failed"] else 0


# -- gdpr-delete-contacts ---------------------------------------------------

def cmd_gdpr(args: argparse.Namespace) -> int:
    settings = _settings_or_die()
    gdpr_live = _gate(APPROVE_GDPR_ENV)
    _print_banner(
        scope="gdpr-delete-contacts",
        archive_live=_gate(APPROVE_ARCHIVE_ENV),
        gdpr_live=gdpr_live,
        prop_live=_gate(APPROVE_PROPERTIES_ENV),
    )

    client = HubSpotClient.from_settings(settings)
    ledger = CleanupLedger(settings.prod_postgres_dsn)
    ledger.bootstrap()

    summary = gdpr_delete_contacts(
        client=client, ledger=ledger, live=gdpr_live,
        sleep_between_calls_s=args.sleep,
    )
    json.dump(summary, sys.stdout, indent=2)
    print()
    return 1 if summary["failed"] else 0


# -- delete-properties ------------------------------------------------------

def cmd_delete_properties(args: argparse.Namespace) -> int:
    settings = _settings_or_die()
    prop_live = _gate(APPROVE_PROPERTIES_ENV)
    _print_banner(
        scope=f"delete-properties {args.object}",
        archive_live=_gate(APPROVE_ARCHIVE_ENV),
        gdpr_live=_gate(APPROVE_GDPR_ENV),
        prop_live=prop_live,
    )

    client = HubSpotClient.from_settings(settings)
    ledger = CleanupLedger(settings.prod_postgres_dsn)
    ledger.bootstrap()

    manifest = load_manifest()
    try:
        property_list = resolve_property_list(
            manifest,
            object_type=args.object,
            include_join_keys=args.include_join_keys,
            library_migration_complete=args.library_migration_complete,
        )
    except JoinKeyGuardError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    print(f"property list ({len(property_list)} names): {property_list}", file=sys.stderr)

    summary = delete_properties(
        client=client, ledger=ledger,
        object_type=args.object, properties=property_list,
        live=prop_live,
    )
    json.dump(summary, sys.stdout, indent=2)
    print()
    return 1 if summary["failed"] else 0


# -- status -----------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    settings = _settings_or_die()
    ledger = CleanupLedger(settings.prod_postgres_dsn)
    summary = ledger.status_summary()
    json.dump(summary, sys.stdout, indent=2)
    print()
    return 0


# -- argparse plumbing ------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline.cleanup.runner")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_snap = sub.add_parser("snapshot", help="Populate staging.fct_cleanup_manifest.")
    p_snap.add_argument("--object", required=True, choices=SUPPORTED_OBJECTS)
    src = p_snap.add_mutually_exclusive_group()
    src.add_argument("--where", help="SQL predicate against hubspot.{object}.")
    src.add_argument("--source-view", help="Fully qualified view name (e.g. staging.fct_cleanup_companies).")
    p_snap.set_defaults(func=cmd_snapshot)

    p_overlap = sub.add_parser(
        "check-overlap",
        help="Fail if cleanup manifest overlaps library_files attached notes.",
    )
    p_overlap.add_argument("--allow-overlap", action="store_true")
    p_overlap.set_defaults(func=cmd_check_overlap)

    p_arch = sub.add_parser("archive", help="Batch-archive manifest rows (gated).")
    p_arch.add_argument("--object", required=True, choices=SUPPORTED_OBJECTS)
    p_arch.add_argument("--sleep", type=float, default=1.0,
                        help="Seconds between batches (default 1.0).")
    p_arch.set_defaults(func=cmd_archive)

    p_gdpr = sub.add_parser(
        "gdpr-delete-contacts",
        help="Irreversibly purge contacts already at archive status='archived' (gated).",
    )
    p_gdpr.add_argument("--sleep", type=float, default=0.2,
                        help="Seconds between calls (default 0.2).")
    p_gdpr.set_defaults(func=cmd_gdpr)

    p_props = sub.add_parser(
        "delete-properties",
        help="Delete HubSpot custom properties for object (gated).",
    )
    p_props.add_argument("--object", required=True, choices=SUPPORTED_OBJECTS)
    p_props.add_argument(
        "--include-join-keys", action="store_true",
        help="Also delete the icalps_*_id join keys. Requires --library-migration-complete.",
    )
    p_props.add_argument(
        "--library-migration-complete", action="store_true",
        help="Operator assertion that staging.fct_file_notes_posted is fully attached.",
    )
    p_props.set_defaults(func=cmd_delete_properties)

    p_status = sub.add_parser("status", help="Print ledger summary.")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
