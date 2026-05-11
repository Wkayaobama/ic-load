"""Pytest config for the library_files module.

Loads .env at session start so the early skip-check in live_sandbox tests sees
HUBSPOT_SANDBOX_TOKEN without having to call Settings.from_env() first.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def _load_env_from_repo_root() -> None:
    """Walk up from this file to find the repo root (.env or .git) and load it."""
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        candidate = parent / ".env"
        if candidate.is_file():
            load_dotenv(candidate)
            return
    # Fall back to default .env discovery (cwd-based) — harmless if absent.
    load_dotenv()


_load_env_from_repo_root()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live_sandbox: hits the live HubSpot sandbox; skipped when "
        "HUBSPOT_SANDBOX_TOKEN is not set.",
    )
