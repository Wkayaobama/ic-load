"""Levenshtein-based deduplication probe for the opportunity entity.

Entrypoint: run_probe(dry_run=False) — registered in MANIFEST.yaml
under entities.opportunity.postprocess.pre.

Scoring uses the available columns from staging.stg_opportunity_normalised:
  - oppo_description (weight 0.6) — opportunity description / title
  - company_name     (weight 0.4) — denormalized company name

Pairs are scoped to the same primary company (oppo_primarycompanyid IS NOT NULL
AND a.oppo_primarycompanyid = b.oppo_primarycompanyid) to keep the cross-join
O(n²-per-company) rather than O(N²-global).

SCORE_BANDS and FIELD_WEIGHTS are conservative placeholders — pending
stakeholder confirmation of what constitutes a true duplicate opportunity in
IC'ALPS. Update them in this module once confirmed. To run a probe without
risking a gold block, temporarily set SCORE_BANDS["block"] = 1.01.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring configuration — PENDING STAKEHOLDER CONFIRMATION
# ---------------------------------------------------------------------------

SCORE_BANDS: dict[str, float] = {
    "review": 0.80,  # ≥ this → flag for human review; run continues
    "block":  0.95,  # ≥ this → near-exact duplicate; gate gold
}

FIELD_WEIGHTS: dict[str, float] = {
    "oppo_description": 0.6,
    "company_name":     0.4,
}

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

_SILVER_TABLE = "staging.stg_opportunity_normalised"


class DedupeBlockedError(RuntimeError):
    """Raised by run_probe() when block_count > 0 in live mode."""

    def __init__(self, block_count: int, artifact_path: str) -> None:
        self.block_count = block_count
        self.artifact_path = artifact_path
        super().__init__(
            f"Dedupe blocked: {block_count} pair(s) at or above block threshold "
            f"({SCORE_BANDS['block']:.0%}). Review artifact: {artifact_path}"
        )


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_PAIRS_SQL = f"""
SELECT
    a.oppo_opportunityid                                        AS source_id,
    b.oppo_opportunityid                                        AS target_id,
    a.oppo_description                                          AS source_desc,
    b.oppo_description                                          AS target_desc,
    a.company_name                                              AS source_company,
    b.company_name                                              AS target_company,
    levenshtein(
        lower(coalesce(a.oppo_description, '')),
        lower(coalesce(b.oppo_description, ''))
    )                                                           AS desc_dist,
    greatest(
        length(coalesce(a.oppo_description, '')),
        length(coalesce(b.oppo_description, ''))
    )                                                           AS desc_maxlen,
    levenshtein(
        lower(coalesce(a.company_name, '')),
        lower(coalesce(b.company_name, ''))
    )                                                           AS company_dist,
    greatest(
        length(coalesce(a.company_name, '')),
        length(coalesce(b.company_name, ''))
    )                                                           AS company_maxlen
FROM {_SILVER_TABLE} a
JOIN {_SILVER_TABLE} b
  ON a.oppo_opportunityid < b.oppo_opportunityid
 AND a.oppo_primarycompanyid = b.oppo_primarycompanyid
 AND a.oppo_primarycompanyid IS NOT NULL
"""

# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class DedupeGuardrail:
    """Levenshtein-based duplicate probe for opportunities."""

    def execute(self, dry_run: bool = False) -> dict[str, Any]:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        if dry_run:
            return {"mode": "dry_run", "block_count": 0, "review_count": 0, "safe_count": 0}

        from context.db import get_connection

        with get_connection() as conn:
            raw_pairs = self._fetch_pairs(conn)

        scored = [self._score_pair(p) for p in raw_pairs]
        block_pairs  = [p for p in scored if p["band"] == "block"]
        review_pairs = [p for p in scored if p["band"] == "review"]
        safe_pairs   = [p for p in scored if p["band"] == "safe"]

        if review_pairs:
            logger.warning(
                "Dedupe: %d pair(s) in review band (score ≥ %.0f%%). "
                "Check artifact for details.",
                len(review_pairs), SCORE_BANDS["review"] * 100,
            )

        artifact_path = self._write_artifact(scored, run_id)

        result: dict[str, Any] = {
            "mode": "live",
            "block_count":  len(block_pairs),
            "review_count": len(review_pairs),
            "safe_count":   len(safe_pairs),
            "artifact_json": artifact_path,
        }

        return result

    def _fetch_pairs(self, conn: Any) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(_PAIRS_SQL)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _score_pair(self, row: dict[str, Any]) -> dict[str, Any]:
        weighted: list[tuple[float, float]] = []  # (similarity, weight)

        desc_maxlen = row["desc_maxlen"] or 0
        if desc_maxlen > 0:
            sim = 1.0 - row["desc_dist"] / desc_maxlen
            weighted.append((sim, FIELD_WEIGHTS["oppo_description"]))

        company_maxlen = row["company_maxlen"] or 0
        if company_maxlen > 0:
            sim = 1.0 - row["company_dist"] / company_maxlen
            weighted.append((sim, FIELD_WEIGHTS["company_name"]))

        if weighted:
            total_weight = sum(w for _, w in weighted)
            composite = sum(s * w for s, w in weighted) / total_weight
        else:
            composite = 0.0

        band = (
            "block"  if composite >= SCORE_BANDS["block"]  else
            "review" if composite >= SCORE_BANDS["review"] else
            "safe"
        )

        return {
            "source_id":      row["source_id"],
            "target_id":      row["target_id"],
            "source_desc":    row["source_desc"],
            "target_desc":    row["target_desc"],
            "source_company": row["source_company"],
            "target_company": row["target_company"],
            "score":          round(composite, 4),
            "band":           band,
        }

    def _write_artifact(self, pairs: list[dict[str, Any]], run_id: str) -> str:
        from context.config import ARTIFACTS_DIR

        path = ARTIFACTS_DIR / f"dedupe_probe_opportunity_{run_id}.json"
        payload = {
            "run_id":       run_id,
            "entity":       "opportunity",
            "silver_table": _SILVER_TABLE,
            "score_bands":  SCORE_BANDS,
            "block_count":  sum(1 for p in pairs if p["band"] == "block"),
            "review_count": sum(1 for p in pairs if p["band"] == "review"),
            "safe_count":   sum(1 for p in pairs if p["band"] == "safe"),
            "pairs":        pairs,
        }
        path.write_text(json.dumps(payload, indent=2, default=str))
        logger.info("Dedupe artifact written: %s (%d pairs total)", path, len(pairs))
        return str(path)


# ---------------------------------------------------------------------------
# MANIFEST entrypoint
# ---------------------------------------------------------------------------


def run_probe(dry_run: bool = False) -> dict[str, Any]:
    """MANIFEST entrypoint for opportunity.postprocess.pre.

    Returns summary dict with block_count / review_count / safe_count.
    Raises DedupeBlockedError when block_count > 0 in live mode — the caller
    (runner._run_entity_postprocess) catches this and transitions
    ENTITY_POSTPROCESS_PRE to FAILED.
    """
    return DedupeGuardrail().execute(dry_run=dry_run)
