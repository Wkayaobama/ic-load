from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from context.config import DBT_PROJECT_DIR, ENTITIES, dbt_command, latest_bronze_path
from pipeline.state import (
    PipelineContext,
    PipelineStage,
    StageStatus,
    latest_artifact_for_entity,
    load_thresholds,
    transition,
)


@dataclass
class PipelineHooks:
    """Inject the live or probe implementations behind each stage boundary."""

    bronze_loader_factory: Callable[[], Any]
    silver_normaliser_factory: Callable[[], Any]
    silver_validator_factory: Callable[[], Any]
    dbt_runner: Callable[[str, bool], bool]
    gold_upserter: Callable[[str, bool], dict[str, Any]]
    sync_waiter: Callable[[str, bool], dict[str, Any]]
    association_runner: Callable[[str, bool], dict[str, Any]]


def _default_dbt_runner(entity: str, dry_run: bool) -> bool:
    del entity
    if dry_run:
        return True
    command = dbt_command()
    if command is None:
        raise RuntimeError("dbt boundary is not configured. Set ICALPS_DBT_COMMAND or inject a dbt hook.")
    completed = subprocess.run(command, cwd=DBT_PROJECT_DIR, check=False)
    return completed.returncode == 0


def build_default_hooks() -> PipelineHooks:
    from pipeline.associations import AssociationBridgeExecutor
    from pipeline.bronze import DuckDBBronzeLoader
    from pipeline.gold import GoldUpsertExecutor
    from pipeline.silver import SilverNormaliser, SilverValidator
    from pipeline.sync import StackSyncCheckpoint

    gold_executor = GoldUpsertExecutor()
    sync_checkpoint = StackSyncCheckpoint()
    assoc_executor = AssociationBridgeExecutor()

    return PipelineHooks(
        bronze_loader_factory=DuckDBBronzeLoader,
        silver_normaliser_factory=SilverNormaliser,
        silver_validator_factory=SilverValidator,
        dbt_runner=_default_dbt_runner,
        gold_upserter=lambda entity, dry_run: gold_executor.execute(entity, dry_run=dry_run),
        sync_waiter=lambda entity, dry_run: sync_checkpoint.wait(entity, dry_run=dry_run),
        association_runner=lambda entity, dry_run: assoc_executor.execute(entity, dry_run=dry_run),
    )


def run(
    entity: str = "company",
    dry_run: bool = False,
    resume_from: str | None = None,
    skip_validation: bool = False,
    bronze_only: bool = False,
    silver_only: bool = False,
    dbt_only: bool = False,
    assoc_only: bool = False,
    verbosity: str = "low",
    probe_mode: bool = False,
    hooks: PipelineHooks | None = None,
    bronze_csv_override: str | None = None,
) -> PipelineContext:
    """Execute the salvage runner while keeping each major boundary explicit."""
    hooks = hooks or build_default_hooks()
    ctx = PipelineContext(entity=entity)
    thresholds = load_thresholds(entity)
    owner_blocking = thresholds.get("owner_resolution_blocking", False)
    ctx.metadata["thresholds"] = thresholds
    ctx.metadata["probe_mode"] = probe_mode

    resume_stage: PipelineStage | None = None
    if resume_from:
        resume_stage = PipelineStage[resume_from.upper()]
        artifact = latest_artifact_for_entity(entity)
        if artifact:
            ctx = PipelineContext.from_artifact(artifact)
        _skip_stages_before(ctx, resume_stage)

    if assoc_only:
        _skip_stages_before(ctx, PipelineStage.ASSOC_VALIDATE)
        _run_assoc_validate(ctx, entity, dry_run, hooks)
        transition(ctx, PipelineStage.COMPLETE, StageStatus.SUCCESS, reason="assoc_only_stop")
        _finish(ctx)
        return ctx

    if not dbt_only and not _already_past(ctx, PipelineStage.BRONZE_EXPORT):
        _run_bronze(ctx, entity, dry_run, resume_stage, hooks, bronze_csv_override)

    if bronze_only:
        transition(ctx, PipelineStage.COMPLETE, StageStatus.SUCCESS, reason="bronze_only_stop")
        _finish(ctx)
        return ctx

    if not dbt_only and not _already_past(ctx, PipelineStage.SILVER_VALIDATE):
        _run_silver(ctx, entity, dry_run, skip_validation, owner_blocking, verbosity, hooks)

    if silver_only:
        transition(ctx, PipelineStage.COMPLETE, StageStatus.SUCCESS, reason="silver_only_stop")
        _finish(ctx)
        return ctx

    # Keep the downstream write path intentionally split so remote collaborators
    # can see where dbt ends, Gold begins, StackSync sync happens, and associations follow.
    _run_dbt(ctx, entity, dry_run, hooks)
    _run_gold_upsert(ctx, entity, dry_run, hooks)
    _run_stacksync_sync(ctx, entity, dry_run, hooks)
    _run_assoc_validate(ctx, entity, dry_run, hooks)

    transition(ctx, PipelineStage.COMPLETE, StageStatus.SUCCESS)
    _finish(ctx)
    return ctx


