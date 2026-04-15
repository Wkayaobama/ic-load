from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any

from context.config import ARTIFACTS_DIR, load_thresholds as _load_thresholds


class PipelineStage(Enum):
    """Stage boundaries in the pipeline.

    Legacy stages (SILVER_NORMALISE, DBT_BUILD) are retained for backwards
    compatibility with the existing runner.py. They are deprecated and
    will be removed in Phase 2 of the migration plan (see
    IC_Load_Production_Plan.md §11 Phase 2) once runner.py is rewired
    to use the finer-grained DBT_* stages.

    New stages introduced in Phase 1 scaffolding align with the hooks
    defined in pipeline/hooks/ (one-to-one mapping; see §7.3 and §7.4
    of the plan).
    """

    INIT = auto()

    # Phase 1 NEW — pg functions install (Contract A, §7.6)
    PG_FUNCTIONS_INSTALL = auto()

    # Bronze
    BRONZE_LOAD = auto()
    BRONZE_METADATA = auto()
    BRONZE_WATERMARK = auto()
    BRONZE_EXPORT = auto()

    # Silver
    SILVER_NORMALISE = auto()  # DEPRECATED — replaced by DBT_STAGING + DBT_INTERMEDIATE
    SILVER_VALIDATE = auto()

    # dbt — Phase 1 NEW (replaces monolithic DBT_BUILD)
    DBT_STAGING = auto()
    DBT_INTERMEDIATE = auto()
    DBT_TEST_SILVER = auto()
    DBT_MARTS = auto()
    DBT_TEST_MARTS = auto()
    DBT_BUILD = auto()  # DEPRECATED — kept for backwards compat

    # Entity postprocess — Phase 1 NEW (MANIFEST-driven dispatcher)
    ENTITY_POSTPROCESS_PRE = auto()
    ENTITY_POSTPROCESS_POST = auto()

    # Guardrails + Gold
    DEDUPE_GUARD = auto()
    GOLD_VALIDATE = auto()
    GOLD_UPSERT = auto()

    # Sync + Associations
    STACKSYNC_SYNC = auto()
    ASSOC_VALIDATE = auto()

    # Phase 1 NEW — post-run verification
    POST_RUN_VERIFY = auto()

    COMPLETE = auto()
    FAILED = auto()


class StageStatus(Enum):
    SUCCESS = auto()
    WARNING = auto()
    SKIPPED = auto()
    FAILED = auto()


class PipelineContext:
    def __init__(self, entity: str):
        self.entity = entity
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.current_stage = PipelineStage.INIT
        self.status = StageStatus.SUCCESS
        self.history: list[dict[str, Any]] = []
        self.metadata: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "run_id": self.run_id,
            "current_stage": self.current_stage.name,
            "status": self.status.name,
            "history": self.history,
            "metadata": self.metadata,
        }

    def save_artifact(self) -> Path:
        path = ARTIFACTS_DIR / f"pipeline_run_{self.entity}_{self.run_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        return path

    @classmethod
    def from_artifact(cls, path: Path) -> "PipelineContext":
        data = json.loads(path.read_text(encoding="utf-8"))
        ctx = cls(entity=data["entity"])
        ctx.run_id = data["run_id"]
        ctx.current_stage = PipelineStage[data["current_stage"]]
        ctx.status = StageStatus[data["status"]]
        ctx.history = data.get("history", [])
        ctx.metadata = data.get("metadata", {})
        return ctx


def transition(ctx: PipelineContext, to_stage: PipelineStage, status: StageStatus, **details: Any) -> None:
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "from": ctx.current_stage.name,
        "to": to_stage.name,
        "status": status.name,
    }
    if details:
        record["details"] = details

    ctx.history.append(record)
    ctx.current_stage = to_stage

    if status == StageStatus.FAILED:
        ctx.status = StageStatus.FAILED
        ctx.save_artifact()
        raise RuntimeError(
            f"[{ctx.entity}] stage {to_stage.name} FAILED. "
            f"Details: {details}. "
            f"Artifact: artifacts/pipeline_run_{ctx.entity}_{ctx.run_id}.json"
        )

    if status == StageStatus.WARNING and ctx.status != StageStatus.FAILED:
        ctx.status = StageStatus.WARNING

    detail_str = "  " + "  ".join(f"{key}={value}" for key, value in details.items()) if details else ""
    print(f"  [{status.name:7}]  {ctx.current_stage.name}{detail_str}")


def load_thresholds(entity: str) -> dict[str, Any]:
    return _load_thresholds(entity)


def latest_artifact_for_entity(entity: str) -> Path | None:
    candidates = sorted(ARTIFACTS_DIR.glob(f"pipeline_run_{entity}_*.json"))
    return candidates[-1] if candidates else None
