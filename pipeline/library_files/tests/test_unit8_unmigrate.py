"""Unit 8 — `runner unmigrate` rollback subcommand.

Exercises cmd_unmigrate against an in-memory LedgerLike fake + a
requests_mock-backed HubSpotClient. Verifies:

  * empty ledger → exit 0, no API calls
  * gate unset (DRY-RUN) → enumerates `would_unattach`, no API calls, no ledger writes
  * gate set + HubSpot 204 → ledger flips to `unattached_via_unmigrate`, exit 0
  * gate set + HubSpot 404 → partial failure (`unattach_failed`), exit 1

All offline. The live-DB path is covered by the operator runbook.
"""
from __future__ import annotations

import argparse
from typing import Any, Iterable, Mapping
from unittest.mock import patch

import pytest
import requests
import requests_mock as rm_module

from pipeline.library_files import runner as runner_mod
from pipeline.library_files.client import HubSpotClient
from pipeline.library_files.config import Settings


# -- FakeLedger extends the unit-5 surface with the new rollback methods -----


class FakeLedger:
    """In-memory implementation of the extended LedgerLike interface."""

    def __init__(self, attached: list[dict] | None = None) -> None:
        # Modelled as a dict keyed on legacy_library_id so record_unattach
        # can find and flip the right row.
        self._rows: dict[str, dict] = {}
        for row in attached or []:
            self._rows[row["legacy_library_id"]] = {**row}
        self.bootstrap_called = False
        self.unattach_calls: list[tuple[str, str, str | None]] = []

    # Existing surface (unused by unmigrate but kept so the Protocol is satisfied)
    def upload_skip_set(self) -> set[str]:
        return set()

    def attach_skip_set(self) -> set[str]:
        return {k for k, v in self._rows.items() if v.get("status") == "attached"}

    def load_existing(self, legacy_ids: Iterable[str]) -> dict[str, dict]:
        return {lid: {"legacy_id": lid} for lid in legacy_ids}

    def record_upload(self, entry: Mapping[str, object]) -> None:
        pass

    def record_attach(self, entry: Mapping[str, object]) -> None:
        pass

    # Rollback surface — the new methods unmigrate consumes
    def bootstrap(self) -> None:
        self.bootstrap_called = True

    def load_attached_rows(self) -> list[dict]:
        return [
            {
                "legacy_library_id": k,
                "hs_note_id": v["hs_note_id"],
                "idempotency_key": v.get("idempotency_key", f"icalps_libfile_{k}"),
                "status": v.get("status", "attached"),
            }
            for k, v in self._rows.items()
            if v.get("status") == "attached"
        ]

    def record_unattach(self, legacy_id: str, status: str, error: str | None) -> None:
        self.unattach_calls.append((legacy_id, status, error))
        if legacy_id in self._rows:
            self._rows[legacy_id]["status"] = status
            self._rows[legacy_id]["error"] = error


def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make Settings.from_env() return a synthetic settings object so the
    runner doesn't try to walk dotenv during the test."""
    fake = Settings(
        hubspot_token="test-token",
        hubspot_portal_id="49610528",
        library_base_dir=None,
        prod_postgres_dsn="postgresql://dummy@localhost/dummy",
    )
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls, **kw: fake))


def _bind_ledger(monkeypatch: pytest.MonkeyPatch, fake: FakeLedger) -> None:
    """Force PostgresLedger(...) to yield `fake` regardless of constructor args."""
    monkeypatch.setattr(runner_mod, "PostgresLedger", lambda *_a, **_kw: fake)


def _bind_client(monkeypatch: pytest.MonkeyPatch, client: HubSpotClient) -> None:
    """Force HubSpotClient.from_settings(...) to yield the requests_mock-bound client."""
    monkeypatch.setattr(
        runner_mod.HubSpotClient, "from_settings",
        classmethod(lambda cls, _settings: client),
    )


def _ns() -> argparse.Namespace:
    return argparse.Namespace()


# -- Test 1: empty ledger ----------------------------------------------------


def test_unmigrate_with_empty_ledger_returns_zero(monkeypatch, capsys):
    _stub_settings(monkeypatch)
    fake = FakeLedger(attached=[])
    _bind_ledger(monkeypatch, fake)

    session = requests.Session()
    client = HubSpotClient(token="dummy", session=session)
    _bind_client(monkeypatch, client)
    monkeypatch.delenv(runner_mod.APPROVE_UNMIGRATE_ENV, raising=False)

    rc = runner_mod.cmd_unmigrate(_ns())

    assert rc == 0
    assert fake.bootstrap_called is True
    assert fake.unattach_calls == []
    err = capsys.readouterr().err
    assert "nothing to unmigrate" in err


