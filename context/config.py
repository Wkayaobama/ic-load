from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Keep all core paths repo-relative so Windows, Codespaces, and optional WSL
# checkouts all resolve the same runtime layout without changing code.
# WSL is only a convenience path for Windows users who want Linux-side tooling;
# it is not a runtime requirement and must not alter functional behavior.
# The only path contract collaborators should rely on is "repo root contains
# context/, pipeline/, sql/, ValidationRules/, and GomplateRepoMix/".
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

BRONZE_DIR = PROJECT_ROOT / "bronze_layer"
DBT_PROJECT_DIR = PROJECT_ROOT / "dbt"
VALIDATION_SCHEMA_PATH = PROJECT_ROOT / "ValidationRules" / "icalps_crm_schema.yaml"
SCHEMA_CONTEXT_PATH = PROJECT_ROOT / "GomplateRepoMix" / "schema_context.yaml"
RUN_CONTEXT_PATH = PROJECT_ROOT / "GomplateRepoMix" / "run_context.yaml"
BUSINESS_RULES_PATH = PROJECT_ROOT / "GomplateRepoMix" / "business_rules.yaml"
SQL_TEMPLATE_DIR = PROJECT_ROOT / "sql" / "templates"
SQL_RENDERED_DIR = PROJECT_ROOT / "sql" / "rendered"
BENCHMARK_DIR = PROJECT_ROOT.parent / "benchmark"

_BRONZE_PREFIX = {
    "communication": "Bronze_Communication",
    "company": "Bronze_Company",
    "contact": "Bronze_Person",
    "opportunity": "Bronze_Opportunity",
}


@dataclass(frozen=True)
class EntityConfig:
    name: str
    bronze_csv: str
    staging_table: str
    primary_key: str
    columns: list[str] = field(default_factory=list)


ENTITIES: dict[str, EntityConfig] = {
    "communication": EntityConfig(
        name="communication",
        bronze_csv="Bronze_Communication.csv",
        staging_table="stg_communication",
        primary_key="Comm_CommunicationId",
    ),
    "company": EntityConfig(
        name="company",
        bronze_csv="Bronze_Company.csv",
        staging_table="stg_company",
        primary_key="Comp_CompanyId",
    ),
    "contact": EntityConfig(
        name="contact",
        bronze_csv="Bronze_Person.csv",
        staging_table="stg_contact",
        primary_key="Pers_PersonId",
    ),
    "opportunity": EntityConfig(
        name="opportunity",
        bronze_csv="Bronze_Opportunity.csv",
        staging_table="stg_opportunity",
        primary_key="Oppo_OpportunityId",
    ),
}


def latest_bronze_path(entity: str) -> Path | None:
    prefix = _BRONZE_PREFIX.get(entity.lower())
    if prefix is None or not BRONZE_DIR.exists():
        return None

    candidates = sorted(
        [path for path in BRONZE_DIR.glob(f"{prefix}_2*.csv") if "_ready" not in path.name],
        reverse=True,
    )
    if candidates:
        return candidates[0]

    stable = BRONZE_DIR / f"{prefix}.csv"
    return stable if stable.exists() else None


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


def load_schema_context() -> dict[str, Any]:
    return load_yaml(SCHEMA_CONTEXT_PATH)


def load_run_context() -> dict[str, Any]:
    return load_yaml(RUN_CONTEXT_PATH)


def load_business_rules() -> dict[str, Any]:
    return load_yaml(BUSINESS_RULES_PATH)


def load_validation_schema() -> dict[str, Any]:
    return load_yaml(VALIDATION_SCHEMA_PATH)


def load_thresholds(entity: str) -> dict[str, Any]:
    schema = load_validation_schema()
    entities = schema.get("crm", {}).get("entities", {})
    for key, value in entities.items():
        if key.lower() == entity.lower():
            return value.get("pipeline_thresholds", {})
    return {}


