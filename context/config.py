from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)

BRONZE_DIR = PROJECT_ROOT / "bronze_layer"
DBT_PROJECT_DIR = PROJECT_ROOT / "dbt"
VALIDATION_SCHEMA_PATH = PROJECT_ROOT / "ValidationRules" / "icalps_crm_schema.yaml"
SCHEMA_CONTEXT_PATH = PROJECT_ROOT / "GomplateRepoMix" / "schema_context.yaml"
RUN_CONTEXT_PATH = PROJECT_ROOT / "GomplateRepoMix" / "run_context.yaml"
SQL_TEMPLATE_DIR = PROJECT_ROOT / "sql" / "templates"
SQL_RENDERED_DIR = PROJECT_ROOT / "sql" / "rendered"

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


def load_validation_schema() -> dict[str, Any]:
    return load_yaml(VALIDATION_SCHEMA_PATH)


def load_thresholds(entity: str) -> dict[str, Any]:
    schema = load_validation_schema()
    entities = schema.get("crm", {}).get("entities", {})
    for key, value in entities.items():
        if key.lower() == entity.lower():
            return value.get("pipeline_thresholds", {})
    return {}


def dbt_command() -> list[str] | None:
    raw = os.getenv("ICALPS_DBT_COMMAND")
    if not raw:
        return None
    return raw.split()


def stacksync_sync_assumed() -> bool:
    return os.getenv("ICALPS_ASSUME_STACKSYNC_SYNC", "").lower() in {"1", "true", "yes"}
