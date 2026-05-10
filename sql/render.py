"""SQL rendering — the single source of truth for what the runner executes.

Shape
-----
Three pairs of functions. Each pair exposes both execution-form SQL
(INSERT ... ON CONFLICT) and preview-form SQL (SELECT only). The INSERT
variants compose themselves from the SELECT variants so a drift in one
automatically lands in both:

    render_entity_upsert        ←── wraps ←── select_body_entity
    render_engagement_upsert    ←── wraps ←── select_body_engagement
    render_association_bridge   ←── wraps ←── select_body_association

    Runtime (GoldUpsertExecutor.execute / AssociationBridgeExecutor.execute)
        calls the render_* variants.
    Preview (GoldUpsertExecutor.preview / AssociationBridgeExecutor.preview)
        calls the select_body_* variants to run read-only SELECTs and emit
        candidate-row CSVs without mutating hubspot.* tables.

The select_body_* helpers also include any NOT EXISTS idempotency guards
(engagement unique_id guard, association-table guard) because those are
what define "candidate rows" — rows that would actually be inserted.
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Any

from context.config import SQL_RENDERED_DIR, load_run_context, load_schema_context


def _load_contracts(schema: dict[str, Any] | None = None, run: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    return schema or load_schema_context(), run or load_run_context()


# ─────────────────────────────────────────────────────────────────────────────
# Entity upsert — Company / Person / Opportunity
# ─────────────────────────────────────────────────────────────────────────────

def select_body_entity(entity: str, schema: dict[str, Any] | None = None, run: dict[str, Any] | None = None) -> str:
    """Return the SELECT ... FROM ... WHERE body that identifies candidate rows.

    Safe to execute read-only for preview. Does not include the surrounding
    INSERT INTO (...) wrapper or ON CONFLICT clause.
    """
    schema, run = _load_contracts(schema, run)
    cfg = schema["entities"][entity]

    if entity == "Company":
        body = f"""
        SELECT
            stg.icalps_company_id::text AS icalps_company_id,
            stg.icalps_comp_language,
            stg.icalps_comp_website,
            stg.icalps_full_address,
            stg.icalps_owner_fullname AS hubspot_owner_id,
            stg.icalps_companytype,
            stg.icalps_street_address,
            stg.icalps_address_country,
            stg.icalps_full_country AS country,
            stg.icalps_canonical_domain AS domain,
            stg.icalps_addresscity,
            stg.icalps_primarycontact_id,
            stg.icalps_address_postcode,
            stg.icalps_compsource,
            stg.icalps_industry_drill_down,
            stg.icalps_companystatus,
            stg.icalps_companyprimarycontact,
            stg.icalps_companyphone,
            stg.icalps_linkedin_url AS linkedin_company_page,
            stg.icalps_address_state AS state,
            stg.icalps_comp_numemployees,
            stg.icalps_companyemail
        FROM {cfg['silver_table']} AS stg
        WHERE stg.{cfg['upsert']['load_status_column']} IN ('NEW', 'MODIFIED')
        """
    elif entity == "Person":
        body = f"""
        SELECT
            stg.icalps_contact_id::text AS icalps_contact_id,
            stg.icalps_company_id::text AS icalps_company_id,
            stg.company_name AS company,
            stg.icalps_full_country AS country,
            stg.icalps_owner_fullname AS hubspot_owner_id,
            stg.pers_firstname AS firstname,
            stg.pers_lastname AS lastname,
            stg.pers_marketable AS hs_marketable_status,
            stg.icalps_addresscity AS city,
            stg.address_postcode AS zip,
            stg.icalps_salutations,
            stg.icalps_perstitle,
            stg.icalps_linkedin_url AS hs_linkedin_url,
            stg.icalps_email AS email,
            stg.address_state AS state,
            stg.icalps_businessphone,
            stg.icalps_mobilephone,
            stg.icalps_pers_source,
            stg.icalps_contactstatus
        FROM {cfg['silver_table']} AS stg
        WHERE stg.{cfg['upsert']['load_status_column']} IN ('NEW', 'MODIFIED')
        """
    elif entity == "Opportunity":
        body = f"""
        SELECT
            stg.icalps_deal_id::text AS icalps_deal_id,
            stg.icalps_company_id::text AS icalps_company_id,
            stg.icalps_contact_id::text AS icalps_contact_id,
            stg.oppo_description AS dealname,
            stg.hubspot_stageid AS dealstage,
            stg.icalps_owner_fullname AS hubspot_owner_id,
            stg.icalps_primarydealcompany,
            stg.icalps_targetclose,
            stg.icalps_dealnotes,
            stg.icalps_dealstatus,
            stg.icalps_forecast::numeric AS amount,
            stg.icalps_netamount_k__::numeric AS icalps_netamount_k__,
            stg.icalps_netweighted_amount__k__::numeric AS icalps_netweighted_amount__k__,
            stg.icalps_opendate::timestamp AS icalps_opendate,
            stg.icalps_oppocertainty::numeric AS icalps_oppocertainty,
            stg.icalps_stage,
            stg.icalps_primarycontactlastname,
            stg.icalps_dealprimarycontactfirstname,
            stg.ic_alps_cost::numeric AS ic_alps_cost,
            stg.icalps_dealtype,
            stg.icalps_closedate::timestamp AS icalps_closedate
        FROM {cfg['silver_table']} AS stg
        WHERE stg.{cfg['upsert']['load_status_column']} IN ('NEW', 'MODIFIED')
        """
    else:
        raise KeyError(f"Unsupported entity for select_body_entity: {entity}")

    return dedent(body).strip()


def render_entity_upsert(entity: str, schema: dict[str, Any] | None = None, run: dict[str, Any] | None = None) -> str:
    schema, run = _load_contracts(schema, run)
    cfg = schema["entities"][entity]
    run_cfg = run.get("entities", {}).get(entity, {})
    sel = select_body_entity(entity, schema, run)

    if entity == "Company":
        body = f"""
        INSERT INTO {cfg['gold_table']} (
            icalps_company_id, icalps_comp_language, icalps_comp_website,
            icalps_full_address, hubspot_owner_id, icalps_companytype,
            icalps_street_address, icalps_address_country, country, domain,
            icalps_addresscity, icalps_primarycontact_id, icalps_address_postcode,
            icalps_compsource, icalps_industry_drill_down, icalps_companystatus,
            icalps_companyprimarycontact, icalps_companyphone, linkedin_company_page,
            state, icalps_comp_numemployees, icalps_companyemail
        )
        {sel}
        ON CONFLICT ({cfg['upsert']['match_column']}) DO UPDATE
        SET
            icalps_comp_language = EXCLUDED.icalps_comp_language,
            icalps_comp_website = EXCLUDED.icalps_comp_website,
            icalps_full_address = EXCLUDED.icalps_full_address,
            hubspot_owner_id = EXCLUDED.hubspot_owner_id,
            icalps_companytype = EXCLUDED.icalps_companytype,
            icalps_street_address = EXCLUDED.icalps_street_address,
            icalps_address_country = EXCLUDED.icalps_address_country,
            country = EXCLUDED.country,
            domain = EXCLUDED.domain,
            icalps_addresscity = EXCLUDED.icalps_addresscity,
            icalps_primarycontact_id = EXCLUDED.icalps_primarycontact_id,
            icalps_address_postcode = EXCLUDED.icalps_address_postcode,
            icalps_compsource = EXCLUDED.icalps_compsource,
            icalps_industry_drill_down = EXCLUDED.icalps_industry_drill_down,
            icalps_companystatus = EXCLUDED.icalps_companystatus,
            icalps_companyprimarycontact = EXCLUDED.icalps_companyprimarycontact,
            icalps_companyphone = EXCLUDED.icalps_companyphone,
            linkedin_company_page = EXCLUDED.linkedin_company_page,
            state = EXCLUDED.state,
            icalps_comp_numemployees = EXCLUDED.icalps_comp_numemployees,
            icalps_companyemail = EXCLUDED.icalps_companyemail;
        """
    elif entity == "Person":
        body = f"""
        INSERT INTO {cfg['gold_table']} (
            icalps_contact_id, icalps_company_id, company, country,
            hubspot_owner_id, firstname, lastname, hs_marketable_status,
            city, zip, icalps_salutations, icalps_perstitle, hs_linkedin_url,
            email, state, icalps_businessphone, icalps_mobilephone,
            icalps_pers_source, icalps_contactstatus
        )
        {sel}
        ON CONFLICT ({cfg['upsert']['match_column']}) DO UPDATE
        SET
            icalps_company_id = EXCLUDED.icalps_company_id,
            company = EXCLUDED.company,
            country = EXCLUDED.country,
            hubspot_owner_id = EXCLUDED.hubspot_owner_id,
            firstname = EXCLUDED.firstname,
            lastname = EXCLUDED.lastname,
            hs_marketable_status = EXCLUDED.hs_marketable_status,
            city = EXCLUDED.city,
            zip = EXCLUDED.zip,
            icalps_salutations = EXCLUDED.icalps_salutations,
            icalps_perstitle = EXCLUDED.icalps_perstitle,
            hs_linkedin_url = EXCLUDED.hs_linkedin_url,
            email = EXCLUDED.email,
            state = EXCLUDED.state,
            icalps_businessphone = EXCLUDED.icalps_businessphone,
            icalps_mobilephone = EXCLUDED.icalps_mobilephone,
            icalps_pers_source = EXCLUDED.icalps_pers_source,
            icalps_contactstatus = EXCLUDED.icalps_contactstatus;
        """
    elif entity == "Opportunity":
        body = f"""
        INSERT INTO {cfg['gold_table']} (
            icalps_deal_id, icalps_company_id, icalps_contact_id, dealname,
            dealstage, hubspot_owner_id, icalps_primarydealcompany, icalps_targetclose,
            icalps_dealnotes, icalps_dealstatus, amount, icalps_netamount_k__,
            icalps_netweighted_amount__k__, icalps_opendate, icalps_oppocertainty,
            icalps_stage, icalps_primarycontactlastname, icalps_dealprimarycontactfirstname,
            ic_alps_cost, icalps_dealtype, icalps_closedate
        )
        {sel}
        ON CONFLICT ({cfg['upsert']['match_column']}) DO UPDATE
        SET
            icalps_company_id = EXCLUDED.icalps_company_id,
            icalps_contact_id = EXCLUDED.icalps_contact_id,
            dealname = EXCLUDED.dealname,
            dealstage = EXCLUDED.dealstage,
            hubspot_owner_id = EXCLUDED.hubspot_owner_id,
            icalps_primarydealcompany = EXCLUDED.icalps_primarydealcompany,
            icalps_targetclose = EXCLUDED.icalps_targetclose,
            icalps_dealnotes = EXCLUDED.icalps_dealnotes,
            icalps_dealstatus = EXCLUDED.icalps_dealstatus,
            amount = EXCLUDED.amount,
            icalps_netamount_k__ = EXCLUDED.icalps_netamount_k__,
            icalps_netweighted_amount__k__ = EXCLUDED.icalps_netweighted_amount__k__,
            icalps_opendate = EXCLUDED.icalps_opendate,
            icalps_oppocertainty = EXCLUDED.icalps_oppocertainty,
            icalps_stage = EXCLUDED.icalps_stage,
            icalps_primarycontactlastname = EXCLUDED.icalps_primarycontactlastname,
            icalps_dealprimarycontactfirstname = EXCLUDED.icalps_dealprimarycontactfirstname,
            ic_alps_cost = EXCLUDED.ic_alps_cost,
            icalps_dealtype = EXCLUDED.icalps_dealtype,
            icalps_closedate = EXCLUDED.icalps_closedate;
        """
    else:
        raise KeyError(f"Unsupported entity upsert rendering target: {entity}")

    return f"""\