# -- Test 2: dry-run (gate unset) -------------------------------------------


def test_unmigrate_dry_run_enumerates_without_calling_api(monkeypatch, capsys):
    _stub_settings(monkeypatch)
    fake = FakeLedger(attached=[
        {"legacy_library_id": "L1", "hs_note_id": "note-1", "status": "attached"},
        {"legacy_library_id": "L2", "hs_note_id": "note-2", "status": "attached"},
    ])
    _bind_ledger(monkeypatch, fake)

    session = requests.Session()
    client = HubSpotClient(token="dummy", session=session)
    _bind_client(monkeypatch, client)
    monkeypatch.delenv(runner_mod.APPROVE_UNMIGRATE_ENV, raising=False)

    with rm_module.Mocker(session=session) as m:
        rc = runner_mod.cmd_unmigrate(_ns())
        # No DELETE calls in dry-run — the mocker would 404 any uncaught URL.
        assert all(req.method != "DELETE" for req in m.request_history)

    assert rc == 0
    assert fake.unattach_calls == []  # no ledger writes in dry-run
    # Both rows still show 'attached' (no flip)
    assert fake._rows["L1"]["status"] == "attached"
    assert fake._rows["L2"]["status"] == "attached"
    out = capsys.readouterr().out
    assert "would_unattach" in out


# -- Test 3: live, all succeed ----------------------------------------------


def test_unmigrate_live_archives_and_flips_ledger(monkeypatch, capsys):
    _stub_settings(monkeypatch)
    fake = FakeLedger(attached=[
        {"legacy_library_id": "L1", "hs_note_id": "note-1", "status": "attached"},
        {"legacy_library_id": "L2", "hs_note_id": "note-2", "status": "attached"},
    ])
    _bind_ledger(monkeypatch, fake)

    session = requests.Session()
    client = HubSpotClient(token="dummy", session=session)
    _bind_client(monkeypatch, client)
    monkeypatch.setenv(runner_mod.APPROVE_UNMIGRATE_ENV, "1")

    with rm_module.Mocker(session=session) as m:
        m.delete("https://api.hubapi.com/crm/v3/objects/notes/note-1", status_code=204)
        m.delete("https://api.hubapi.com/crm/v3/objects/notes/note-2", status_code=204)
        rc = runner_mod.cmd_unmigrate(_ns())

    assert rc == 0
    assert len(fake.unattach_calls) == 2
    for legacy_id, status, error in fake.unattach_calls:
        assert status == "unattached_via_unmigrate"
        assert error is None
    # Ledger rows have flipped
    assert fake._rows["L1"]["status"] == "unattached_via_unmigrate"
    assert fake._rows["L2"]["status"] == "unattached_via_unmigrate"
    out = capsys.readouterr().out
    assert "unattached_via_unmigrate" in out


# -- Test 4: live, one DELETE fails -----------------------------------------


def test_unmigrate_live_records_partial_failure(monkeypatch, capsys):
    _stub_settings(monkeypatch)
    fake = FakeLedger(attached=[
        {"legacy_library_id": "L1", "hs_note_id": "note-1", "status": "attached"},
        {"legacy_library_id": "L2", "hs_note_id": "note-2", "status": "attached"},
    ])
    _bind_ledger(monkeypatch, fake)

    session = requests.Session()
    client = HubSpotClient(token="dummy", session=session)
    _bind_client(monkeypatch, client)
    monkeypatch.setenv(runner_mod.APPROVE_UNMIGRATE_ENV, "1")

    with rm_module.Mocker(session=session) as m:
        m.delete("https://api.hubapi.com/crm/v3/objects/notes/note-1", status_code=204)
        m.delete(
            "https://api.hubapi.com/crm/v3/objects/notes/note-2",
            status_code=404,
            json={"message": "not found"},
        )
        rc = runner_mod.cmd_unmigrate(_ns())

    assert rc == 1  # partial failure → non-zero
    statuses = {legacy: status for legacy, status, _ in fake.unattach_calls}
    assert statuses["L1"] == "unattached_via_unmigrate"
    assert statuses["L2"] == "unattach_failed"
    # The failure error is preserved on the ledger row
    assert fake._rows["L2"]["status"] == "unattach_failed"
    assert fake._rows["L2"]["error"] is not None
