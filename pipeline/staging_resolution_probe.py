from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from psycopg2.extras import execute_values

from context.config import PROJECT_ROOT, load_entity_translation_contract, load_entity_resolution_map
from context.db import get_connection


@dataclass(frozen=True)
class BronzeProbeSpec:
    entity_type: str
    csv_path: Path
    raw_table: str
    normalised_table: str
    bronze_pk: str
    raw_pk: str
    normalised_pk: str
    selected_columns: list[str]


def _default_bronze_root() -> Path:
    # Salvage-time default only: the clean repo does not own Bronze payloads.
    return PROJECT_ROOT.parent / "bronze_layer"


def _default_specs(bronze_root: Path) -> list[BronzeProbeSpec]:
    return [
        BronzeProbeSpec(
            entity_type="company",
            csv_path=bronze_root / "Bronze_Company_20260227_143639.csv",
            raw_table="stg_company",
            normalised_table="stg_company_normalised",
            bronze_pk="Comp_CompanyId",
            raw_pk="Comp_CompanyId",
            normalised_pk="comp_companyid",
            selected_columns=["Comp_CompanyId", "Comp_Name", "Comp_WebSite", "Comp_Territory", "Comp_Sector", "Comp_UpdatedDate"],
        ),
        BronzeProbeSpec(
            entity_type="contact",
            csv_path=bronze_root / "Bronze_Person_20260225_102729.csv",
            raw_table="stg_contact",
            normalised_table="stg_contact_normalised",
            bronze_pk="Pers_PersonId",
            raw_pk="Pers_PersonId",
            normalised_pk="pers_personid",
            selected_columns=["Pers_PersonId", "Pers_CompanyId", "Pers_FirstName", "Pers_LastName", "Person_Email", "Pers_UpdatedDate"],
        ),
        BronzeProbeSpec(
            entity_type="opportunity",
            csv_path=bronze_root / "Bronze_Opportunity_20260225_102732.csv",
            raw_table="stg_opportunity",
            normalised_table="stg_opportunity_normalised",
            bronze_pk="Oppo_OpportunityId",
            raw_pk="Oppo_OpportunityId",
            normalised_pk="oppo_opportunityid",
            selected_columns=[
                "Oppo_OpportunityId",
                "Oppo_PrimaryCompanyId",
                "Oppo_PrimaryPersonId",
                "Oppo_Description",
                "Oppo_Stage",
                "Oppo_Status",
            ],
        ),
        BronzeProbeSpec(
            entity_type="communication",
            csv_path=bronze_root / "Bronze_Communication_20260225_102722.csv",
            raw_table="stg_communication",
            normalised_table="stg_communication_normalised",
            bronze_pk="Comm_CommunicationId",
            raw_pk="Comm_CommunicationId",
            normalised_pk="comm_communicationid",
            selected_columns=[
                "Comm_CommunicationId",
                "Company_Id",
                "Person_Id",
                "Comm_OpportunityId",
                "Comm_CaseId",
                "Comm_Type",
                "Comm_Action",
                "Comm_Subject",
                "Comm_Note",
            ],
        ),
    ]