-- Rendered SQL upsert pattern
-- Entity: {entity}
-- Run ID: {run['run_id']}
-- Boundary: SQL upserts only. Validation and dbt stay outside this template.
-- bronze_file={run_cfg.get('bronze_file', 'n/a')}
-- previous_bronze_file={run_cfg.get('previous_bronze_file', 'n/a')}

{dedent(body).strip()}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Engagement upsert — Calls / Notes / Tasks / Meetings
# ─────────────────────────────────────────────────────────────────────────────

def _engagement_context(comm_type: str, schema: dict[str, Any]) -> tuple[str, str, str]:
    """Return (prefix, bridge_table, gold_table) for a given comm_type."""
    comm = schema["entities"]["Communication"]
    prefix = comm["idempotency_prefix"]
    bridge_table = comm.get("bridge_tables", {}).get(comm_type) or f"staging.fct_communication_{comm_type.lower()}"
    gold_table = comm.get("gold_tables", {}).get(comm_type) or f"hubspot.{comm_type.lower()}"
    return prefix, bridge_table, gold_table


def select_body_engagement(comm_type: str, schema: dict[str, Any] | None = None, run: dict[str, Any] | None = None) -> str:
    """Return the SELECT body for an engagement upsert — candidate rows that
    would be inserted into hubspot.{calls|notes|tasks|meetings}.

    Includes the NOT EXISTS (existing.unique_id = ...) idempotency guard so
    preview-mode returns only TRULY new rows, not rows already in hubspot.
    """
    schema, _ = _load_contracts(schema, run)
    prefix, bridge_table, gold_table = _engagement_context(comm_type, schema)

    bodies = {
        "Calls": f"""
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
          )
        """,
        "Tasks": f"""
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
          )
        """,
        "Notes": f"""
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
          )
        """,
        "Meetings": f"""
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
          )
        """,
    }
    if comm_type not in bodies:
        raise KeyError(f"Unsupported communication type: {comm_type}")
    return dedent(bodies[comm_type]).strip()


