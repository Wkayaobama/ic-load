"""Pipeline hooks — one module per PipelineStage boundary.

Public surface
--------------
The runner imports only `PipelineHooks` and `build_default_hooks` from this
package. Individual hook modules are internal; they are wired into the
dataclass here and should not be imported directly by runner/orchestrator.

Folder layout (see IC_Load_Production_Plan.md §7.4)
---------------------------------------------------
pipeline/hooks/
├── __init__.py                 (this file — public surface)
├── _primitives.py              (shared: run_sql_file, run_sql_text, StructuredLogger)
├── pg_functions.py             → PG_FUNCTIONS_INSTALL
├── bronze.py                   → BRONZE_{LOAD,METADATA,WATERMARK,EXPORT}
├── silver_validator.py         → SILVER_VALIDATE
├── dbt.py                      → DBT_{STAGING,INTERMEDIATE,MARTS,TEST_SILVER,TEST_MARTS,BUILD}
├── dedupe.py                   → DEDUPE_GUARD
├── gold.py                     → GOLD_{VALIDATE,UPSERT}
├── sync.py                     → STACKSYNC_SYNC
├── associations.py             → ASSOC_VALIDATE
├── entity_postprocess.py       → ENTITY_POSTPROCESS_{PRE,POST}
└── post_run_verify.py          → POST_RUN_VERIFY

Every hook module carries a standardized docstring block describing stage,
upstream assumptions, writes, common failures, and re-running semantics
(see §7.5). Operators reading a failed log can walk from stage name to
module to diagnosis without reading implementation code.

Phase 2 status
--------------
Delegation hooks (bronze, silver_validator, gold, sync, associations,
dbt_runner) are implemented — they wire the existing pipeline/* modules
through the new package surface. Remaining stubs (pg_functions, dedupe,
entity_postprocess, post_run_verify) raise NotImplementedError; they
require Phase 3+ dependencies (pg function SQL files, dbt entity models,
MANIFEST-driven dispatcher).

SilverNormaliserFactory remains as a LEGACY field — runner.py still uses
it for the deprecated SILVER_NORMALISE stage. Phase 3 removes both once
dbt staging + intermediate models fully cover normalisation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping


@dataclass
class PipelineHooks:
    """Injection surface for every stage boundary in PipelineStage.

    See IC_Load_Production_Plan.md §7.3 for the stage → hook mapping and
    §7.6 for the idempotency contracts each hook must satisfy.
    """

    # Bronze — BRONZE_LOAD / METADATA / WATERMARK / EXPORT
    bronze_loader_factory: Callable[[], Any]

    # Silver — SILVER_NORMALISE (LEGACY, deprecated) and SILVER_VALIDATE
    silver_normaliser_factory: Callable[[], Any]
    silver_validator_factory: Callable[[], Any]

    # pg functions — PG_FUNCTIONS_INSTALL (Contract A: runs per-runner, not only orchestrator)
    pg_functions_installer: Callable[[bool], dict[str, Any]]

    # dbt — DBT_{STAGING,INTERMEDIATE,MARTS,TEST_SILVER,TEST_MARTS,BUILD}
    # Signature: (entity, selector, command, dry_run) → dict
    # Empty selector means "all models" (used by deprecated DBT_BUILD fallback).
    dbt_runner: Callable[[str, str, Literal["run", "test"], bool], dict[str, Any]]

    # Entity-specific postprocess — ENTITY_POSTPROCESS_{PRE,POST}
    # Dispatches via MANIFEST.yaml entities.{entity}.postprocess.{phase}
    entity_postprocessor: Callable[[str, Literal["pre", "post"], bool], dict[str, Any]]

    # Dedupe — DEDUPE_GUARD (opportunity-only by default)
    dedupe_guarder: Callable[[str, bool], dict[str, Any]]

    # Gold — GOLD_UPSERT (GOLD_VALIDATE is inline in runner, no hook)
    gold_upserter: Callable[[str, bool], dict[str, Any]]

    # StackSync — STACKSYNC_SYNC (non-blocking)
    sync_waiter: Callable[[str, bool], dict[str, Any]]

    # Association bridge — ASSOC_VALIDATE (reads GomplateRepoMix/schema_context.yaml)
    association_runner: Callable[[str, bool], dict[str, Any]]

    # Post-run verification — POST_RUN_VERIFY
    post_run_verifier: Callable[[str, bool], dict[str, Any]]

    # Shared primitive — runs a .sql file against Postgres in a fresh transaction
    sql_file_runner: Callable[[Path, Mapping[str, Any] | None, bool], dict[str, Any]]


def build_default_hooks() -> PipelineHooks:
    """Wire up the production hook set.

    Phase 2: delegation hooks (bronze, silver, gold, sync, associations,
    dbt) return real implementations. Remaining hooks raise
    NotImplementedError with pointers to the migration phase that adds them.
    """
    from pipeline.hooks import (
        _primitives,
        associations,
        bronze,
        dbt,
        dedupe,
        entity_postprocess,
        gold,
        pg_functions,
        post_run_verify,
        silver_validator,
        sync,
    )
    from pipeline.silver import SilverNormaliser

    return PipelineHooks(
        bronze_loader_factory=bronze.bronze_loader_factory,
        silver_normaliser_factory=SilverNormaliser,
        silver_validator_factory=silver_validator.silver_validator_factory,
        pg_functions_installer=pg_functions.install,
        dbt_runner=dbt.run_dbt,
        entity_postprocessor=entity_postprocess.dispatch,
        dedupe_guarder=dedupe.guard,
        gold_upserter=gold.upsert,
        sync_waiter=sync.wait_for_sync,
        association_runner=associations.run_bridge,
        post_run_verifier=post_run_verify.verify,
        sql_file_runner=_primitives.run_sql_file,
    )
