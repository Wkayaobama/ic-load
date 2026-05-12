"""Smoke test the bootstrap-views subcommand wiring.

Verifies the runner parses the subcommand, dispatches to CleanupLedger
methods, and exits 0. Does not re-test the ledger logic itself
(covered in test_ledger.py).
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _require_dsn() -> None:
    if not os.environ.get("PROD_POSTGRES_DSN"):
        pytest.skip("no PROD_POSTGRES_DSN")


def test_bootstrap_views_subcommand_exits_zero() -> None:
    from pipeline.cleanup.runner import main

    with patch("pipeline.cleanup.runner.CleanupLedger") as MockLedger:
        instance = MockLedger.return_value
        rc = main(["bootstrap-views"])
        assert rc == 0
        instance.bootstrap.assert_called_once()
        instance.bootstrap_views.assert_called_once()
        instance.bootstrap_communication_view.assert_called_once()