def _run_bronze(
    ctx: PipelineContext,
    entity: str,
    dry_run: bool,
    resume_stage: PipelineStage | None,
    hooks: PipelineHooks,
    bronze_csv_override: str | None,
) -> None:
    loader = hooks.bronze_loader_factory()
    entity_cfg = ENTITIES.get(entity)
    if entity_cfg is None:
        raise RuntimeError(f"Entity {entity!r} not found in ENTITIES config.")

    csv_path = Path(bronze_csv_override) if bronze_csv_override else latest_bronze_path(entity)
    if csv_path is None:
        transition(ctx, PipelineStage.BRONZE_LOAD, StageStatus.FAILED, reason="no_bronze_csv_found", entity=entity)

    if _should_run(ctx, PipelineStage.BRONZE_LOAD, resume_stage):
        try:
            rows = loader.load_csv_to_duckdb(str(csv_path), f"bronze_{entity}")
        except Exception as exc:
            transition(ctx, PipelineStage.BRONZE_LOAD, StageStatus.FAILED, reason=str(exc))
        transition(ctx, PipelineStage.BRONZE_LOAD, StageStatus.SUCCESS, row_count=rows, csv=str(csv_path))

    if _should_run(ctx, PipelineStage.BRONZE_METADATA, resume_stage):
        try:
            loader.add_bronze_metadata(f"bronze_{entity}", str(csv_path))
        except Exception as exc:
            transition(ctx, PipelineStage.BRONZE_METADATA, StageStatus.FAILED, reason=str(exc))
        transition(ctx, PipelineStage.BRONZE_METADATA, StageStatus.SUCCESS)

    if _should_run(ctx, PipelineStage.BRONZE_WATERMARK, resume_stage):
        try:
            counts = loader._tag_load_status(f"bronze_{entity}", entity_cfg.primary_key)
        except Exception as exc:
            transition(ctx, PipelineStage.BRONZE_WATERMARK, StageStatus.FAILED, reason=str(exc))
        transition(ctx, PipelineStage.BRONZE_WATERMARK, StageStatus.SUCCESS, **counts)

    if _should_run(ctx, PipelineStage.BRONZE_EXPORT, resume_stage):
        if dry_run:
            transition(ctx, PipelineStage.BRONZE_EXPORT, StageStatus.SKIPPED, reason="dry_run")
        else:
            try:
                exported = loader.export_to_postgres(f"bronze_{entity}", entity_cfg.staging_table)
            except Exception as exc:
                transition(ctx, PipelineStage.BRONZE_EXPORT, StageStatus.FAILED, reason=str(exc))
            transition(ctx, PipelineStage.BRONZE_EXPORT, StageStatus.SUCCESS, exported=exported)


