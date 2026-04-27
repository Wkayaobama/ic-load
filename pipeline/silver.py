from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from types import ModuleType
from typing import Any

_log = logging.getLogger(__name__)

from context.config import PROJECT_ROOT
from context.db import get_connection

_LEGACY_ROOT = PROJECT_ROOT.parent / "ic_load_pipeline" / "python-ignorethis"

# Native company normaliser — preferred over legacy
_NATIVE_COMPANY_AVAILABLE = False
try:
    from pipeline.silver_company import SilverCompanyNormaliser as NativeCompanyNormaliser
    _NATIVE_COMPANY_AVAILABLE = True
except ImportError:
    NativeCompanyNormaliser = None  # type: ignore

# Path to the Case Silver SQL files (self-contained, no legacy dependency)
_CASE_SQL_DIR = PROJECT_ROOT / "sql" / "case"


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

    For 'case', the normaliser is self-contained in sql/case/ and does NOT
    depend on the legacy module path — it uses native SQL executed via context.db.
    """

    def __init__(self):
        # Legacy delegate loaded lazily; case entity uses its own path
        self._legacy_delegate: Any = None

    def _ensure_legacy(self) -> None:
        if self._legacy_delegate is None:
            module = _load_legacy_module("ic_load_legacy_silver_normalise", "silver_normalise.py")
            self._legacy_delegate = module.SilverNormaliser()

    def normalise_case(self) -> dict[str, Any]:
        """Materialise staging.stg_case_v2 from the Bronze raw stg_cases table.

        Executes sql/case/02_stg_case_v2_materialize.sql directly against the
        PostgreSQL instance. No legacy module dependency.

        Returns a summary dict with row_count and column coverage metrics.
        """
        sql_path = _CASE_SQL_DIR / "02_stg_case_v2_materialize.sql"
        if not sql_path.exists():
            raise RuntimeError(f"Case Silver SQL not found: {sql_path}")

        sql = sql_path.read_text(encoding="utf-8")

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                # The last statement in the file is a SELECT returning coverage metrics
                try:
                    row = cur.fetchone()
                    if row and cur.description is not None:
                        cols = [desc[0] for desc in cur.description]
                        return dict(zip(cols, row))
                except Exception:
                    pass
            conn.commit()

        return {"entity": "case", "status": "materialised"}

    def normalise_company(self) -> dict[str, Any]:
        """Normalise company data using native module (preferred) or legacy fallback.

        Native module:
        - Uses context.algorithms.company_siblings for sibling detection
        - Uses context.algorithms.phone_normalise for E.164 normalisation
        - Writes to staging.stg_company_normalised

        Falls back to legacy if native is unavailable or fails.
        """
        if _NATIVE_COMPANY_AVAILABLE and NativeCompanyNormaliser is not None:
            try:
                normaliser = NativeCompanyNormaliser()
                result = normaliser.normalise()
                return result
            except Exception as e:
                _log.warning(
                    "Native company normaliser failed, falling back to legacy: %s", e
                )

        # Fallback to legacy
        self._ensure_legacy()
        self._legacy_delegate.normalise_company()
        return {"entity": "company", "status": "legacy", "source": "fallback"}

    def run_all(self) -> None:
        """Delegate to legacy normaliser for all non-case entities."""
        self._ensure_legacy()
        self._legacy_delegate.run_all()

    def __getattr__(self, item: str) -> Any:
        self._ensure_legacy()
        return getattr(self._legacy_delegate, item)


@dataclass
class _ValidationResult:
    name: str
    passed: bool
    severity: str
    row_count_failing: int
    notes: str


class SilverValidator:
    """Silver validator.

    For 'case': runs sql/case/04_silver_validate.sql directly.
    For all other entities: delegates to the legacy validator.
    """

    def __init__(self, entity: str = ""):
        self._entity = entity.lower()
        self._legacy_delegate: Any = None
        self.results: list[_ValidationResult] = []

    def _ensure_legacy(self) -> None:
        if self._legacy_delegate is None:
            module = _load_legacy_module("ic_load_legacy_validate_silver", "validate_silver.py")
            self._legacy_delegate = module.SilverValidator()

    def run_checks(self) -> bool:
        if self._entity == "case":
            return self._run_case_checks()
        self._ensure_legacy()
        result = self._legacy_delegate.run_checks()
        self.results = list(getattr(self._legacy_delegate, "results", []))
        return result

    def _run_case_checks(self) -> bool:
        sql_path = _CASE_SQL_DIR / "04_silver_validate.sql"
        if not sql_path.exists():
            raise RuntimeError(f"Case validation SQL not found: {sql_path}")

        sql = sql_path.read_text(encoding="utf-8")
        self.results = []

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
                cols = [desc[0] for desc in cur.description] if cur.description is not None else []

        for row in rows:
            d = dict(zip(cols, row))
            self.results.append(_ValidationResult(
                name=d["check_name"],
                passed=bool(d["passed"]),
                severity=d["severity"],
                row_count_failing=int(d["row_count_failing"] or 0),
                notes=d.get("notes", ""),
            ))

        stop_failures = [r for r in self.results if r.severity == "STOP" and not r.passed]
        return len(stop_failures) == 0
