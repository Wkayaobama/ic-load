"""Unit 6 — approval gates (default DRY-RUN, env-var to enable live writes).

Two offline tests prove the dry-run contract:
  1. Both gates unset → zero REST calls fire (Mocker.call_count == 0); every
     row ends up at status='dry_run'.
  2. Phase 1 gate set, Phase 2 unset → file upload mocks fire, note creation
     and association mocks must NOT be reached. Ledger row carries the
     hs_file_id from Phase 1 but has status='dry_run' from Phase 2.

The live-sandbox path with both gates set is already covered by Unit 2's
``test_uploader_round_trip_against_sandbox`` — when invoked through the
class default ``live=True``, behavior is identical to pre-Phase-6.
"""
from __future__ import annotations

from pathlib import Path

import requests
import requests_mock as rm_module

from pipeline.library_files.client import HubSpotClient
from pipeline.library_files.uploader import (
    HubSpotFileUploader,
    LibraryFileRow,
    STATUS_DRY_RUN,
    STATUS_UPLOADED,
)

FIXTURES = Path(__file__).parent / "fixtures" / "library_root"


def _make_uploader():
    s = requests.Session()
    client = HubSpotClient(token="dummy", session=s)
    uploader = HubSpotFileUploader(client, backoff_schedule=(), sleep_fn=lambda _: None)
    return s, uploader


def _row(legacy_id: str = "L1") -> LibraryFileRow:
    return LibraryFileRow(
        legacy_id=legacy_id,
        file_path=FIXTURES / "sample_invoice.txt",
        note_body="x",
        target_associations=[("company", "9999")],
    )


def test_both_gates_unset_zero_rest_calls():
    """Both phases dry-run; the Mocker has no handlers registered, so any
    actual REST call would raise NoMockAddress. We assert call_count==0."""
    session, uploader = _make_uploader()
    rows = [_row()]

    with rm_module.Mocker(session=session) as m:
        ledger = uploader.upload_phase(rows, live=False)
        ledger = uploader.attach_phase(rows, ledger, live=False)
        assert m.call_count == 0, "no REST calls expected when both gates are unset"

    assert ledger[0]["status"] == STATUS_DRY_RUN
    assert ledger[0]["hs_file_id"] is None
    assert ledger[0]["hs_note_id"] is None


def test_phase1_live_phase2_dry_run():
    """Phase 1 gate ON, Phase 2 gate OFF — upload fires once, note creation and
    association are not reached. The ledger entry shows hs_file_id (from the
    upload) but status=dry_run (from Phase 2)."""
    session, uploader = _make_uploader()
    rows = [_row()]

    with rm_module.Mocker(session=session) as m:
        m.post("https://api.hubapi.com/files/v3/files", json={"id": "file-abc"})
        # Note + association handlers intentionally NOT registered.
        ledger = uploader.upload_phase(rows, live=True)
        assert ledger[0]["status"] == STATUS_UPLOADED
        assert ledger[0]["hs_file_id"] == "file-abc"

        ledger = uploader.attach_phase(rows, ledger, live=False)
        # Exactly one REST call total (the upload). Note create / assoc never hit.
        assert m.call_count == 1, f"expected 1 REST call (upload only), got {m.call_count}"

    assert ledger[0]["status"] == STATUS_DRY_RUN
    assert ledger[0]["hs_file_id"] == "file-abc"
    assert ledger[0]["hs_note_id"] is None


def test_phase1_dry_propagates_to_phase2_dry():
    """If Phase 1 was dry-run, Phase 2 has no file id to attach. Even when
    Phase 2 gate is set, those rows must remain dry-run (cannot attach what
    was never uploaded)."""
    session, uploader = _make_uploader()
    rows = [_row()]

    with rm_module.Mocker(session=session) as m:
        ledger = uploader.upload_phase(rows, live=False)
        # No REST. Status='dry_run', hs_file_id=None.
        ledger = uploader.attach_phase(rows, ledger, live=True)
        # Still no REST: Phase 2 sees a dry_run row and propagates.
        assert m.call_count == 0

    assert ledger[0]["status"] == STATUS_DRY_RUN
    assert ledger[0]["hs_note_id"] is None
