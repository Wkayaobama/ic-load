from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.probe import make_probe_hooks
from pipeline.runner import PipelineHooks, run


@dataclass
class _StopResult:
    name: str
    severity: str
    passed: bool


class _StopValidator:
    def __init__(self):
        self.results = [_StopResult(name="company.row_count", severity="STOP", passed=False)]

    def run_checks(self) -> bool:
        return False


def test_warning_only_probe_reaches_dbt_gold_sync_and_assoc():
    tmp_path = Path.cwd() / "artifacts" / "test_probe_warning"
    tmp_path.mkdir(parents=True, exist_ok=True)
    hooks = make_probe_hooks(warning_only=True)
    with patch("pipeline.state.ARTIFACTS_DIR", tmp_path):
        ctx = run(
            entity="company",
            dry_run=False,
            probe_mode=True,
            hooks=hooks,
            bronze_csv_override="probe.csv",
        )

    stages = [entry["to"] for entry in ctx.history]
    assert "ENTITY_POSTPROCESS_PRE" in stages
    assert "GOLD_UPSERT" in stages
    assert "STACKSYNC_SYNC" in stages
    assert "ASSOC_VALIDATE" in stages
    assert stages.index("GOLD_UPSERT") < stages.index("STACKSYNC_SYNC") < stages.index("ASSOC_VALIDATE")

    silver_record = next(entry for entry in ctx.history if entry["to"] == "SILVER_VALIDATE")
    assert silver_record["status"] == "WARNING"

    assert (tmp_path / f"pipeline_run_company_{ctx.run_id}.json").exists()


def test_stop_validation_prevents_dbt_gold_sync_and_assoc():
    tmp_path = Path.cwd() / "artifacts" / "test_probe_stop"
    tmp_path.mkdir(parents=True, exist_ok=True)
    probe_hooks = make_probe_hooks()
    hooks = PipelineHooks(
        bronze_loader_factory=probe_hooks.bronze_loader_factory,
        silver_normaliser_factory=probe_hooks.silver_normaliser_factory,
        silver_validator_factory=_StopValidator,
        pg_functions_installer=probe_hooks.pg_functions_installer,
        entity_postprocessor=probe_hooks.entity_postprocessor,
        dedupe_guarder=probe_hooks.dedupe_guarder,
        gold_upserter=probe_hooks.gold_upserter,
        sync_waiter=probe_hooks.sync_waiter,
        association_runner=probe_hooks.association_runner,
        post_run_verifier=probe_hooks.post_run_verifier,
        sql_file_runner=probe_hooks.sql_file_runner,
    )

    with patch("pipeline.state.ARTIFACTS_DIR", tmp_path):
        with pytest.raises(RuntimeError, match="FAILED"):
            run(
                entity="company",
                dry_run=False,
                probe_mode=True,
                hooks=hooks,
                bronze_csv_override="probe.csv",
            )

    assert any(tmp_path.glob("pipeline_run_company_*.json"))


def test_resume_from_silver_normalise_skips_bronze_stages():
    tmp_path = Path.cwd() / "artifacts" / "test_probe_resume"
    tmp_path.mkdir(parents=True, exist_ok=True)
    hooks = make_probe_hooks()
    with patch("pipeline.state.ARTIFACTS_DIR", tmp_path):
        ctx = run(
            entity="company",
            resume_from="SILVER_NORMALISE",
            probe_mode=True,
            hooks=hooks,
        )

    skipped = {entry["to"] for entry in ctx.history if entry["status"] == "SKIPPED"}
    assert {"BRONZE_LOAD", "BRONZE_METADATA", "BRONZE_WATERMARK", "BRONZE_EXPORT"}.issubset(skipped)


def test_communication_probe_reaches_sync_before_associations():
    tmp_path = Path.cwd() / "artifacts" / "test_probe_communication"
    tmp_path.mkdir(parents=True, exist_ok=True)
    hooks = make_probe_hooks()
    with patch("pipeline.state.ARTIFACTS_DIR", tmp_path):
        ctx = run(
            entity="communication",
            probe_mode=True,
            hooks=hooks,
            bronze_csv_override="probe.csv",
        )

    stages = [entry["to"] for entry in ctx.history]
    assert stages.index("STACKSYNC_SYNC") < stages.index("ASSOC_VALIDATE")