def load_entity_resolution_map() -> dict[str, Any]:
    schema = load_schema_context()
    return {
        "company": {
            "legacy_pk": schema["entities"]["Company"]["primary_key"]["source"],
            "canonical_pk": schema["entities"]["Company"]["primary_key"]["canonical"],
            "stacksync_record_id_column": schema["stacksync"]["company_record_id_column"],
        },
        "contact": {
            "legacy_pk": schema["entities"]["Person"]["primary_key"]["source"],
            "canonical_pk": schema["entities"]["Person"]["primary_key"]["canonical"],
            "stacksync_record_id_column": schema["stacksync"]["contact_record_id_column"],
        },
        "opportunity": {
            "legacy_pk": schema["entities"]["Opportunity"]["primary_key"]["source"],
            "canonical_pk": schema["entities"]["Opportunity"]["primary_key"]["canonical"],
            "stacksync_record_id_column": schema["stacksync"]["deal_record_id_column"],
        },
        "communication": {
            "legacy_pk": schema["entities"]["Communication"]["idempotency_source_key"],
            "idempotency_prefix": schema["entities"]["Communication"]["idempotency_prefix"],
            "association_resolution": {
                "company": {
                    "legacy_field": "legacy_company_id",
                    "associated_field": "associated_company_id",
                    "target_pk": "icalps_company_id",
                    "stacksync_record_id_column": schema["stacksync"]["company_record_id_column"],
                },
                "contact": {
                    "legacy_field": "legacy_contact_id",
                    "associated_field": "associated_contact_id",
                    "target_pk": "icalps_contact_id",
                    "stacksync_record_id_column": schema["stacksync"]["contact_record_id_column"],
                },
                "deal": {
                    "legacy_field": "legacy_deal_id",
                    "associated_field": "associated_deal_id",
                    "target_pk": "icalps_deal_id",
                    "stacksync_record_id_column": schema["stacksync"]["deal_record_id_column"],
                },
            },
        },
        "resolution_policy": "prefer_record_with_most_metadata",
    }


