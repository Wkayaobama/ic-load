"""Unit 5 — postgres-backed idempotency ledger.

Three offline tests cover crash-recovery semantics through a FakeLedger that
mimics the LedgerLike interface in memory:
  - Phase 1 + Phase 2 first pass: ledger captures upload + attach
  - Run twice with the same FakeLedger: second pass issues zero REST calls

One live sandbox test gated by LEDGER_TEST_DSN runs the full chain twice
against a real postgres + sandbox; second run must be a no-op.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Mapping

import pytest
import requests
import requests_mock as rm_module

from pipeline.library_files.client import HubSpotClient
from pipeline.library_files.config import Settings
from pipeline.library_files.ledger import PostgresLedger
from pipeline.library_files.uploader import (
    HubSpotFileUploader,
    LibraryFileRow,
    STATUS_ATTACHED,
    STATUS_UPLOADED,
)

FIXTURES = Path(__file__).parent / "fixtures" / "library_root"


# -- FakeLedger for offline tests --------------------------------------------


class FakeLedger:
    """In-memory implementation of LedgerLike."""

    def __init__(self) -> None:
        self.uploads: dict[str, dict] = {}
        self.attaches: dict[str, dict] = {}

    def upload_skip_set(self) -> set[str]:
        return {k for k, v in self.uploads.items() if v["status"] == "uploaded"}

    def attach_skip_set(self) -> set[str]:
        return {k for k, v in self.attaches.items() if v["status"] == "attached"}

    def load_existing(self, legacy_ids: Iterable[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for lid in legacy_ids:
            entry: dict = {"legacy_id": lid}
            if lid in self.uploads:
                entry["hs_file_id"] = self.uploads[lid].get("hs_file_id")
                entry["upload_status"] = self.uploads[lid]["status"]
            if lid in self.attaches:
                entry["hs_note_id"] = self.attaches[lid].get("hs_note_id")
                entry["attach_status"] = self.attaches[lid]["status"]
            out[lid] = entry
        return out

    def record_upload(self, entry: Mapping[str, object]) -> None:
        self.uploads[str(entry["legacy_id"])] = dict(entry)

    def record_attach(self, entry: Mapping[str, object]) -> None:
        self.attaches[str(entry["legacy_id"])] = dict(entry)


# -- Offline: ledger captures first pass ------------------------------------


def test_first_pass_records_upload_and_attach():
    s = requests.Session()
    client = HubSpotClient(token="dummy", session=s)
    fake = FakeLedger()
    uploader = HubSpotFileUploader(
        client, backoff_schedule=(), sleep_fn=lambda _: None, ledger=fake
    )

    with rm_module.Mocker(session=s) as m:
        m.post(
            "https://api.hubapi.com/files/v3/files",
            json={"id": "file-1"},
        )
        m.post(
            "https://api.hubapi.com/crm/v3/objects/notes",
            json={"id": "note-1"},
        )
        m.put(
            "https://api.hubapi.com/crm/v4/objects/note/note-1/associations/default/company/comp-1",
            json={},
        )
        rows = [LibraryFileRow(
            legacy_id="L1",
            file_path=FIXTURES / "sample_invoice.txt",
            note_body="x",
            target_associations=[("company", "comp-1")],
        )]
        ledger = uploader.upload_phase(rows)
        ledger = uploader.attach_phase(rows, ledger)

    assert ledger[0]["status"] == STATUS_ATTACHED
    assert fake.uploads["L1"]["status"] == "uploaded"
    assert fake.uploads["L1"]["hs_file_id"] == "file-1"
    assert fake.attaches["L1"]["status"] == "attached"
    assert fake.attaches["L1"]["hs_note_id"] == "note-1"


# -- Offline: second pass is a true no-op ------------------------------------


def test_second_pass_with_same_ledger_issues_zero_rest_calls():
    """After a successful first pass, re-running with the same ledger must
    not POST or PUT to HubSpot. The skip-set logic should short-circuit."""
    s = requests.Session()
    client = HubSpotClient(token="dummy", session=s)

    fake = FakeLedger()
    fake.uploads["L1"] = {
        "legacy_id": "L1", "hs_file_id": "file-1",
        "status": "uploaded", "error": None, "attempts": 1,
    }
    fake.attaches["L1"] = {
        "legacy_id": "L1", "hs_note_id": "note-1",
        "status": "attached", "error": None, "attempts": 1,
    }

    uploader = HubSpotFileUploader(
        client, backoff_schedule=(), sleep_fn=lambda _: None, ledger=fake
    )
    rows = [LibraryFileRow(
        legacy_id="L1",
        file_path=FIXTURES / "sample_invoice.txt",
        note_body="x",
        target_associations=[("company", "comp-1")],
    )]

    with rm_module.Mocker(session=s) as m:
        # Register handlers that fail loudly if hit.
        m.post(
            "https://api.hubapi.com/files/v3/files",
            exc=AssertionError("upload should not be called on second pass"),
        )
        m.post(
            "https://api.hubapi.com/crm/v3/objects/notes",
            exc=AssertionError("note create should not be called on second pass"),
        )
        m.put(
            requests_mock_any_url := "https://api.hubapi.com/crm/v4/objects/note/note-1/associations/default/company/comp-1",
            exc=AssertionError("association should not be called on second pass"),
        )
        ledger = uploader.upload_phase(rows)
        ledger = uploader.attach_phase(rows, ledger)

    assert ledger[0]["status"] == STATUS_ATTACHED
    assert ledger[0]["hs_file_id"] == "file-1"
    assert ledger[0]["hs_note_id"] == "note-1"


# -- Offline: schema-name validation -----------------------------------------


def test_postgres_ledger_rejects_invalid_schema_names():
    with pytest.raises(ValueError):
        PostgresLedger(dsn="dummy", schema="staging; DROP TABLE notes;--")
    with pytest.raises(ValueError):
        PostgresLedger(dsn="dummy", schema="Staging")  # uppercase rejected
    PostgresLedger(dsn="dummy", schema="staging_test")  # OK
    PostgresLedger(dsn="dummy", schema="lib_v2")  # OK


# -- Live: postgres + sandbox run-twice no-op --------------------------------


@pytest.mark.live_sandbox
def test_run_twice_against_postgres_and_sandbox_is_idempotent():
    if not os.environ.get("HUBSPOT_SANDBOX_TOKEN"):
        pytest.skip("HUBSPOT_SANDBOX_TOKEN not set")
    dsn = os.environ.get("LEDGER_TEST_DSN")
    if not dsn:
        pytest.skip("LEDGER_TEST_DSN not set; live ledger test skipped")

    schema = "library_files_test"
    ledger = PostgresLedger(dsn=dsn, schema=schema)
    ledger.bootstrap()

    # Clean any prior test residue so this test can be re-run.
    import psycopg2
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(f"TRUNCATE {schema}.fct_files_uploaded, {schema}.fct_file_notes_posted")
        conn.commit()

    client = HubSpotClient.from_settings(Settings.from_env())
    uploader = HubSpotFileUploader(client, ledger=ledger)

    cleanups: list = []
    try:
        company = client.create_company(name="__icalps_libfile_unit5__")
        company_id = company["id"]
        cleanups.append(lambda: client.delete_company(company_id))

        rows = [LibraryFileRow(
            legacy_id="UNIT5_L1",
            file_path=FIXTURES / "sample_invoice.txt",
            note_body="unit 5 idempotency",
            target_associations=[("company", company_id)],
        )]

        # First pass — full chain
        ledger_state = uploader.upload_phase(rows)
        ledger_state = uploader.attach_phase(rows, ledger_state)
        first_file_id = ledger_state[0]["hs_file_id"]
        first_note_id = ledger_state[0]["hs_note_id"]
        cleanups.append(lambda: client.delete_file(first_file_id))
        cleanups.append(lambda: client.delete_note(first_note_id))
        assert ledger_state[0]["status"] == STATUS_ATTACHED

        # Second pass — must yield same ids, no new HubSpot resources
        ledger_state2 = uploader.upload_phase(rows)
        ledger_state2 = uploader.attach_phase(rows, ledger_state2)
        assert ledger_state2[0]["hs_file_id"] == first_file_id
        assert ledger_state2[0]["hs_note_id"] == first_note_id
        assert ledger_state2[0]["status"] == STATUS_ATTACHED
    finally:
        for fn in reversed(cleanups):
            try:
                fn()
            except Exception:
                pass
