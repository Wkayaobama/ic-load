"""
Stages: DBT_STAGING, DBT_INTERMEDIATE, DBT_TEST_SILVER, DBT_MARTS, DBT_TEST_MARTS
        (also covers the deprecated monolithic DBT_BUILD stage)
Hook:   run_dbt (PipelineHooks.dbt_runner)

What it does
------------
Single parameterized hook that runs `dbt run` or `dbt test` with a given
selector. Each of the five dbt stages calls this hook with its own
selector and command derived from MANIFEST.yaml:entities.{entity}.dbt_selectors.

Invokes dbt via subprocess against DBT_PROJECT_DIR (context/config.py).
Parses dbt/target/run_results.json to count nodes / passed / failed.

Signature
---------
run_dbt(entity, selector, command, dry_run) → dict
    entity:   "company" | "contact" | "opportunity" | "communication" | "case"
    selector: dbt selector string, e.g. "stg_company", "tag:communication_marts"
              (empty string means "all models" — used by the deprecated
              DBT_BUILD stage for backwards compat)
    command:  "run" | "test"
    dry_run:  if True, return {"mode": "dry_run", ...} without invoking dbt

Returns
-------
{"mode": "dry_run" | "executed", "nodes": int, "passed": int, "failed": int,
 "duration_s": float, "exit_code": int, "stdout_tail": str, "stderr_tail": str,
 "artifact": Path | None, "entity": str, "selector": str, "command": str}

Upstream assumptions
--------------------
- DBT_STAGING:      BRONZE_EXPORT → staging.stg_{entity} exists.
- DBT_INTERMEDIATE: DBT_STAGING → stg_{entity} view materialized.
- DBT_TEST_SILVER:  DBT_INTERMEDIATE → int_{entity}_reconciled materialized.
- DBT_MARTS:        ENTITY_POSTPROCESS_PRE successful; intermediate OK.
- DBT_TEST_MARTS:   DBT_MARTS → fct_{entity}_silver materialized.

Writes / side effects
---------------------
- Invokes dbt subprocess against dbt/ project.
- `dbt run`: materializes views/tables in PostgreSQL.
- `dbt test`: read-only; emits run_results.json.
- Parses run_results.json for node counts; does NOT copy it to artifacts/
  (operator can inspect dbt/target/run_results.json directly).

Common failure modes and diagnosis
----------------------------------
- "dbt command not configured"
    → ICALPS_DBT_COMMAND env var missing and no default resolvable.
      Set it or add dbt to PATH. See .env.example.

- exit_code != 0, failed > 0
    → Inspect dbt/target/run_results.json for the failing node and its
      message. stdout_tail/stderr_tail in the hook result surface the
      last 1KB for quick diagnosis.

- "Database Error ... relation does not exist"
    → Upstream source not created. Usually BRONZE_EXPORT hasn't run or
      ran against a different database than the dbt profile points to.

- nodes=0 after a `run` command
    → Selector matched nothing. Verify the selector string against
      dbt project models. Empty selector runs ALL models — deliberate
      for the deprecated DBT_BUILD fallback.

Re-running
----------
Idempotent. `dbt run` is incremental-aware; views are always replaced.
Tests are read-only. Safe to re-invoke any dbt stage.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

from context.config import DBT_PROJECT_DIR, dbt_command


def run_dbt(
    entity: str,
    selector: str,
    command: Literal["run", "test"],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run `dbt {command} --select {selector}` via subprocess."""
    base_result: dict[str, Any] = {
        "entity": entity,
        "selector": selector,
        "command": command,
    }

    if dry_run:
        return {
            **base_result,
            "mode": "dry_run",
            "nodes": 0,
            "passed": 0,
            "failed": 0,
            "duration_s": 0.0,
            "exit_code": 0,
            "stdout_tail": "",
            "stderr_tail": "",
            "artifact": None,
        }

    dbt_cmd = dbt_command()
    if dbt_cmd is None:
        raise RuntimeError(
            "dbt command not configured. Set ICALPS_DBT_COMMAND env var "
            "or ensure `dbt` is on PATH. See .env.example for defaults."
        )

    full_cmd: list[str] = list(dbt_cmd) + [command]
    if selector:
        full_cmd += ["--select", selector]

    start = time.perf_counter()
    completed = subprocess.run(
        full_cmd,
        cwd=str(DBT_PROJECT_DIR),
        check=False,
        capture_output=True,
        text=True,
    )
    duration = time.perf_counter() - start

    nodes, passed, failed = 0, 0, 0
    artifact: Path | None = None
    results_path = Path(DBT_PROJECT_DIR) / "target" / "run_results.json"
    if results_path.exists():
        try:
            data = json.loads(results_path.read_text(encoding="utf-8"))
            results = data.get("results", [])
            nodes = len(results)
            passed = sum(1 for r in results if r.get("status") in {"success", "pass"})
            failed = sum(1 for r in results if r.get("status") in {"error", "fail"})
            artifact = results_path
        except (json.JSONDecodeError, OSError):
            # run_results.json unparseable — fall back to exit code.
            pass

    return {
        **base_result,
        "mode": "executed",
        "nodes": nodes,
        "passed": passed,
        "failed": failed,
        "duration_s": round(duration, 3),
        "exit_code": completed.returncode,
        "stdout_tail": (completed.stdout or "")[-1024:],
        "stderr_tail": (completed.stderr or "")[-1024:],
        "artifact": str(artifact) if artifact else None,
    }
