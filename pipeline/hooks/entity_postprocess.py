"""
Stages: ENTITY_POSTPROCESS_PRE, ENTITY_POSTPROCESS_POST
Hook:   dispatch (PipelineHooks.entity_postprocessor)

What it does
------------
Reads MANIFEST.yaml:entities.{entity}.postprocess.{phase} and dispatches
each registered step. Each step is one of:

    type: python  → module + fn resolution and call with dry_run
    type: sql     → path to .sql file; delegates to sql_file_runner

This is the MANIFEST-driven dispatcher. The runner calls it twice per
entity (pre-GOLD_VALIDATE and post-ASSOC_VALIDATE). Entities without
postprocess entries receive mode="not_applicable" and the stage
transitions to SKIPPED.

Current postprocess registry (see MANIFEST.yaml)
------------------------------------------------
- company.post:        pipeline.hierarchy.run        (native COMPANY hierarchy)
- opportunity.pre:     pipeline.dedupe.run_probe     (Levenshtein probe)
- communication.post:  pipeline.unflatten.run        (BFS hierarchy unflatten)
- case.pre:            sql/case/02b_materialize_view.sql
- case.pre:            sql/case/09b_pre_gold_association_probe.sql

Upstream assumptions
--------------------
- PRE phase: after SILVER_VALIDATE, before GOLD_VALIDATE
- POST phase: after ASSOC_VALIDATE, before POST_RUN_VERIFY

Writes / side effects
---------------------
- Depends on the registered step. SQL steps use sql_file_runner semantics
  (single transaction per file). Python steps have whatever side effects
  their module declares.

Common failure modes and diagnosis
----------------------------------
- "module not found: pipeline.hierarchy"
    → MANIFEST references a module that doesn't exist. Usually means the
      registered module hasn't been migrated into the ic-load package yet.
      Check module path; verify it's importable from pipeline root.

- "attribute error: module has no attribute 'run'"
    → MANIFEST references a fn that doesn't match module API. Verify fn
      name; by convention postprocess entrypoints are named `run` or
      `run_probe`.

- SQL step failure
    → Same diagnostic path as any SQL hook: check sql_file_runner output,
      inspect the specific .sql file locally with psql.

Re-running
----------
Each registered step declares its own idempotency (SQL via ON CONFLICT,
Python via documented contract). The dispatcher is idempotent by proxy —
re-dispatching runs the same steps in the same order.

Phase 1 notes
-------------
No existing equivalent. This hook is NEW. It replaces the current pattern
where hierarchy/unflatten/dedupe_probe scripts are invoked manually by
the operator outside the runner.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Literal


def dispatch(
    entity: str,
    phase: Literal["pre", "post"],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Dispatch MANIFEST-registered postprocess steps for entity/phase.

    Reads MANIFEST.yaml:entities.{entity}.postprocess.{phase} and runs
    each registered step in order. Step types:
      sql_call — direct SQL string via run_sql_text
      sql      — .sql file via run_sql_file
      python   — importlib module.fn call; ImportError is caught and
                 recorded as skipped (handles not-yet-created modules
                 such as pipeline.dedupe in Phase 5)
    """
    from context.config import load_manifest
    from pipeline.hooks._primitives import run_sql_file, run_sql_text

    manifest = load_manifest()
    steps = (
        manifest.get("entities", {})
                .get(entity, {})
                .get("postprocess", {})
                .get(phase, [])
    )
    if not steps:
        return {"mode": "not_applicable", "steps": []}

    results: list[dict[str, Any]] = []
    for step in steps:
        step_type = step.get("type")
        if step_type == "sql_call":
            if dry_run:
                results.append({"type": "sql_call", "mode": "dry_run"})
            else:
                run_sql_text(step["call"])
                results.append({"type": "sql_call", "mode": "executed"})
        elif step_type == "sql":
            result = run_sql_file(Path(step["file"]), dry_run=dry_run)
            results.append({"type": "sql", **result})
        elif step_type == "python":
            try:
                mod = importlib.import_module(step["module"])
                fn = getattr(mod, step["fn"])
                result = fn(dry_run=dry_run)
                results.append({
                    "type": "python",
                    "module": step["module"],
                    "fn": step["fn"],
                    "result": result,
                })
            except ImportError as exc:
                results.append({
                    "type": "python",
                    "module": step["module"],
                    "status": "skipped",
                    "reason": str(exc),
                })

    return {"mode": "dry_run" if dry_run else "live", "steps": results}
