"""Pipeline runtime modules for the ic-load salvage spine."""

from .state import (  # noqa: F401
    PipelineContext,
    PipelineStage,
    StageStatus,
    latest_artifact_for_entity,
    transition,
)
