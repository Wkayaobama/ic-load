"""Verify BRONZE_DIR honours the PIPELINE_BRONZE_DIR env var with an in-repo default.

The pre-change default was PROJECT_ROOT.parent / "bronze_layer" (sibling layout).
The post-change default is PROJECT_ROOT / "bronze_layer" (in-repo layout), and
operators can override via PIPELINE_BRONZE_DIR — same pattern as ARTIFACTS_DIR.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _reload_config():
    import context.config as cfg
    return importlib.reload(cfg)


def test_bronze_dir_default_is_in_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PIPELINE_BRONZE_DIR", raising=False)
    cfg = _reload_config()
    # PROJECT_ROOT is the repo root; default bronze_layer lives inside it now.
    assert cfg.BRONZE_DIR == cfg.PROJECT_ROOT / "bronze_layer"


def test_bronze_dir_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    # BRONZE_DIR resolution does not require the path to exist on disk —
    # it's a Path() wrap around the env value. Use a synthetic absolute
    # path so the test is independent of tmp_path / filesystem permissions.
    custom = Path("/synthetic/elsewhere/bronze_layer").resolve()
    monkeypatch.setenv("PIPELINE_BRONZE_DIR", str(custom))
    cfg = _reload_config()
    assert cfg.BRONZE_DIR == custom


def test_bronze_dir_env_override_supports_sibling_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Back-compat: existing collaborators with sibling bronze_layer can keep
    working by setting PIPELINE_BRONZE_DIR=../bronze_layer (or absolute)."""
    import context.config as cfg_initial
    sibling = cfg_initial.PROJECT_ROOT.parent / "bronze_layer"
    monkeypatch.setenv("PIPELINE_BRONZE_DIR", str(sibling))
    cfg = _reload_config()
    assert cfg.BRONZE_DIR == sibling
