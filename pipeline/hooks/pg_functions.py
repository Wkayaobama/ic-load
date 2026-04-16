"""
Stage: PG_FUNCTIONS_INSTALL
Hook:  install (PipelineHooks.pg_functions_installer)

What it does
------------
Iterates MANIFEST.yaml:pg_functions and executes each .sql file against
Postgres via _primitives.run_sql_file. Also executes the hierarchy schema
setup (sql/silver/00_hierarchy_schema.sql) before the function installs so
that the silver schema + target tables exist.

All functions use CREATE OR REPLACE FUNCTION — running twice is a no-op.

Translatability ledger
----------------------
The following algorithms TRANSLATE to pg functions (this hook installs them):

| Function                         | Source (was)                        | Reason SQL works                      |
|----------------------------------|-------------------------------------|---------------------------------------|
| fn_clean_utf8                    | dbt macro clean_french_utf8.sql     | Pure text replace chain               |
| fn_clean_html                    | dbt macro clean_html.sql            | regexp_replace, no state              |
| fn_normalize_phone_e164          | silver_normalise.py::_normalise_phone | String analysis + prefix checks     |
| fn_extract_domain                | upsert_sibling_companies.py::_clean_domain | URL strip/split, no recursion  |
| fn_validate_linkedin_url         | (new)                               | Regex match, no external calls        |
| fn_normalize_employee_range      | silver_delta_company.sql            | CASE mapping                          |
| fn_map_company_status            | silver_normalise.py COMPANY_STATUS_MAP | CASE mapping                      |
| fn_map_company_type              | silver_normalise.py COMPANY_TYPE_MAP   | CASE mapping                      |
| fn_map_contact_status            | silver_normalise.py CONTACT_STATUS_MAP | CASE mapping                      |
| fn_map_country_iso               | silver_normalise.py COUNTRY_ISO_MAP    | CASE mapping                      |
| fn_map_lifecycle_stage           | silver_delta_company.sql               | CASE mapping                      |
| fn_build_communication_hierarchy | pipeline/unflatten.py (Python BFS)     | Fixed 3-level depth = 3 JOIN passes |
| fn_build_company_tree            | pipeline/hierarchy.py (Python API)     | WITH RECURSIVE + cycle detection    |
| fn_traverse_hierarchy            | (new)                                  | Read-only CTE traversal             |
| fn_get_hierarchy_json            | (new)                                  | Recursive PL/pgSQL for QA only      |

The following algorithms STAY IN PYTHON (NOT installed by this hook):

| Algorithm          | Why it cannot translate                                              |
|--------------------|----------------------------------------------------------------------|
| deal_stage_mapper  | Must raise ValueError on unmapped combinations (safety contract).    |
|                    | SQL CASE returns NULL on unmapped — silent failure.                  |
| levenshtein_dedup  | Threshold-band bucketing (block/review/safe) + artifact JSON output. |
|                    | pg_trgm provides similarity but not the orchestration logic.         |

Upstream assumptions
--------------------
- None. This is the first stage of every runner invocation (Contract A, §7.6).

Writes / side effects
---------------------
- CREATE SCHEMA IF NOT EXISTS silver (via 00_hierarchy_schema.sql)
- CREATE TABLE IF NOT EXISTS silver.communication_hierarchy, silver.company_tree
- CREATE OR REPLACE FUNCTION staging.fn_* (11 transformation functions)
- CREATE OR REPLACE FUNCTION silver.fn_* (4 hierarchy functions)

Common failure modes and diagnosis
----------------------------------
- "permission denied for schema staging / silver"
    → Postgres role lacks CREATE on the schema. Not a pipeline bug.

- "syntax error at or near ..."
    → A .sql file has malformed SQL. Check the file named in the error.

Re-running
----------
Always safe. CREATE OR REPLACE / IF NOT EXISTS are idempotent.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from context.config import PROJECT_ROOT, load_manifest
from pipeline.hooks._primitives import run_sql_file


# Schema setup files run BEFORE individual function installs.
_SCHEMA_SETUP_FILES = [
    "sql/silver/00_hierarchy_schema.sql",
]


def install(dry_run: bool = False) -> dict[str, Any]:
    """Install all pg functions listed in MANIFEST.yaml plus schema setup.

    Executes schema setup files first (CREATE SCHEMA / TABLE IF NOT EXISTS),
    then iterates MANIFEST.yaml:pg_functions and runs each .sql file.
    """
    manifest = load_manifest()
    function_files = manifest.get("pg_functions", [])
    if not function_files:
        raise RuntimeError(
            "MANIFEST.yaml:pg_functions is empty. Expected a list of .sql file paths."
        )

    all_files = _SCHEMA_SETUP_FILES + function_files
    installed: list[str] = []
    start = time.perf_counter()

    for rel_path in all_files:
        sql_path = PROJECT_ROOT / rel_path
        if dry_run:
            installed.append(f"{rel_path} [dry-run]")
            continue
        if not sql_path.exists():
            raise FileNotFoundError(
                f"pg_functions install: file not found: {sql_path}. "
                f"Registered in MANIFEST.yaml but missing from disk."
            )
        run_sql_file(sql_path, dry_run=False)
        installed.append(rel_path)

    duration = time.perf_counter() - start

    return {
        "installed": installed,
        "count": len(installed),
        "duration_s": round(duration, 3),
        "mode": "dry_run" if dry_run else "executed",
    }
