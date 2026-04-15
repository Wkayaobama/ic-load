"""
Stages: DBT_STAGING, DBT_INTERMEDIATE, DBT_TEST_SILVER, DBT_MARTS, DBT_TEST_MARTS
Hook:   run_dbt (PipelineHooks.dbt_runner)

What it does
------------
Single parameterized hook that runs `dbt run` or `dbt test` with a given
selector. Each of the five dbt stages calls this hook with its own
selector and command derived from MANIFEST.yaml:entities.{entity}.dbt_selectors.

Signature
---------
run_dbt(entity, selector, command, dry_run) → dict
    entity:   "company" | "contact" | "opportunity" | "communication" | "case"
    selector: dbt selector string, e.g. "stg_company", "tag:communication_marts"
    command:  "run" | "test"
    dry_run:  if True, return {"mode": "dry_run", ...} without invoking dbt

Returns
-------
{"nodes": int, "passed": int, "failed": int,
 "duration_s": float, "artifact": Path | None}

Upstream assumptions
--------------------
- DBT_STAGING:      BRONZE_EXPORT → staging.stg_{entity} exists.
- DBT_INTERMEDIATE: DBT_STAGING → stg_{entity} view materialized.
- DBT_TEST_SILVER:  DBT_INTERMEDIATE → int_{entity}_reconciled materialized.
- DBT_MARTS:        ENTITY_POSTPROCESS_PRE successful; intermediate OK.
- DBT_TEST_MARTS:   DBT_MARTS → fct_{entity}_silver materialized.

Writes / side effects
---------------------
- Invokes dbt subprocess against dbt/ project using DBT_PROFILES_DIR from env.
- `dbt run`: materializes views/tables in PostgreSQL.
- `dbt test`: read-only; emits run_results.json.
- Copies dbt run_results.json into artifacts/ per stage invocation.

Common failure modes and diagnosis
----------------------------------
- "dbt command not configured"
    → ICALPS_DBT_COMMAND env var missing, or profiles.yml not found.
      Verify .env.example defaults, DBT_PROJECT_DIR in context/config.py.

- "Database Error ... relation does not exist"
    → Upstream source not created. Usually means BRONZE_EXPORT hasn't run
      or ran against a different database than dbt profile points to.

- dbt test failure (non-zero exit, failed > 0)
    → Inspect dbt/target/run_results.json for the failing test name and
      its assertion SQL. Fix the underlying data, re-run from the failed
      stage.

Re-running
----------
Idempotent. `dbt run` is incremental-aware; views are always replaced.
Tests are read-only. Safe to re-invoke any dbt stage.

Phase 1 notes
-------------
Existing runner.py contains a monolithic `_default_dbt_runner(entity, dry_run)`
that ignores entity and runs unscoped `dbt`. Phase 2 replaces it with the
parameterized hook below, driven by MANIFEST.yaml selectors.
"""
from __future__ import annotations

from typing import Any, Literal


def run_dbt(
    entity: str,
    selector: str,
    command: Literal["run", "test"],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Invoke dbt with a specific selector and command.

    Phase 2 implementation sketch:
        1. If dry_run, return {"mode": "dry_run", "nodes": 0, ...}.
        2. Build `dbt {command} --select {selector} --project-dir DBT_PROJECT_DIR`.
        3. subprocess.run with capture_output=True.
        4. Parse dbt/target/run_results.json for node_count, pass/fail counts.
        5. Copy run_results.json to artifacts/ for post-mortem.
        6. Return {"nodes": n, "passed": p, "failed": f, "duration_s": d, "artifact": path}.
    """
    raise NotImplementedError(
        f"pipeline.hooks.dbt.run_dbt — Phase 1 scaffolding. "
        f"Called with entity={entity!r}, selector={selector!r}, command={command!r}. "
        f"Phase 2: replace the monolithic `_default_dbt_runner` in runner.py with this."
    )
