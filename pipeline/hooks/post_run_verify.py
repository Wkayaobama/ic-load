"""
Stage: POST_RUN_VERIFY
Hook:  verify (PipelineHooks.post_run_verifier)

What it does
------------
Executes sql/{entity}/10_post_run_verify.sql via sql_file_runner. The SQL
returns a single-row result set with reconciliation coverage metrics:

    reconciliation_rate   → % of staging rows matched to hubspot.*
    association_coverage  → % of expected associations created
    warnings              → array of ad-hoc warnings from the SQL

The hook parses the result, compares against thresholds from
context.config.load_thresholds(entity), and transitions the stage:

    SUCCESS — all metrics ≥ threshold
    WARNING — any metric below threshold (does NOT fail the run)

Upstream assumptions
--------------------
- GOLD_UPSERT successful
- ASSOC_VALIDATE successful
- ENTITY_POSTPROCESS_POST successful

Writes / side effects
---------------------
- Reads: staging.*, hubspot.* (read-only).
- No DB writes.
- Appends stage block with reconciliation_rate, association_coverage,
  warnings array to the log.
- Writes a summary artifact artifacts/post_run_verify_{entity}_{run_id}.json.

Common failure modes and diagnosis
----------------------------------
- reconciliation_rate below threshold → WARNING
    → Open the artifact JSON. The SQL exposes which entities failed to
      match. Typical cause: silver normalizer mapped a source value to
      NULL and the reconciliation join failed. Check fn_map_* coverage.

- association_coverage below threshold → WARNING
    → Usually a StackSync-lag issue immediately post-run. Re-run
      --assoc-only later. If persistent, inspect ASSOC_VALIDATE
      pass_a vs pass_b ratio: low pass_a indicates stuck UUIDs.

- warnings array non-empty
    → SQL-level warnings (e.g. duplicate icalps_{entity}_id in staging).
      Each entry should carry enough context to investigate; fix upstream
      and re-run from SILVER_VALIDATE.

Re-running
----------
Idempotent (read-only). Cheap to re-invoke; useful as a health check
after StackSync cycles or after manual data fixes.

Phase 1 notes
-------------
No existing equivalent. This hook is NEW. Current post-run verification
lives in ad-hoc SQL snippets scattered across custom_objects/ docs.
Phase 2 moves them into sql/{entity}/10_post_run_verify.sql files.
"""
from __future__ import annotations

from typing import Any


def verify(entity: str, dry_run: bool = False) -> dict[str, Any]:
    """Execute post-run verification SQL and compare against thresholds.

    Phase 2 implementation sketch:
        1. Resolve sql path from MANIFEST.yaml:entities.{entity}.sql_files.post_run_verify.
        2. Call _primitives.run_sql_file; expect a single-row result set.
        3. thresholds = context.config.load_thresholds(entity)
        4. reconciliation_rate = result.reconciliation_rate
           association_coverage = result.association_coverage
           warnings = result.warnings
        5. Compare against thresholds; record per-metric pass/fail.
        6. Write artifacts/post_run_verify_{entity}_{run_id}.json.
        7. Return {"reconciliation_rate": ..., "association_coverage": ...,
           "warnings": [...], "threshold_results": {...}}.
    """
    raise NotImplementedError(
        f"pipeline.hooks.post_run_verify.verify — Phase 1 scaffolding. "
        f"Called for entity={entity!r}. "
        f"Phase 2: execute sql/{entity}/10_post_run_verify.sql, compare thresholds."
    )