def render_engagement_upsert(comm_type: str, schema: dict[str, Any] | None = None, run: dict[str, Any] | None = None) -> str:
    schema, run = _load_contracts(schema, run)
    _, _, gold_table = _engagement_context(comm_type, schema)
    sel = select_body_engagement(comm_type, schema, run)

    wrappers = {
        "Calls": f"""
        INSERT INTO {gold_table} (
            call_title, call_notes, activity_date, call_direction, call_status,
            call_duration, unique_id, engagement_source
        )
        {sel};
        """,
        "Tasks": f"""
        INSERT INTO {gold_table} (
            task_title, task_notes, due_date, task_status, priority, task_type, unique_id, source
        )
        {sel};
        """,
        "Notes": f"""
        INSERT INTO {gold_table} (
            note_body, activity_date, unique_id, engagement_source
        )
        {sel};
        """,
        "Meetings": f"""
        INSERT INTO {gold_table} (
            meeting_title, meeting_body, meeting_start_time, meeting_end_time,
            meeting_outcome, meeting_source, meeting_duration, unique_id, engagement_source
        )
        {sel};
        """,
    }

    return f"""\
-- Rendered SQL engagement upsert
-- Communication type: {comm_type}
-- Run ID: {run['run_id']}
-- Invariant: deterministic unique_id and NOT EXISTS idempotency guard.

{dedent(wrappers[comm_type]).strip()}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Association bridge — Calls/Notes/Tasks × company/contact/deal
# ─────────────────────────────────────────────────────────────────────────────

def _association_context(comm_type: str, target: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Return the full set of local variables used by both select_body and render.
    Single place to look up schema references; both functions see identical values.
    """
    comm_lower = comm_type.lower()
    return {
        "comm_lower":        comm_lower,
        "assoc_type_id":     schema["association_type_ids"][f"{comm_lower}_{target}"],
        "bridge_table":      schema["entities"]["Communication"]["bridge_tables"][comm_type],
        "gold_table":        schema["entities"]["Communication"]["gold_tables"][comm_type],
        "target_gold_table": {"company": "hubspot.companies", "contact": "hubspot.contacts", "deal": "hubspot.deals"}[target],
        "stacksync_column":  {
            "company": schema["stacksync"]["company_record_id_column"],
            "contact": schema["stacksync"]["contact_record_id_column"],
            "deal":    schema["stacksync"]["deal_record_id_column"],
        }[target],
        "target_key":        {"company": "icalps_company_id", "contact": "icalps_contact_id", "deal": "icalps_deal_id"}[target],
        "association_table": f"hubspot.associations_{comm_lower}_{target}",
        "engagement_id_col": f"{comm_lower}_id",
        "target_id_col":     f"{target}_id",
        "associated_col":    f"associated_{target}_id",
        "legacy_col":        f"legacy_{target}_id",
        "prefix":            schema["entities"]["Communication"]["idempotency_prefix"],
    }


