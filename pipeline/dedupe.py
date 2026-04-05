from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from context.algorithms.levenshtein import get_scorer
from context.config import ARTIFACTS_DIR, load_business_rules, load_entity_translation_contract
from context.db import get_connection
from pipeline.text_normalization import clean_text_utf8

# SequenceMatcher is kept as a fallback for long free-text fields only.
# Short identity strings (names, domains, emails) now use Levenshtein via get_scorer().
# To swap in an MCP scorer: call context.algorithms.levenshtein.set_scorer(MCPScorer(call_fn))
# before running the guardrail. The scorer is module-level and injectable at startup.

_COMPANY_STOPWORDS = {
    "ag",
    "corp",
    "corporation",
    "company",
    "co",
    "gmbh",
    "holding",
    "inc",
    "ltd",
    "llc",
    "sa",
    "sarl",
    "sas",
    "solutions",
    "systems",
    "technology",
    "technologies",
}


@dataclass(frozen=True)
class ThresholdBand:
    review_score_min: float
    block_score_min: float


def _norm_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    cleaned = clean_text_utf8(value)
    if cleaned is None:
        return ""
    text = unicodedata.normalize("NFKD", str(cleaned))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[\s\r\n\t]+", " ", text)
    text = re.sub(r"[^a-z0-9@._/:\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _norm_digits(value: Any) -> str:
    return "".join(ch for ch in _norm_text(value) if ch.isdigit())


def _norm_id(value: Any) -> str:
    text = _norm_text(value)
    if not text:
        return ""
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def _norm_email(value: Any) -> str:
    return _norm_text(value).replace("mailto:", "")


def _norm_domain(value: Any) -> str:
    text = _norm_text(value)
    if not text:
        return ""
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    text = text.split("/")[0].split("?")[0].split("#")[0]
    return text.strip(". ")


def _company_root(value: Any) -> str:
    tokens = [token for token in re.split(r"[^a-z0-9]+", _norm_text(value)) if token]
    kept = [token for token in tokens if token not in _COMPANY_STOPWORDS]
    return " ".join(kept or tokens[:3])


def _similarity(left: Any, right: Any) -> float:
    """Levenshtein-based similarity for short identity strings.

    Uses the module-level scorer from context.algorithms.levenshtein.
    Swap scorer via set_scorer(MCPScorer(call_fn)) for semantic matching.
    Suitable for: company names, contact names, domains, email addresses.
    For long free-text (notes, descriptions): scorer falls back gracefully.
    """
    lhs = _norm_text(left)
    rhs = _norm_text(right)
    if not lhs or not rhs:
        return 0.0
    return get_scorer().score(lhs, rhs)


def _coerce_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        result[column] = result[column].where(pd.notna(result[column]), None)
    return result


class DedupeGuardrail:
    """Assess duplicate risk before Gold upserts or mirrored association writes."""

    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or (ARTIFACTS_DIR / "dedupe_guard")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.contract = load_entity_translation_contract()
        self.rules = load_business_rules().get("dedupe_guardrail", {})

    def execute(
        self,
        entity: str,
        *,
        dry_run: bool = False,
        candidate_frame: pd.DataFrame | None = None,
        reference_frame: pd.DataFrame | None = None,
    ) -> dict[str, Any]:
        normalized = entity.lower()
        if normalized == "communication":
            return self._assess_communication(dry_run=dry_run)

        if normalized not in self.contract:
            return {"entity": entity, "mode": "not_applicable", "block_count": 0, "review_count": 0, "safe_count": 0}

        candidate = _coerce_frame(candidate_frame if candidate_frame is not None else self._load_candidate_frame(normalized))
        reference = _coerce_frame(reference_frame if reference_frame is not None else self._load_reference_frame(normalized))
        thresholds = self._thresholds_for(normalized)

        decisions = self._score_rows(normalized, candidate, reference, thresholds)
        scored = pd.DataFrame(decisions)
        artifact_base = self.output_dir / f"dedupe_{normalized}"
        artifact_csv = artifact_base.with_suffix(".csv")
        artifact_json = artifact_base.with_suffix(".json")
        scored.to_csv(artifact_csv, index=False, encoding="utf-8")

        summary = {
            "entity": normalized,
            "mode": "dry_run" if dry_run else "assessed",
            "candidate_rows": int(len(candidate)),
            "reference_rows": int(len(reference)),
            "block_count": int((scored["decision"] == "block").sum()) if not scored.empty else 0,
            "review_count": int((scored["decision"] == "review").sum()) if not scored.empty else 0,
            "safe_count": int((scored["decision"] == "safe").sum()) if not scored.empty else 0,
            "artifact_csv": str(artifact_csv),
            "artifact_json": str(artifact_json),
        }
        artifact_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    def _thresholds_for(self, entity: str) -> ThresholdBand:
        defaults = {
            "company": ThresholdBand(review_score_min=0.65, block_score_min=0.82),
            "contact": ThresholdBand(review_score_min=0.60, block_score_min=0.80),
            "opportunity": ThresholdBand(review_score_min=0.62, block_score_min=0.78),
            "case": ThresholdBand(review_score_min=0.65, block_score_min=0.82),
        }
        raw = self.rules.get("thresholds", {}).get(entity, {})
        base = defaults.get(entity, ThresholdBand(0.65, 0.82))
        return ThresholdBand(
            review_score_min=float(raw.get("review_score_min", base.review_score_min)),
            block_score_min=float(raw.get("block_score_min", base.block_score_min)),
        )

    def _load_candidate_frame(self, entity: str) -> pd.DataFrame:
        table_map = {
            "company": "stg_company_normalised",
            "contact": "stg_contact_normalised",
            "opportunity": "stg_opportunity_normalised",
            "case": "stg_case",
        }
        table_name = table_map[entity]
        with get_connection() as conn:
            frame = pd.read_sql_query(f"SELECT * FROM staging.{table_name}", conn)
        if "_load_status" in frame.columns:
            eligible = frame["_load_status"].astype(str).str.upper().isin({"NEW", "MODIFIED"})
            if eligible.any():
                frame = frame.loc[eligible].copy()
        return frame

    def _load_reference_frame(self, entity: str) -> pd.DataFrame:
        benchmark = self.contract[entity]["gold"]["benchmark_export"]
        path = Path(benchmark)
        if not path.exists():
            return pd.DataFrame()
        return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8-sig")

    def _score_rows(
        self,
        entity: str,
        candidate: pd.DataFrame,
        reference: pd.DataFrame,
        thresholds: ThresholdBand,
    ) -> list[dict[str, Any]]:
        if candidate.empty:
            return []

        rows: list[dict[str, Any]] = []
        candidate_duplicates = self._candidate_duplicate_flags(entity, candidate)

        for _, row in candidate.iterrows():
            candidate_id, exact_id_match = self._candidate_identifier(entity, row)
            duplicate_reason = candidate_duplicates.get(candidate_id) or candidate_duplicates.get(self._candidate_identity_key(entity, row))
            if duplicate_reason:
                rows.append(
                    self._decision_row(
                        entity,
                        row,
                        decision="block",
                        score=1.0,
                        reason=f"intra_candidate_duplicate:{duplicate_reason}",
                        matched_reference_id=None,
                    )
                )
                continue

            if exact_id_match and self._reference_contains_exact_id(entity, reference, exact_id_match):
                rows.append(
                    self._decision_row(
                        entity,
                        row,
                        decision="safe",
                        score=0.0,
                        reason="exact_canonical_id_match",
                        matched_reference_id=exact_id_match,
                    )
                )
                continue

            match = self._best_reference_match(entity, row, reference)
            if match is None:
                rows.append(
                    self._decision_row(entity, row, decision="safe", score=0.0, reason="no_reference_match", matched_reference_id=None)
                )
                continue

            score, reason, reference_id = match
            if score >= thresholds.block_score_min:
                decision = "block"
            elif score >= thresholds.review_score_min:
                decision = "review"
            else:
                decision = "safe"

            rows.append(self._decision_row(entity, row, decision=decision, score=score, reason=reason, matched_reference_id=reference_id))

        return rows

    def _candidate_identifier(self, entity: str, row: pd.Series) -> tuple[str, str]:
        if entity == "company":
            key = _norm_id(row.get("comp_companyid"))
            return key, key
        if entity == "contact":
            key = _norm_id(row.get("pers_personid"))
            return key, key
        if entity == "opportunity":
            key = _norm_id(row.get("oppo_opportunityid"))
            return key, key
        key = _norm_id(row.get("icalps_ticket_id"))
        return key, key

    def _candidate_identity_key(self, entity: str, row: pd.Series) -> str:
        if entity == "company":
            return f"{_norm_domain(row.get('comp_website'))}|{_company_root(row.get('comp_name'))}"
        if entity == "contact":
            email = _norm_email(row.get("icalps_email"))
            return email or f"{_norm_text(row.get('pers_firstname'))}|{_norm_text(row.get('pers_lastname'))}|{_norm_id(row.get('pers_companyid'))}"
        if entity == "opportunity":
            return f"{_norm_text(row.get('oppo_description'))}|{_norm_id(row.get('oppo_primarycompanyid'))}"
        if entity == "case":
            return f"{_norm_text(row.get('subject'))}|{_norm_id(row.get('icalps_company_id'))}"
        return ""

    def _candidate_duplicate_flags(self, entity: str, frame: pd.DataFrame) -> dict[str, str]:
        flags: dict[str, str] = {}
        id_keys: dict[str, int] = {}
        identity_keys: dict[str, int] = {}

        for _, row in frame.iterrows():
            candidate_id, _ = self._candidate_identifier(entity, row)
            identity_key = self._candidate_identity_key(entity, row)

            if candidate_id:
                id_keys[candidate_id] = id_keys.get(candidate_id, 0) + 1
            if identity_key:
                identity_keys[identity_key] = identity_keys.get(identity_key, 0) + 1

        for key, count in id_keys.items():
            if count > 1:
                flags[key] = "duplicate_primary_key"
        for key, count in identity_keys.items():
            if count > 1:
                flags[key] = "duplicate_identity_signature"
        return flags

    def _reference_contains_exact_id(self, entity: str, reference: pd.DataFrame, exact_id: str) -> bool:
        if reference.empty or not exact_id:
            return False
        column = {
            "company": "icalps_company_id",
            "contact": "icalps_contact_id",
            "opportunity": "icalps_deal_id",
            "case": "IcAlps_TicketID",
        }[entity]
        if column not in reference.columns:
            return False
        return reference[column].map(_norm_id).eq(exact_id).any()

    def _best_reference_match(self, entity: str, row: pd.Series, reference: pd.DataFrame) -> tuple[float, str, str | None] | None:
        if reference.empty:
            return None

        pool = self._reference_pool(entity, row, reference)
        if pool.empty:
            return None

        best_score = 0.0
        best_reason = "no_match"
        best_ref_id: str | None = None

        for _, ref in pool.iterrows():
            if entity == "company":
                score, reason = self._company_match_score(row, ref)
                ref_id = _norm_id(ref.get("icalps_company_id")) or None
            elif entity == "contact":
                score, reason = self._contact_match_score(row, ref)
                ref_id = _norm_id(ref.get("icalps_contact_id")) or None
            elif entity == "opportunity":
                score, reason = self._opportunity_match_score(row, ref)
                ref_id = _norm_id(ref.get("icalps_deal_id")) or None
            else:
                score, reason = self._case_match_score(row, ref)
                ref_id = _norm_id(ref.get("IcAlps_TicketID")) or None

            if score > best_score:
                best_score = score
                best_reason = reason
                best_ref_id = ref_id

        return best_score, best_reason, best_ref_id

    def _reference_pool(self, entity: str, row: pd.Series, reference: pd.DataFrame) -> pd.DataFrame:
        if entity == "company":
            domain = _norm_domain(row.get("comp_website"))
            root = _company_root(row.get("comp_name"))
            domain_matches = reference["Company Domain Name"].fillna("").map(_norm_domain).eq(domain) if "Company Domain Name" in reference.columns else pd.Series(False, index=reference.index)
            root_matches = reference["Company name"].fillna("").map(_company_root).eq(root) if "Company name" in reference.columns else pd.Series(False, index=reference.index)
            pool = reference.loc[domain_matches | root_matches]
            return pool if not pool.empty else reference.head(200)

        if entity == "contact":
            email = _norm_email(row.get("icalps_email"))
            company_id = _norm_id(row.get("pers_companyid"))
            email_matches = reference["Email"].fillna("").map(_norm_email).eq(email) if "Email" in reference.columns else pd.Series(False, index=reference.index)
            company_matches = reference["Primary Associated Company ID"].fillna("").map(_norm_id).eq(company_id) if "Primary Associated Company ID" in reference.columns else pd.Series(False, index=reference.index)
            lastname = _norm_text(row.get("pers_lastname"))
            name_matches = reference["Last Name"].fillna("").map(_norm_text).eq(lastname) if "Last Name" in reference.columns else pd.Series(False, index=reference.index)
            pool = reference.loc[email_matches | company_matches | name_matches]
            return pool if not pool.empty else reference.head(250)

        if entity == "opportunity":
            company_id = _norm_id(row.get("oppo_primarycompanyid"))
            name_root = _norm_text(row.get("oppo_description"))[:30]
            company_matches = reference["icalps_company_id"].fillna("").map(_norm_id).eq(company_id) if "icalps_company_id" in reference.columns else pd.Series(False, index=reference.index)
            name_matches = reference["Deal Name"].fillna("").map(_norm_text).str.startswith(name_root[:10]) if "Deal Name" in reference.columns and name_root else pd.Series(False, index=reference.index)
            pool = reference.loc[company_matches | name_matches]
            return pool if not pool.empty else reference

        subject_root = _norm_text(row.get("subject"))[:24]
        company_id = _norm_id(row.get("icalps_company_id"))
        company_matches = reference["IcAlps_CompanyID"].fillna("").map(_norm_id).eq(company_id) if "IcAlps_CompanyID" in reference.columns else pd.Series(False, index=reference.index)
        subject_matches = reference["Ticket name"].fillna("").map(_norm_text).str.startswith(subject_root[:10]) if "Ticket name" in reference.columns and subject_root else pd.Series(False, index=reference.index)
        pool = reference.loc[company_matches | subject_matches]
        return pool if not pool.empty else reference

    def _company_match_score(self, candidate: pd.Series, reference: pd.Series) -> tuple[float, str]:
        score = 0.0
        reasons: list[str] = []

        if _norm_domain(candidate.get("comp_website")) and _norm_domain(candidate.get("comp_website")) == _norm_domain(reference.get("Company Domain Name")):
            score += 0.45
            reasons.append("domain_exact")

        name_score = _similarity(_company_root(candidate.get("comp_name")), _company_root(reference.get("Company name")))
        score += 0.35 * name_score
        if name_score >= 0.85:
            reasons.append(f"name_sim={name_score:.2f}")

        if _norm_text(candidate.get("address_city")) and _norm_text(candidate.get("address_city")) == _norm_text(reference.get("City")):
            score += 0.10
            reasons.append("city_exact")

        if _norm_digits(candidate.get("icalps_companyphone")) and _norm_digits(candidate.get("icalps_companyphone")) == _norm_digits(reference.get("Icalps_CompanyPhone")):
            score += 0.10
            reasons.append("phone_exact")

        return min(score, 1.0), ",".join(reasons) or "weak_match"

    def _contact_match_score(self, candidate: pd.Series, reference: pd.Series) -> tuple[float, str]:
        score = 0.0
        reasons: list[str] = []

        if _norm_email(candidate.get("icalps_email")) and _norm_email(candidate.get("icalps_email")) == _norm_email(reference.get("Email")):
            score += 0.65
            reasons.append("email_exact")

        full_name_candidate = f"{candidate.get('pers_firstname', '')} {candidate.get('pers_lastname', '')}"
        full_name_reference = f"{reference.get('First Name', '')} {reference.get('Last Name', '')}"
        name_score = _similarity(full_name_candidate, full_name_reference)
        score += 0.20 * name_score
        if name_score >= 0.85:
            reasons.append(f"name_sim={name_score:.2f}")

        if _norm_id(candidate.get("pers_companyid")) and _norm_id(candidate.get("pers_companyid")) == _norm_id(reference.get("Primary Associated Company ID")):
            score += 0.10
            reasons.append("company_exact")

        candidate_phone = _norm_digits(candidate.get("icalps_businessphone")) or _norm_digits(candidate.get("icalps_mobilephone"))
        reference_phone = _norm_digits(reference.get("Phone Number")) or _norm_digits(reference.get("IcAlps_BusinessPhone"))
        if candidate_phone and candidate_phone == reference_phone:
            score += 0.10
            reasons.append("phone_exact")

        return min(score, 1.0), ",".join(reasons) or "weak_match"

    def _opportunity_match_score(self, candidate: pd.Series, reference: pd.Series) -> tuple[float, str]:
        score = 0.0
        reasons: list[str] = []

        name_score = _similarity(candidate.get("oppo_description"), reference.get("Deal Name"))
        score += 0.45 * name_score
        if name_score >= 0.80:
            reasons.append(f"name_sim={name_score:.2f}")

        if _norm_id(candidate.get("oppo_primarycompanyid")) and _norm_id(candidate.get("oppo_primarycompanyid")) == _norm_id(reference.get("icalps_company_id")):
            score += 0.20
            reasons.append("company_exact")

        if _norm_id(candidate.get("oppo_primarypersonid")) and _norm_id(candidate.get("oppo_primarypersonid")) == _norm_id(reference.get("icalps_contact_id")):
            score += 0.10
            reasons.append("contact_exact")

        if _norm_text(candidate.get("hubspot_pipeline_id")) and _norm_text(candidate.get("hubspot_pipeline_id")) == _norm_text(reference.get("Pipeline")):
            score += 0.10
            reasons.append("pipeline_exact")

        if _norm_text(candidate.get("hubspot_dealstage_name")) and _norm_text(candidate.get("hubspot_dealstage_name")) == _norm_text(reference.get("IcAlps_Stage")):
            score += 0.05
            reasons.append("stage_exact")

        amount_left = _norm_digits(candidate.get("icalps_forecast"))
        amount_right = _norm_digits(reference.get("Amount"))
        if amount_left and amount_left == amount_right:
            score += 0.10
            reasons.append("amount_exact")

        return min(score, 1.0), ",".join(reasons) or "weak_match"

    def _case_match_score(self, candidate: pd.Series, reference: pd.Series) -> tuple[float, str]:
        score = 0.0
        reasons: list[str] = []

        subject_score = _similarity(candidate.get("subject"), reference.get("Ticket name"))
        score += 0.45 * subject_score
        if subject_score >= 0.80:
            reasons.append(f"subject_sim={subject_score:.2f}")

        if _norm_id(candidate.get("icalps_company_id")) and _norm_id(candidate.get("icalps_company_id")) == _norm_id(reference.get("IcAlps_CompanyID")):
            score += 0.20
            reasons.append("company_exact")

        if _norm_email(candidate.get("icalps_contact_email")) and _norm_email(candidate.get("icalps_contact_email")) == _norm_email(reference.get("IcAlps_TicketPersonEmailAddress")):
            score += 0.15
            reasons.append("contact_email_exact")

        if _norm_text(candidate.get("icalps_case_stage")) and _norm_text(candidate.get("icalps_case_stage")) == _norm_text(reference.get("IcAlps_TicketStage")):
            score += 0.10
            reasons.append("stage_exact")

        if _norm_text(candidate.get("icalps_case_status")) and _norm_text(candidate.get("icalps_case_status")) == _norm_text(reference.get("Ticket status")):
            score += 0.05
            reasons.append("status_exact")

        if _norm_text(candidate.get("hs_ticket_priority")) and _norm_text(candidate.get("hs_ticket_priority")) == _norm_text(reference.get("Priority")):
            score += 0.05
            reasons.append("priority_exact")

        return min(score, 1.0), ",".join(reasons) or "weak_match"

    def _decision_row(
        self,
        entity: str,
        row: pd.Series,
        *,
        decision: str,
        score: float,
        reason: str,
        matched_reference_id: str | None,
    ) -> dict[str, Any]:
        candidate_id, _ = self._candidate_identifier(entity, row)
        return {
            "entity": entity,
            "candidate_id": candidate_id,
            "decision": decision,
            "score": round(score, 4),
            "reason": reason,
            "matched_reference_id": matched_reference_id,
            "display_name": self._display_name(entity, row),
        }

    def _display_name(self, entity: str, row: pd.Series) -> str:
        if entity == "company":
            return str(row.get("comp_name", ""))
        if entity == "contact":
            return f"{row.get('pers_firstname', '')} {row.get('pers_lastname', '')}".strip()
        if entity == "opportunity":
            return str(row.get("oppo_description", ""))
        if entity == "case":
            return str(row.get("subject", ""))
        return str(row.get("icalps_communication_id", ""))

    def _assess_communication(self, *, dry_run: bool = False) -> dict[str, Any]:
        with get_connection() as conn:
            frames = {
                "calls": pd.read_sql_query("SELECT icalps_communication_id FROM staging.fct_communication_calls", conn),
                "notes": pd.read_sql_query("SELECT icalps_communication_id FROM staging.fct_communication_notes", conn),
                "tasks": pd.read_sql_query("SELECT icalps_communication_id FROM staging.fct_communication_tasks", conn),
                "meetings": pd.read_sql_query("SELECT icalps_communication_id FROM staging.fct_communication_meetings", conn),
            }

        rows: list[dict[str, Any]] = []
        block_count = 0
        safe_count = 0

        for comm_type, frame in frames.items():
            dupes = frame["icalps_communication_id"].duplicated(keep=False)
            for _, value in frame.loc[dupes, "icalps_communication_id"].items():
                rows.append(
                    {
                        "entity": "communication",
                        "candidate_id": str(value),
                        "decision": "block",
                        "score": 1.0,
                        "reason": f"duplicate_unique_id_in_{comm_type}",
                        "matched_reference_id": None,
                        "display_name": comm_type,
                    }
                )
                block_count += 1
            safe_count += int((~dupes).sum())

        if not rows:
            for comm_type, frame in frames.items():
                rows.append(
                    {
                        "entity": "communication",
                        "candidate_id": comm_type,
                        "decision": "safe",
                        "score": 0.0,
                        "reason": f"unique_ids_ok:{len(frame)}",
                        "matched_reference_id": None,
                        "display_name": comm_type,
                    }
                )

        scored = pd.DataFrame(rows)
        artifact_base = self.output_dir / "dedupe_communication"
        artifact_csv = artifact_base.with_suffix(".csv")
        artifact_json = artifact_base.with_suffix(".json")
        scored.to_csv(artifact_csv, index=False, encoding="utf-8")

        summary = {
            "entity": "communication",
            "mode": "dry_run" if dry_run else "assessed",
            "candidate_rows": int(sum(len(frame) for frame in frames.values())),
            "reference_rows": 0,
            "block_count": block_count,
            "review_count": 0,
            "safe_count": safe_count,
            "artifact_csv": str(artifact_csv),
            "artifact_json": str(artifact_json),
        }
        artifact_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary
