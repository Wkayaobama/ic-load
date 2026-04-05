"""
_stubs.py — Stub classes for legacy modules that are not yet promoted into ic-load.

These stubs exist to give a clear, actionable error when the runner attempts to
load legacy modules from the IC_Load parent workspace (M4 — silver.py path dependency).

Instead of a cryptic ImportError or FileNotFoundError deep in pipeline/silver.py,
these stubs raise a RuntimeError that names the exact file that must be copied
into ic-load/context/algorithms/ to resolve the blocker.

## To resolve M4

Copy the following files from the legacy workspace:
  ic_load_pipeline/python-ignorethis/silver_normalise.py  → ic-load/context/algorithms/
  ic_load_pipeline/python-ignorethis/validate_silver.py   → ic-load/context/algorithms/

Then update pipeline/silver.py to import from context.algorithms instead of
using importlib.util to load from the parent directory path.

Until then, these stubs are the fallback. They will never be imported in the
full IC_Load workspace (silver.py will find the real modules first), but they
protect Codespaces and CI runs from silent failures.
"""
from __future__ import annotations

_RESOLUTION_HINT = (
    "\n\nTo resolve this (M4 blocker):\n"
    "  1. Copy ic_load_pipeline/python-ignorethis/silver_normalise.py\n"
    "     → ic-load/context/algorithms/silver_normalise.py\n"
    "  2. Copy ic_load_pipeline/python-ignorethis/validate_silver.py\n"
    "     → ic-load/context/algorithms/validate_silver.py\n"
    "  3. Update pipeline/silver.py imports to use context.algorithms\n"
    "  See salvation.md 'Known Blockers Before Codespaces Execution' section."
)


class _SilverNormaliserStub:
    """Stub that raises a clear M4 error if the real module is unavailable."""

    def __getattr__(self, item: str):
        raise RuntimeError(
            f"SilverNormaliser.{item} is not available: silver_normalise.py "
            f"has not been promoted into ic-load/context/algorithms/."
            + _RESOLUTION_HINT
        )

    def run_all(self):
        raise RuntimeError(
            "SilverNormaliser.run_all() is not available: silver_normalise.py "
            "has not been promoted into ic-load/context/algorithms/."
            + _RESOLUTION_HINT
        )


class _SilverValidatorStub:
    """Stub that raises a clear M4 error if the real module is unavailable."""

    @property
    def results(self):
        raise RuntimeError(
            "SilverValidator.results is not available: validate_silver.py "
            "has not been promoted into ic-load/context/algorithms/."
            + _RESOLUTION_HINT
        )

    def run_checks(self) -> bool:
        raise RuntimeError(
            "SilverValidator.run_checks() is not available: validate_silver.py "
            "has not been promoted into ic-load/context/algorithms/."
            + _RESOLUTION_HINT
        )


def get_silver_normaliser():
    """Return the real SilverNormaliser if available, or the stub with clear error."""
    try:
        from context.algorithms import silver_normalise  # type: ignore[import]
        return silver_normalise.SilverNormaliser()
    except ImportError:
        return _SilverNormaliserStub()


def get_silver_validator():
    """Return the real SilverValidator if available, or the stub with clear error."""
    try:
        from context.algorithms import validate_silver  # type: ignore[import]
        return validate_silver.SilverValidator()
    except ImportError:
        return _SilverValidatorStub()
