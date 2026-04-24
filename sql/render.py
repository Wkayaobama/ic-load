from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Any

from context.config import SQL_RENDERED_DIR, load_run_context, load_schema_context


def _load_contracts(schema: dict[str, Any] | None = None, run: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    return schema or load_schema_context(), run or load_run_context()


def render_entity_upsert(entity: str, schema: dict[str, Any] | None = None, run: dict[str, Any] | None = None) -> str:
    schema, run = _load_contracts(schema, run)
    cfg = schema["entities"][entity]
    run_cfg = run.get("entities", {}).get(entity, {})

    if entity == "Company":
        body = f"""
        INSERT INTO {cfg['gold_table']} (
            icalps_company_id, name, icalps_comp_website, city, country, state,
            zip, industry, phone, comp_type, comp_sector
        )
        SELECT
            stg.icalps_company_id::text,
            stg.name,
            stg.icalps_comp_website,
            stg.city,
            stg.icalps_address_country,
            stg.icalps_company_state,
            stg.icalps_address_postcode,
            stg.icalps_industry_drill_down,
            stg.icalps_companyphone,
            stg.icalps_companytype,
            stg.icalps_industry_drill_down
        FROM {cfg['silver_table']} AS stg
        WHERE stg.{cfg['upsert']['load_status_column']} IN ('NEW', 'MODIFIED')
        ON CONFLICT ({cfg['upsert']['match_column']}) DO UPDATE
        SET
            name = EXCLUDED.name,
            icalps_comp_website = EXCLUDED.icalps_comp_website,
            city = EXCLUDED.city,
            country = EXCLUDED.country,
            state = EXCLUDED.state,
            zip = EXCLUDED.zip,
            industry = EXCLUDED.industry,
            phone = EXCLUDED.phone,
            comp_type = EXCLUDED.comp_type,
            comp_sector = EXCLUDED.comp_sector;
        """
    elif entity == "Person":
        body = f"""
        INSERT INTO {cfg['gold_table']} (
            icalps_contact_id, email, firstname, lastname, jobtitle, phone,
            mobilephone, city, state, country, zip, lastmodifieddate
        )
        SELECT
            stg.icalps_contact_id::text,
            stg.email,
            stg.firstname,
            stg.lastname,
            stg.icalps_perstitle,
            stg.icalps_businessphone,
            stg.icalps_mobilephone,
            stg.icalps_addresscity,
            stg.state,
            stg.icalps_address_country,
            stg.zip,
            stg.lastmodifieddate::timestamp
        FROM {cfg['silver_table']} AS stg
        WHERE stg.{cfg['upsert']['load_status_column']} IN ('NEW', 'MODIFIED')
        ON CONFLICT ({cfg['upsert']['match_column']}) DO UPDATE
        SET
            email = EXCLUDED.email,
            firstname = EXCLUDED.firstname,
            lastname = EXCLUDED.lastname,
            jobtitle = EXCLUDED.jobtitle,
            phone = EXCLUDED.phone,
            mobilephone = EXCLUDED.mobilephone,
            city = EXCLUDED.city,
            state = EXCLUDED.state,
            country = EXCLUDED.country,
            zip = EXCLUDED.zip,
            lastmodifieddate = EXCLUDED.lastmodifieddate;
        """
    elif entity == "Opportunity":
        body = f"""
        INSERT INTO {cfg['gold_table']} (
            icalps_deal_id, dealname, pipeline, dealstage, amount,
            icalps_oppocertainty, icalps_dealtype, icalps_dealnotes, icalps_closedate
        )
        SELECT
            stg.icalps_deal_id::text,
            stg.dealname,
            stg.pipeline,
            stg.dealstage,
            stg.amount::numeric,
            stg.icalps_oppocertainty::numeric,
            stg.icalps_dealtype,
            stg.icalps_dealnotes,
            stg.icalps_closedate
        FROM {cfg['silver_table']} AS stg
        WHERE stg.{cfg['upsert']['load_status_column']} IN ('NEW', 'MODIFIED')
        ON CONFLICT ({cfg['upsert']['match_column']}) DO UPDATE
        SET
            dealname = EXCLUDED.dealname,
            pipeline = EXCLUDED.pipeline,
            dealstage = EXCLUDED.dealstage,
            amount = EXCLUDED.amount,
            icalps_oppocertainty = EXCLUDED.icalps_oppocertainty,
            icalps_dealtype = EXCLUDED.icalps_dealtype,
            icalps_dealnotes = EXCLUDED.icalps_dealnotes,
            icalps_closedate = EXCLUDED.icalps_closedate;
        """
    else:
        raise KeyError(f"Unsupported entity upsert rendering target: {entity}")

    return dedent(
        f"""\
        -- Rendered SQL upsert pattern
        -- Entity: {entity}
        -- Run ID: {run['run_id']}
        -- Boundary: SQL upserts only. Validation and dbt stay outside this template.
        -- bronze_file={run_cfg.get('bronze_file', 'n/a')}
        -- previous_bronze_file={run_cfg.get('previous_bronze_file', 'n/a')}

        {dedent(body).strip()}
        """
    )


def render_engagement_upsert(comm_type: str, schema: dict[str, Any] | None = None, run: dict[str, Any] | None = None) -> str:
    schema, run = _load_contracts(schema, run)
    prefix = schema["entities"]["Communication"]["idempotency_prefix"]
    bridge_table = schema["entities"]["Communication"]["bridge_tables"].get(comm_type) or f"staging.fct_communication_{comm_type.lower()}"
    gold_table = schema["entities"]["Communication"]["gold_tables"].get(comm_type) or f"hubspot.{comm_type.lower()}"

    bodies = {
        "Calls": f"""
        INSERT INTO {gold_table} (
            call_title, call_notes, activity_date, call_direction, call_status,
            call_duration, unique_id, engagement_source
        )
        SELECT
            hs_call_title,
            hs_call_body,
            hs_timestamp,
            hs_call_direction,
            hs_call_status,
            hs_call_duration,
            '{prefix}' || icalps_communication_id::text,
            'IC_ALPS_MIGRATION'
        FROM {bridge_table}
        WHERE icalps_communication_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM {gold_table} existing
              WHERE existing.unique_id = '{prefix}' || icalps_communication_id::text
          );
        """,
        "Tasks": f"""
        INSERT INTO {gold_table} (
            task_title, task_notes, due_date, task_status, priority, task_type, unique_id, source
        )
        SELECT
            hs_task_subject,
            hs_task_body,
            hs_timestamp,
            hs_task_status,
            'MEDIUM',
            hs_task_type,
            '{prefix}' || icalps_communication_id::text,
            'IC_ALPS_MIGRATION'
        FROM {bridge_table}
        WHERE icalps_communication_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM {gold_table} existing
              WHERE existing.unique_id = '{prefix}' || icalps_communication_id::text
          );
        """,
        "Notes": f"""
        INSERT INTO {gold_table} (
            note_body, activity_date, unique_id, engagement_source
        )
        SELECT
            COALESCE(hs_note_body, hs_note_subject, 'Note from IC''ALPS'),
            hs_timestamp,
            '{prefix}' || icalps_communication_id::text,
            'IC_ALPS_MIGRATION'
        FROM {bridge_table}
        WHERE icalps_communication_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM {gold_table} existing
              WHERE existing.unique_id = '{prefix}' || icalps_communication_id::text
          );
        """,
        "Meetings": f"""
        INSERT INTO {gold_table} (
            meeting_title, meeting_body, meeting_start_time, meeting_end_time,
            meeting_outcome, meeting_source, meeting_duration, unique_id, engagement_source
        )
        SELECT
            hs_meeting_title,
            hs_meeting_body,
            hs_meeting_start_time,
            hs_meeting_end_time,
            hs_meeting_outcome,
            hs_meeting_source,
            hs_meeting_duration_minutes,
            '{prefix}' || icalps_communication_id::text,
            'IC_ALPS_MIGRATION'
        FROM {bridge_table}
        WHERE icalps_communication_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM {gold_table} existing
              WHERE existing.unique_id = '{prefix}' || icalps_communication_id::text
          );
        """,
    }

    return dedent(
        f"""\
        -- Rendered SQL engagement upsert
        -- Communication type: {comm_type}
        -- Run ID: {run['run_id']}
        -- Invariant: deterministic unique_id and NOT EXISTS idempotency guard.

        {dedent(bodies[comm_type]).strip()}
        """
    )


def render_association_bridge(comm_type: str, target: str, schema: dict[str, Any] | None = None, run: dict[str, Any] | None = None) -> str:
    schema, run = _load_contracts(schema, run)
    comm_lower = comm_type.lower()
    assoc_type_id = schema["association_type_ids"][f"{comm_lower}_{target}"]
    bridge_table = schema["entities"]["Communication"]["bridge_tables"][comm_type]
    gold_table = schema["entities"]["Communication"]["gold_tables"][comm_type]
    target_gold_table = {"company": "hubspot.companies", "contact": "hubspot.contacts", "deal": "hubspot.deals"}[target]
    stacksync_column = {
        "company": schema["stacksync"]["company_record_id_column"],
        "contact": schema["stacksync"]["contact_record_id_column"],
        "deal": schema["stacksync"]["deal_record_id_column"],
    }[target]
    target_key = {"company": "icalps_company_id", "contact": "icalps_contact_id", "deal": "icalps_deal_id"}[target]
    association_table = f"hubspot.associations_{comm_lower}_{target}"
    engagement_id_col = f"{comm_lower}_id"
    target_id_col = f"{target}_id"
    associated_col = f"associated_{target}_id"
    legacy_col = f"legacy_{target}_id"
    prefix = schema["entities"]["Communication"]["idempotency_prefix"]

    return dedent(
        f"""\
        -- Rendered SQL association bridge
        -- Communication type: {comm_type}
        -- Association target: {target}
        -- Run ID: {run['run_id']}
        -- Invariant: shared StackSync instance, fixed association_type_id, unique_id prefix '{prefix}', two-pass resolution, NOT EXISTS idempotency guard.

        INSERT INTO {association_table} (
            association_type_id,
            {target_id_col},
            {engagement_id_col}
        )
        -- Pass A: StackSync UUID join
        SELECT DISTINCT
            {assoc_type_id},
            target.id,
            comm.id
        FROM {gold_table} AS comm
        INNER JOIN {bridge_table} AS fct
            ON comm.unique_id = '{prefix}' || fct.icalps_communication_id::text
        INNER JOIN {target_gold_table} AS target
            ON fct.{associated_col}::text = target.{stacksync_column}::text
        WHERE comm.unique_id LIKE '{prefix}%'
          AND fct.{associated_col} IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM {association_table} AS assoc
              WHERE assoc.{engagement_id_col} = comm.id
                AND assoc.{target_id_col} = target.id
                AND assoc.association_type_id = {assoc_type_id}
          )

        UNION

        -- Pass B: legacy ID fallback
        SELECT DISTINCT
            {assoc_type_id},
            target.id,
            comm.id
        FROM {gold_table} AS comm
        INNER JOIN {bridge_table} AS fct
            ON comm.unique_id = '{prefix}' || fct.icalps_communication_id::text
        INNER JOIN {target_gold_table} AS target
            ON fct.{legacy_col}::text = target.{target_key}::text
        WHERE comm.unique_id LIKE '{prefix}%'
          AND fct.{associated_col} IS NULL
          AND fct.{legacy_col} IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM {association_table} AS assoc
              WHERE assoc.{engagement_id_col} = comm.id
                AND assoc.{target_id_col} = target.id
                AND assoc.association_type_id = {assoc_type_id}
          );
        """
    )


def _write_rendered(filename: str, sql_text: str, output_dir: Path | None = None) -> Path:
    output_root = output_dir or SQL_RENDERED_DIR
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / filename
    path.write_text(sql_text, encoding="utf-8")
    return path


def write_all_rendered_sql(output_dir: Path | None = None) -> list[Path]:
    schema, run = _load_contracts()
    paths: list[Path] = []

    for entity in ("Company", "Person", "Opportunity"):
        paths.append(_write_rendered(f"upsert_{entity.lower()}.sql", render_entity_upsert(entity, schema, run), output_dir))

    for comm_type in ("Calls", "Notes", "Tasks", "Meetings"):
        paths.append(_write_rendered(f"engagement_{comm_type.lower()}.sql", render_engagement_upsert(comm_type, schema, run), output_dir))

    for mapping in schema["association_bridge"]["supported_patterns"]:
        for target in mapping["targets"]:
            paths.append(
                _write_rendered(
                    f"association_{mapping['comm_type'].lower()}_{target}.sql",
                    render_association_bridge(mapping["comm_type"], target, schema, run),
                    output_dir,
                )
            )

    return paths
