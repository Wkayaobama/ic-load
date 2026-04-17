#!/usr/bin/env python3
"""
Deal Stage Mapper - Map IC'ALPS pipeline+stage+outcome → HubSpot stage IDs
Updated with CORRECT pipeline IDs from HubSpot export (Feb 2026)

Handles BOTH French and English stage names from database.
"""

# CORRECTED: Actual HubSpot Pipeline IDs from user-provided mapping (Feb 2026)
HUBSPOT_HARDWARE_PIPELINE = 766126206  # Icalps_hardware

# Complete stage mapping based on user-provided IDs (Feb 2026 update)
# Pipeline: Icalps_hardware (766126206)
HARDWARE_STAGES = {
    "Identified": 85103752,
    "Qualified": 85103753,
    "Design In": 85103754,
    "Design Win": 85103756,
    "Closed Won": 85103757,
    "Closed Lost": 85103758,
}

# Stage name normalization (handle both French and English)
STAGE_NORMALIZATION = {
    # English names (from database)
    "Identification": "01 - Identification",
    "Qualified": "02 - Qualifiée",
    "Evaluation technique": "03 - Evaluation technique",
    "Construction offre": "04 - Construction propositions",
    "Negotiating": "05 - Négociations",

    # French names (from original schema)
    "01 - Identification": "01 - Identification",
    "02 - Qualifiée": "02 - Qualifiée",
    "03 - Evaluation technique": "03 - Evaluation technique",
    "04 - Construction propositions": "04 - Construction propositions",
    "05 - Négociations": "05 - Négociations",
}

# Outcome normalization (handle both French and English)
OUTCOME_NORMALIZATION = {
    # English
    "NoGo": "No-go",
    "Abandonne": "Abandonnée",
    "In Progress": "En cours",
    "Lost": "Perdue",
    "Won": "Gagnée",

    # French
    "No-go": "No-go",
    "Abandonnée": "Abandonnée",
    "En cours": "En cours",
    "Perdue": "Perdue",
    "Gagnée": "Gagnée",
}

# IC'ALPS Stage + Outcome → HubSpot Stage Name mapping
# UPDATED: Feb 2026 - New stage IDs from user requirements
STAGE_OUTCOME_TO_HUBSPOT = {
    # Hardware Pipeline mappings (pipeline 766126206)
    # 01 - Identification
    ("Hardware", "01 - Identification", "No-go"): "Closed Lost",
    ("Hardware", "01 - Identification", "Abandonnée"): "Closed Lost",
    ("Hardware", "01 - Identification", "En cours"): "Identified",
    ("Hardware", "01 - Identification", "Perdue"): "Closed Lost",
    ("Hardware", "01 - Identification", "Gagnée"): "Closed Won",

    # 02 - Qualifiée
    ("Hardware", "02 - Qualifiée", "No-go"): "Closed Lost",
    ("Hardware", "02 - Qualifiée", "Abandonnée"): "Closed Lost",
    ("Hardware", "02 - Qualifiée", "En cours"): "Qualified",
    ("Hardware", "02 - Qualifiée", "Perdue"): "Closed Lost",
    ("Hardware", "02 - Qualifiée", "Gagnée"): "Closed Won",

    # 03 - Evaluation technique
    ("Hardware", "03 - Evaluation technique", "No-go"): "Closed Lost",
    ("Hardware", "03 - Evaluation technique", "Abandonnée"): "Closed Lost",
    ("Hardware", "03 - Evaluation technique", "En cours"): "Design In",
    ("Hardware", "03 - Evaluation technique", "Perdue"): "Closed Lost",
    ("Hardware", "03 - Evaluation technique", "Gagnée"): "Closed Won",

    # 04 - Construction propositions
    ("Hardware", "04 - Construction propositions", "No-go"): "Closed Lost",
    ("Hardware", "04 - Construction propositions", "Abandonnée"): "Closed Lost",
    ("Hardware", "04 - Construction propositions", "En cours"): "Design In",
    ("Hardware", "04 - Construction propositions", "Perdue"): "Closed Lost",
    ("Hardware", "04 - Construction propositions", "Gagnée"): "Closed Won",

    # 05 - Négociations
    ("Hardware", "05 - Négociations", "No-go"): "Closed Lost",
    ("Hardware", "05 - Négociations", "Abandonnée"): "Closed Lost",
    ("Hardware", "05 - Négociations", "En cours"): "Design Win",
    ("Hardware", "05 - Négociations", "Perdue"): "Closed Lost",
    ("Hardware", "05 - Négociations", "Gagnée"): "Closed Won",
}


def map_deal_stage(pipeline: str, stage: str, outcome: str) -> tuple:
    """
    Map IC'ALPS pipeline+stage+outcome to HubSpot pipeline ID and stage ID.

    Args:
        pipeline: "Hardware" or "Software"
        stage: IC'ALPS stage (English or French)
        outcome: IC'ALPS outcome (English or French)

    Returns:
        Tuple of (pipeline_id, stage_id, stage_name)

    Raises:
        ValueError: If combination not found in mapping
    """
    # Normalize stage name (handle both English and French)
    normalized_stage = STAGE_NORMALIZATION.get(stage)
    if not normalized_stage:
        raise ValueError(f"Unknown stage: {stage}")

    # Normalize outcome (handle both English and French)
    normalized_outcome = OUTCOME_NORMALIZATION.get(outcome)
    if not normalized_outcome:
        raise ValueError(f"Unknown outcome: {outcome}")

    # Get HubSpot stage name
    key = (pipeline, normalized_stage, normalized_outcome)
    if key not in STAGE_OUTCOME_TO_HUBSPOT:
        raise ValueError(
            f"Unknown stage combination: pipeline={pipeline}, stage={normalized_stage}, outcome={normalized_outcome}"
        )

    hubspot_stage_name = STAGE_OUTCOME_TO_HUBSPOT[key]

    # Get pipeline ID and stage ID
    if pipeline == "Hardware":
        pipeline_id = HUBSPOT_HARDWARE_PIPELINE
        if hubspot_stage_name not in HARDWARE_STAGES:
            raise ValueError(f"Stage '{hubspot_stage_name}' not found in Hardware pipeline")
        stage_id = HARDWARE_STAGES[hubspot_stage_name]
    else:
        raise ValueError(f"Unknown pipeline: {pipeline} (only Hardware pipeline supported with new IDs)")

    return (pipeline_id, stage_id, hubspot_stage_name)
