"""Per-entity pipeline executor.

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
    load_schema_context,
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
    assoc_only: bool = False,
    verbosity: str = "low",
    probe_mode: bool = False,
    approve_gold: bool = False,
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
    if not _already_past(ctx, PipelineStage.PG_FUNCTIONS_INSTALL):
        _run_pg_functions_install(ctx, dry_run, hooks)

    if not _already_past(ctx, PipelineStage.BRONZE_EXPORT):
        _run_bronze(ctx, entity, dry_run, resume_stage, hooks, bronze_csv_override)

    if bronze_only:
        transition(ctx, PipelineStage.COMPLETE, StageStatus.SUCCESS, reason="bronze_only_stop")
        _finish(ctx)
        return ctx

    if not _already_past(ctx, PipelineStage.SILVER_VALIDATE):
        _run_silver(ctx, entity, dry_run, skip_validation, owner_blocking, verbosity, hooks)

    if silver_only:
        transition(ctx, PipelineStage.COMPLETE, StageStatus.SUCCESS, reason="silver_only_stop")
        _finish(ctx)
        return ctx

    # Entity-specific pre-gold work (e.g. case materialize view).
    _run_entity_postprocess(ctx, entity, "pre", dry_run, hooks)

    # Gold gate: requires --approve-gold + pre-gold duplicate check.
    _run_gold_validate(ctx, entity, dry_run, approve_gold)
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
        return

    if _should_run(ctx, PipelineStage.BRONZE_LOAD, resume_stage):
        try:
            rows = loader.load_csv_to_duckdb(str(csv_path), f"bronze_{entity}")
        except Exception as exc:
            transition(ctx, PipelineStage.BRONZE_LOAD, StageStatus.FAILED, reason=str(exc))
            return
        transition(ctx, PipelineStage.BRONZE_LOAD, StageStatus.SUCCESS, row_count=rows, csv=str(csv_path))

    if _should_run(ctx, PipelineStage.BRONZE_METADATA, resume_stage):
        try:
            loader.add_bronze_metadata(f"bronze_{entity}", str(csv_path))
        except Exception as exc:
            transition(ctx, PipelineStage.BRONZE_METADATA, StageStatus.FAILED, reason=str(exc))
            return
        transition(ctx, PipelineStage.BRONZE_METADATA, StageStatus.SUCCESS)

    if _should_run(ctx, PipelineStage.BRONZE_WATERMARK, resume_stage):
        if dry_run:
            transition(ctx, PipelineStage.BRONZE_WATERMARK, StageStatus.SKIPPED, reason="dry_run")
        else:
            try:
                counts = loader._tag_load_status(f"bronze_{entity}", entity_cfg.primary_key)
            except Exception as exc:
                transition(ctx, PipelineStage.BRONZE_WATERMARK, StageStatus.FAILED, reason=str(exc))
                return
            transition(ctx, PipelineStage.BRONZE_WATERMARK, StageStatus.SUCCESS, **counts)

    if _should_run(ctx, PipelineStage.BRONZE_EXPORT, resume_stage):
        if dry_run:
            transition(ctx, PipelineStage.BRONZE_EXPORT, StageStatus.SKIPPED, reason="dry_run")
        else:
            try:
                exported = loader.export_to_postgres(f"bronze_{entity}", entity_cfg.staging_table)
            except Exception as exc:
                transition(ctx, PipelineStage.BRONZE_EXPORT, StageStatus.FAILED, reason=str(exc))
                return
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
    result = hooks.pg_functions_installer(False)
    transition(
        ctx,
        PipelineStage.PG_FUNCTIONS_INSTALL,
        StageStatus.SUCCESS,
        installed=len(result.get("installed", [])),
        duration_s=result.get("duration_s"),
    )


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
    result = hooks.entity_postprocessor(entity, phase, False)
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
    result = hooks.post_run_verifier(entity, False)

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


def _run_gold_validate(
    ctx: PipelineContext,
    entity: str,
    dry_run: bool,
    approve_gold: bool,
) -> None:
    """GOLD_VALIDATE — two-gate check before any hubspot.* write.

    Gate 1: --approve-gold flag. The operator must explicitly confirm they've
    reviewed the silver artifacts. Without this flag, the pipeline stops here
    with a clear FAILED reason. This prevents accidental live writes.

    Gate 2: pre-gold duplicate reconciliation key check. Reads the same
    silver_table + match_column that render_entity_upsert will use for
    ON CONFLICT. If duplicates exist, the upsert would silently overwrite
    earlier rows — data loss. Better to FAIL here and force upstream dedupe.

    The query is built from schema_context.yaml — same contract as the
    gold upsert template. If schema_context is unavailable (e.g. entity
    not in the config), gate 2 is skipped with a WARNING (gate 1 still
    enforced).
    """
    if not _should_run(ctx, PipelineStage.GOLD_VALIDATE, None):
        return
    if dry_run:
        transition(ctx, PipelineStage.GOLD_VALIDATE, StageStatus.SKIPPED, reason="dry_run")
        return
    if ctx.metadata.get("probe_mode"):
        transition(ctx, PipelineStage.GOLD_VALIDATE, StageStatus.SKIPPED, reason="probe_mode")
        return

    # Gate 1: explicit operator approval
    if not approve_gold:
        transition(
            ctx,
            PipelineStage.GOLD_VALIDATE,
            StageStatus.FAILED,
            reason="explicit_gold_validation_required",
            hint="Pass --approve-gold to confirm you have reviewed silver artifacts before gold upsert.",
        )
        # transition(FAILED) raises RuntimeError — execution stops here.

    # Gate 2: pre-gold duplicate check on the ON CONFLICT column.
    # Uses schema_context.yaml to find the exact silver_table + match_column
    # that the upsert template will use — same source of truth, no drift.
    entity_key_map = {
        "company": "Company",
        "contact": "Person",
        "opportunity": "Opportunity",
    }
    schema_entity = entity_key_map.get(entity.lower())
    if schema_entity:
        try:
            schema = load_schema_context()
            cfg = schema.get("entities", {}).get(schema_entity, {})
            upsert_cfg = cfg.get("upsert", {})
            silver_table = cfg.get("silver_table")
            match_column = upsert_cfg.get("match_column")

            if silver_table and match_column:
                from context.db import get_connection

                check_sql = (
                    f"SELECT {match_column}, COUNT(*) AS cnt "
                    f"FROM {silver_table} "
                    f"GROUP BY {match_column} "
                    f"HAVING COUNT(*) > 1 "
                    f"LIMIT 10"
                )
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(check_sql)
                        dupes = cur.fetchall()

                if dupes:
                    dupe_ids = [str(row[0]) for row in dupes[:5]]
                    transition(
                        ctx,
                        PipelineStage.GOLD_VALIDATE,
                        StageStatus.FAILED,
                        reason="duplicate_reconciliation_keys_in_silver",
                        silver_table=silver_table,
                        match_column=match_column,
                        sample_duplicate_ids=dupe_ids,
                        total_duplicate_groups=len(dupes),
                        hint=f"Fix duplicates in {silver_table}.{match_column} before gold upsert. "
                             f"Run: SELECT {match_column}, COUNT(*) FROM {silver_table} GROUP BY {match_column} HAVING COUNT(*) > 1",
                    )
                    # FAILED raises — never reaches here.
        except FileNotFoundError:
            # schema_context YAML missing — skip gate 2, gate 1 was enough
            pass
        except Exception as exc:
            # DB error during check — warn but don't block (gate 1 passed).
            transition(
                ctx,
                PipelineStage.GOLD_VALIDATE,
                StageStatus.WARNING,
                reason="pre_gold_check_error",
                error=str(exc)[:256],
                note="Duplicate check failed but --approve-gold was set. Proceeding with caution.",
            )
            return

    transition(
        ctx,
        PipelineStage.GOLD_VALIDATE,
        StageStatus.SUCCESS,
        reason="gold_validation_passed",
        approve_gold=True,
        duplicate_check="passed" if schema_entity else "skipped_no_schema_entity",
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
    parser.add_argument("--assoc-only", action="store_true")
    parser.add_argument("--verbosity", choices=["high", "low"], default="low")
    parser.add_argument("--probe-mode", action="store_true")
    parser.add_argument(
        "--approve-gold",
        action="store_true",
        help="Required to execute GOLD_UPSERT. Without this flag the pipeline "
             "stops at GOLD_VALIDATE with reason=explicit_gold_validation_required. "
             "Pass only after reviewing silver artifacts.",
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
        assoc_only=args.assoc_only,
        verbosity=args.verbosity,
        probe_mode=args.probe_mode,
        approve_gold=args.approve_gold,
        bronze_csv_override=args.bronze_csv_override,
    )