def _safe_text(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _csv_field_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _quote_ident(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def _load_bronze_rows(spec: BronzeProbeSpec) -> pd.DataFrame:
    if not spec.csv_path.exists():
        raise FileNotFoundError(f"Bronze file not found for {spec.entity_type}: {spec.csv_path}")
    return pd.read_csv(spec.csv_path, usecols=spec.selected_columns, dtype=str, keep_default_na=False, na_values=[""])


def _load_staging_lookup(table_name: str, pk_column: str, capture_columns: list[str]) -> dict[str, dict[str, Any]]:
    selected_columns = [pk_column]
    if "_load_status" not in selected_columns:
        selected_columns.append("_load_status")
    for column in capture_columns:
        if column not in selected_columns:
            selected_columns.append(column)

    select_sql = ", ".join(_quote_ident(column) for column in selected_columns)
    sql = f"SELECT {select_sql} FROM staging.{table_name}"
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()

    pk_index = selected_columns.index(pk_column)
    load_status_index = selected_columns.index("_load_status")
    value_indexes = [idx for idx, name in enumerate(selected_columns) if name not in {pk_column, "_load_status"}]

    lookup: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _safe_text(row[pk_index])
        if key is None:
            continue

        captured_values = {selected_columns[idx]: _safe_text(row[idx]) for idx in value_indexes}
        values = {pk_column: key}
        values.update(captured_values)
        metadata_score = sum(1 for value in captured_values.values() if value is not None)
        candidate = {
            "load_status": _safe_text(row[load_status_index]),
            "metadata_score": metadata_score,
            "values": values,
        }
        existing = lookup.get(key)
        if existing is None or candidate["metadata_score"] > existing["metadata_score"]:
            lookup[key] = candidate
    return lookup


def _comparison_state(entity_type: str, raw_exists: bool, normalised_exists: bool, row: pd.Series) -> str:
    if raw_exists and normalised_exists:
        return "matched_raw_and_normalised"
    if raw_exists and not normalised_exists:
        if entity_type == "communication" and not (_safe_text(row.get("Company_Id")) or _safe_text(row.get("Person_Id"))):
            return "dropped_no_company_or_person_anchor"
        return "missing_from_normalised"
    if not raw_exists and normalised_exists:
        return "normalised_without_raw_match"
    return "missing_from_staging"


def _normalised_values(contract: dict[str, Any], normalised_hit: dict[str, Any] | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    raw_values = normalised_hit["values"] if normalised_hit else {}
    for alias, column_name in contract["silver"]["canonical_fields"].items():
        if column_name == "_load_status":
            values[alias] = normalised_hit["load_status"] if normalised_hit else None
        else:
            values[alias] = raw_values.get(column_name)
    return values


def _legacy_projection(row: pd.Series, contract: dict[str, Any]) -> dict[str, Any]:
    projected = {
        "legacy__primary_key_field": contract["legacy"]["primary_key"],
        "legacy__primary_key": _safe_text(row.get(contract["legacy"]["primary_key"])),
    }
    for field_name in contract["legacy"]["fields"]:
        projected[f"legacy__{_csv_field_name(field_name)}"] = _safe_text(row.get(field_name))
    return projected


def _silver_projection(spec: BronzeProbeSpec, contract: dict[str, Any], raw_hit: dict[str, Any] | None, normalised_hit: dict[str, Any] | None) -> dict[str, Any]:
    projected = {
        "silver__raw_table": spec.raw_table,
        "silver__normalised_table": spec.normalised_table,
        "silver__raw_exists": raw_hit is not None,
        "silver__normalised_exists": normalised_hit is not None,
        "silver__raw_load_status": raw_hit["load_status"] if raw_hit else None,
        "silver__normalised_load_status": normalised_hit["load_status"] if normalised_hit else None,
        "silver__raw_metadata_score": raw_hit["metadata_score"] if raw_hit else None,
        "silver__normalised_metadata_score": normalised_hit["metadata_score"] if normalised_hit else None,
    }

    normalised_values = _normalised_values(contract, normalised_hit)
    for alias, value in normalised_values.items():
        projected[f"silver__{_csv_field_name(alias)}"] = value
    return projected


def _gold_projection(entity_type: str, contract: dict[str, Any], legacy_row: pd.Series, silver_values: dict[str, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {
        "gold__target_fields": "|".join(contract["gold"]["target_fields"]),
        "gold__benchmark_export": str(contract["gold"]["benchmark_export"]),
    }

    if "target_table" in contract["gold"]:
        projected["gold__target_table"] = contract["gold"]["target_table"]
        projected["gold__match_field"] = contract["gold"]["match_field"]
    else:
        projected["gold__target_boundary"] = contract["gold"]["target_boundary"]

    if entity_type == "company":
        for field_name in contract["gold"]["target_fields"]:
            projected[f"gold__candidate_{_csv_field_name(field_name)}"] = silver_values.get(field_name)
    elif entity_type == "contact":
        for field_name in contract["gold"]["target_fields"]:
            projected[f"gold__candidate_{_csv_field_name(field_name)}"] = silver_values.get(field_name)
    elif entity_type == "opportunity":
        for field_name in contract["gold"]["target_fields"]:
            projected[f"gold__candidate_{_csv_field_name(field_name)}"] = silver_values.get(field_name)
        projected["gold__business_rule"] = contract["gold"]["business_rule"]
    elif entity_type == "communication":
        comm_id = _safe_text(legacy_row.get("Comm_CommunicationId"))
        projected["gold__candidate_unique_id"] = f"icalps_{comm_id}" if comm_id else None
        projected["gold__candidate_engagement_source"] = "IC_ALPS_MIGRATION"
        projected["gold__candidate_target_object_hint"] = "dbt_classification_required"
        projected["gold__candidate_legacy_company_id"] = silver_values.get("legacy_company_id")
        projected["gold__candidate_legacy_contact_id"] = silver_values.get("legacy_contact_id")
        projected["gold__candidate_legacy_deal_id"] = silver_values.get("legacy_deal_id")
        projected["gold__note"] = contract["gold"]["note"]
    return projected


def _resolution_projection(entity_type: str, contract: dict[str, Any], comparison_state: str) -> dict[str, Any]:
    resolution_map = load_entity_resolution_map()
    entity_resolution = resolution_map[entity_type]

    projected: dict[str, Any] = {
        "resolution__comparison_state": comparison_state,
        "resolution__policy": resolution_map["resolution_policy"],
    }

    if entity_type == "communication":
        projected["resolution__legacy_match_field"] = entity_resolution["legacy_pk"]
        for target_name, target_contract in entity_resolution["association_resolution"].items():
            prefix = f"resolution__{target_name}"
            projected[f"{prefix}_legacy_field"] = target_contract["legacy_field"]
            projected[f"{prefix}_associated_field"] = target_contract["associated_field"]
            projected[f"{prefix}_target_pk"] = target_contract["target_pk"]
            projected[f"{prefix}_stacksync_record_id_column"] = target_contract["stacksync_record_id_column"]
    else:
        projected["resolution__legacy_match_field"] = entity_resolution["legacy_pk"]
        projected["resolution__canonical_match_field"] = entity_resolution["canonical_pk"]
        projected["resolution__stacksync_record_id_column"] = entity_resolution["stacksync_record_id_column"]
    return projected


def build_resolution_rows(specs: list[BronzeProbeSpec]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    translation_contract = load_entity_translation_contract()

    for spec in specs:
        contract = translation_contract[spec.entity_type]
        normalised_capture_columns = list(contract["silver"]["canonical_fields"].values())

        bronze_df = _load_bronze_rows(spec)
        raw_lookup = _load_staging_lookup(spec.raw_table, spec.raw_pk, [])
        normalised_lookup = _load_staging_lookup(spec.normalised_table, spec.normalised_pk, normalised_capture_columns)

        entity_rows: list[dict[str, Any]] = []
        for _, row in bronze_df.iterrows():
            bronze_pk = _safe_text(row.get(spec.bronze_pk))
            if bronze_pk is None:
                continue

            raw_hit = raw_lookup.get(bronze_pk)
            normalised_hit = normalised_lookup.get(bronze_pk)
            comparison_state = _comparison_state(spec.entity_type, raw_hit is not None, normalised_hit is not None, row)
            silver_values = _normalised_values(contract, normalised_hit)

            output_row = {
                "entity_type": spec.entity_type,
                "bronze_file": spec.csv_path.name,
            }
            output_row.update(_legacy_projection(row, contract))
            output_row.update(_silver_projection(spec, contract, raw_hit, normalised_hit))
            output_row.update(_gold_projection(spec.entity_type, contract, row, silver_values))
            output_row.update(_resolution_projection(spec.entity_type, contract, comparison_state))

            entity_rows.append(output_row)

        all_rows.extend(entity_rows)
        summary = (
            pd.DataFrame(entity_rows)
            .groupby("resolution__comparison_state", dropna=False)
            .size()
            .reset_index(name="row_count")
            .sort_values(["row_count", "resolution__comparison_state"], ascending=[False, True])
            .to_dict(orient="records")
        )
        summaries.append(
            {
                "entity_type": spec.entity_type,
                "bronze_file": spec.csv_path.name,
                "bronze_rows": len(bronze_df),
                "summary": summary,
            }
        )

    return all_rows, summaries


def write_assessment_csv(rows: list[dict[str, Any]], output_path: Path, sample_size: int | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if sample_size is not None:
        frame = (
            frame.sort_values(
                by=[
                    "entity_type",
                    "silver__normalised_exists",
                    "silver__normalised_metadata_score",
                    "silver__raw_exists",
                    "silver__raw_metadata_score",
                    "legacy__primary_key",
                ],
                ascending=[True, False, False, False, False, True],
            )
            .groupby("entity_type", group_keys=False)
            .head(sample_size)
        )
    frame.to_csv(output_path, index=False, encoding="utf-8")
    return output_path


def write_resolution_table(rows: list[dict[str, Any]], test_run_id: str, table_name: str = "icload_test_entity_resolution") -> None:
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS staging.{table_name} (
        test_run_id TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        bronze_file TEXT NOT NULL,
        legacy_primary_key TEXT NOT NULL,
        silver_normalised_exists BOOLEAN NOT NULL,
        silver_normalised_load_status TEXT NULL,
        silver_normalised_metadata_score INTEGER NULL,
        comparison_state TEXT NOT NULL,
        gold_target_table TEXT NULL,
        resolution_policy TEXT NOT NULL,
        row_payload JSONB NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_{table_name}_run_entity ON staging.{table_name} (test_run_id, entity_type);
    """

    values = [
        (
            test_run_id,
            row["entity_type"],
            row["bronze_file"],
            row["legacy__primary_key"],
            row["silver__normalised_exists"],
            row["silver__normalised_load_status"],
            row["silver__normalised_metadata_score"],
            row["resolution__comparison_state"],
            row.get("gold__target_table") or row.get("gold__target_boundary"),
            row["resolution__policy"],
            json.dumps(row),
        )
        for row in rows
    ]

    with get_connection() as conn:
        conn.autocommit = False
        with conn.cursor() as cursor:
            cursor.execute(create_sql)
            cursor.execute(f"DELETE FROM staging.{table_name} WHERE test_run_id = %s", (test_run_id,))
            execute_values(
                cursor,
                f"""
                INSERT INTO staging.{table_name} (
                    test_run_id,
                    entity_type,
                    bronze_file,
                    legacy_primary_key,
                    silver_normalised_exists,
                    silver_normalised_load_status,
                    silver_normalised_metadata_score,
                    comparison_state,
                    gold_target_table,
                    resolution_policy,
                    row_payload
                ) VALUES %s
                """,
                values,
                page_size=1000,
            )
        conn.commit()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a staging-only legacy-to-Silver-to-HubSpot translation probe."
    )
    parser.add_argument("--bronze-root", default=str(_default_bronze_root()))
    parser.add_argument("--test-run-id", default="2026-04-04_resolution_probe")
    parser.add_argument("--write-postgres", action="store_true")
    parser.add_argument("--table-name", default="icload_test_entity_resolution")
    parser.add_argument(
        "--csv-output",
        default=str(PROJECT_ROOT / "artifacts" / "assessment" / "entity_translation_probe_sample.csv"),
    )
    parser.add_argument("--sample-size", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    specs = _default_specs(Path(args.bronze_root))
    rows, summaries = build_resolution_rows(specs)
    csv_path = write_assessment_csv(rows, Path(args.csv_output), sample_size=args.sample_size)

    if args.write_postgres:
        write_resolution_table(rows, test_run_id=args.test_run_id, table_name=args.table_name)

    print(
        json.dumps(
            {
                "test_run_id": args.test_run_id,
                "bronze_root": args.bronze_root,
                "row_count": len(rows),
                "csv_output": str(csv_path),
                "sample_size_per_entity": args.sample_size,
                "written_to_postgres": args.write_postgres,
                "table_name": f"staging.{args.table_name}" if args.write_postgres else None,
                "summaries": summaries,
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
