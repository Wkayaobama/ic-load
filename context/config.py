from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import find_dotenv, load_dotenv

# Two-stage env load so every salvage-runner entry point (and anything that
# imports `context.config`) picks up the canonical `.env.icalps` at the
# Codebase root without each caller having to remember to load it. Mirrors
# the pattern in `pipeline/library_files/config.py:Settings.from_env`.
# Precedence: process env > worktree-local `.env` > `.env.icalps`.
# find_dotenv walks up from cwd, so this works from any subdirectory inside
# any worktree. Module-level side effect is intentional — context.config is
# imported by `pipeline.runner` before any os.getenv call hits ICALPS_*.
load_dotenv(find_dotenv(filename=".env.icalps", usecwd=True))
load_dotenv(find_dotenv(usecwd=True), override=True)

# Keep all core paths repo-relative so Windows, Codespaces, and optional WSL
# checkouts all resolve the same runtime layout without changing code.
# WSL is only a convenience path for Windows users who want Linux-side tooling;
# it is not a runtime requirement and must not alter functional behavior.
# The only path contract collaborators should rely on is "repo root contains
# context/, pipeline/, sql/, ValidationRules/, and GomplateRepoMix/".
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = Path(os.getenv("PIPELINE_ARTIFACTS_DIR", str(PROJECT_ROOT / "artifacts")))
ARTIFACTS_DIR.mkdir(exist_ok=True)

BRONZE_DIR = PROJECT_ROOT / "bronze_layer"
DBT_PROJECT_DIR = PROJECT_ROOT / "dbt"
VALIDATION_SCHEMA_PATH = PROJECT_ROOT / "ValidationRules" / "icalps_crm_schema.yaml"
SCHEMA_CONTEXT_PATH = PROJECT_ROOT / "GomplateRepoMix" / "schema_context.yaml"
RUN_CONTEXT_PATH = PROJECT_ROOT / "GomplateRepoMix" / "run_context.yaml"
BUSINESS_RULES_PATH = PROJECT_ROOT / "GomplateRepoMix" / "business_rules.yaml"
MANIFEST_PATH = PROJECT_ROOT / "MANIFEST.yaml"
SQL_TEMPLATE_DIR = PROJECT_ROOT / "sql" / "templates"
SQL_RENDERED_DIR = PROJECT_ROOT / "sql" / "rendered"
BENCHMARK_DIR = PROJECT_ROOT.parent / "benchmark"
MANIFEST_PATH = PROJECT_ROOT / "MANIFEST.yaml"

_BRONZE_PREFIX = {
    "communication": "Bronze_Communication",
    "company": "Bronze_Company",
    "contact": "Bronze_Person",
    "opportunity": "Bronze_Opportunity",
    "case": "Bronze_Case",
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
    # Case/Ticket — import_order=5, live_push_ready=FALSE
    # Bronze CSV override: artifacts/assessment/case_ticket_snippet.csv
    # Silver target: staging.stg_case_v2 (assessed) → staging.stg_case (live, after promotion)
    # Gold target: hubspot.tickets (NOT YET LIVE — awaiting stage mapper + match rate ≥95%)
    "case": EntityConfig(
        name="case",
        bronze_csv="Bronze_Case.csv",
        staging_table="stg_cases",      # Bronze raw table (legacy preservation)
        primary_key="Case_CaseId",
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


def load_manifest() -> dict[str, Any]:
    return load_yaml(MANIFEST_PATH)


def load_schema_context() -> dict[str, Any]:
    return load_yaml(SCHEMA_CONTEXT_PATH)


def load_run_context() -> dict[str, Any]:
    return load_yaml(RUN_CONTEXT_PATH)


def load_business_rules() -> dict[str, Any]:
    return load_yaml(BUSINESS_RULES_PATH)


def load_validation_schema() -> dict[str, Any]:
    return load_yaml(VALIDATION_SCHEMA_PATH)


def load_manifest() -> dict[str, Any]:
    """Load MANIFEST.yaml — data registry for pipeline entities + hooks.

    See IC_Load_Production_Plan.md §10 for the schema. Keys used by the
    runner: entities.{entity}.sql_files.{gold_upsert,association_bridge,post_run_verify},
    entities.{entity}.postprocess.{pre,post}.
    """
    return load_yaml(MANIFEST_PATH)


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
                # Actual column names from stg_company_normalised (probe_post_dbt.csv)
                "normalised_primary_key": "icalps_company_id",
                "canonical_fields": {
                    # Mapping: HubSpot target field -> silver source column
                    "icalps_company_id": "icalps_company_id",
                    "name": "name",
                    "icalps_comp_website": "icalps_comp_website",
                    "icalps_companyphone": "icalps_companyphone",
                    "icalps_companytype": "icalps_companytype",
                    "icalps_companystatus": "icalps_companystatus",
                    "icalps_compsource": "icalps_compsource",
                    "icalps_comp_language": "icalps_comp_language",
                    "icalps_comp_numemployees": "icalps_comp_numemployees",
                    "icalps_industry_drill_down": "icalps_industry_drill_down",
                    "icalps_full_address": "icalps_full_address",
                    "icalps_street_address": "icalps_street_address",
                    "icalps_addresscity": "city",
                    "icalps_address_state": "icalps_address_state",
                    "icalps_address_postcode": "icalps_address_postcode",
                    "icalps_address_country": "icalps_address_country",
                    "icalps_companyemail": "icalps_companyemail",
                    "linkedin_company_page": "linkedin_company_page",
                    "icalps_ownerid_raw": "icalps_ownerid_raw",
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
                # Actual column names from stg_contact_normalised (probe_post_dbt.csv)
                "normalised_primary_key": "icalps_contact_id",
                "canonical_fields": {
                    # Mapping: HubSpot target field -> silver source column
                    "icalps_contact_id": "icalps_contact_id",
                    "icalps_company_id": "icalps_company_id",
                    "firstname": "firstname",
                    "lastname": "lastname",
                    "email": "email",
                    "icalps_perstitle": "icalps_perstitle",
                    "icalps_businessphone": "icalps_businessphone",
                    "icalps_mobilephone": "icalps_mobilephone",
                    "icalps_contactstatus": "icalps_contactstatus",
                    "icalps_department": "icalps_department",
                    "salutation": "salutation",
                    "icalps_addresscity": "icalps_addresscity",
                    "state": "state",
                    "zip": "zip",
                    "icalps_address_country": "icalps_address_country",
                    "linkedin_url": "linkedin_url",
                    "lastmodifieddate": "lastmodifieddate",
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
                # Actual column names from stg_opportunity_normalised (probe_post_dbt.csv)
                "normalised_primary_key": "icalps_deal_id",
                "canonical_fields": {
                    # Mapping: HubSpot target field -> silver source column
                    "icalps_deal_id": "icalps_deal_id",
                    "icalps_company_id": "icalps_company_id",
                    "icalps_contact_id": "icalps_contact_id",
                    "dealname": "dealname",
                    "icalps_dealtype": "icalps_dealtype",
                    "icalps_dealnotes": "icalps_dealnotes",
                    "amount": "amount",
                    "icalps_dealforecast": "amount",
                    "icalps_dealcertainty": "icalps_oppocertainty",
                    "pipeline": "pipeline",
                    "dealstage": "hubspot_stageid",
                    "closedate": "icalps_closedate",
                    "ic_alps_cost": "ic_alps_cost",
                    "icalps_stage": "icalps_stage",
                    "icalps_dealstatus": "icalps_dealstatus",
                    "icalps_opendate": "icalps_opendate",
                    "hubspot_owner_id": "hubspot_owner_id",
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
