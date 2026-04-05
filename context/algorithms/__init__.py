"""
context/algorithms — Canonical algorithm package for the IC'ALPS salvage pipeline.

This package makes non-negotiable business logic first-class Python modules:
- No more 930-line scripts referenced by path from a sibling workspace
- Importable, testable, injectable
- Codespaces-safe (no external path dependencies)

## Contents

levenshtein.py
    Wagner-Fischer Levenshtein edit distance and similarity.
    Replaces difflib.SequenceMatcher for short identity strings.
    Includes SimilarityScorer protocol and MCPScorer injectable fallback.

company_siblings.py
    Canonical sibling/parent-child inference for IC'ALPS companies.
    Implements the domain-hack grouping, 3-tier parent selection,
    sibling index assignment, and cross-group Levenshtein similarity flagging.

deal_stage_mapper.py
    IC'ALPS pipeline + stage + outcome → HubSpot pipeline_id and stage_id.
    Canonical mapping extracted from the authoritative legacy source.
    Supports French and English label normalization.

_stubs.py
    Clear error stubs for silver_normalise.py and validate_silver.py
    until those files are promoted into this package (M4 resolution).

## Public exports

from context.algorithms import (
    levenshtein_ratio,
    edit_distance,
    similarity,
    LevenshteinScorer,
    MCPScorer,
    SimilarityScorer,
    clean_domain,
    company_root,
    SiblingGroup,
    CrossGroupCandidate,
    find_plural_domain_groups,
    select_canonical_parent,
    assign_sibling_indices,
    detect_all_sibling_groups,
    flag_cross_group_candidates,
    DealStageResult,
    map_deal_stage,
    normalize_stage,
    normalize_outcome,
    list_all_mappings,
)
"""
from context.algorithms.levenshtein import (
    edit_distance,
    get_scorer,
    levenshtein_ratio,
    LevenshteinScorer,
    MCPScorer,
    set_scorer,
    similarity,
    SimilarityScorer,
)
from context.algorithms.company_siblings import (
    assign_sibling_indices,
    clean_domain,
    company_root,
    CrossGroupCandidate,
    detect_all_sibling_groups,
    find_plural_domain_groups,
    flag_cross_group_candidates,
    select_canonical_parent,
    SiblingGroup,
)
from context.algorithms.deal_stage_mapper import (
    DealStageResult,
    list_all_mappings,
    map_deal_stage,
    normalize_outcome,
    normalize_stage,
)

__all__ = [
    # levenshtein
    "edit_distance",
    "get_scorer",
    "levenshtein_ratio",
    "LevenshteinScorer",
    "MCPScorer",
    "set_scorer",
    "similarity",
    "SimilarityScorer",
    # company_siblings
    "assign_sibling_indices",
    "clean_domain",
    "company_root",
    "CrossGroupCandidate",
    "detect_all_sibling_groups",
    "find_plural_domain_groups",
    "flag_cross_group_candidates",
    "select_canonical_parent",
    "SiblingGroup",
    # deal_stage_mapper
    "DealStageResult",
    "list_all_mappings",
    "map_deal_stage",
    "normalize_outcome",
    "normalize_stage",
]
