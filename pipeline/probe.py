from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from pipeline.runner import PipelineHooks, run


class _ProbeBronzeLoader:
    def load_csv_to_duckdb(self, csv_path: str, table_name: str) -> int:
        del csv_path, table_name
        return 3

    def add_bronze_metadata(self, table_name: str, source_file: str) -> None:
        del table_name, source_file

    def _tag_load_status(self, duckdb_table: str, pk_col: str) -> dict[str, int]:
        del duckdb_table, pk_col
        return {"NEW": 1, "MODIFIED": 1, "UNCHANGED": 1}

    def export_to_postgres(self, duckdb_table: str, postgres_table: str) -> int:
        del duckdb_table, postgres_table
        return 3


class _ProbeNormaliser:
    def normalise_company(self) -> int:
        return 3

    def normalise_communication(self) -> int:
        return 4

    def run_all(self) -> dict[str, int]:
        return {"company": 3, "communication": 4}


@dataclass
class _ProbeCheckResult:
    name: str
    severity: str
    passed: bool


class _ProbeValidator:
    def __init__(self, *, warning_only: bool = False):
        self.results = []
        if warning_only:
            self.results.append(_ProbeCheckResult(name="owner.unresolved", severity="WARN", passed=False))

    def run_checks(self) -> bool:
        return not any(result.severity == "STOP" and not result.passed for result in self.results)


def make_probe_hooks(*, warning_only: bool = False) -> PipelineHooks:
    """Build a remote-safe orchestration probe that avoids live external writes."""
    return PipelineHooks(
        bronze_loader_factory=_ProbeBronzeLoader,
        silver_normaliser_factory=_ProbeNormaliser,
        silver_validator_factory=lambda: _ProbeValidator(warning_only=warning_only),
        dbt_runner=lambda entity, dry_run: True,
        gold_upserter=lambda entity, dry_run: {"entity": entity, "mode": "probe", "statements": [{"file": "probe.sql"}]},
        sync_waiter=lambda entity, dry_run: {"entity": entity, "synced": True, "mode": "probe"},
        association_runner=lambda entity, dry_run: {"entity": entity, "mode": "probe", "statements": [{"file": "probe_assoc.sql"}]},
    )


def run_orchestration_probe(entity: str = "company", *, warning_only: bool = False) -> Any:
    """Exercise the full stage contract without requiring a live database or StackSync sync."""
    return run(
        entity=entity,
        dry_run=False,
        probe_mode=True,
        hooks=make_probe_hooks(warning_only=warning_only),
        bronze_csv_override="probe.csv",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ic-load orchestration probe.")
    parser.add_argument("--entity", default="company")
    parser.add_argument("--warning-only", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_orchestration_probe(entity=args.entity, warning_only=args.warning_only)
