from __future__ import annotations

import argparse
import json
from typing import Any

from context.db import get_connection


def _relation_exists(cursor: Any, schema_name: str, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_name = %s
        """,
        (schema_name, table_name),
    )
    return cursor.fetchone() is not None


def _column_names(cursor: Any, schema_name: str, table_name: str) -> list[str]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema_name, table_name),
    )
    return [row[0] for row in cursor.fetchall()]


def _rows(cursor: Any, sql_text: str) -> list[dict[str, Any]]:
    cursor.execute(sql_text)
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _row(cursor: Any, sql_text: str) -> dict[str, Any]:
    cursor.execute(sql_text)
    columns = [desc[0] for desc in cursor.description]
    values = cursor.fetchone()
    return dict(zip(columns, values)) if values else {}


def inspect_staging_contract(sample_limit: int = 5) -> dict[str, Any]:
    """
    Staging-only smoke probe.

    Guardrail: never read from or write to hubspot.* here.
    This probe exists to validate the transformation contract, not the production
    Gold layer. It is safe to run against the shared PostgreSQL instance because
    it only touches information_schema and staging.*.
    """

    expected_columns = {
        ("staging", "raw_stg_communication"): [
            "Comm_CommunicationId",
            "Comm_OpportunityId",
            "Comm_CaseId",
            "Comm_Type",
            "Comm_Action",
            "Comm_Status",
            "Comm_Priority",
            "Comm_DateTime",
            "Comm_ToDateTime",
            "Comm_Note",
            "Comm_Subject",
            "Comm_Email",
            "Person_Id",
            "Company_Id",
            "Case_Description",
        ],
        ("staging", "stg_communication"): [
            "Comm_CommunicationId",
            "_load_status",
            "_first_seen_at",
            "_last_modified_at",
        ],
        ("staging", "stg_communication_normalised"): [
            "comm_communicationid",
            "comm_action",
            "comm_subject",
            "comm_note",
            "person_id",
            "company_id",
            "comm_opportunityid",
            "_load_status",
        ],
        ("staging", "fct_communication_calls"): [
            "icalps_communication_id",
            "associated_company_id",
            "associated_contact_id",
            "associated_deal_id",
            "legacy_company_id",
            "legacy_contact_id",
            "legacy_deal_id",
            "reconciliation_status",
        ],
        ("staging", "fct_communication_notes"): [
            "icalps_communication_id",
            "associated_company_id",
            "associated_contact_id",
            "associated_deal_id",
            "legacy_company_id",
            "legacy_contact_id",
            "legacy_deal_id",
            "reconciliation_status",
        ],
        ("staging", "fct_communication_tasks"): [
            "icalps_communication_id",
            "associated_company_id",
            "associated_contact_id",
            "associated_deal_id",
            "legacy_company_id",
            "legacy_contact_id",
            "legacy_deal_id",
            "reconciliation_status",
        ],
        ("staging", "fct_communication_meetings"): [
            "icalps_communication_id",
            "associated_company_id",
            "associated_contact_id",
            "associated_deal_id",
            "legacy_company_id",
            "legacy_contact_id",
            "legacy_deal_id",
            "reconciliation_status",
        ],
        ("staging", "stg_company_normalised"): [
            "comp_companyid",
            "comp_name",
            "icalps_comp_website",
            "icalps_companytype",
            "icalps_companystatus",
            "icalps_full_country",
            "_load_status",
        ],
    }

    relation_report: list[dict[str, Any]] = []
    mismatches: list[str] = []
    counts: dict[str, int] = {}

    with get_connection() as conn:
        with conn.cursor() as cursor:
            for (schema_name, table_name), columns in expected_columns.items():
                exists = _relation_exists(cursor, schema_name, table_name)
                actual_columns = _column_names(cursor, schema_name, table_name) if exists else []
                missing_columns = [column for column in columns if column not in actual_columns]
                relation_report.append(
                    {
                        "relation": f"{schema_name}.{table_name}",
                        "exists": exists,
                        "missing_columns": missing_columns,
                        "column_count": len(actual_columns),
                    }
                )
                if exists:
                    cursor.execute(f"SELECT COUNT(*) FROM {schema_name}.{table_name}")
                    counts[f"{schema_name}.{table_name}"] = int(cursor.fetchone()[0])
                if not exists:
                    mismatches.append(f"Missing relation: {schema_name}.{table_name}")
                elif missing_columns:
                    mismatches.append(f"Missing columns on {schema_name}.{table_name}: {', '.join(missing_columns)}")

            metrics = {
                "plural_domain_summary": _row(
                    cursor,
                    """
                    WITH groups AS (
                        SELECT icalps_comp_website, COUNT(*) AS row_count
                        FROM staging.stg_company_normalised
                        WHERE icalps_comp_website IS NOT NULL
                        GROUP BY icalps_comp_website
                        HAVING COUNT(*) > 1
                    )
                    SELECT
                        COUNT(*) AS plural_domain_groups,
                        COALESCE(SUM(row_count), 0) AS plural_domain_rows
                    FROM groups
                    """,
                ),
                "communication_normalised_anchor_summary": _row(
                    cursor,
                    """
                    SELECT
                        COUNT(*) AS total_rows,
                        COUNT(*) FILTER (WHERE company_id IS NOT NULL) AS rows_with_company,
                        COUNT(*) FILTER (WHERE person_id IS NOT NULL) AS rows_with_person,
                        COUNT(*) FILTER (WHERE company_id IS NULL AND person_id IS NULL) AS rows_without_company_or_person
                    FROM staging.stg_communication_normalised
                    """,
                ),
                "calls_reconciliation_summary": _row(
                    cursor,
                    """
                    SELECT
                        COUNT(*) AS total_rows,
                        COUNT(*) FILTER (WHERE associated_company_id IS NOT NULL) AS with_company_uuid,
                        COUNT(*) FILTER (WHERE associated_contact_id IS NOT NULL) AS with_contact_uuid,
                        COUNT(*) FILTER (WHERE associated_deal_id IS NOT NULL) AS with_deal_uuid,
                        COUNT(*) FILTER (WHERE reconciliation_status = 'reconciled') AS reconciled_rows,
                        COUNT(*) FILTER (WHERE reconciliation_status = 'unreconciled') AS unreconciled_rows
                    FROM staging.fct_communication_calls
                    """,
                ),
                "notes_reconciliation_summary": _row(
                    cursor,
                    """
                    SELECT
                        COUNT(*) AS total_rows,
                        COUNT(*) FILTER (WHERE associated_company_id IS NOT NULL) AS with_company_uuid,
                        COUNT(*) FILTER (WHERE associated_contact_id IS NOT NULL) AS with_contact_uuid,
                        COUNT(*) FILTER (WHERE associated_deal_id IS NOT NULL) AS with_deal_uuid,
                        COUNT(*) FILTER (WHERE reconciliation_status = 'reconciled') AS reconciled_rows,
                        COUNT(*) FILTER (WHERE reconciliation_status = 'unreconciled') AS unreconciled_rows
                    FROM staging.fct_communication_notes
                    """,
                ),
                "tasks_reconciliation_summary": _row(
                    cursor,
                    """
                    SELECT
                        COUNT(*) AS total_rows,
                        COUNT(*) FILTER (WHERE associated_company_id IS NOT NULL) AS with_company_uuid,
                        COUNT(*) FILTER (WHERE associated_contact_id IS NOT NULL) AS with_contact_uuid,
                        COUNT(*) FILTER (WHERE associated_deal_id IS NOT NULL) AS with_deal_uuid,
                        COUNT(*) FILTER (WHERE reconciliation_status = 'reconciled') AS reconciled_rows,
                        COUNT(*) FILTER (WHERE reconciliation_status = 'unreconciled') AS unreconciled_rows
                    FROM staging.fct_communication_tasks
                    """,
                ),
                "meetings_reconciliation_summary": _row(
                    cursor,
                    """
                    SELECT
                        COUNT(*) AS total_rows,
                        COUNT(*) FILTER (WHERE associated_company_id IS NOT NULL) AS with_company_uuid,
                        COUNT(*) FILTER (WHERE associated_contact_id IS NOT NULL) AS with_contact_uuid,
                        COUNT(*) FILTER (WHERE associated_deal_id IS NOT NULL) AS with_deal_uuid,
                        COUNT(*) FILTER (WHERE reconciliation_status = 'reconciled') AS reconciled_rows,
                        COUNT(*) FILTER (WHERE reconciliation_status = 'unreconciled') AS unreconciled_rows
                    FROM staging.fct_communication_meetings
                    """,
                ),
            }

            plural_domain_sample = _rows(
                cursor,
                f"""
                SELECT
                    icalps_comp_website,
                    COUNT(*) AS row_count
                FROM staging.stg_company_normalised
                WHERE icalps_comp_website IS NOT NULL
                GROUP BY icalps_comp_website
                HAVING COUNT(*) > 1
                ORDER BY COUNT(*) DESC, icalps_comp_website
                LIMIT {int(sample_limit)}
                """,
            )

    return {
        "ok": not mismatches,
        "scope": "staging_only",
        "mismatches": mismatches,
        "relations": relation_report,
        "counts": counts,
        "metrics": metrics,
        "plural_domain_sample": plural_domain_sample,
        "notes": [
            "This smoke probe intentionally excludes hubspot.* because the Gold layer is production.",
            "Communication reconciliation is inferred from staging.fct_communication_* only.",
            "Sibling-company candidate pressure is inferred from plural domains in staging.stg_company_normalised.",
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe the live staging contract behind ic-load without touching hubspot.*.")
    parser.add_argument("--sample-limit", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    print(json.dumps(inspect_staging_contract(sample_limit=args.sample_limit), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
