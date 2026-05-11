"""Unit 1 — sandbox round-trip MVP.

Five live REST calls against the sandbox portal:
  1. POST /crm/v3/objects/companies          (seed target)
  2. POST /files/v3/files                    (upload fixture)
  3. POST /crm/v3/objects/notes              (create note with hs_attachment_ids)
  4. PUT  /crm/v4/objects/note/{id}/associations/default/company/{id}
  5. GET  /crm/v3/objects/notes/{id}?associations=companies&properties=...

Asserts the GET-back contains both the file id in hs_attachment_ids and the seed
company id in associations.companies.results.

Cleanup is best-effort LIFO via a registered cleanup list, run in finally.

Skipped automatically when HUBSPOT_SANDBOX_TOKEN is not set, so unit-test CI
still passes without sandbox creds.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from pipeline.library_files.client import HubSpotClient
from pipeline.library_files.config import Settings

FIXTURES = Path(__file__).parent / "fixtures" / "library_root"


@pytest.mark.live_sandbox
def test_round_trip_creates_note_with_attachment_and_company_association():
    if not os.environ.get("HUBSPOT_SANDBOX_TOKEN"):
        pytest.skip("HUBSPOT_SANDBOX_TOKEN not set; live sandbox test skipped")

    client = HubSpotClient.from_settings(Settings.from_env())
    cleanups: list = []

    try:
        company = client.create_company(name="__icalps_libfile_unit1__")
        company_id = company["id"]
        cleanups.append(lambda: client.delete_company(company_id))

        upload = client.upload_file(FIXTURES / "sample_invoice.txt")
        file_id = upload["id"]
        cleanups.append(lambda: client.delete_file(file_id))

        note = client.create_note(
            hs_note_body="Legacy migrated file: sample_invoice.txt",
            hs_attachment_ids=[file_id],
        )
        note_id = note["id"]
        cleanups.append(lambda: client.delete_note(note_id))

        client.associate_default("note", note_id, "company", company_id)

        fetched = client.get_note(
            note_id,
            associations=["companies"],
            properties=["hs_attachment_ids", "hs_note_body"],
        )

        attachment_ids_str = fetched["properties"].get("hs_attachment_ids", "")
        assert str(file_id) in str(attachment_ids_str), (
            f"expected file_id {file_id} in hs_attachment_ids, got {attachment_ids_str!r}"
        )

        assoc_results = (
            fetched.get("associations", {})
            .get("companies", {})
            .get("results", [])
        )
        assoc_ids = {str(a.get("id")) for a in assoc_results}
        assert str(company_id) in assoc_ids, (
            f"expected company_id {company_id} in association results, got {assoc_ids}"
        )
    finally:
        for fn in reversed(cleanups):
            try:
                fn()
            except Exception:
                pass
