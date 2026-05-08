"""
deal_stage_mapper.py — IC'ALPS pipeline + stage + outcome → HubSpot stage IDs.

This is the canonical module inside ic-load. It was extracted from:
  ic_load_pipeline/python-ignorethis/deal_stage_mapper.py

The mapping data is the authoritative source (Feb 2026 update from HubSpot export).
Do NOT modify stage or pipeline IDs without verifying them against the live
HubSpot portal for account 9201667.

## Usage

    from context.algorithms.deal_stage_mapper import map_deal_stage, DealStageResult

    result = map_deal_stage("Hardware", "01 - Identification", "Perdue")
    # DealStageResult(pipeline_id=766126206, stage_id=85103758, stage_name="Closed Lost")

## Invariants

- Only the "Hardware" pipeline (766126206) is currently supported.
- Stage names are accepted in both French and English (normalized internally).
- Outcome names are accepted in both French and English (normalized internally).
- Any unmapped combination raises ValueError — never silently produces a wrong ID.
- The runner passes `business_rules.yaml` deal_stage_mapper.non_negotiable=true;
  this function enforces that contract.
"""
from __future__ import annotations

from dataclasses import dataclass


# ──────────────────────────────────────────────────────────────────────────────
# HubSpot pipeline and stage IDs (verified Feb 2026, account 9201667)
# ──────────────────────────────────────────────────────────────────────────────

HUBSPOT_HARDWARE_PIPELINE_ID: int = 766126206  # Icalps_hardware

HARDWARE_STAGE_IDS: dict[str, int] = {
    "Identified":   85103752,
    "Qualified":    85103753,
    "Design In":    85103754,
    "Design Win":   85103756,
    "Closed Won":   85103757,
    "Closed Lost":  85103758,
}

# ──────────────────────────────────────────────────────────────────────────────
# Normalization tables (accept French and English labels from the database)
# ──────────────────────────────────────────────────────────────────────────────

_STAGE_NORMALIZATION: dict[str, str] = {
    # English (legacy export labels)
    "Identification":           "01 - Identification",
    "Qualified":                "02 - Qualifiée",
    "Evaluation technique":     "03 - Evaluation technique",
    "Construction offre":       "04 - Construction propositions",
    "Negotiating":              "05 - Négociations",
    # French (original schema labels)
    "01 - Identification":                "01 - Identification",
    "02 - Qualifiée":                     "02 - Qualifiée",
    "03 - Evaluation technique":          "03 - Evaluation technique",
    "04 - Construction propositions":     "04 - Construction propositions",
    "05 - Négociations":                  "05 - Négociations",
}

_OUTCOME_NORMALIZATION: dict[str, str] = {
    # English
    "NoGo":         "No-go",
    "Abandonne":    "Abandonnée",
    "In Progress":  "En cours",
    "Lost":         "Perdue",
    "Won":          "Gagnée",
    # French
    "No-go":        "No-go",
    "Abandonnée":   "Abandonnée",
    "En cours":     "En cours",
    "Perdue":       "Perdue",
    "Gagnée":       "Gagnée",
}

# ──────────────────────────────────────────────────────────────────────────────
# Mapping: (pipeline, normalized_stage, normalized_outcome) → HubSpot stage name
# ──────────────────────────────────────────────────────────────────────────────

_STAGE_OUTCOME_MAP: dict[tuple[str, str, str], str] = {
    # 01 - Identification
    ("Hardware", "01 - Identification", "No-go"):       "Closed Lost",
    ("Hardware", "01 - Identification", "Abandonnée"):  "Closed Lost",
    ("Hardware", "01 - Identification", "En cours"):    "Identified",
    ("Hardware", "01 - Identification", "Perdue"):      "Closed Lost",
    ("Hardware", "01 - Identification", "Gagnée"):      "Closed Won",
    # 02 - Qualifiée
    ("Hardware", "02 - Qualifiée", "No-go"):            "Closed Lost",
    ("Hardware", "02 - Qualifiée", "Abandonnée"):       "Closed Lost",
    ("Hardware", "02 - Qualifiée", "En cours"):         "Qualified",
    ("Hardware", "02 - Qualifiée", "Perdue"):           "Closed Lost",
    ("Hardware", "02 - Qualifiée", "Gagnée"):           "Closed Won",
    # 03 - Evaluation technique
    ("Hardware", "03 - Evaluation technique", "No-go"):       "Closed Lost",
    ("Hardware", "03 - Evaluation technique", "Abandonnée"):  "Closed Lost",
    ("Hardware", "03 - Evaluation technique", "En cours"):    "Design In",
    ("Hardware", "03 - Evaluation technique", "Perdue"):      "Closed Lost",
    ("Hardware", "03 - Evaluation technique", "Gagnée"):      "Closed Won",
    # 04 - Construction propositions
    ("Hardware", "04 - Construction propositions", "No-go"):       "Closed Lost",
    ("Hardware", "04 - Construction propositions", "Abandonnée"):  "Closed Lost",
    ("Hardware", "04 - Construction propositions", "En cours"):    "Design In",
    ("Hardware", "04 - Construction propositions", "Perdue"):      "Closed Lost",
    ("Hardware", "04 - Construction propositions", "Gagnée"):      "Closed Won",
    # 05 - Négociations
    ("Hardware", "05 - Négociations", "No-go"):       "Closed Lost",
    ("Hardware", "05 - Négociations", "Abandonnée"):  "Closed Lost",
    ("Hardware", "05 - Négociations", "En cours"):    "Design Win",
    ("Hardware", "05 - Négociations", "Perdue"):      "Closed Lost",
    ("Hardware", "05 - Négociations", "Gagnée"):      "Closed Won",
}


