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

The hook exposes `DuckDBBronzeLoader` directly as the factory. The runner
calls the factory once per run and invokes instance methods for each
sub-stage.

Upstream assumptions (must be SUCCESS before this stage)
--------------------------------------------------------
- PG_FUNCTIONS_INSTALL → staging functions available (not strictly
  required by bronze itself; keeps stage ordering coherent).

Writes / side effects
---------------------
- BRONZE_LOAD:      in-memory DuckDB table `bronze_{entity}`.
- BRONZE_METADATA:  adds _first_seen_at / _last_modified_at / _load_status.
- BRONZE_WATERMARK: tags load_status values (new / modified / unchanged).
- BRONZE_EXPORT:    INSERT/UPSERT into staging.stg_{entity} (Postgres).

Common failure modes and diagnosis
----------------------------------
- BRONZE_LOAD: "no_bronze_csv_found"
    → latest_bronze_path(entity) returned None. Verify BRONZE_CSV_DIR env
      and filename convention Bronze_{Entity}.csv.

- BRONZE_METADATA: column not found
    → CSV columns changed upstream. Re-run extraction with current schema.

- BRONZE_WATERMARK: primary key missing
    → ENTITIES[entity].primary_key column absent from CSV. Verify extractor.

- BRONZE_EXPORT: Postgres write fails
    → Row count mismatch or FK violation. Check staging.stg_{entity}
      schema matches DuckDB table columns.

Re-running
----------
Idempotent — BRONZE_EXPORT uses INSERT ... ON CONFLICT on primary key.
Load-status tagging ensures only changed rows trigger downstream work,
so re-runs are cheap.
"""
from __future__ import annotations

from pipeline.bronze import DuckDBBronzeLoader

# Direct factory reference. Calling bronze_loader_factory() returns a fresh
# DuckDBBronzeLoader instance (per Contract B: no state reuse across runs).
bronze_loader_factory = DuckDBBronzeLoader
