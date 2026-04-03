from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.state import PipelineContext, PipelineStage, StageStatus, transition


def test_bronze_load_transitions_init_to_bronze_load():
    ctx = PipelineContext(entity="company")
    assert ctx.current_stage == PipelineStage.INIT

    transition(ctx, PipelineStage.BRONZE_LOAD, StageStatus.SUCCESS, row_count=42)

    assert ctx.current_stage == PipelineStage.BRONZE_LOAD
    assert ctx.history[0]["from"] == "INIT"
    assert ctx.history[0]["to"] == "BRONZE_LOAD"
    assert ctx.history[0]["status"] == "SUCCESS"
    assert ctx.history[0]["details"]["row_count"] == 42


def test_failed_transition_writes_artifact():
    ctx = PipelineContext(entity="company")
    tmp_path = Path.cwd() / "artifacts" / "test_state"
    tmp_path.mkdir(parents=True, exist_ok=True)
    with patch("pipeline.state.ARTIFACTS_DIR", tmp_path):
        with pytest.raises(RuntimeError, match="FAILED"):
            transition(ctx, PipelineStage.BRONZE_EXPORT, StageStatus.FAILED, reason="probe")

    assert (tmp_path / f"pipeline_run_company_{ctx.run_id}.json").exists()
    assert ctx.current_stage == PipelineStage.BRONZE_EXPORT
    assert ctx.status == StageStatus.FAILED
