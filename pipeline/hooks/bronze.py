"""
Stages: BRONZE_LOAD, BRONZE_METADATA, BRONZE_WATERMARK, BRONZE_EXPORT
Hook:   bronze_loader_factory (PipelineHooks.bronze_loader_factory)

What it does
------------
Loads a CSV from BRONZE_CSV_DIR into DuckDB (BRONZE_LOAD), adds metadata
columns _first_seen_at / _last_modified_at / _load_status (BRONZE_METADATA),
tags each row as new / modified / unchanged by comparing against the
existing staging.stg_{entity} table (BRONZE_WATERMARK), then exports the
DuckDB table to Postgres staging schema (BRONZE_EXPORT).

This hook returns a factory (not a function) because the existing
DuckDBBronzeLoader class holds per-instance state (the DuckDB in-memory
database). The runner calls the factory once per run and invokes
instance methods for each sub-stage.

Upstream assumptions (must be SUCCESS before this stage)
--------------------------------------------------------
- PG_FUNCTIONS_INSTALL → staging functions available (not required by
  bronze itself but keeps the stage ordering coherent).

Writes / side effects
---------------------
- BRONZE_LOAD:      in-memory DuckDB table `bronze_{entity}`.
- BRONZE_METADATA:  adds _first_seen_at / _last_modified_at / _load_status.
- BRONZE_WATERMARK: tags load_status values (new / modified / unchanged).
- BRONZE_EXPORT:    INSERT/UPSERT into staging.stg_{entity} (Postgres).

Common failure modes and diagnosis
----------------------------------
- BRONZE_LOAD: "no_bronze_csv_found"
    → The runner could not find a CSV matching entity. Inspect
      context.config.latest_bronze_path(entity) output; verify
      BRONZE_CSV_DIR env var and filename convention Bronze_{Entity}.csv.

- BRONZE_METADATA: column not found
    → CSV columns changed upstream. Re-run extraction with current schema.

- BRONZE_WATERMARK: primary key missing
    → Log shows primary_key from ENTITIES[entity].primary_key but column
      is absent from CSV. Verify extractor includes the PK.

- BRONZE_EXPORT: Postgres write fails
    → Row count mismatch or FK violation. Check staging.stg_{entity}
      schema matches DuckDB table columns.

Re-running
----------
Idempotent — BRONZE_EXPORT uses INSERT ... ON CONFLICT on primary key.
Load status tagging ensures only changed rows are marked for downstream
processing, so re-runs are cheap.

Phase 1 notes
-------------
bronze_loader_factory below is a direct reference to the existing
pipeline.bronze.DuckDBBronzeLoader class. No wrapping required — the
class already conforms to the factory contract.
"""
from __future__ import annotations

from typing import Any


def bronze_loader_factory() -> Any:
    """Return a DuckDBBronzeLoader instance.

    Phase 2 will replace this with direct import + export:
        from pipeline.bronze import DuckDBBronzeLoader
        bronze_loader_factory = DuckDBBronzeLoader
    """
    raise NotImplementedError(
        "pipeline.hooks.bronze.bronze_loader_factory — Phase 1 scaffolding. "
        "Phase 2: replace with `from pipeline.bronze import DuckDBBronzeLoader; "
        "bronze_loader_factory = DuckDBBronzeLoader`."
    )
