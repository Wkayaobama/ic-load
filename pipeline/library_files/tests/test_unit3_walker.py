"""Unit 3 — folder walker drives Unit 2 against a single sandbox target.

Two offline tests assert walker semantics (image filter, row construction).
One live sandbox test seeds a company, walks the fixtures dir, runs upload+
attach for the two .txt fixtures (sample_image.png is skipped), and verifies
the GET-back of each created note carries the correct attachment + association.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from pipeline.library_files.client import HubSpotClient
from pipeline.library_files.config import Settings
from pipeline.library_files.uploader import (
    HubSpotFileUploader,
    STATUS_ATTACHED,
)
from pipeline.library_files.walker import build_rows, walk_files

FIXTURES = Path(__file__).parent / "fixtures" / "library_root"


# -- Offline walker tests ----------------------------------------------------


def test_walker_skips_image_extensions():
    found = {p.name for p in walk_files(FIXTURES)}
    assert "sample_invoice.txt" in found
    assert "sample_quote.txt" in found
    assert "sample_image.png" not in found, "image extension should be filtered out"


def test_build_rows_assigns_targets_and_synthetic_ids_to_each_row():
    rows = build_rows(FIXTURES, target_associations=[("company", "999")])
    assert len(rows) == 2
    legacy_ids = {r.legacy_id for r in rows}
    assert len(legacy_ids) == 2, "synthetic ids must be unique per file"
    for r in rows:
        assert r.target_associations == [("company", "999")]
        assert r.note_body.startswith("Legacy migrated file: ")


# -- Live sandbox: walker → uploader full chain ------------------------------


@pytest.mark.live_sandbox
def test_walker_drives_upload_and_attach_for_all_files():
    if not os.environ.get("HUBSPOT_SANDBOX_TOKEN"):
        pytest.skip("HUBSPOT_SANDBOX_TOKEN not set; live sandbox test skipped")

    client = HubSpotClient.from_settings(Settings.from_env())
    uploader = HubSpotFileUploader(client)

    cleanups: list = []
    try:
        company = client.create_company(name="__icalps_libfile_unit3__")
        company_id = company["id"]
        cleanups.append(lambda: client.delete_company(company_id))

        rows = build_rows(
            FIXTURES,
            target_associations=[("company", company_id)],
        )
        assert len(rows) == 2  # sample_image.png filtered out

        ledger = uploader.upload_phase(rows)
        for entry in ledger:
            if entry["hs_file_id"]:
                fid = entry["hs_file_id"]
                cleanups.append(lambda f=fid: client.delete_file(f))

        ledger = uploader.attach_phase(rows, ledger)
        for entry in ledger:
            if entry["hs_note_id"]:
                nid = entry["hs_note_id"]
                cleanups.append(lambda n=nid: client.delete_note(n))

        assert all(e["status"] == STATUS_ATTACHED for e in ledger), ledger

        # GET-back: each note should carry exactly one attachment + the seeded company
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
            assert str(company_id) in assoc_ids
    finally:
        for fn in reversed(cleanups):
            try:
                fn()
            except Exception:
                pass
