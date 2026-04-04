from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from context.config import PROJECT_ROOT

_LEGACY_ROOT = PROJECT_ROOT.parent / "ic_load_pipeline" / "python-ignorethis"


def _load_legacy_module(module_name: str, filename: str) -> ModuleType:
    path = _LEGACY_ROOT / filename
    if not path.exists():
        raise RuntimeError(f"Legacy module is unavailable: {path}")

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load legacy module spec for {path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SilverNormaliser:
    """Thin salvage wrapper around the proven legacy Silver normaliser.

    This keeps the validated business logic alive while the clean repo owns the
    orchestration, SQL rendering, and remote execution surface around it.
    """

    def __init__(self):
        module = _load_legacy_module("ic_load_legacy_silver_normalise", "silver_normalise.py")
        self._delegate = module.SilverNormaliser()

    def __getattr__(self, item: str) -> Any:
        return getattr(self._delegate, item)


class SilverValidator:
    """Thin salvage wrapper around the proven legacy Silver validator."""

    def __init__(self):
        module = _load_legacy_module("ic_load_legacy_validate_silver", "validate_silver.py")
        self._delegate = module.SilverValidator()

    @property
    def results(self):
        return self._delegate.results

    def run_checks(self) -> bool:
        return self._delegate.run_checks()
