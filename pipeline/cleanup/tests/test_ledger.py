"""Tests for pipeline.cleanup.ledger.CleanupLedger.

Integration-flavoured: requires a reachable Postgres DSN. Skipped if neither
TEST_POSTGRES_DSN nor PROD_POSTGRES_DSN is set in the environment. Uses
schema='staging' (the default) -- the bootstrap is idempotent, so re-running
against the real prod staging schema does not corrupt state.
"""
from __future__ import annotations

import os

import pytest

from pipeline.cleanup.ledger import CleanupLedger


@pytest.fixture
def dsn() -> str:
    val = os.environ.get("TEST_POSTGRES_DSN") or os.environ.get("PROD_POSTGRES_DSN")
    if not val:
        pytest.skip("no postgres DSN available (set TEST_POSTGRES_DSN or PROD_POSTGRES_DSN)")
    return val


def test_bootstrap_views_creates_three_standard_views(dsn: str) -> None:
    ledger = CleanupLedger(dsn)
    ledger.bootstrap()
    ledger.bootstrap_views()

    import psycopg2  # type: ignore[import-not-found]
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.views
            WHERE table_schema = 'staging'
              AND table_name IN (
                'fct_cleanup_companies',
                'fct_cleanup_contacts',
                'fct_cleanup_deals'
              )
            ORDER BY table_name
            """
        )
        rows = [r[0] for r in cur.fetchall()]

    assert rows == [
        "fct_cleanup_companies",
        "fct_cleanup_contacts",
        "fct_cleanup_deals",
    ]


def test_bootstrap_views_is_idempotent(dsn: str) -> None:
    ledger = CleanupLedger(dsn)
    ledger.bootstrap()
    ledger.bootstrap_views()
    ledger.bootstrap_views()  # second call must not raise


def test_bootstrap_views_emit_three_column_contract(dsn: str) -> None:
    """Each standard view must have exactly (hubspot_id, legacy_id, label)
    in that order, all text. This is the contract selection.plan_from_view
    relies on."""
    ledger = CleanupLedger(dsn)
    ledger.bootstrap()
    ledger.bootstrap_views()

    import psycopg2  # type: ignore[import-not-found]
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        for view in ("fct_cleanup_companies", "fct_cleanup_contacts", "fct_cleanup_deals"):
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'staging'
                  AND table_name = %s
                ORDER BY ordinal_position
                """,
                (view,),
            )
            cols = [r[0] for r in cur.fetchall()]
            assert cols == ["hubspot_id", "legacy_id", "label"], (view, cols)
