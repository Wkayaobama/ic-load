"""Generate pipeline audit trail CSV with comprehensive metrics across all layers."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from context.db import get_connection


def main():
    metrics = []

    def add_metric(entity: str, layer: str, metric_name: str, value, notes: str = ""):
        metrics.append({
            "entity": entity,
            "layer": layer,
            "metric": metric_name,
            "value": value,
            "notes": notes,
        })

    with get_connection() as conn:
        with conn.cursor() as cur:
            # ═══════════════════════════════════════════════════════════════════
            # COMPANY METRICS
            # ═══════════════════════════════════════════════════════════════════

            # Bronze layer - raw staging
            try:
                cur.execute("SELECT COUNT(*) FROM staging.stg_company")
                add_metric("Company", "Bronze", "total_records", cur.fetchone()[0], "Raw extraction from IC ALPS")
            except Exception as e:
                add_metric("Company", "Bronze", "total_records", "ERROR", str(e)[:50])

            # Silver layer - normalized
            try:
                cur.execute("SELECT COUNT(*) FROM staging.stg_company_normalised")
                add_metric("Company", "Silver", "total_records", cur.fetchone()[0])

                cur.execute("SELECT COUNT(*) FROM staging.stg_company_normalised WHERE _load_status = 'NEW'")
                add_metric("Company", "Silver", "status_new", cur.fetchone()[0])

                cur.execute("SELECT COUNT(*) FROM staging.stg_company_normalised WHERE _load_status = 'MODIFIED'")
                add_metric("Company", "Silver", "status_modified", cur.fetchone()[0])

                cur.execute("SELECT COUNT(icalps_sibling_index) FROM staging.stg_company_normalised")
                add_metric("Company", "Silver", "with_sibling_index", cur.fetchone()[0], "Companies assigned to sibling groups")

                cur.execute("SELECT COUNT(DISTINCT icalps_canonical_domain) FROM staging.stg_company_normalised WHERE icalps_canonical_domain IS NOT NULL")
                add_metric("Company", "Silver", "unique_domains", cur.fetchone()[0], "Distinct canonical domains")

                cur.execute("SELECT COUNT(*) FROM staging.stg_company_normalised WHERE icalps_canonical_domain IS NOT NULL")
                add_metric("Company", "Silver", "with_domain", cur.fetchone()[0], "Companies with parsed domain")

                cur.execute("SELECT COUNT(*) FROM staging.stg_company_normalised WHERE icalps_companyphone IS NOT NULL")
                add_metric("Company", "Silver", "with_phone_e164", cur.fetchone()[0], "E.164 normalized phone numbers")

                cur.execute("SELECT COUNT(*) FROM staging.stg_company_normalised WHERE icalps_sibling_index = 0")
                add_metric("Company", "Silver", "sibling_parent_companies", cur.fetchone()[0], "Companies that are group parents (index=0)")

                cur.execute("SELECT COUNT(*) FROM staging.stg_company_normalised WHERE icalps_sibling_index > 0")
                add_metric("Company", "Silver", "sibling_child_companies", cur.fetchone()[0], "Companies that are siblings (index>0)")

            except Exception as e:
                add_metric("Company", "Silver", "error", 0, str(e)[:100])

            # ═══════════════════════════════════════════════════════════════════
            # CONTACT METRICS
            # ═══════════════════════════════════════════════════════════════════

            try:
                cur.execute("SELECT COUNT(*) FROM staging.stg_contact")
                add_metric("Contact", "Bronze", "total_records", cur.fetchone()[0], "Raw extraction from IC ALPS")
            except Exception as e:
                add_metric("Contact", "Bronze", "total_records", "ERROR", str(e)[:50])

            try:
                cur.execute("SELECT COUNT(*) FROM staging.stg_contact_normalised")
                add_metric("Contact", "Silver", "total_records", cur.fetchone()[0])

                cur.execute("SELECT COUNT(*) FROM staging.stg_contact_normalised WHERE _load_status IN ('NEW', 'MODIFIED')")
                add_metric("Contact", "Silver", "upsert_candidates", cur.fetchone()[0], "Records eligible for gold upsert")

                cur.execute("SELECT COUNT(*) FROM staging.stg_contact_normalised WHERE email IS NOT NULL")
                add_metric("Contact", "Silver", "with_email", cur.fetchone()[0])

                cur.execute("SELECT COUNT(DISTINCT icalps_company_id) FROM staging.stg_contact_normalised WHERE icalps_company_id IS NOT NULL")
                add_metric("Contact", "Silver", "linked_to_companies", cur.fetchone()[0], "Distinct companies with contacts")

            except Exception as e:
                add_metric("Contact", "Silver", "error", 0, str(e)[:100])

            # ═══════════════════════════════════════════════════════════════════
            # OPPORTUNITY/DEAL METRICS
            # ═══════════════════════════════════════════════════════════════════

            try:
                cur.execute("SELECT COUNT(*) FROM staging.stg_opportunity")
                add_metric("Opportunity", "Bronze", "total_records", cur.fetchone()[0], "Raw extraction from IC ALPS")
            except Exception as e:
                add_metric("Opportunity", "Bronze", "total_records", "ERROR", str(e)[:50])

            try:
                cur.execute("SELECT COUNT(*) FROM staging.stg_opportunity_normalised")
                add_metric("Opportunity", "Silver", "total_records", cur.fetchone()[0])

                cur.execute("SELECT COUNT(*) FROM staging.stg_opportunity_normalised WHERE _load_status IN ('NEW', 'MODIFIED')")
                add_metric("Opportunity", "Silver", "upsert_candidates", cur.fetchone()[0])

                cur.execute("SELECT COUNT(*) FROM staging.stg_opportunity_normalised WHERE amount IS NOT NULL AND amount::numeric > 0")
                add_metric("Opportunity", "Silver", "with_amount", cur.fetchone()[0], "Deals with positive amount")

                cur.execute("SELECT COALESCE(SUM(amount::numeric), 0) FROM staging.stg_opportunity_normalised WHERE amount IS NOT NULL")
                add_metric("Opportunity", "Silver", "total_amount_eur", round(cur.fetchone()[0], 2), "Sum of deal amounts")

                cur.execute("SELECT COUNT(DISTINCT pipeline) FROM staging.stg_opportunity_normalised WHERE pipeline IS NOT NULL")
                add_metric("Opportunity", "Silver", "distinct_pipelines", cur.fetchone()[0])

                cur.execute("SELECT COUNT(DISTINCT dealstage) FROM staging.stg_opportunity_normalised WHERE dealstage IS NOT NULL")
                add_metric("Opportunity", "Silver", "distinct_stages", cur.fetchone()[0])

            except Exception as e:
                add_metric("Opportunity", "Silver", "error", 0, str(e)[:100])

            # ═══════════════════════════════════════════════════════════════════
            # COMMUNICATION METRICS
            # ═══════════════════════════════════════════════════════════════════

            try:
                cur.execute("SELECT COUNT(*) FROM staging.stg_communication")
                add_metric("Communication", "Bronze", "total_records", cur.fetchone()[0], "Raw extraction from IC ALPS")
            except Exception as e:
                add_metric("Communication", "Bronze", "total_records", "ERROR", str(e)[:50])

            # Communication subtypes - bridge tables
            for comm_type in ["calls", "notes", "tasks", "meetings"]:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM staging.fct_communication_{comm_type}")
                    add_metric(f"Communication_{comm_type.title()}", "Silver", "total_records", cur.fetchone()[0], f"Bridge table for {comm_type}")

                    cur.execute(f"SELECT COUNT(*) FROM staging.fct_communication_{comm_type} WHERE icalps_communication_id IS NOT NULL")
                    add_metric(f"Communication_{comm_type.title()}", "Silver", "with_comm_id", cur.fetchone()[0], "Valid communication IDs")

                except Exception as e:
                    add_metric(f"Communication_{comm_type.title()}", "Silver", "error", 0, str(e)[:50])

            # ═══════════════════════════════════════════════════════════════════
            # CASE/TICKET METRICS
            # ═══════════════════════════════════════════════════════════════════

            try:
                cur.execute("SELECT COUNT(*) FROM staging.stg_cases")
                add_metric("Case", "Bronze", "total_records", cur.fetchone()[0], "Raw extraction from IC ALPS")
            except Exception as e:
                add_metric("Case", "Bronze", "total_records", "ERROR", str(e)[:50])

            try:
                cur.execute("SELECT COUNT(*) FROM staging.stg_case_v2")
                add_metric("Case", "Silver", "total_records", cur.fetchone()[0], "Normalized case records")
            except Exception as e:
                add_metric("Case", "Silver", "total_records", 0, str(e)[:80])
                conn.rollback()  # Reset transaction state

            # ═══════════════════════════════════════════════════════════════════
            # SIBLING GROUP METRICS
            # ═══════════════════════════════════════════════════════════════════

            try:
                cur.execute("""
                    SELECT
                        COUNT(DISTINCT icalps_canonical_domain) AS domain_groups,
                        COUNT(*) AS companies_in_groups
                    FROM staging.stg_company_normalised
                    WHERE icalps_sibling_index IS NOT NULL
                """)
                row = cur.fetchone()
                add_metric("Sibling_Groups", "Silver", "total_domain_groups", row[0], "Domains with sibling companies")
                add_metric("Sibling_Groups", "Silver", "companies_in_groups", row[1], "Total companies assigned to sibling groups")

                # Multi-company sibling groups (>1 company per domain)
                cur.execute("""
                    SELECT COUNT(*) FROM (
                        SELECT icalps_canonical_domain
                        FROM staging.stg_company_normalised
                        WHERE icalps_sibling_index IS NOT NULL
                        GROUP BY icalps_canonical_domain
                        HAVING COUNT(*) > 1
                    ) multi_groups
                """)
                add_metric("Sibling_Groups", "Silver", "multi_company_groups", cur.fetchone()[0], "Domain groups with 2+ companies")

                # Distribution of sibling group sizes
                cur.execute("""
                    SELECT icalps_canonical_domain, COUNT(*) as group_size
                    FROM staging.stg_company_normalised
                    WHERE icalps_sibling_index IS NOT NULL
                    GROUP BY icalps_canonical_domain
                    HAVING COUNT(*) > 1
                    ORDER BY COUNT(*) DESC
                    LIMIT 5
                """)
                for i, row in enumerate(cur.fetchall()):
                    add_metric("Sibling_Groups", "Silver", f"top_{i+1}_group_domain", row[0], f"Size: {row[1]} companies")

            except Exception as e:
                add_metric("Sibling_Groups", "Silver", "error", 0, str(e)[:100])
                conn.rollback()

    print(f"Collected {len(metrics)} metrics from database")

    # ═══════════════════════════════════════════════════════════════════
    # GOLD LAYER PREVIEW METRICS (from CSVs)
    # ═══════════════════════════════════════════════════════════════════

    csv_dir = Path(__file__).resolve().parent.parent.parent / "artifacts" / "ops"
    gold_csvs = {
        "Company": "gold_preview_company.csv",
        "Contact": "gold_preview_contact.csv",
        "Opportunity": "gold_preview_opportunity.csv",
        "Communication_Calls": "gold_preview_engagement_calls.csv",
        "Communication_Notes": "gold_preview_engagement_notes.csv",
        "Communication_Tasks": "gold_preview_engagement_tasks.csv",
        "Communication_Meetings": "gold_preview_engagement_meetings.csv",
    }

    for entity, filename in gold_csvs.items():
        csv_path = csv_dir / filename
        if csv_path.exists():
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                add_metric(entity, "Gold_Preview", "total_records", len(rows), f"Rows in {filename}")
                add_metric(entity, "Gold_Preview", "columns", len(reader.fieldnames) if reader.fieldnames else 0)
        else:
            add_metric(entity, "Gold_Preview", "total_records", 0, f"{filename} not found")

    # ═══════════════════════════════════════════════════════════════════
    # WRITE AUDIT TRAIL CSV
    # ═══════════════════════════════════════════════════════════════════

    audit_path = csv_dir / "pipeline_audit_trail.csv"
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    with open(audit_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "entity", "layer", "metric", "value", "notes"])
        writer.writeheader()
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for m in metrics:
            m["timestamp"] = ts
            writer.writerow(m)

    print(f"Wrote {len(metrics)} metrics to {audit_path}")
    return audit_path


if __name__ == "__main__":
    main()
