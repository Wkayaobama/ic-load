from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from context.config import (
    DBT_PROJECT_DIR,
    ENTITIES,
    dbt_command,
    latest_bronze_path,
    load_business_rules,
    load_entity_resolution_map,
)
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
    pg_functions_installer: Callable[[bool], dict[str, Any]]
    dbt_runner: Callable[[str, bool], bool]
    dedupe_guarder: Callable[[str, bool], dict[str, Any]]
    gold_upserter: Callable[[str, bool], dict[str, Any]]
    sync_waiter: Callable[[str, bool], dict[str, Any]]
    association_runner: Callable[[str, bool], dict[str, Any]]
    # Preview hooks: execute SELECT portion read-only, emit candidate-row CSVs.
    # Used when the runner is invoked with --preview. No hubspot.* writes.
    gold_previewer: Callable[[str], dict[str, Any]]
    association_previewer: Callable[[str], dict[str, Any]]


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
    from context.db import get_connection
    from pipeline.associations import AssociationBridgeExecutor
    from pipeline.bronze import DuckDBBronzeLoader
    from pipeline.dedupe import DedupeGuardrail
    from pipeline.gold import GoldUpsertExecutor
    from pipeline.hooks.pg_functions import install as install_pg_functions
    from pipeline.silver import SilverNormaliser, SilverValidator
    from pipeline.sync import StackSyncCheckpoint

    # ── Live SQL callables ─────────────────────────────────────────────────
    # Gold upsert and association bridge both render SQL via sql.render.* and
    # need an executor to land INSERTs in Postgres. Previously no callable
    # was passed, so render output was written to disk but never executed —
    # leaving the pipeline's final step a no-op. These two closures provide:
    #
    #   _execute_sql(sql_text) → int       used by .execute(): runs INSERT, returns rowcount
    #   _execute_sql_fetch(sql_text)       used by .preview(): runs SELECT, returns (columns, rows)
    #
    # Both open/commit/close their own transaction; no shared state.
    def _execute_sql(sql_text: str) -> int:
        with get_connection() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(sql_text)
                    rc = cur.rowcount if cur.rowcount is not None else 0
                conn.commit()
                return rc
            except Exception:
                conn.rollback()
                raise

    def _execute_sql_fetch(sql_text: str) -> tuple[list[str], list[tuple]]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_text)
                columns = [d[0] for d in cur.description] if cur.description else []
                rows = cur.fetchall() if cur.description else []
        return columns, rows

    dedupe_guardrail = DedupeGuardrail()
    gold_executor = GoldUpsertExecutor()
    sync_checkpoint = StackSyncCheckpoint()
    assoc_executor = AssociationBridgeExecutor()

    return PipelineHooks(
        bronze_loader_factory=DuckDBBronzeLoader,
        silver_normaliser_factory=SilverNormaliser,
        silver_validator_factory=SilverValidator,
        pg_functions_installer=install_pg_functions,
        dbt_runner=_default_dbt_runner,
        dedupe_guarder=lambda entity, dry_run: dedupe_guardrail.execute(entity, dry_run=dry_run),
        gold_upserter=lambda entity, dry_run: gold_executor.execute(
            entity, dry_run=dry_run, execute_sql=None if dry_run else _execute_sql
        ),
        sync_waiter=lambda entity, dry_run: sync_checkpoint.wait(entity, dry_run=dry_run),
        association_runner=lambda entity, dry_run: assoc_executor.execute(
            entity, dry_run=dry_run, execute_sql=None if dry_run else _execute_sql
        ),
        gold_previewer=lambda entity: gold_executor.preview(entity, execute_sql_fetch=_execute_sql_fetch),
        association_previewer=lambda entity: assoc_executor.preview(entity, execute_sql_fetch=_execute_sql_fetch),
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
    enable_post_gold: bool = False,
    approve_gold: bool = False,
    enable_dedupe_guard: bool = False,
    preview: bool = False,
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
    ctx.metadata["enable_post_gold"] = enable_post_gold
    ctx.metadata["approve_gold"] = approve_gold
    ctx.metadata["enable_dedupe_guard"] = enable_dedupe_guard
    ctx.metadata["preview"] = preview
    ctx.metadata["entity_resolution_map"] = load_entity_resolution_map()
    ctx.metadata["business_rules"] = load_business_rules()

    resume_stage: PipelineStage | None = None
    if resume_from:
        resume_stage = PipelineStage[resume_from.upper()]
        artifact = latest_artifact_for_entity(entity)
        if artifact:
            ctx = PipelineContext.from_artifact(artifact)
        _skip_stages_before(ctx, resume_stage)

    if not assoc_only and _should_run(ctx, PipelineStage.PG_FUNCTIONS_INSTALL, resume_stage):
        _run_pg_functions_install(ctx, dry_run, hooks)

    if assoc_only:
        _skip_stages_before(ctx, PipelineStage.ASSOC_VALIDATE)
        _run_assoc_validate(ctx, entity, dry_run, preview, hooks)
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

    # Gold is the default final boundary for the clean runner. StackSync sync and
    # mirrored associations stay available behind an explicit opt-in.
    _run_dbt(ctx, entity, dry_run, hooks)
    _run_dedupe_guard(ctx, entity, dry_run, probe_mode, enable_dedupe_guard, hooks)
    _run_gold_validate(ctx, entity, dry_run, probe_mode, approve_gold, preview)
    _run_gold_upsert(ctx, entity, dry_run, preview, hooks)

    if not enable_post_gold:
        transition(ctx, PipelineStage.COMPLETE, StageStatus.SUCCESS, reason="gold_upsert_stop")
        _finish(ctx)
        return ctx

    _run_stacksync_sync(ctx, entity, dry_run, hooks)
    _run_assoc_validate(ctx, entity, dry_run, preview, hooks)

    transition(ctx, PipelineStage.COMPLETE, StageStatus.SUCCESS)
    _finish(ctx)
    return ctx


def _run_pg_functions_install(ctx: PipelineContext, dry_run: bool, hooks: PipelineHooks) -> None:
    if dry_run:
        transition(ctx, PipelineStage.PG_FUNCTIONS_INSTALL, StageStatus.SKIPPED, reason="dry_run")
        return
    try:
        result = hooks.pg_functions_installer(dry_run)
    except Exception as exc:
        transition(ctx, PipelineStage.PG_FUNCTIONS_INSTALL, StageStatus.FAILED, reason=str(exc))
    transition(
        ctx,
        PipelineStage.PG_FUNCTIONS_INSTALL,
        StageStatus.SUCCESS,
        installed=result.get("count"),
        duration_s=result.get("duration_s"),
    )


def _run_bronze(
    ctx: PipelineContext,
    entity: str,
    dry_run: bool,
    resume_stage: PipelineStage | None,
    hooks: PipelineHooks,
    bronze_csv_override: str | None,
) -> None:
    # Dry-run contract: touch nothing. Skip all four BRONZE_* stages as a
    # block so a fresh clone without bronze_layer co-located can still
    # validate the stage wiring end-to-end without a CSV lookup or DuckDB
    # load. Previously _run_bronze called latest_bronze_path() first and
    # transitioned to FAILED when it returned None, which killed the
    # pipeline regardless of the dry_run flag.
    if dry_run:
        for stage in (
            PipelineStage.BRONZE_LOAD,
            PipelineStage.BRONZE_METADATA,
            PipelineStage.BRONZE_WATERMARK,
            PipelineStage.BRONZE_EXPORT,
        ):
            if _should_run(ctx, stage, resume_stage):
                transition(ctx, stage, StageStatus.SKIPPED, reason="dry_run")
        return

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
        elif dry_run:
            # Validators query Postgres — skip in dry-run to keep it DB-free.
            transition(ctx, PipelineStage.SILVER_VALIDATE, StageStatus.SKIPPED, reason="dry_run")
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


def _run_dedupe_guard(
    ctx: PipelineContext,
    entity: str,
    dry_run: bool,
    probe_mode: bool,
    enable_dedupe_guard: bool,
    hooks: PipelineHooks,
) -> None:
    if not _should_run(ctx, PipelineStage.DEDUPE_GUARD, None):
        return

    if not enable_dedupe_guard:
        transition(ctx, PipelineStage.DEDUPE_GUARD, StageStatus.SKIPPED, reason="not_enabled")
        return

    if not (dry_run or probe_mode):
        transition(ctx, PipelineStage.DEDUPE_GUARD, StageStatus.SKIPPED, reason="probe_only_guardrail")
        return

    result = hooks.dedupe_guarder(entity, dry_run)
    ctx.metadata["dedupe_guard"] = result

    block_count = int(result.get("block_count", 0))
    review_count = int(result.get("review_count", 0))
    not_applicable = result.get("mode") == "not_applicable"

    if not_applicable:
        transition(ctx, PipelineStage.DEDUPE_GUARD, StageStatus.SKIPPED, reason="not_applicable", entity=entity)
        return

    if block_count > 0:
        transition(
            ctx,
            PipelineStage.DEDUPE_GUARD,
            StageStatus.FAILED,
            block_count=block_count,
            review_count=review_count,
            artifact=result.get("artifact_json"),
        )

    if review_count > 0:
        status = StageStatus.WARNING if dry_run or probe_mode else StageStatus.FAILED
        transition(
            ctx,
            PipelineStage.DEDUPE_GUARD,
            status,
            block_count=block_count,
            review_count=review_count,
            safe_count=result.get("safe_count", 0),
            artifact=result.get("artifact_json"),
        )
        return

    transition(
        ctx,
        PipelineStage.DEDUPE_GUARD,
        StageStatus.SUCCESS,
        block_count=block_count,
        review_count=review_count,
        safe_count=result.get("safe_count", 0),
        artifact=result.get("artifact_json"),
    )


def _run_gold_upsert(ctx: PipelineContext, entity: str, dry_run: bool, preview: bool, hooks: PipelineHooks) -> None:
    if not _should_run(ctx, PipelineStage.GOLD_UPSERT, None):
        return
    if dry_run:
        # Dry-run contract: executor .execute() would still render SQL to
        # sql/rendered/ even with execute_sql=None. Skip the stage entirely
        # so dry-run produces zero filesystem side effects.
        transition(ctx, PipelineStage.GOLD_UPSERT, StageStatus.SKIPPED, reason="dry_run")
        return
    if preview:
        # Preview mode: executes SELECT portion read-only, writes candidate
        # rows to artifacts/ops/gold_preview_*.csv. No hubspot.* INSERT.
        result = hooks.gold_previewer(entity)
    else:
        result = hooks.gold_upserter(entity, dry_run)
    transition(
        ctx,
        PipelineStage.GOLD_UPSERT,
        StageStatus.SUCCESS,
        mode=result.get("mode"),
        statements=len(result.get("statements", [])),
    )


def _run_gold_validate(
    ctx: PipelineContext,
    entity: str,
    dry_run: bool,
    probe_mode: bool,
    approve_gold: bool,
    preview: bool,
) -> None:
    del entity
    if not _should_run(ctx, PipelineStage.GOLD_VALIDATE, None):
        return

    if dry_run:
        transition(ctx, PipelineStage.GOLD_VALIDATE, StageStatus.SKIPPED, reason="dry_run")
        return

    if probe_mode:
        transition(ctx, PipelineStage.GOLD_VALIDATE, StageStatus.SKIPPED, reason="probe_mode")
        return

    if preview:
        # Preview runs SELECT only; the --approve-gold safety gate is only
        # meaningful for actual INSERT execution. Skip it in preview mode.
        transition(ctx, PipelineStage.GOLD_VALIDATE, StageStatus.SKIPPED, reason="preview_mode")
        return

    if not approve_gold:
        transition(
            ctx,
            PipelineStage.GOLD_VALIDATE,
            StageStatus.FAILED,
            reason="explicit_gold_validation_required",
        )

    transition(
        ctx,
        PipelineStage.GOLD_VALIDATE,
        StageStatus.SUCCESS,
        reason="explicit_gold_validation_received",
    )


def _run_stacksync_sync(ctx: PipelineContext, entity: str, dry_run: bool, hooks: PipelineHooks) -> None:
    if not _should_run(ctx, PipelineStage.STACKSYNC_SYNC, None):
        return
    if dry_run:
        # StackSyncCheckpoint.wait hits the DB to verify mirror freshness.
        # Skip in dry-run — we're validating wiring, not mirror state.
        transition(ctx, PipelineStage.STACKSYNC_SYNC, StageStatus.SKIPPED, reason="dry_run")
        return
    try:
        result = hooks.sync_waiter(entity, dry_run)
    except Exception as exc:
        transition(ctx, PipelineStage.STACKSYNC_SYNC, StageStatus.FAILED, reason=str(exc))
    status = StageStatus.SUCCESS if result.get("synced", True) or result.get("mode") == "dry_run" else StageStatus.WARNING
    transition(ctx, PipelineStage.STACKSYNC_SYNC, status, **result)


def _run_assoc_validate(ctx: PipelineContext, entity: str, dry_run: bool, preview: bool, hooks: PipelineHooks) -> None:
    if not _should_run(ctx, PipelineStage.ASSOC_VALIDATE, None):
        return
    if dry_run:
        # Dry-run contract: AssociationBridgeExecutor.execute() still renders
        # SQL to sql/rendered/ even with execute_sql=None. Skip entirely.
        transition(ctx, PipelineStage.ASSOC_VALIDATE, StageStatus.SKIPPED, reason="dry_run")
        return
    if preview:
        # Preview mode: executes Pass-A-UNION-Pass-B SELECT read-only, writes
        # candidate associations to artifacts/ops/assoc_preview_*.csv.
        # No hubspot.associations_*_* INSERT.
        result = hooks.association_previewer(entity)
    else:
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
        PipelineStage.PG_FUNCTIONS_INSTALL,
        PipelineStage.BRONZE_LOAD,
        PipelineStage.BRONZE_METADATA,
        PipelineStage.BRONZE_WATERMARK,
        PipelineStage.BRONZE_EXPORT,
        PipelineStage.SILVER_NORMALISE,
        PipelineStage.SILVER_VALIDATE,
        PipelineStage.DBT_BUILD,
        PipelineStage.DEDUPE_GUARD,
        PipelineStage.GOLD_VALIDATE,
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
    parser.add_argument("--enable-post-gold", action="store_true")
    parser.add_argument("--approve-gold", action="store_true")
    parser.add_argument("--enable-dedupe-guard", action="store_true")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Execute SELECT portion of gold upsert / association bridge read-only; "
             "write candidate rows to artifacts/ops/. No hubspot.* writes. "
             "Skips --approve-gold gate (only relevant for real INSERTs).",
    )
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
        enable_post_gold=args.enable_post_gold,
        approve_gold=args.approve_gold,
        enable_dedupe_guard=args.enable_dedupe_guard,
        preview=args.preview,
        bronze_csv_override=args.bronze_csv_override,
    )
