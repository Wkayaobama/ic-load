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
from .uploader import HubSpotFileUploader
from .walker import build_rows


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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