@dataclass(frozen=True)
class DealStageResult:
    """Resolved HubSpot pipeline and stage identifiers."""
    pipeline_id: int
    stage_id: int
    stage_name: str


def normalize_stage(stage: str) -> str | None:
    """Return the canonical IC'ALPS stage label or None if unknown."""
    return _STAGE_NORMALIZATION.get(stage)


def normalize_outcome(outcome: str) -> str | None:
    """Return the canonical IC'ALPS outcome label or None if unknown."""
    return _OUTCOME_NORMALIZATION.get(outcome)


def map_deal_stage(pipeline: str, stage: str, outcome: str) -> DealStageResult:
    """Map IC'ALPS pipeline + stage + outcome → HubSpot pipeline_id and stage_id.

    Args:
        pipeline: "Hardware" (only supported value)
        stage:    IC'ALPS stage label (French or English accepted)
        outcome:  IC'ALPS outcome label (French or English accepted)

    Returns:
        DealStageResult with pipeline_id, stage_id, stage_name.

    Raises:
        ValueError: For any unknown stage, outcome, or combination.
                    Never silently produces a wrong ID.
    """
    norm_stage = normalize_stage(stage)
    if norm_stage is None:
        raise ValueError(
            f"Unknown IC'ALPS stage: {stage!r}. "
            f"Known stages: {list(_STAGE_NORMALIZATION.keys())}"
        )

    norm_outcome = normalize_outcome(outcome)
    if norm_outcome is None:
        raise ValueError(
            f"Unknown IC'ALPS outcome: {outcome!r}. "
            f"Known outcomes: {list(_OUTCOME_NORMALIZATION.keys())}"
        )

    key = (pipeline, norm_stage, norm_outcome)
    if key not in _STAGE_OUTCOME_MAP:
        raise ValueError(
            f"No mapping found for combination: pipeline={pipeline!r}, "
            f"stage={norm_stage!r}, outcome={norm_outcome!r}"
        )

    hs_stage_name = _STAGE_OUTCOME_MAP[key]

    if pipeline == "Hardware":
        pipeline_id = HUBSPOT_HARDWARE_PIPELINE_ID
        stage_id = HARDWARE_STAGE_IDS.get(hs_stage_name)
        if stage_id is None:
            raise ValueError(
                f"Stage name {hs_stage_name!r} not found in Hardware pipeline stage IDs. "
                f"Known names: {list(HARDWARE_STAGE_IDS.keys())}"
            )
        return DealStageResult(pipeline_id=pipeline_id, stage_id=stage_id, stage_name=hs_stage_name)

    raise ValueError(
        f"Unknown pipeline: {pipeline!r}. Only 'Hardware' is currently supported."
    )


def list_all_mappings() -> list[dict]:
    """Return all supported combinations as a list of dicts (useful for validation SQL generation)."""
    rows = []
    for (pipeline, stage, outcome), hs_stage in _STAGE_OUTCOME_MAP.items():
        pipeline_id = HUBSPOT_HARDWARE_PIPELINE_ID if pipeline == "Hardware" else None
        stage_id = HARDWARE_STAGE_IDS.get(hs_stage)
        rows.append({
            "icalps_pipeline": pipeline,
            "icalps_stage": stage,
            "icalps_outcome": outcome,
            "hubspot_pipeline_id": pipeline_id,
            "hubspot_stage_id": stage_id,
            "hubspot_stage_name": hs_stage,
        })
    return rows


from context.algorithms._instrumentation import log_debug, log_info_with_artifact  # noqa: E402

normalize_stage = log_debug(
    normalize_stage,
    stat_fn=lambda result, stage, **_: {
        "call_count": 1,
        "unknown_count": 1 if result is None else 0,
    },
    sample_fn=lambda result, stage, **_: {
        "input": stage,
        "canonical": result,
    },
)
normalize_outcome = log_debug(
    normalize_outcome,
    stat_fn=lambda result, outcome, **_: {
        "call_count": 1,
        "unknown_count": 1 if result is None else 0,
    },
    sample_fn=lambda result, outcome, **_: {
        "input": outcome,
        "canonical": result,
    },
)
map_deal_stage = log_debug(
    map_deal_stage,
    stat_fn=lambda result, pipeline, stage, outcome, **_: {
        "call_count": 1,
    },
    sample_fn=lambda result, pipeline, stage, outcome, **_: {
        "pipeline": pipeline,
        "stage": stage,
        "outcome": outcome,
        "hubspot_stage": result.stage_name,
        "stage_id": result.stage_id,
    },
)

list_all_mappings = log_info_with_artifact(
    description="Enumerate all IC'ALPS -> HubSpot pipeline+stage+outcome mappings.",
    artifact_builder=lambda result, **kw: {
        "total_mappings": len(result),
        "pipelines": list({r["icalps_pipeline"] for r in result}),
        "stages": list({r["icalps_stage"] for r in result}),
        "hubspot_stage_names": list({r["hubspot_stage_name"] for r in result}),
        "mappings": result,
    },
)(list_all_mappings)
