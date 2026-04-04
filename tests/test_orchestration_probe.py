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


def test_warning_only_probe_reaches_dbt_and_stops_at_gold():
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
    assert "DBT_BUILD" in stages
    assert "DEDUPE_GUARD" in stages
    assert "GOLD_VALIDATE" in stages
    assert "GOLD_UPSERT" in stages
    assert "STACKSYNC_SYNC" not in stages
    assert "ASSOC_VALIDATE" not in stages
    assert stages.index("DEDUPE_GUARD") < stages.index("GOLD_VALIDATE") < stages.index("GOLD_UPSERT")

    silver_record = next(entry for entry in ctx.history if entry["to"] == "SILVER_VALIDATE")
    assert silver_record["status"] == "WARNING"
    gold_validate_record = next(entry for entry in ctx.history if entry["to"] == "GOLD_VALIDATE")
    assert gold_validate_record["status"] == "SKIPPED"
    assert gold_validate_record["details"]["reason"] == "probe_mode"
    complete_record = next(entry for entry in ctx.history if entry["to"] == "COMPLETE")
    assert complete_record["details"]["reason"] == "gold_upsert_stop"

    assert (tmp_path / f"pipeline_run_company_{ctx.run_id}.json").exists()


def test_stop_validation_prevents_dbt_and_gold():
    tmp_path = Path.cwd() / "artifacts" / "test_probe_stop"
    tmp_path.mkdir(parents=True, exist_ok=True)
    probe_hooks = make_probe_hooks()
    hooks = PipelineHooks(
        bronze_loader_factory=probe_hooks.bronze_loader_factory,
        silver_normaliser_factory=probe_hooks.silver_normaliser_factory,
        silver_validator_factory=_StopValidator,
        dbt_runner=probe_hooks.dbt_runner,
        dedupe_guarder=probe_hooks.dedupe_guarder,
        gold_upserter=probe_hooks.gold_upserter,
        sync_waiter=probe_hooks.sync_waiter,
        association_runner=probe_hooks.association_runner,
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


def test_communication_probe_stops_at_gold_by_default():
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
    assert "GOLD_VALIDATE" in stages
    assert "STACKSYNC_SYNC" not in stages
    assert "ASSOC_VALIDATE" not in stages
    assert "GOLD_UPSERT" in stages


def test_probe_warning_only_dedupe_still_allows_gold_stage():
    tmp_path = Path.cwd() / "artifacts" / "test_probe_dedupe_warning"
    tmp_path.mkdir(parents=True, exist_ok=True)
    hooks = make_probe_hooks(warning_only=True)
    with patch("pipeline.state.ARTIFACTS_DIR", tmp_path):
        ctx = run(
            entity="contact",
            probe_mode=True,
            hooks=hooks,
            bronze_csv_override="probe.csv",
        )

    dedupe_record = next(entry for entry in ctx.history if entry["to"] == "DEDUPE_GUARD")
    assert dedupe_record["status"] == "WARNING"
    stages = [entry["to"] for entry in ctx.history]
    assert stages.index("DEDUPE_GUARD") < stages.index("GOLD_VALIDATE") < stages.index("GOLD_UPSERT")


def test_dedupe_block_prevents_gold_stage():
    tmp_path = Path.cwd() / "artifacts" / "test_probe_dedupe_block"
    tmp_path.mkdir(parents=True, exist_ok=True)
    probe_hooks = make_probe_hooks()
    hooks = PipelineHooks(
        bronze_loader_factory=probe_hooks.bronze_loader_factory,
        silver_normaliser_factory=probe_hooks.silver_normaliser_factory,
        silver_validator_factory=probe_hooks.silver_validator_factory,
        dbt_runner=probe_hooks.dbt_runner,
        dedupe_guarder=lambda entity, dry_run: {
            "entity": entity,
            "mode": "probe",
            "block_count": 2,
            "review_count": 0,
            "safe_count": 0,
            "artifact_json": "dedupe_block.json",
        },
        gold_upserter=probe_hooks.gold_upserter,
        sync_waiter=probe_hooks.sync_waiter,
        association_runner=probe_hooks.association_runner,
    )

    with patch("pipeline.state.ARTIFACTS_DIR", tmp_path):
        with pytest.raises(RuntimeError, match="FAILED"):
            run(
                entity="company",
                probe_mode=True,
                hooks=hooks,
                bronze_csv_override="probe.csv",
            )


def test_live_mode_requires_explicit_gold_validation():
    tmp_path = Path.cwd() / "artifacts" / "test_probe_gold_validation"
    tmp_path.mkdir(parents=True, exist_ok=True)
    hooks = make_probe_hooks()
    with patch("pipeline.state.ARTIFACTS_DIR", tmp_path):
        with pytest.raises(RuntimeError, match="explicit_gold_validation_required"):
            run(
                entity="company",
                probe_mode=False,
                hooks=hooks,
                bronze_csv_override="probe.csv",
            )


def test_live_mode_gold_can_run_after_explicit_validation():
    tmp_path = Path.cwd() / "artifacts" / "test_probe_gold_validation_approved"
    tmp_path.mkdir(parents=True, exist_ok=True)
    hooks = make_probe_hooks()
    with patch("pipeline.state.ARTIFACTS_DIR", tmp_path):
        ctx = run(
            entity="company",
            probe_mode=False,
            approve_gold=True,
            hooks=hooks,
            bronze_csv_override="probe.csv",
        )

    gold_validate_record = next(entry for entry in ctx.history if entry["to"] == "GOLD_VALIDATE")
    assert gold_validate_record["status"] == "SUCCESS"
    assert gold_validate_record["details"]["reason"] == "explicit_gold_validation_received"
    assert "GOLD_UPSERT" in [entry["to"] for entry in ctx.history]


def test_enable_post_gold_allows_sync_and_associations():
    tmp_path = Path.cwd() / "artifacts" / "test_probe_post_gold"
    tmp_path.mkdir(parents=True, exist_ok=True)
    hooks = make_probe_hooks()
    with patch("pipeline.state.ARTIFACTS_DIR", tmp_path):
        ctx = run(
            entity="company",
            probe_mode=True,
            enable_post_gold=True,
            hooks=hooks,
            bronze_csv_override="probe.csv",
        )

    stages = [entry["to"] for entry in ctx.history]
    assert stages.index("GOLD_VALIDATE") < stages.index("GOLD_UPSERT") < stages.index("STACKSYNC_SYNC") < stages.index("ASSOC_VALIDATE")
