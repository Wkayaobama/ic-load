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
entity (pre-DBT_MARTS and post-ASSOC_VALIDATE). Entities without
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
- PRE phase: after DBT_TEST_SILVER, before DBT_MARTS
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

from typing import Any, Literal


def dispatch(
    entity: str,
    phase: Literal["pre", "post"],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Dispatch MANIFEST-registered postprocess steps for entity/phase.

    Phase 2 implementation sketch:
        1. Load MANIFEST.yaml.
        2. steps = manifest["entities"][entity]["postprocess"].get(phase, [])
        3. If empty: return {"mode": "not_applicable", "steps": []}.
        4. For each step:
             if step["type"] == "python":
                 mod = importlib.import_module(step["module"])
                 fn = getattr(mod, step["fn"])
                 result = fn(dry_run=dry_run)
             elif step["type"] == "sql":
                 result = _primitives.run_sql_file(Path(step["file"]), dry_run=dry_run)
             record (step, result) in ctx.metadata.
        5. Return {"mode": "live", "steps": [{kind, result}, ...]}.
    """
    return {"mode": "not_applicable", "steps": []}
