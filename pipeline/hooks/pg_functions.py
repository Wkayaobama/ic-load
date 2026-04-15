"""
Stage: PG_FUNCTIONS_INSTALL
Hook:  install (PipelineHooks.pg_functions_installer)

What it does
------------
Executes every .sql file listed under `pg_functions:` in MANIFEST.yaml
against Postgres in a single transaction. All files use CREATE OR REPLACE
FUNCTION so the operation is idempotent — running twice produces the same
catalog state as running once.

Upstream assumptions (must be SUCCESS before this stage)
--------------------------------------------------------
- None. This is the FIRST stage of every runner invocation (Contract A,
  IC_Load_Production_Plan.md §7.6). The orchestrator also calls this
  once up-front; the runner's call is a harmless no-op in that case.

Writes / side effects
---------------------
- Creates/replaces functions under `staging.*` schema in Postgres.
- Appends stage block to artifacts/logs/pipeline_run_{entity}_{run_id}.log.
- Updates transition details: installed (list of fn names), duration_s.

Common failure modes and diagnosis
----------------------------------
- "permission denied for schema staging"
    → Postgres role lacks CREATE FUNCTION on staging. Verify grants:
        GRANT USAGE, CREATE ON SCHEMA staging TO <role>;
      Not a pipeline bug — contact DBA.

- "syntax error at or near ..."
    → A newly-added function has malformed SQL. The error line names
      the file. Test locally: psql -f sql/functions/<fn>.sql

- "relation does not exist"
    → A function body references a table. pg_functions must be PURE
      transformers — only builtins and type casts. Refactor to remove
      the table reference.

Re-running
----------
Always safe. CREATE OR REPLACE idempotency makes this stage a no-op on
repeat invocation. Contract A in §7.6 specifically relies on this.
"""
from __future__ import annotations

from typing import Any


def install(dry_run: bool = False) -> dict[str, Any]:
    """Install all pg functions listed in MANIFEST.yaml.

    Phase 2 implementation sketch:
        1. Load MANIFEST.yaml
        2. For each path in pg_functions list:
            _primitives.run_sql_file(Path(entry), dry_run=dry_run)
        3. Return {"installed": [fn_names], "duration_s": total}
    """
    raise NotImplementedError(
        "pipeline.hooks.pg_functions.install — Phase 1 scaffolding. "
        "Phase 2: iterate MANIFEST.yaml:pg_functions, call _primitives.run_sql_file "
        "on each. See IC_Load_Production_Plan.md §4 and §11 Phase 1."
    )
