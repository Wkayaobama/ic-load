"""Per-entity pipeline executor.

Phase 2: PipelineHooks and build_default_hooks imported from pipeline.hooks.
Phase 3: DBT_BUILD monolithic transition replaced by the five granular dbt
stages (DBT_STAGING, DBT_INTERMEDIATE, DBT_TEST_SILVER, DBT_MARTS,
DBT_TEST_MARTS). Added PG_FUNCTIONS_INSTALL at run start, ENTITY_POSTPROCESS
before/after marts+assoc, and POST_RUN_VERIFY at run end.

Hooks that have no implementation yet (pg_functions.install,
entity_postprocess.dispatch, post_run_verify.verify) raise
NotImplementedError; the runner catches this and transitions to SKIPPED
with reason='hook_not_implemented_yet'. This keeps the full state machine
visible in artifacts while Phase 4+ fills in the bodies.

See IC_Load_Production_Plan.md §5.1 for the stage sequence.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Literal

from context.config import (
    ENTITIES,
    latest_bronze_path,
    load_business_rules,
    load_entity_resolution_map,
    resolve_dbt_selector,
)
from pipeline.hooks import PipelineHooks, build_default_hooks
from pipeline.state import (
    PipelineContext,
    PipelineStage,
    StageStatus,
    latest_artifact_for_entity,
    load_thresholds,
    transition,
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
    ctx.metadata["entity_resolution_map"] = load_entity_resolution_map()
    ctx.metadata["business_rules"] = load_business_rules()

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

    # PG_FUNCTIONS_INSTALL runs once per run invocation (Contract A, §7.6).
    # Harmless repeat when the orchestrator also calls it up-front (CREATE OR REPLACE).
    if not dbt_only and not _already_past(ctx, PipelineStage.PG_FUNCTIONS_INSTALL):
        _run_pg_functions_install(ctx, dry_run, hooks)

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

    # Granular dbt silver stages — replaces the monolithic DBT_BUILD transition.
    # Each reads its selector from MANIFEST.yaml:entities.{entity}.dbt_selectors.
    _run_dbt_staging(ctx, entity, dry_run, hooks)
    _run_dbt_intermediate(ctx, entity, dry_run, hooks)
    _run_dbt_test_silver(ctx, entity, dry_run, hooks)

    # Entity-specific pre-marts work (e.g. case materialize view).
    _run_entity_postprocess(ctx, entity, "pre", dry_run, hooks)

    # Granular dbt marts stages.
    _run_dbt_marts(ctx, entity, dry_run, hooks)
    _run_dbt_test_marts(ctx, entity, dry_run, hooks)

    # Gold gate + upsert + StackSync + associations.
    _run_gold_upsert(ctx, entity, dry_run, hooks)
    _run_stacksync_sync(ctx, entity, dry_run, hooks)
    _run_assoc_validate(ctx, entity, dry_run, hooks)

    # Entity-specific post-assoc work (e.g. company hierarchy, comm unflatten).
    _run_entity_postprocess(ctx, entity, "post", dry_run, hooks)

    # Reconciliation coverage report (WARNING if below threshold, never FAILED).
    _run_post_run_verify(ctx, entity, dry_run, hooks)

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


def _run_pg_functions_install(ctx: PipelineContext, dry_run: bool, hooks: PipelineHooks) -> None:
    """PG_FUNCTIONS_INSTALL — install all pg functions from MANIFEST.yaml.

    Contract A (§7.6): runs as a stage of EVERY runner invocation, not
    only at the orchestrator level. Idempotent — CREATE OR REPLACE.
    """
    if not _should_run(ctx, PipelineStage.PG_FUNCTIONS_INSTALL, None):
        return
    if dry_run:
        transition(ctx, PipelineStage.PG_FUNCTIONS_INSTALL, StageStatus.SKIPPED, reason="dry_run")
        return
    try:
        result = hooks.pg_functions_installer(False)
    except NotImplementedError:
        transition(
            ctx,
            PipelineStage.PG_FUNCTIONS_INSTALL,
            StageStatus.SKIPPED,
            reason="hook_not_implemented_yet",
        )
        return
    transition(
        ctx,
        PipelineStage.PG_FUNCTIONS_INSTALL,
        StageStatus.SUCCESS,
        installed=len(result.get("installed", [])),
        duration_s=result.get("duration_s"),
    )


def _run_dbt_transition(
    ctx: PipelineContext,
    entity: str,
    dry_run: bool,
    hooks: PipelineHooks,
    stage: PipelineStage,
    selector: str,
    command: Literal["run", "test"],
) -> None:
    """Shared handler for every granular dbt stage.

    Calls hooks.dbt_runner with an explicit selector + command and maps the
    result to a state-machine transition. Failures include exit_code and
    stderr_tail so operators can diagnose from the artifact without
    re-running dbt locally.
    """
    if not _should_run(ctx, stage, None):
        return
    if dry_run:
        transition(ctx, stage, StageStatus.SKIPPED, reason="dry_run", selector=selector)
        return
    result = hooks.dbt_runner(entity, selector, command, False)
    if result.get("exit_code", 0) != 0 or result.get("failed", 0) > 0:
        transition(
            ctx,
            stage,
            StageStatus.FAILED,
            reason="dbt_nonzero_exit",
            selector=selector,
            command=command,
            exit_code=result.get("exit_code"),
            failed=result.get("failed", 0),
            stderr_tail=result.get("stderr_tail", "")[:256],
        )
    transition(
        ctx,
        stage,
        StageStatus.SUCCESS,
        selector=selector,
        command=command,
        nodes=result.get("nodes", 0),
        passed=result.get("passed", 0),
        duration_s=result.get("duration_s"),
    )


def _run_dbt_staging(ctx: PipelineContext, entity: str, dry_run: bool, hooks: PipelineHooks) -> None:
    """DBT_STAGING — dbt run --select stg_{entity} (from MANIFEST)."""
    try:
        selector = resolve_dbt_selector(entity, "staging")
    except RuntimeError as exc:
        transition(ctx, PipelineStage.DBT_STAGING, StageStatus.FAILED, reason=str(exc))
        return
    _run_dbt_transition(ctx, entity, dry_run, hooks, PipelineStage.DBT_STAGING, selector, "run")


def _run_dbt_intermediate(ctx: PipelineContext, entity: str, dry_run: bool, hooks: PipelineHooks) -> None:
    """DBT_INTERMEDIATE — dbt run --select int_{entity}_reconciled."""
    try:
        selector = resolve_dbt_selector(entity, "intermediate")
    except RuntimeError as exc:
        transition(ctx, PipelineStage.DBT_INTERMEDIATE, StageStatus.FAILED, reason=str(exc))
        return
    _run_dbt_transition(ctx, entity, dry_run, hooks, PipelineStage.DBT_INTERMEDIATE, selector, "run")


def _run_dbt_test_silver(ctx: PipelineContext, entity: str, dry_run: bool, hooks: PipelineHooks) -> None:
    """DBT_TEST_SILVER — dbt test on staging + intermediate selectors combined."""
    try:
        stg_selector = resolve_dbt_selector(entity, "staging")
        int_selector = resolve_dbt_selector(entity, "intermediate")
    except RuntimeError as exc:
        transition(ctx, PipelineStage.DBT_TEST_SILVER, StageStatus.FAILED, reason=str(exc))
        return
    # dbt accepts space-separated selectors in a single --select.
    combined = f"{stg_selector} {int_selector}"
    _run_dbt_transition(ctx, entity, dry_run, hooks, PipelineStage.DBT_TEST_SILVER, combined, "test")


def _run_dbt_marts(ctx: PipelineContext, entity: str, dry_run: bool, hooks: PipelineHooks) -> None:
    """DBT_MARTS — dbt run --select fct_{entity}_silver (and related marts)."""
    try:
        selector = resolve_dbt_selector(entity, "marts")
    except RuntimeError as exc:
        transition(ctx, PipelineStage.DBT_MARTS, StageStatus.FAILED, reason=str(exc))
        return
    _run_dbt_transition(ctx, entity, dry_run, hooks, PipelineStage.DBT_MARTS, selector, "run")


def _run_dbt_test_marts(ctx: PipelineContext, entity: str, dry_run: bool, hooks: PipelineHooks) -> None:
    """DBT_TEST_MARTS — dbt test on the marts selector."""
    try:
        selector = resolve_dbt_selector(entity, "marts")
    except RuntimeError as exc:
        transition(ctx, PipelineStage.DBT_TEST_MARTS, StageStatus.FAILED, reason=str(exc))
        return
    _run_dbt_transition(ctx, entity, dry_run, hooks, PipelineStage.DBT_TEST_MARTS, selector, "test")


def _run_entity_postprocess(
    ctx: PipelineContext,
    entity: str,
    phase: Literal["pre", "post"],
    dry_run: bool,
    hooks: PipelineHooks,
) -> None:
    """ENTITY_POSTPROCESS_{PRE,POST} — MANIFEST-driven dispatcher.

    Dispatches entity-specific steps registered under
    MANIFEST.yaml:entities.{entity}.postprocess.{phase}. Entities without
    postprocess entries for the phase receive mode='not_applicable' and
    the stage transitions to SKIPPED.
    """
    stage = (
        PipelineStage.ENTITY_POSTPROCESS_PRE if phase == "pre"
        else PipelineStage.ENTITY_POSTPROCESS_POST
    )
    if not _should_run(ctx, stage, None):
        return
    if dry_run:
        transition(ctx, stage, StageStatus.SKIPPED, reason="dry_run", phase=phase)
        return
    try:
        result = hooks.entity_postprocessor(entity, phase, False)
    except NotImplementedError:
        transition(ctx, stage, StageStatus.SKIPPED, reason="hook_not_implemented_yet", phase=phase)
        return
    mode = result.get("mode", "unknown")
    if mode == "not_applicable":
        transition(ctx, stage, StageStatus.SKIPPED, reason="no_postprocess_registered", phase=phase)
        return
    transition(
        ctx,
        stage,
        StageStatus.SUCCESS,
        phase=phase,
        mode=mode,
        steps=len(result.get("steps", [])),
    )


def _run_post_run_verify(ctx: PipelineContext, entity: str, dry_run: bool, hooks: PipelineHooks) -> None:
    """POST_RUN_VERIFY — reconciliation coverage + association coverage report.

    WARNING (not FAILED) when metrics fall below thresholds — the upsert
    already landed; a low coverage report is informational, not a rollback.
    """
    if not _should_run(ctx, PipelineStage.POST_RUN_VERIFY, None):
        return
    if dry_run:
        transition(ctx, PipelineStage.POST_RUN_VERIFY, StageStatus.SKIPPED, reason="dry_run")
        return
    try:
        result = hooks.post_run_verifier(entity, False)
    except NotImplementedError:
        transition(
            ctx,
            PipelineStage.POST_RUN_VERIFY,
            StageStatus.SKIPPED,
            reason="hook_not_implemented_yet",
        )
        return

    reconciliation_rate = result.get("reconciliation_rate", 0.0)
    association_coverage = result.get("association_coverage", 0.0)
    warnings_list = result.get("warnings", [])
    thresholds = ctx.metadata.get("thresholds", {})
    min_reconciliation = thresholds.get("min_reconciliation_rate", 0.85)
    min_association = thresholds.get("min_association_coverage", 0.85)

    status = StageStatus.SUCCESS
    if reconciliation_rate < min_reconciliation or association_coverage < min_association:
        status = StageStatus.WARNING

    transition(
        ctx,
        PipelineStage.POST_RUN_VERIFY,
        status,
        reconciliation_rate=reconciliation_rate,
        association_coverage=association_coverage,
        warnings_count=len(warnings_list),
        min_reconciliation=min_reconciliation,
        min_association=min_association,
    )


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
    """Mark all stages before resume_stage as SKIPPED.

    Iterates PipelineStage in enum-declaration order, comparing by .value.
    This replaces the previous hardcoded list — adding a new stage to the
    enum now automatically participates in resume semantics.

    INIT / COMPLETE / FAILED are skipped here — they are terminal or
    initial sentinels, not resumable work units.
    """
    terminal = {PipelineStage.INIT, PipelineStage.COMPLETE, PipelineStage.FAILED}
    for stage in PipelineStage:
        if stage in terminal:
            continue
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
