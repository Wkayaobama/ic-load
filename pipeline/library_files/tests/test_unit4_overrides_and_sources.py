"""Unit 4 — postgres-shaped source reader + sandbox override map.

Three offline tests cover the override map (resolve/persist) and the CSV reader.
One live sandbox test seeds a company, writes a tiny override map keyed by a
synthetic legacy_company_id, runs source → override → uploader, and asserts the
GET-back invariants against the seeded company.

PostgresLibraryReader is not exercised here — it's the prod-pilot path and gets
its first run only when the user explicitly invokes `runner migrate --source
postgres` against PROD_POSTGRES_DSN. Unit 4 stops at the abstraction.

Uses tempfile.TemporaryDirectory directly because pytest's tmp_path fixture
hits a per-account permission issue on this Windows machine.
"""
from __future__ import annotations

import csv
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from pipeline.library_files.client import HubSpotClient
from pipeline.library_files.config import Settings
from pipeline.library_files.overrides import SandboxOverrideMap
from pipeline.library_files.runner import _records_to_rows
from pipeline.library_files.sources import CsvLibraryReader
from pipeline.library_files.uploader import (
    HubSpotFileUploader,
    STATUS_ATTACHED,
)

FIXTURES = Path(__file__).parent / "fixtures" / "library_root"


@contextmanager
def _temp_dir():
    with tempfile.TemporaryDirectory(prefix="libfiles_unit4_") as d:
        yield Path(d)


# -- Offline override map ----------------------------------------------------


def test_override_map_resolves_only_supplied_legacy_ids():
    om = SandboxOverrideMap()
    om.set("LEG_COMP_1", "company", "SBX_COMP_1")
    om.set("LEG_CONT_1", "contact", "SBX_CONT_1")

    targets = om.resolve(
        legacy_company_id="LEG_COMP_1",
        legacy_contact_id="LEG_CONT_1",
        legacy_deal_id="LEG_DEAL_NOT_MAPPED",
    )
    assert ("company", "SBX_COMP_1") in targets
    assert ("contact", "SBX_CONT_1") in targets
    assert all(t[0] != "deal" for t in targets), "unmapped deal must be dropped"


def test_override_map_round_trip_through_json():
    with _temp_dir() as tmp:
        om = SandboxOverrideMap()
        om.set("LEG_1", "company", "SBX_1")
        p = tmp / "overrides.json"
        om.to_json(p)

        om2 = SandboxOverrideMap.from_json(p)
        assert om2.resolve(legacy_company_id="LEG_1") == [("company", "SBX_1")]


# -- Offline CSV reader ------------------------------------------------------


def test_csv_reader_yields_records_with_optional_legacy_keys():
    with _temp_dir() as tmp:
        p = tmp / "src.csv"
        with p.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.writer(fp)
            writer.writerow([
                "legacy_library_id", "legacy_file_name", "legacy_file_path",
                "legacy_company_id", "legacy_contact_id", "legacy_deal_id",
            ])
            writer.writerow(["L1", "sample_invoice.txt", "", "C1", "", ""])
            writer.writerow(["L2", "sample_quote.txt", "sub", "", "P1", ""])

        rows = list(CsvLibraryReader(p).fetch_rows())
        assert len(rows) == 2
        assert rows[0].legacy_company_id == "C1"
        assert rows[0].legacy_contact_id is None
        assert rows[1].legacy_contact_id == "P1"
        assert rows[1].legacy_file_path == "sub"


# -- Live sandbox: csv source + override map → upload+attach -----------------


@pytest.mark.live_sandbox
def test_migrate_csv_source_with_override_map_against_sandbox():
    if not os.environ.get("HUBSPOT_SANDBOX_TOKEN"):
        pytest.skip("HUBSPOT_SANDBOX_TOKEN not set; live sandbox test skipped")

    client = HubSpotClient.from_settings(Settings.from_env())
    uploader = HubSpotFileUploader(client)

    cleanups: list = []
    with _temp_dir() as tmp:
        try:
            company = client.create_company(name="__icalps_libfile_unit4__")
            sandbox_company_id = company["id"]
            cleanups.append(lambda: client.delete_company(sandbox_company_id))

            csv_path = tmp / "src.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as fp:
                w = csv.writer(fp)
                w.writerow([
                    "legacy_library_id", "legacy_file_name", "legacy_file_path",
                    "legacy_company_id", "legacy_contact_id", "legacy_deal_id",
                ])
                w.writerow(["LIB1", "sample_invoice.txt", "",    "LEG_COMP_X", "", ""])
                w.writerow(["LIB2", "sample_quote.txt",   "sub", "LEG_COMP_X", "", ""])

            overrides = SandboxOverrideMap()
            overrides.set("LEG_COMP_X", "company", sandbox_company_id)

            records = list(CsvLibraryReader(csv_path).fetch_rows())
            rows = _records_to_rows(
                records, library_base_dir=FIXTURES, overrides=overrides
            )
            assert len(rows) == 2

            ledger = uploader.upload_phase(rows)
            for entry in ledger:
                if entry["hs_file_id"]:
                    cleanups.append(lambda f=entry["hs_file_id"]: client.delete_file(f))

            ledger = uploader.attach_phase(rows, ledger)
            for entry in ledger:
                if entry["hs_note_id"]:
                    cleanups.append(lambda n=entry["hs_note_id"]: client.delete_note(n))

            assert all(e["status"] == STATUS_ATTACHED for e in ledger), ledger

            for entry in ledger:
                fetched = client.get_note(
                    entry["hs_note_id"],
                    associations=["companies"],
                    properties=["hs_attachment_ids"],
                )
                assert str(entry["hs_file_id"]) in str(
                    fetched["properties"]["hs_attachment_ids"]
                )
                assoc_ids = {
                    str(a["id"])
                    for a in fetched.get("associations", {})
                    .get("companies", {})
                    .get("results", [])
                }
                assert str(sandbox_company_id) in assoc_ids
        finally:
            for fn in reversed(cleanups):
                try:
                    fn()
                except Exception:
                    pass