def load_entity_translation_contract() -> dict[str, Any]:
    resolution_map = load_entity_resolution_map()
    return {
        "company": {
            "legacy": {
                "primary_key": "Comp_CompanyId",
                "fields": [
                    "Comp_CompanyId",
                    "Comp_Name",
                    "Comp_WebSite",
                    "Comp_Territory",
                    "Comp_Sector",
                    "Comp_UpdatedDate",
                ],
            },
            "silver": {
                "raw_table": "stg_company",
                "normalised_table": "stg_company_normalised",
                "raw_primary_key": "Comp_CompanyId",
                "normalised_primary_key": "comp_companyid",
                "canonical_fields": {
                    "icalps_company_id": "comp_companyid",
                    "name": "comp_name",
                    "icalps_comp_website": "comp_website",
                    "territory": "comp_territory",
                    "industry": "comp_sector",
                    "comp_sector": "comp_sector",
                    "comp_type": "icalps_companytype",
                    "city": "address_city",
                    "state": "address_state",
                    "zip": "address_postcode",
                    "country": "icalps_country",
                    "phone": "icalps_companyphone",
                    "_load_status": "_load_status",
                },
            },
            "gold": {
                "target_table": "hubspot.companies",
                "match_field": "icalps_company_id",
                "target_fields": [
                    "name",
                    "icalps_comp_website",
                    "city",
                    "country",
                    "state",
                    "zip",
                    "industry",
                    "phone",
                    "comp_type",
                    "comp_sector",
                ],
                "benchmark_export": BENCHMARK_DIR / "benchmark_hubspot-crm-exports-icalps-companies-2026-03-07.csv",
            },
            "resolution": {
                "legacy_match_field": resolution_map["company"]["legacy_pk"],
                "canonical_match_field": resolution_map["company"]["canonical_pk"],
                "stacksync_record_id_column": resolution_map["company"]["stacksync_record_id_column"],
            },
        },
        "contact": {
            "legacy": {
                "primary_key": "Pers_PersonId",
                "fields": [
                    "Pers_PersonId",
                    "Pers_CompanyId",
                    "Pers_FirstName",
                    "Pers_LastName",
                    "Person_Email",
                    "Pers_UpdatedDate",
                ],
            },
            "silver": {
                "raw_table": "stg_contact",
                "normalised_table": "stg_contact_normalised",
                "raw_primary_key": "Pers_PersonId",
                "normalised_primary_key": "pers_personid",
                "canonical_fields": {
                    "icalps_contact_id": "pers_personid",
                    "icalps_company_id": "pers_companyid",
                    "firstname": "pers_firstname",
                    "lastname": "pers_lastname",
                    "email": "icalps_email",
                    "jobtitle": "icalps_title",
                    "phone": "icalps_businessphone",
                    "mobilephone": "icalps_mobilephone",
                    "city": "address_city",
                    "state": "address_state",
                    "zip": "address_postcode",
                    "country": "icalps_country",
                    "lastmodifieddate": "pers_updateddate",
                    "_load_status": "_load_status",
                },
            },
            "gold": {
                "target_table": "hubspot.contacts",
                "match_field": "icalps_contact_id",
                "target_fields": [
                    "email",
                    "firstname",
                    "lastname",
                    "jobtitle",
                    "phone",
                    "mobilephone",
                    "city",
                    "state",
                    "country",
                    "zip",
                    "lastmodifieddate",
                ],
                "benchmark_export": BENCHMARK_DIR / "benchmark_hubspot-crm-exports-icalps_contact-2026-03-07.csv",
            },
            "resolution": {
                "legacy_match_field": resolution_map["contact"]["legacy_pk"],
                "canonical_match_field": resolution_map["contact"]["canonical_pk"],
                "stacksync_record_id_column": resolution_map["contact"]["stacksync_record_id_column"],
            },
        },
        "opportunity": {
            "legacy": {
                "primary_key": "Oppo_OpportunityId",
                "fields": [
                    "Oppo_OpportunityId",
                    "Oppo_PrimaryCompanyId",
                    "Oppo_PrimaryPersonId",
                    "Oppo_Description",
                    "Oppo_Stage",
                    "Oppo_Status",
                ],
            },
            "silver": {
                "raw_table": "stg_opportunity",
                "normalised_table": "stg_opportunity_normalised",
                "raw_primary_key": "Oppo_OpportunityId",
                "normalised_primary_key": "oppo_opportunityid",
                "canonical_fields": {
                    "icalps_deal_id": "oppo_opportunityid",
                    "icalps_company_id": "oppo_primarycompanyid",
                    "icalps_contact_id": "oppo_primarypersonid",
                    "dealname": "oppo_description",
                    "icalps_dealtype": "oppo_type",
                    "icalps_dealnotes": "oppo_notes",
                    "amount": "icalps_forecast",
                    "icalps_dealforecast": "icalps_forecast",
                    "icalps_dealcertainty": "icalps_certainty",
                    "pipeline": "hubspot_pipeline_id",
                    "dealstage": "hubspot_dealstage_name",
                    "closedate": "icalps_closedate",
                    "_load_status": "_load_status",
                },
            },
            "gold": {
                "target_table": "hubspot.deals",
                "match_field": "icalps_deal_id",
                "target_fields": [
                    "dealname",
                    "pipeline",
                    "dealstage",
                    "amount",
                    "icalps_dealforecast",
                    "icalps_dealcertainty",
                    "icalps_dealtype",
                    "icalps_dealnotes",
                    "closedate",
                ],
                "benchmark_export": BENCHMARK_DIR / "benchmark_hubspot-crm-exports-icalps_deals-2026-03-07.csv",
                "business_rule": "deal_stage_mapper.py is authoritative for pipeline/stage resolution.",
            },
            "resolution": {
                "legacy_match_field": resolution_map["opportunity"]["legacy_pk"],
                "canonical_match_field": resolution_map["opportunity"]["canonical_pk"],
                "stacksync_record_id_column": resolution_map["opportunity"]["stacksync_record_id_column"],
            },
        },
        "communication": {
            "legacy": {
                "primary_key": "Comm_CommunicationId",
                "fields": [
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
            },
            "silver": {
                "raw_table": "stg_communication",
                "normalised_table": "stg_communication_normalised",
                "raw_primary_key": "Comm_CommunicationId",
                "normalised_primary_key": "comm_communicationid",
                "canonical_fields": {
                    "icalps_communication_id": "comm_communicationid",
                    "legacy_company_id": "company_id",
                    "legacy_contact_id": "person_id",
                    "legacy_deal_id": "comm_opportunityid",
                    "comm_type": "comm_type",
                    "comm_action": "comm_action",
                    "comm_subject": "comm_subject",
                    "comm_note": "comm_note",
                    "comm_datetime": "comm_datetime",
                    "_load_status": "_load_status",
                },
            },
            "gold": {
                "target_boundary": "dbt marts -> hubspot.calls|notes|tasks|meetings",
                "target_fields": [
                    "unique_id",
                    "hs_timestamp",
                    "hs_call_title|hs_note_body|hs_task_subject|hs_meeting_title",
                    "engagement_source",
                ],
                "idempotency_key_pattern": "icalps_<Comm_CommunicationId>",
                "benchmark_export": BENCHMARK_DIR / "hubspot-crm-exports-all-tickets-2026-04-04-1.csv",
                "note": "Communication Gold shape is dbt-mart-specific; staging normalised is the last staging-owned canonical form.",
            },
            "resolution": {
                "legacy_match_field": resolution_map["communication"]["legacy_pk"],
                "association_resolution": resolution_map["communication"]["association_resolution"],
            },
        },
        "case": {
            "legacy": {
                "primary_key": "Case_CaseId",
                "fields": [
                    "Case_CaseId",
                    "Case_PrimaryCompanyId",
                    "Case_PrimaryPersonId",
                    "Case_Description",
                    "Case_Status",
                    "Case_Stage",
                    "Case_Priority",
                    "Case_CreateDate",
                    "Case_CloseDate",
                    "Company_Name",
                    "Person_EmailAddress",
                ],
            },
            "silver": {
                "raw_table": "stg_cases",
                "normalised_table": "stg_case",
                "raw_primary_key": "Case_CaseId",
                "normalised_primary_key": "icalps_ticket_id",
                "canonical_fields": {
                    "icalps_ticket_id": "icalps_ticket_id",
                    "subject": "subject",
                    "content": "content",
                    "pipeline": "hs_pipeline",
                    "pipeline_stage": "hs_pipeline_stage",
                    "ticket_priority": "hs_ticket_priority",
                    "createdate": "createdate",
                    "closed_date": "closed_date",
                    "icalps_case_status": "icalps_case_status",
                    "icalps_case_stage": "icalps_case_stage",
                    "icalps_case_priority": "icalps_case_priority",
                    "icalps_company_id": "icalps_company_id",
                    "icalps_contact_id": "icalps_contact_id",
                    "icalps_company_name": "icalps_company_name",
                    "icalps_contact_email": "icalps_contact_email",
                    "reconciliation_status": "reconciliation_status",
                },
            },
            "gold": {
                "target_table": "hubspot.tickets",
                "match_field": "IcAlps_TicketID",
                "target_fields": [
                    "Ticket name",
                    "Pipeline",
                    "Create date",
                    "Ticket status",
                    "Priority",
                    "IcAlps_TicketStage",
                    "Ticket description",
                    "IcAlps_TicketPersonEmailAddress",
                    "IcAlps_CompanyID",
                ],
                "benchmark_export": BENCHMARK_DIR / "hubspot-crm-exports-all-tickets-2026-04-04-1.csv",
            },
            "resolution": {
                "legacy_match_field": "Case_CaseId",
                "canonical_match_field": "icalps_ticket_id",
            },
        },
    }


def dbt_command() -> list[str] | None:
    raw = os.getenv("ICALPS_DBT_COMMAND")
    if not raw:
        return None
    return raw.split()


def stacksync_sync_assumed() -> bool:
    return os.getenv("ICALPS_ASSUME_STACKSYNC_SYNC", "").lower() in {"1", "true", "yes"}
