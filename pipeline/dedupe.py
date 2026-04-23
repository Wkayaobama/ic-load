"""Levenshtein-based deduplication probe for opportunity and contact entities.

Entrypoint: run_probe(entity, dry_run=False)

Pairs are scoped to the same primary company to keep the cross-join
O(n²-per-company) rather than O(N²-global).

SCORE_BANDS are conservative placeholders — pending stakeholder confirmation.
To run a probe without risking a gold block, temporarily set
SCORE_BANDS["block"] = 1.01.
"""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring configuration — PENDING STAKEHOLDER CONFIRMATION
# ---------------------------------------------------------------------------

SCORE_BANDS: dict[str, float] = {
    "review": 0.80,  # ≥ this → flag for human review; run continues
    "block":  0.95,  # ≥ this → near-exact duplicate; gate gold
}

# ---------------------------------------------------------------------------
# Entity configs
# ---------------------------------------------------------------------------

# Each field expr uses {t} as a placeholder for the table alias (a or b).
ENTITY_CONFIGS: dict[str, dict[str, Any]] = {
    "opportunity": {
        "table":     "staging.stg_opportunity_normalised",
        "id_col":    "oppo_opportunityid",
        "scope_col": "oppo_primarycompanyid",
        "fields": [
            {"name": "description",  "expr": "LOWER(COALESCE({t}.oppo_description, ''))", "weight": 0.6},
            {"name": "company_name", "expr": "LOWER(COALESCE({t}.company_name, ''))",     "weight": 0.4},
        ],
    },
    "contact": {
        "table":     "staging.stg_contact_normalised",
        "id_col":    "pers_personid",
        "scope_col": "pers_companyid",
        "fields": [
            {"name": "full_name",    "expr": "LOWER(COALESCE({t}.pers_firstname,'') || ' ' || COALESCE({t}.pers_lastname,''))", "weight": 0.5},
            {"name": "email",        "expr": "LOWER(COALESCE({t}.icalps_email, ''))",   "weight": 0.3},
            {"name": "company_name", "expr": "LOWER(COALESCE({t}.company_name, ''))",   "weight": 0.2},
        ],
    },
}

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


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
# Main class
# ---------------------------------------------------------------------------


class DedupeGuardrail:
    """Generic Levenshtein-based duplicate probe."""

    def __init__(self, entity: str) -> None:
        if entity not in ENTITY_CONFIGS:
            raise ValueError(f"No dedupe config for entity {entity!r}. Known: {list(ENTITY_CONFIGS)}")
        self.entity = entity
        self.cfg = ENTITY_CONFIGS[entity]

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

        json_path, csv_path = self._write_artifacts(scored, run_id)

        return {
            "mode":          "live",
            "block_count":   len(block_pairs),
            "review_count":  len(review_pairs),
            "safe_count":    len(safe_pairs),
            "artifact_json": json_path,
            "artifact_csv":  csv_path,
        }

    def _build_sql(self) -> str:
        table     = self.cfg["table"]
        id_col    = self.cfg["id_col"]
        scope_col = self.cfg["scope_col"]
        fields    = self.cfg["fields"]

        select_parts = [
            f"a.{id_col} AS id_a",
            f"b.{id_col} AS id_b",
        ]
        for f in fields:
            name   = f["name"]
            expr_a = f["expr"].format(t="a")
            expr_b = f["expr"].format(t="b")
            select_parts += [
                f"{expr_a} AS {name}_a",
                f"{expr_b} AS {name}_b",
                f"levenshtein({expr_a}, {expr_b}) AS {name}_dist",
                f"greatest(length({expr_a}), length({expr_b})) AS {name}_maxlen",
            ]

        select_clause = ",\n    ".join(select_parts)
        return (
            f"SELECT\n    {select_clause}\n"
            f"FROM {table} a\n"
            f"JOIN {table} b\n"
            f"  ON a.{id_col} < b.{id_col}\n"
            f" AND a.{scope_col} = b.{scope_col}\n"
            f" AND a.{scope_col} IS NOT NULL"
        )

    def _fetch_pairs(self, conn: Any) -> list[dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(self._build_sql())
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _score_pair(self, row: dict[str, Any]) -> dict[str, Any]:
        fields = self.cfg["fields"]
        weighted: list[tuple[float, float]] = []

        for f in fields:
            name   = f["name"]
            maxlen = row[f"{name}_maxlen"] or 0
            if maxlen > 0:
                sim = 1.0 - row[f"{name}_dist"] / maxlen
                weighted.append((sim, f["weight"]))

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

        result: dict[str, Any] = {
            "id_a":  row["id_a"],
            "id_b":  row["id_b"],
            "score": round(composite, 4),
            "band":  band,
        }
        for f in fields:
            name = f["name"]
            result[f"{name}_a"] = row[f"{name}_a"]
            result[f"{name}_b"] = row[f"{name}_b"]
        return result

    def _write_artifacts(self, pairs: list[dict[str, Any]], run_id: str) -> tuple[str, str]:
        from context.config import ARTIFACTS_DIR

        base      = ARTIFACTS_DIR / f"dedupe_probe_{self.entity}_{run_id}"
        json_path = Path(str(base) + ".json")
        csv_path  = Path(str(base) + ".csv")

        block_count  = sum(1 for p in pairs if p["band"] == "block")
        review_count = sum(1 for p in pairs if p["band"] == "review")
        safe_count   = sum(1 for p in pairs if p["band"] == "safe")

        # JSON: summary only — all pair detail lives in the CSV
        payload = {
            "run_id":        run_id,
            "entity":        self.entity,
            "silver_table":  self.cfg["table"],
            "score_bands":   SCORE_BANDS,
            "field_weights": {f["name"]: f["weight"] for f in self.cfg["fields"]},
            "block_count":   block_count,
            "review_count":  review_count,
            "safe_count":    safe_count,
            "artifact_csv":  str(csv_path),
        }
        json_path.write_text(json.dumps(payload, indent=2, default=str))

        # CSV: one row per pair
        fields = self.cfg["fields"]
        if pairs:
            fieldnames = list(pairs[0].keys())
        else:
            fieldnames = ["id_a", "id_b", "score", "band"]
            for f in fields:
                fieldnames += [f"{f['name']}_a", f"{f['name']}_b"]

        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(pairs)

        logger.info(
            "Dedupe artifacts written: %s, %s (%d pairs total)",
            json_path.name, csv_path.name, len(pairs),
        )
        return str(json_path), str(csv_path)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def run_probe(entity: str, dry_run: bool = False) -> dict[str, Any]:
    """Run the dedupe probe for the given entity.

    Returns summary dict with block_count / review_count / safe_count.
    Raises ValueError for unknown entities — the hook is responsible for
    returning {"mode": "not_applicable"} for unsupported entities.
    """
    return DedupeGuardrail(entity).execute(dry_run=dry_run)
