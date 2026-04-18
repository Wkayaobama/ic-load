from __future__ import annotations

from pathlib import Path

from context.config import PROJECT_ROOT
from pipeline.hooks._primitives import run_sql_file

_SILVER_SQL_DIR = PROJECT_ROOT / "sql" / "silver"

_NORMALISE_SCRIPTS: dict[str, Path] = {
    "company":       _SILVER_SQL_DIR / "normalise_company.sql",
    "contact":       _SILVER_SQL_DIR / "normalise_contact.sql",
    "opportunity":   _SILVER_SQL_DIR / "normalise_opportunity.sql",
    "communication": _SILVER_SQL_DIR / "normalise_communication.sql",
}


class SilverNormaliser:
    """Runs the SQL-based silver normalisation script for an entity.

    Each script reads staging.stg_{entity}, applies transformations via
    pg UDFs installed at PG_FUNCTIONS_INSTALL, and writes
    staging.stg_{entity}_normalised.

    Replaces the legacy Python/DuckDB silver_normalise.py approach.
    """

    def __init__(self, entity: str | None = None):
        self._entity = entity

    def _run(self, entity: str) -> None:
        script = _NORMALISE_SCRIPTS.get(entity.lower())
        if script is None:
            raise RuntimeError(
                f"No silver normalisation script for entity {entity!r}. "
                f"Known entities: {list(_NORMALISE_SCRIPTS)}"
            )
        run_sql_file(script)

    def normalise_company(self) -> None:
        self._run("company")

    def normalise_contact(self) -> None:
        self._run("contact")

    def normalise_opportunity(self) -> None:
        self._run("opportunity")

    def normalise_communication(self) -> None:
        self._run("communication")

    def run_all(self) -> None:
        for entity in _NORMALISE_SCRIPTS:
            self._run(entity)


class SilverValidator:
    """Thin salvage wrapper around the proven legacy Silver validator."""

    def __init__(self):
        import importlib.util
        from types import ModuleType

        path = PROJECT_ROOT / "validate_silver.py"
        if not path.exists():
            raise RuntimeError(f"Legacy validator unavailable: {path}")
        spec = importlib.util.spec_from_file_location("ic_load_legacy_validate_silver", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load legacy validator spec for {path}")
        module: ModuleType = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._delegate = module.SilverValidator()

    @property
    def results(self):
        return self._delegate.results

    def run_checks(self) -> bool:
        return self._delegate.run_checks()