def _run_silver(
    ctx: PipelineContext,
    entity: str,
    dry_run: bool,
    skip_validation: bool,
    owner_blocking: bool,
    verbosity: str,
    hooks: PipelineHooks,
) -> None:
    if _should_run(ctx, PipelineStage.SILVER_NORMALISE, None):
        if dry_run:
            transition(ctx, PipelineStage.SILVER_NORMALISE, StageStatus.SKIPPED, reason="dry_run")
        else:
            try:
                normaliser = hooks.silver_normaliser_factory()
                method_name = f"normalise_{entity}"
                if hasattr(normaliser, method_name):
                    getattr(normaliser, method_name)()
                else:
                    normaliser.run_all()
            except Exception as exc:
                transition(ctx, PipelineStage.SILVER_NORMALISE, StageStatus.FAILED, reason=str(exc))
            transition(ctx, PipelineStage.SILVER_NORMALISE, StageStatus.SUCCESS)

    if _should_run(ctx, PipelineStage.SILVER_VALIDATE, None):
        if skip_validation:
            transition(ctx, PipelineStage.SILVER_VALIDATE, StageStatus.SKIPPED, reason="skip_validation_flag")
        else:
            _run_silver_validate(ctx, owner_blocking, verbosity, hooks)


def _run_silver_validate(ctx: PipelineContext, owner_blocking: bool, verbosity: str, hooks: PipelineHooks) -> None:
    validator = hooks.silver_validator_factory()
    validator.run_checks()

    if verbosity == "high":
        for result in validator.results:
            print(f"    {result}")

    stop_failures = [result for result in validator.results if result.severity == "STOP" and not result.passed]
    warn_failures = [result for result in validator.results if result.severity == "WARN" and not result.passed]
    owner_warns = [result for result in warn_failures if "owner" in result.name.lower()]

    ctx.metadata["validation"] = {
        "stop_count": len(stop_failures),
        "warn_count": len(warn_failures),
        "owner_warn_count": len(owner_warns),
        "stop_check_names": [result.name for result in stop_failures],
        "warn_check_names": [result.name for result in warn_failures],
    }

    if stop_failures:
        transition(
            ctx,
            PipelineStage.SILVER_VALIDATE,
            StageStatus.FAILED,
            stop_count=len(stop_failures),
            checks=[result.name for result in stop_failures],
        )

    if owner_warns and owner_blocking:
        transition(
            ctx,
            PipelineStage.SILVER_VALIDATE,
            StageStatus.FAILED,
            reason="owner_resolution_blocking_mode",
            owner_warn_count=len(owner_warns),
        )

    if warn_failures:
        transition(ctx, PipelineStage.SILVER_VALIDATE, StageStatus.WARNING, warn_count=len(warn_failures))
    else:
        transition(ctx, PipelineStage.SILVER_VALIDATE, StageStatus.SUCCESS)


def _run_dbt(ctx: PipelineContext, entity: str, dry_run: bool, hooks: PipelineHooks) -> None:
    if not _should_run(ctx, PipelineStage.DBT_BUILD, None):
        return
    if dry_run:
        transition(ctx, PipelineStage.DBT_BUILD, StageStatus.SKIPPED, reason="dry_run")
        return
    ok = hooks.dbt_runner(entity, dry_run)
    if not ok:
        transition(ctx, PipelineStage.DBT_BUILD, StageStatus.FAILED, reason="dbt_run_nonzero_exit")
    transition(ctx, PipelineStage.DBT_BUILD, StageStatus.SUCCESS)


def _run_gold_upsert(ctx: PipelineContext, entity: str, dry_run: bool, hooks: PipelineHooks) -> None:
    if not _should_run(ctx, PipelineStage.GOLD_UPSERT, None):
        return
    result = hooks.gold_upserter(entity, dry_run)
    transition(
        ctx,
        PipelineStage.GOLD_UPSERT,
        StageStatus.SUCCESS,
        mode=result.get("mode"),
        statements=len(result.get("statements", [])),
    )


