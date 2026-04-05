"""
company_siblings.py — Canonical sibling/parent-child inference for IC'ALPS companies.

This module makes the "domain hack" logic a first-class, importable module.
Previously this lived only in create_company_hierarchy.py (930 lines).
Here it is extracted as pure, testable functions with no HubSpot API dependency.

The HubSpot API write (batch/create child, register association typeId 269/270)
remains in create_company_hierarchy.py. This module owns the detection and
classification logic only.

## The Domain Hack

Child companies receive a synthetic domain encoding their position:
  parent:    domain = "{clean_domain}"         icalps_sibling_index = 0
  child 1:   domain = "1.{clean_domain}"       icalps_sibling_index = 1
  child N:   domain = "{N}.{clean_domain}"     icalps_sibling_index = N

icalps_real_domain (custom HubSpot property) stores the actual domain.

## Algorithm

1. Normalize and clean each company's domain from comp_website.
2. Group by clean_domain. Only groups with count > 1 are plural.
3. For each plural group:
   a. Among Gold-matched rows (present in hubspot.companies):
      - Pick the row with the highest contact_count.
      - Tie-break: minimum comp_companyid (deterministic).
   b. If no Gold-matched row → mark group unresolved, skip entirely.
   c. Remaining rows = children, sorted by comp_companyid ASC.
   d. Assign icalps_sibling_index: parent=0, children=1..N.

## Levenshtein cross-group similarity (NEW)

After domain-based grouping, some companies that belong together may have
slightly different domains (typos, www-prefix differences, ccTLD variants).
This module optionally uses Levenshtein similarity to flag cross-group pairs
where company name roots are close enough to warrant manual review.

These are not merged automatically — they are flagged for operator confirmation.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from context.algorithms.levenshtein import levenshtein_ratio

_COMPANY_STOPWORDS = {
    "ag", "corp", "corporation", "company", "co", "gmbh", "holding",
    "inc", "ltd", "llc", "sa", "sarl", "sas", "solutions", "systems",
    "technology", "technologies",
}

# Threshold for flagging two groups as likely same root (operator review only)
_CROSS_GROUP_NAME_SIMILARITY_THRESHOLD = 0.80


def clean_domain(url: Any) -> str:
    """Normalize a URL or domain string to a bare domain for grouping.

    Examples:
        "https://www.gehealthcare.fr/some/path" → "gehealthcare.fr"
        "1.gehealthcare.fr"                     → "gehealthcare.fr"  (strip sibling prefix)
        None / ""                                → ""
    """
    if not url or (isinstance(url, float) and pd.isna(url)):
        return ""
    text = str(url).strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    text = text.split("/")[0].split("?")[0].split("#")[0]
    text = text.strip(". ")
    # Strip synthetic sibling prefix: "1.domain.com" → "domain.com"
    text = re.sub(r"^\d+\.", "", text)
    return text


def company_root(name: Any) -> str:
    """Normalize a company name to its root tokens (no stopwords, lowercase).

    Used for Levenshtein cross-group similarity checks.
    """
    if not name or (isinstance(name, float) and pd.isna(name)):
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t]
    kept = [t for t in tokens if t not in _COMPANY_STOPWORDS]
    return " ".join(kept or tokens[:3])


@dataclass
class SiblingGroup:
    """One resolved plural-domain group with parent and children identified."""
    clean_domain: str
    parent_row: pd.Series
    children: list[pd.Series] = field(default_factory=list)
    unresolved: bool = False

    @property
    def parent_comp_id(self) -> int:
        return int(self.parent_row.get("comp_companyid", 0))

    @property
    def size(self) -> int:
        return 1 + len(self.children)

    def synthetic_domain_for(self, row: pd.Series, sibling_index: int) -> str:
        if sibling_index == 0:
            return self.clean_domain
        return f"{sibling_index}.{self.clean_domain}"


@dataclass
class CrossGroupCandidate:
    """Two groups flagged as likely same root by Levenshtein similarity."""
    domain_a: str
    domain_b: str
    name_similarity: float
    reason: str = "name_levenshtein"


def find_plural_domain_groups(
    df: pd.DataFrame,
    domain_col: str = "comp_website",
    id_col: str = "comp_companyid",
) -> dict[str, pd.DataFrame]:
    """Return only groups where more than one company shares the same clean_domain.

    Returns:
        dict mapping clean_domain → DataFrame of rows in that group.
        Empty dict if no plural groups.
    """
    df = df.copy()
    df["_clean_domain"] = df[domain_col].map(clean_domain)
    # Exclude empty domains — cannot form a meaningful group
    df = df[df["_clean_domain"] != ""]
    counts = df["_clean_domain"].value_counts()
    plural_domains = counts[counts > 1].index.tolist()
    return {
        domain: df[df["_clean_domain"] == domain].copy()
        for domain in plural_domains
    }


def select_canonical_parent(
    group_df: pd.DataFrame,
    gold_df: pd.DataFrame,
    gold_id_col: str = "icalps_company_id",
    id_col: str = "comp_companyid",
) -> SiblingGroup | None:
    """Apply the 3-tier deterministic parent selection rule.

    Tier 1: Among Gold-matched rows, pick the one with the highest contact_count.
    Tier 2: Tie-break by minimum comp_companyid.
    Tier 3: If no Gold-matched row exists → return None (group unresolved).

    Gold-matched = comp_companyid appears in hubspot.companies.icalps_company_id.

    Returns SiblingGroup with parent and children assigned, or None if unresolved.
    """
    gold_ids = set(gold_df[gold_id_col].dropna().astype(str).tolist()) if not gold_df.empty else set()

    group = group_df.copy()
    group["_str_id"] = group[id_col].astype(str)
    group["_gold_matched"] = group["_str_id"].isin(gold_ids)

    gold_matched = group[group["_gold_matched"]].copy()

    if gold_matched.empty:
        # No Gold-matched row → unresolved
        domain = group["_clean_domain"].iloc[0] if "_clean_domain" in group.columns else ""
        return SiblingGroup(
            clean_domain=domain,
            parent_row=pd.Series(dtype=object),
            children=[],
            unresolved=True,
        )

    # Merge contact_count from Gold if available
    if "contact_count" in gold_df.columns:
        gold_map = gold_df.set_index(gold_id_col)["contact_count"].to_dict()
        gold_matched["_contact_count"] = gold_matched["_str_id"].map(gold_map).fillna(0).astype(float)
    elif "contact_count" in gold_matched.columns:
        gold_matched["_contact_count"] = gold_matched["contact_count"].fillna(0).astype(float)
    else:
        gold_matched["_contact_count"] = 0.0

    # Tier 1: highest contact_count; Tier 2: minimum comp_companyid
    parent_row = gold_matched.sort_values(
        ["_contact_count", id_col],
        ascending=[False, True],
    ).iloc[0]

    parent_id = str(parent_row[id_col])
    children_df = group[group["_str_id"] != parent_id].sort_values(id_col)
    domain = group["_clean_domain"].iloc[0] if "_clean_domain" in group.columns else ""

    return SiblingGroup(
        clean_domain=domain,
        parent_row=parent_row,
        children=[row for _, row in children_df.iterrows()],
    )


def assign_sibling_indices(group: SiblingGroup) -> list[dict[str, Any]]:
    """Return a list of dicts with icalps_sibling_index and synthetic_domain assigned.

    Row 0 = parent (sibling_index=0, domain=clean_domain)
    Rows 1..N = children sorted by comp_companyid ASC
    """
    if group.unresolved:
        return []
    rows = []
    rows.append({
        "comp_companyid": group.parent_row.get("comp_companyid"),
        "icalps_sibling_index": 0,
        "icalps_real_domain": group.clean_domain,
        "synthetic_domain": group.clean_domain,
        "role": "parent",
    })
    for i, child in enumerate(group.children, start=1):
        rows.append({
            "comp_companyid": child.get("comp_companyid"),
            "icalps_sibling_index": i,
            "icalps_real_domain": group.clean_domain,
            "synthetic_domain": f"{i}.{group.clean_domain}",
            "role": "child",
        })
    return rows


def detect_all_sibling_groups(
    staging_df: pd.DataFrame,
    gold_df: pd.DataFrame,
    domain_col: str = "comp_website",
    id_col: str = "comp_companyid",
    gold_id_col: str = "icalps_company_id",
) -> tuple[list[SiblingGroup], list[str]]:
    """Run the full sibling detection pipeline.

    Returns:
        (resolved_groups, unresolved_domains)
        resolved_groups: SiblingGroup list with parent+children assigned
        unresolved_domains: list of clean_domain strings where no Gold match was found
    """
    plural_groups = find_plural_domain_groups(staging_df, domain_col=domain_col, id_col=id_col)
    resolved: list[SiblingGroup] = []
    unresolved: list[str] = []

    for domain, group_df in plural_groups.items():
        result = select_canonical_parent(group_df, gold_df, gold_id_col=gold_id_col, id_col=id_col)
        if result is None or result.unresolved:
            unresolved.append(domain)
        else:
            resolved.append(result)

    return resolved, unresolved


def flag_cross_group_candidates(
    plural_groups: dict[str, pd.DataFrame],
    name_col: str = "comp_name",
    threshold: float = _CROSS_GROUP_NAME_SIMILARITY_THRESHOLD,
) -> list[CrossGroupCandidate]:
    """Use Levenshtein similarity to flag pairs of distinct domains that may
    represent the same company (e.g., typo in domain, ccTLD variant).

    These are NOT merged automatically. They are returned for operator review.

    Example:
        "gehealthcare.fr" vs "gehealthcre.fr"  (typo, edit distance=1)
        → flagged if company name roots similarity >= threshold
    """
    domains = list(plural_groups.keys())
    candidates: list[CrossGroupCandidate] = []

    for i in range(len(domains)):
        for j in range(i + 1, len(domains)):
            dom_a, dom_b = domains[i], domains[j]

            # Quick domain similarity check first (avoid O(n^2) name comparisons)
            domain_sim = levenshtein_ratio(dom_a, dom_b)
            if domain_sim < 0.70:
                continue  # Domains too different — skip name comparison

            # Get representative names from each group
            group_a = plural_groups[dom_a]
            group_b = plural_groups[dom_b]
            names_a = group_a[name_col].dropna().tolist() if name_col in group_a.columns else []
            names_b = group_b[name_col].dropna().tolist() if name_col in group_b.columns else []

            if not names_a or not names_b:
                continue

            # Compare all name-root pairs, take max similarity
            best_sim = 0.0
            for na in names_a:
                for nb in names_b:
                    sim = levenshtein_ratio(company_root(na), company_root(nb))
                    if sim > best_sim:
                        best_sim = sim

            if best_sim >= threshold:
                candidates.append(CrossGroupCandidate(
                    domain_a=dom_a,
                    domain_b=dom_b,
                    name_similarity=round(best_sim, 4),
                ))

    return candidates
