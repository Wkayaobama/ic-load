"""Unit 2 — HubSpotFileUploader two-phase round-trip against the sandbox.

Same five REST calls as Unit 1, but driven through the upload_phase / attach_phase
abstraction. Asserts the in-memory ledger walks through pending → uploaded →
attached, and that GET-back from HubSpot still shows the attachment + association.

Also a small offline test for retry/backoff against a 429 response, using
backoff_schedule=(0,) so the test runs in milliseconds.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import requests
import requests_mock as rm_module

from pipeline.library_files.client import HubSpotClient
from pipeline.library_files.config import Settings
from pipeline.library_files.uploader import (
    HubSpotFileUploader,
    LibraryFileRow,
    STATUS_ATTACHED,
    STATUS_UPLOADED,
)

FIXTURES = Path(__file__).parent / "fixtures"


# -- Offline retry test (no sandbox needed) ----------------------------------


def test_retry_honors_429_then_succeeds():
    """Client gets a 429 once, then a 200 — uploader should succeed after retry."""
    s = requests.Session()
    client = HubSpotClient(token="dummy", session=s)
    uploader = HubSpotFileUploader(client, backoff_schedule=(0,), sleep_fn=lambda _: None)

    with rm_module.Mocker(session=s) as m:
        m.post(
            "https://api.hubapi.com/files/v3/files",
            [
                {"status_code": 429, "headers": {"Retry-After": "0"}, "json": {"err": "rate"}},
                {"status_code": 200, "json": {"id": "file-abc-123"}},
            ],
        )
        rows = [LibraryFileRow(
            legacy_id="L1",
            file_path=FIXTURES / "sample_invoice.txt",
            note_body="x",
            target_associations=[("company", "9999")],
        )]
        ledger = uploader.upload_phase(rows)

    assert ledger[0]["status"] == STATUS_UPLOADED
    assert ledger[0]["hs_file_id"] == "file-abc-123"


def test_missing_file_marks_failed_without_raising():
    s = requests.Session()
    client = HubSpotClient(token="dummy", session=s)
    uploader = HubSpotFileUploader(client, backoff_schedule=(), sleep_fn=lambda _: None)
    rows = [LibraryFileRow(
        legacy_id="L1",
        file_path=Path("/no/such/file.txt"),
        note_body="x",
        target_associations=[("company", "1")],
    )]
    ledger = uploader.upload_phase(rows)
    assert ledger[0]["status"] == "failed"
    assert ledger[0]["error"] == "file_not_found"


# -- Live sandbox round-trip via uploader ------------------------------------


@pytest.mark.live_sandbox
def test_uploader_round_trip_against_sandbox():
    if not os.environ.get("HUBSPOT_SANDBOX_TOKEN"):
        pytest.skip("HUBSPOT_SANDBOX_TOKEN not set; live sandbox test skipped")

    client = HubSpotClient.from_settings(Settings.from_env())
    uploader = HubSpotFileUploader(client)

    cleanups: list = []
    try:
        company = client.create_company(name="__icalps_libfile_unit2__")
        company_id = company["id"]
        cleanups.append(lambda: client.delete_company(company_id))

        row = LibraryFileRow(
            legacy_id="unit2_legacy_1",
            file_path=FIXTURES / "sample_invoice.txt",
            note_body="Legacy migrated file: sample_invoice.txt (unit 2)",
            target_associations=[("company", company_id)],
        )

        ledger = uploader.upload_phase([row])
        assert ledger[0]["status"] == STATUS_UPLOADED
        file_id = ledger[0]["hs_file_id"]
        cleanups.append(lambda: client.delete_file(file_id))

        ledger = uploader.attach_phase([row], ledger)
        assert ledger[0]["status"] == STATUS_ATTACHED
        note_id = ledger[0]["hs_note_id"]
        cleanups.append(lambda: client.delete_note(note_id))

        # GET-back assertion — same invariants as Unit 1
        fetched = client.get_note(
            note_id,
            associations=["companies"],
            properties=["hs_attachment_ids", "hs_note_body"],
        )
        assert str(file_id) in str(fetched["properties"]["hs_attachment_ids"])
        assoc_ids = {
            str(a["id"])
            for a in fetched.get("associations", {}).get("companies", {}).get("results", [])
        }
        assert str(company_id) in assoc_ids
    finally:
        for fn in reversed(cleanups):
            try:
                fn()
            except Exception:
                pass
