from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Any

from context.config import ARTIFACTS_DIR, load_thresholds as _load_thresholds


class PipelineStage(Enum):
    """Stage boundaries in the pipeline.

    Enum values are sequential integers (via auto()); ordering in this file
    determines execution order. The runner uses `stage.value < resume.value`
    to decide which stages to skip on resume — no hardcoded stage list.

    Order matches IC_Load_Production_Plan.md §5.1 exactly.
    """

    INIT = auto()                           # 1

    # pg functions — Contract A (§7.6)
    PG_FUNCTIONS_INSTALL = auto()           # 2

    # Bronze
    BRONZE_LOAD = auto()                    # 3
    BRONZE_METADATA = auto()                # 4
    BRONZE_WATERMARK = auto()               # 5
    BRONZE_EXPORT = auto()                  # 6

    # Silver
    SILVER_NORMALISE = auto()               # 7
    SILVER_VALIDATE = auto()                # 8

    # Entity-specific pre-gold postprocess (MANIFEST-driven)
    ENTITY_POSTPROCESS_PRE = auto()         # 9

    # Guardrails + Gold
    DEDUPE_GUARD = auto()                   # 16
    GOLD_VALIDATE = auto()                  # 17
    GOLD_UPSERT = auto()                    # 18

    # Sync + Associations
    STACKSYNC_SYNC = auto()                 # 19
    ASSOC_VALIDATE = auto()                 # 20

    # Entity-specific post-assoc postprocess (MANIFEST-driven)
    ENTITY_POSTPROCESS_POST = auto()        # 21

    # Post-run verification (coverage report)
    POST_RUN_VERIFY = auto()                # 22

    COMPLETE = auto()                       # 23
    FAILED = auto()                         # 24


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
