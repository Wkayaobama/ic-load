"""
Stage: SILVER_VALIDATE
Hook:  silver_validator_factory (PipelineHooks.silver_validator_factory)

What it does
------------
Runs the silver-layer assertion suite defined in
ValidationRules/icalps_crm_schema.yaml. Each assertion has a severity:
STOP assertions block the pipeline on failure; WARN assertions let the
run continue in WARNING state.

This is the ONLY stage that reads ValidationRules/. Confirms the contract
(IC_Load_Production_Plan.md §9.1) — moving the file elsewhere breaks this
stage. Moving it into a directory the runner doesn't read would be a
silent regression.

Upstream assumptions (must be SUCCESS before this stage)
--------------------------------------------------------
- BRONZE_EXPORT → staging.stg_{entity} populated
- SILVER_NORMALISE (legacy) OR DBT_INTERMEDIATE (Phase 3+) → normalised silver tables present

Writes / side effects
---------------------
- Reads: staging.stg_{entity}_normalised, int_{entity}_reconciled,
  ValidationRules/icalps_crm_schema.yaml.
- No DB writes.
- Appends stage block to log with validation.{stop_count,warn_count,...}.
- Updates ctx.metadata["validation"] with STOP/WARN check names.

Common failure modes and diagnosis
----------------------------------
- STOP severity failure (FAILED transition)
    → stop_check_names=[...] in the log lists the specific assertions.
      Each name is defined in ValidationRules/icalps_crm_schema.yaml.
      Typical causes: reconciliation rate collapse, required field NULL
      rate jump, primary key duplicate.

- WARN severity failure (WARNING transition, run continues)
    → Same diagnostic path. These flag drift worth watching but not
      blocking. owner_warn_count > 0 is the common case: owners exist
      in legacy but haven't been resolved to HubSpot users yet. Flip
      thresholds.owner_resolution_blocking=true in context/config.py to
      escalate owner warnings to STOP.

Re-running
----------
Idempotent (read-only). Re-running from SILVER_VALIDATE after fixing
upstream data is the primary debug loop:
    python -m pipeline.runner --entity {X} --resume-from SILVER_VALIDATE
"""
from __future__ import annotations

from pipeline.silver import SilverValidator

# Direct factory reference. Each .silver_validator_factory() call returns
# a fresh SilverValidator instance (Contract B).
silver_validator_factory = SilverValidator