def select_body_association(comm_type: str, target: str, schema: dict[str, Any] | None = None, run: dict[str, Any] | None = None) -> str:
    """Return the Pass A UNION Pass B SELECT body for the association bridge.

    Read-only JOIN against hubspot.<engagement> + staging.fct_communication_*
    + hubspot.<target>. Includes NOT EXISTS guard against the association
    table so preview returns only associations that would actually be
    inserted — existing associations are filtered out.
    """
    schema, _ = _load_contracts(schema, run)
    v = _association_context(comm_type, target, schema)

    body = f"""
    -- Pass A: StackSync UUID join
    SELECT DISTINCT
        {v['assoc_type_id']},
        target.id,
        comm.id
    FROM {v['gold_table']} AS comm
    INNER JOIN {v['bridge_table']} AS fct
        ON comm.unique_id = '{v['prefix']}' || fct.icalps_communication_id::text
    INNER JOIN {v['target_gold_table']} AS target
        ON fct.{v['associated_col']}::text = target.{v['stacksync_column']}::text
    WHERE comm.unique_id LIKE '{v['prefix']}%'
      AND fct.{v['associated_col']} IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM {v['association_table']} AS assoc
          WHERE assoc.{v['engagement_id_col']} = comm.id
            AND assoc.{v['target_id_col']} = target.id
            AND assoc.association_type_id = {v['assoc_type_id']}
      )

    UNION

    -- Pass B: legacy ID fallback
    SELECT DISTINCT
        {v['assoc_type_id']},
        target.id,
        comm.id
    FROM {v['gold_table']} AS comm
    INNER JOIN {v['bridge_table']} AS fct
        ON comm.unique_id = '{v['prefix']}' || fct.icalps_communication_id::text
    INNER JOIN {v['target_gold_table']} AS target
        ON fct.{v['legacy_col']}::text = target.{v['target_key']}::text
    WHERE comm.unique_id LIKE '{v['prefix']}%'
      AND fct.{v['associated_col']} IS NULL
      AND fct.{v['legacy_col']} IS NOT NULL
      AND NOT EXISTS (
          SELECT 1
          FROM {v['association_table']} AS assoc
          WHERE assoc.{v['engagement_id_col']} = comm.id
            AND assoc.{v['target_id_col']} = target.id
            AND assoc.association_type_id = {v['assoc_type_id']}
      )
    """
    return dedent(body).strip()


def render_association_bridge(comm_type: str, target: str, schema: dict[str, Any] | None = None, run: dict[str, Any] | None = None) -> str:
    schema, run = _load_contracts(schema, run)
    v = _association_context(comm_type, target, schema)
    sel = select_body_association(comm_type, target, schema, run)

    return f"""\
-- Rendered SQL association bridge
-- Communication type: {comm_type}
-- Association target: {target}
-- Run ID: {run['run_id']}
-- Invariant: shared StackSync instance, fixed association_type_id, unique_id prefix '{v['prefix']}', two-pass resolution, NOT EXISTS idempotency guard.

INSERT INTO {v['association_table']} (
    association_type_id,
    {v['target_id_col']},
    {v['engagement_id_col']}
)
{sel};
"""


# ─────────────────────────────────────────────────────────────────────────────
# Rendered-file dump helpers (unchanged from prior shape)
# ─────────────────────────────────────────────────────────────────────────────

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