def _run_stacksync_sync(ctx: PipelineContext, entity: str, dry_run: bool, hooks: PipelineHooks) -> None:
    if not _should_run(ctx, PipelineStage.STACKSYNC_SYNC, None):
        return
    try:
        result = hooks.sync_waiter(entity, dry_run)
    except Exception as exc:
        transition(ctx, PipelineStage.STACKSYNC_SYNC, StageStatus.FAILED, reason=str(exc))
    status = StageStatus.SUCCESS if result.get("synced", True) or result.get("mode") == "dry_run" else StageStatus.WARNING
    transition(ctx, PipelineStage.STACKSYNC_SYNC, status, **result)


def _run_assoc_validate(ctx: PipelineContext, entity: str, dry_run: bool, hooks: PipelineHooks) -> None:
    if not _should_run(ctx, PipelineStage.ASSOC_VALIDATE, None):
        return
    result = hooks.association_runner(entity, dry_run)
    transition(
        ctx,
        PipelineStage.ASSOC_VALIDATE,
        StageStatus.SUCCESS if result.get("mode") != "error" else StageStatus.WARNING,
        mode=result.get("mode"),
        statements=len(result.get("statements", [])),
    )


def _skip_stages_before(ctx: PipelineContext, resume_stage: PipelineStage) -> None:
    ordered = [
        PipelineStage.BRONZE_LOAD,
        PipelineStage.BRONZE_METADATA,
        PipelineStage.BRONZE_WATERMARK,
        PipelineStage.BRONZE_EXPORT,
        PipelineStage.SILVER_NORMALISE,
        PipelineStage.SILVER_VALIDATE,
        PipelineStage.DBT_BUILD,
        PipelineStage.GOLD_UPSERT,
        PipelineStage.STACKSYNC_SYNC,
        PipelineStage.ASSOC_VALIDATE,
    ]
    for stage in ordered:
        if stage.value < resume_stage.value:
            transition(ctx, stage, StageStatus.SKIPPED, reason="resume")


def _should_run(ctx: PipelineContext, stage: PipelineStage, resume_stage: PipelineStage | None) -> bool:
    del resume_stage
    executed = {history["to"] for history in ctx.history}
    return stage.name not in executed


def _already_past(ctx: PipelineContext, stage: PipelineStage) -> bool:
    return stage.name in {history["to"] for history in ctx.history}


def _finish(ctx: PipelineContext) -> None:
    artifact = ctx.save_artifact()
    print(f"\n  Pipeline run {ctx.status.name}. Artifact: {artifact.name}")
    print(f"  Stages executed: {', '.join(h['to'] + '(' + h['status'][0] + ')' for h in ctx.history)}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Controlled IC'ALPS salvage runner.")
    parser.add_argument("--entity", default="company")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume-from")
    parser.add_argument("--skip-validation", action="store_true")
    parser.add_argument("--bronze-only", action="store_true")
    parser.add_argument("--silver-only", action="store_true")
    parser.add_argument("--dbt-only", action="store_true")
    parser.add_argument("--assoc-only", action="store_true")
    parser.add_argument("--verbosity", choices=["high", "low"], default="low")
    parser.add_argument("--probe-mode", action="store_true")
    parser.add_argument("--bronze-csv-override")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run(
        entity=args.entity,
        dry_run=args.dry_run,
        resume_from=args.resume_from,
        skip_validation=args.skip_validation,
        bronze_only=args.bronze_only,
        silver_only=args.silver_only,
        dbt_only=args.dbt_only,
        assoc_only=args.assoc_only,
        verbosity=args.verbosity,
        probe_mode=args.probe_mode,
        bronze_csv_override=args.bronze_csv_override,
    )
