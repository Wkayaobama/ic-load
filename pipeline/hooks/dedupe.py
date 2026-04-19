"""
Stage: DEDUPE_GUARD
Hook:  guard (PipelineHooks.dedupe_guarder)

What it does
------------
Levenshtein-based deduplication probe. Scans a silver fact table and
identifies candidate duplicate pairs using name + domain + normalized
phone similarity. Pairs are scored and bucketed:
    safe_count    → below similarity threshold (no action)
    review_count  → in review band (WARNING, run continues)
    block_count   → above block threshold (FAILED, gate gold)

Opportunity-only by default — registered in MANIFEST.yaml postprocess.pre
only for `opportunity`. Other entities receive mode="not_applicable" and
the stage transitions to SKIPPED.

Upstream assumptions
--------------------
- SILVER_VALIDATE → silver tables validated
- ENTITY_POSTPROCESS_PRE → any entity-specific prep complete

Writes / side effects
---------------------
- Reads: staging.fct_{entity}_silver (or equivalent).
- Writes: artifacts/dedupe_probe_{entity}_{run_id}.json listing all
  candidate pairs with scores for human review.
- No DB writes.

Common failure modes and diagnosis
----------------------------------
- block_count > 0 → FAILED
    → Open the artifact JSON. Each row = {source_id, target_id, score,
      fields_matched}. Investigate pairs manually; either merge the
      duplicates upstream in IC'ALPS or adjust threshold bands in
      context/config.py thresholds.

- review_count > 0 (dry_run/probe_mode) → WARNING
    → Expected state when probing. Review the artifact; if any pair is
      a true duplicate, flag for merge. Thresholds can be tuned in
      pipeline/dedupe.py SCORE_BANDS.

- "probe_only_guardrail" SKIPPED
    → This stage only runs in probe or dry-run mode by design. Live
      runs skip it unless --enable-dedupe-guard is passed.

Re-running
----------
Idempotent (read-only + artifact write). Re-running overwrites the
artifact for the current run_id. Safe to resume.

Phase 1 notes
-------------
Existing pipeline.dedupe module (on feature branches) contains the
DedupeGuardrail class with scoring logic. Phase 2 delegates to it.
"""
from __future__ import annotations

from typing import Any


def guard(entity: str, dry_run: bool = False) -> dict[str, Any]:
    """Run dedupe probe for the given entity.

    Phase 2 implementation sketch:
        1. If entity not in MANIFEST postprocess registration for dedupe:
            return {"mode": "not_applicable"}
        2. Load staging.fct_{entity}_silver into pandas.
        3. Run Levenshtein scoring over name/domain/phone tuples.
        4. Bucket by SCORE_BANDS.
        5. Write artifact JSON, return {"block_count": ..., "review_count": ...,
           "safe_count": ..., "artifact_json": path, "mode": "live"}.
    """
    raise NotImplementedError(
        f"pipeline.hooks.dedupe.guard — Phase 1 scaffolding. Called for entity={entity!r}. "
        f"Phase 2: delegate to pipeline.dedupe.DedupeGuardrail.execute()."
    )
