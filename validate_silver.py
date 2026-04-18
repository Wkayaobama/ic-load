#!/usr/bin/env python3
"""
validate_silver.py
==================
Post-normalisation data quality gate.

Runs a suite of checks against ``staging.stg_*_normalised`` tables and
produces a JSON report at ``artifacts/silver_validation_YYYYMMDD_HHMMSS.json``.

Severity levels
---------------
STOP  — critical failure; pipeline must halt before dbt / upsert
WARN  — anomaly logged; pipeline may continue with human review
INFO  — informational metric (always passes)

Usage:
    from ic_load_pipeline.python.validate_silver import SilverValidator
    validator = SilverValidator()
    passed = validator.run_checks()   # returns True if no STOP failures

    # Or from CLI:
    python ic_load_pipeline/python/validate_silver.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from context.db import get_connection

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

Severity = Literal["STOP", "WARN", "INFO"]


# ---------------------------------------------------------------------------
# Check result dataclass
# ---------------------------------------------------------------------------

class CheckResult:
    def __init__(
        self,
        name: str,
        severity: Severity,
        passed: bool,
        value: float | int | str,
        threshold: str,
        detail: str = "",
    ):
        self.name = name
        self.severity = severity
        self.passed = passed
        self.value = value
        self.threshold = threshold
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "name":      self.name,
            "severity":  self.severity,
            "passed":    self.passed,
            "value":     self.value,
            "threshold": self.threshold,
            "detail":    self.detail,
        }

    def __str__(self) -> str:
        icon = "✓" if self.passed else ("✗" if self.severity == "STOP" else "!")
        return f"  [{icon}] {self.severity:4}  {self.name}: {self.value}  ({self.threshold})"


# ---------------------------------------------------------------------------
# SilverValidator
# ---------------------------------------------------------------------------

class SilverValidator:

    def __init__(self):
        self.results: list[CheckResult] = []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _q(self, sql: str) -> pd.DataFrame:
        with get_connection() as conn:
            return pd.read_sql(sql, conn)

    def _scalar(self, sql: str) -> float:
        df = self._q(sql)
        return float(df.iloc[0, 0]) if len(df) > 0 else 0.0

    def _add(
        self,
        name: str,
        severity: Severity,
        value: float | int | str,
        threshold: str,
        passed: bool,
        detail: str = "",
    ) -> None:
        r = CheckResult(name, severity, passed, value, threshold, detail)
        self.results.append(r)
        print(str(r))

    # ------------------------------------------------------------------
    # Company checks
    # ------------------------------------------------------------------

    def check_company(self) -> None:
        print("\n[validate] ── Company ──────────────────────────────────────")

        # Row count
        n = int(self._scalar("SELECT COUNT(*) FROM staging.stg_company_normalised"))
        self._add("company.row_count", "INFO", n, ">0", n > 0)

        # Status void rate
        void_status = self._scalar("""
            SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE icalps_companystatus IS NULL) / COUNT(*), 2)
            FROM staging.stg_company_normalised
        """)
        self._add("company.status_void_pct", "WARN", void_status, "<5%", void_status < 5,
                  "Map French Comp_Status values in silver_normalise.py COMPANY_STATUS_MAP")

        # Type void rate
        void_type = self._scalar("""
            SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE icalps_companytype IS NULL) / COUNT(*), 2)
            FROM staging.stg_company_normalised
        """)
        self._add("company.type_void_pct", "WARN", void_type, "<10%", void_type < 10)

        # Address city fill rate
        city_fill = self._scalar("""
            SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE Address_City IS NOT NULL AND Address_City != '') / COUNT(*), 2)
            FROM staging.stg_company_normalised
        """)
        self._add("company.city_fill_pct", "INFO", city_fill, ">50%", city_fill > 50)

        # Unmapped country values
        unmapped_countries = self._q("""
            SELECT icalps_country_raw, COUNT(*) as n
            FROM staging.stg_company_normalised
            WHERE icalps_country_raw IS NOT NULL
              AND icalps_country_raw != ''
              AND icalps_country IS NULL
            GROUP BY 1 ORDER BY 2 DESC LIMIT 20
        """)
        if not unmapped_countries.empty:
            detail = unmapped_countries.to_string(index=False)
            self._add("company.unmapped_countries", "WARN",
                      len(unmapped_countries), "=0 unmapped",
                      len(unmapped_countries) == 0, detail)
        else:
            self._add("company.unmapped_countries", "INFO", 0, "=0 unmapped", True)

    # ------------------------------------------------------------------
    # Contact checks
    # ------------------------------------------------------------------

    def check_contact(self) -> None:
        print("\n[validate] ── Contact ──────────────────────────────────────")

        n = int(self._scalar("SELECT COUNT(*) FROM staging.stg_contact_normalised"))
        self._add("contact.row_count", "INFO", n, ">0", n > 0)

        # Email void rate (critical — drives reconciliation)
        void_email = self._scalar("""
            SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE icalps_email IS NULL) / COUNT(*), 2)
            FROM staging.stg_contact_normalised
        """)
        passed_email = void_email < 10
        severity: Severity = "STOP" if void_email > 25 else "WARN"
        self._add("contact.email_void_pct", severity, void_email, "<10% warn / >25% STOP",
                  passed_email, "Check Person_Email JOIN in Bronze extraction query")

        # Duplicate email check
        dup_emails = int(self._scalar("""
            SELECT COUNT(*) FROM (
                SELECT icalps_email, COUNT(*) as n
                FROM staging.stg_contact_normalised
                WHERE icalps_email IS NOT NULL
                GROUP BY 1 HAVING COUNT(*) > 1
            ) dups
        """))
        self._add("contact.duplicate_emails", "WARN", dup_emails, "=0",
                  dup_emails == 0, "Duplicate emails may cause HubSpot deduplication conflicts")

        # Phone fill rate
        phone_fill = self._scalar("""
            SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE icalps_businessphone IS NOT NULL OR icalps_mobilephone IS NOT NULL) / COUNT(*), 2)
            FROM staging.stg_contact_normalised
        """)
        self._add("contact.phone_fill_pct", "INFO", phone_fill, ">30%", phone_fill > 30)

        # Status void rate
        void_status = self._scalar("""
            SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE icalps_pers_status IS NULL) / COUNT(*), 2)
            FROM staging.stg_contact_normalised
        """)
        self._add("contact.status_void_pct", "WARN", void_status, "<10%", void_status < 10)

    # ------------------------------------------------------------------
    # Opportunity checks
    # ------------------------------------------------------------------

    def check_opportunity(self) -> None:
        print("\n[validate] ── Opportunity ──────────────────────────────────")

        n = int(self._scalar("SELECT COUNT(*) FROM staging.stg_opportunity_normalised"))
        self._add("opportunity.row_count", "INFO", n, ">0", n > 0)

        # Stage null rate for non-deleted deals (STOP if > 0)
        null_stage = int(self._scalar("""
            SELECT COUNT(*) FROM staging.stg_opportunity_normalised
            WHERE (oppo_deleted IS NULL OR oppo_deleted::text = '0' OR oppo_deleted::text = 'False')
              AND (hubspot_dealstage_name IS NULL OR hubspot_dealstage_name = '')
        """))
        self._add("opportunity.null_stage_count", "STOP", null_stage, "=0",
                  null_stage == 0,
                  "Active deals must have hubspot_dealstage_name. Check deal_stage_mapper.py")

        # Duplicate Oppo_OpportunityId
        dup_ids = int(self._scalar("""
            SELECT COUNT(*) FROM (
                SELECT Oppo_OpportunityId, COUNT(*) as n
                FROM staging.stg_opportunity_normalised
                GROUP BY 1 HAVING COUNT(*) > 1
            ) dups
        """))
        self._add("opportunity.duplicate_ids", "STOP", dup_ids, "=0",
                  dup_ids == 0, "Deduplication failed — check ROW_NUMBER() in silver_normalise.py")

        # Amount unit sanity: avg forecast > 50,000 suggests absolute euros not k€
        avg_forecast = self._scalar("""
            SELECT AVG(icalps_forecast)
            FROM staging.stg_opportunity_normalised
            WHERE icalps_forecast IS NOT NULL AND icalps_forecast > 0
        """)
        likely_absolute = avg_forecast > 50_000
        self._add("opportunity.avg_forecast", "STOP" if likely_absolute else "INFO",
                  round(avg_forecast, 0), "<50,000 (k€ expected)",
                  not likely_absolute,
                  "Average forecast > 50k suggests values are in absolute euros, not k€. Divide by 1000." if likely_absolute else "")

        # Close date null rate for Won/Lost deals
        null_close = int(self._scalar("""
            SELECT COUNT(*) FROM staging.stg_opportunity_normalised
            WHERE Oppo_Status IN ('Gagnée','Perdue','Gagn\u00e9e','Won','Lost','Closed Won','Closed Lost')
              AND icalps_closedate IS NULL
        """))
        self._add("opportunity.null_closedate_won_lost", "WARN", null_close, "=0",
                  null_close == 0, "Closed deals without close date disappear from pipeline reports")

    # ------------------------------------------------------------------
    # Communication checks
    # ------------------------------------------------------------------

    def check_communication(self) -> None:
        print("\n[validate] ── Communication ────────────────────────────────")

        n = int(self._scalar("SELECT COUNT(*) FROM staging.stg_communication_normalised"))
        self._add("communication.row_count", "INFO", n, ">0", n > 0)

        # Person_Id null rate (drives associations)
        null_person = self._scalar("""
            SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE Person_Id IS NULL) / COUNT(*), 2)
            FROM staging.stg_communication_normalised
        """)
        self._add("communication.null_person_id_pct", "WARN", null_person, "<20%", null_person < 20,
                  "High null Person_Id rate will reduce engagement associations")

        # Company_Id null rate
        null_company = self._scalar("""
            SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE Company_Id IS NULL) / COUNT(*), 2)
            FROM staging.stg_communication_normalised
        """)
        self._add("communication.null_company_id_pct", "WARN", null_company, "<20%", null_company < 20)

        # Volume breakdown by action type
        breakdown = self._q("""
            SELECT Comm_Action, COUNT(*) as n
            FROM staging.stg_communication_normalised
            GROUP BY 1 ORDER BY 2 DESC
        """)
        detail = breakdown.to_string(index=False) if not breakdown.empty else "empty"
        self._add("communication.action_breakdown", "INFO", n, "see detail", True, detail)

    # ------------------------------------------------------------------
    # Owner resolution check
    # ------------------------------------------------------------------

    def check_owner_resolution(self) -> None:
        print("\n[validate] ── Owner Resolution ─────────────────────────────")

        try:
            total = int(self._scalar("SELECT COUNT(DISTINCT icalps_ownerid_raw) FROM staging.stg_company_normalised WHERE icalps_ownerid_raw IS NOT NULL"))
            resolved = int(self._scalar("""
                SELECT COUNT(DISTINCT s.icalps_ownerid_raw)
                FROM staging.stg_company_normalised s
                INNER JOIN staging.stg_owner_resolution r ON s.icalps_ownerid_raw = r.owner_email
            """))
            unresolved_pct = round(100.0 * (total - resolved) / total, 1) if total > 0 else 0.0
            self._add("owner.unresolved_pct", "WARN", unresolved_pct, "<5%",
                      unresolved_pct < 5,
                      f"{total - resolved} of {total} owner emails could not be resolved to a HubSpot owner ID")
        except Exception as exc:
            self._add("owner.resolution_check", "WARN", "error", "n/a", False, str(exc))

    # ------------------------------------------------------------------
    # Reconciliation match rates (cross-check with Gold)
    # ------------------------------------------------------------------

    def check_reconciliation_rates(self) -> None:
        print("\n[validate] ── Reconciliation Rates ────────────────────────")

        for entity, staging_table, pk_col, hs_table, hs_key in [
            ("company",  "staging.stg_company_normalised",     "Comp_CompanyId",      "hubspot.companies", "icalps_company_id"),
            ("contact",  "staging.stg_contact_normalised",     "Pers_PersonId",       "hubspot.contacts",  "icalps_contact_id"),
            ("deal",     "staging.stg_opportunity_normalised", "Oppo_OpportunityId",  "hubspot.deals",     "icalps_deal_id"),
        ]:
            try:
                row = self._q(f"""
                    SELECT
                        COUNT(*)                          AS total,
                        COUNT(hs.id)                      AS matched,
                        ROUND(100.0*COUNT(hs.id)/NULLIF(COUNT(*),0), 1) AS match_pct
                    FROM {staging_table} stg
                    LEFT JOIN {hs_table} hs
                        ON stg.{pk_col}::TEXT = hs.{hs_key}::TEXT
                """).iloc[0]
                total    = int(row["total"])
                matched  = int(row["matched"])
                pct      = float(row["match_pct"] or 0)
                target   = {"company": 95, "contact": 80, "deal": 87}[entity]
                self._add(f"reconciliation.{entity}_match_pct", "WARN",
                          pct, f">={target}%", pct >= target,
                          f"{matched}/{total} matched")
            except Exception as exc:
                self._add(f"reconciliation.{entity}_match_pct", "WARN", "error", "n/a", False, str(exc))

    # ------------------------------------------------------------------
    # run_checks
    # ------------------------------------------------------------------

    def run_checks(self) -> bool:
        """
        Execute all checks. Returns True if no STOP-severity failures.

        Writes JSON report to artifacts/silver_validation_YYYYMMDD_HHMMSS.json.
        """
        print("\n" + "=" * 62)
        print("  Silver Layer Validation")
        print("=" * 62)

        self.check_company()
        self.check_contact()
        self.check_opportunity()
        self.check_communication()
        self.check_owner_resolution()
        self.check_reconciliation_rates()

        # Summary
        stops  = [r for r in self.results if r.severity == "STOP"  and not r.passed]
        warns  = [r for r in self.results if r.severity == "WARN"  and not r.passed]
        passed = [r for r in self.results if r.passed]

        print("\n" + "=" * 62)
        print(f"  Checks passed : {len(passed)}/{len(self.results)}")
        print(f"  STOP failures : {len(stops)}")
        print(f"  WARN failures : {len(warns)}")
        if stops:
            print("\n  BLOCKING ISSUES:")
            for r in stops:
                print(f"    • {r.name}: {r.detail or r.value}")
        print("=" * 62)

        # Write JSON report
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = ARTIFACTS_DIR / f"silver_validation_{ts}.json"
        report = {
            "run_at":  ts,
            "summary": {
                "total_checks": len(self.results),
                "passed":       len(passed),
                "stop_failures": len(stops),
                "warn_failures": len(warns),
                "pipeline_blocked": len(stops) > 0,
            },
            "checks": [r.to_dict() for r in self.results],
        }
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  Report: {report_path}")

        return len(stops) == 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    validator = SilverValidator()
    ok = validator.run_checks()
    sys.exit(0 if ok else 1)
