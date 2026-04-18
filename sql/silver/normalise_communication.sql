-- normalise_communication.sql
-- Replaces silver_normalise.py::SilverNormaliser.normalise_communication()
--
-- Reads:  staging.stg_communication  (written by BRONZE_EXPORT)
-- Writes: staging.stg_communication_normalised
--
-- Light cleaning only — heavy transformation is handled downstream by
-- fn_build_communication_hierarchy (postprocess stage).
-- Silver orphan gate: excludes communications with no CRM link
-- (no company_id AND no person_id).
--
-- Run order: PG_FUNCTIONS_INSTALL → BRONZE_EXPORT → this script.

DROP TABLE IF EXISTS staging.stg_communication_normalised CASCADE;

CREATE TABLE staging.stg_communication_normalised AS
SELECT
    comm_communicationid,
    comm_action,
    comm_type,
    comm_status,
    comm_priority,
    comm_channel,

    -- Strip HTML from subject and note
    staging.fn_clean_html(comm_subject)                     AS comm_subject,
    staging.fn_clean_html(comm_note)                        AS comm_note,

    comm_email,

    -- Timestamps (UTC conversion is a Gold-layer concern)
    comm_datetime,
    comm_originaldatetime,
    comm_originaltodatetime,

    -- Linkage
    person_id,
    company_id,
    comm_opportunityid,
    comm_caseid,

    -- Denormalised (may be absent from older Bronze extracts — NULL if missing)
    person_email,
    person_name,
    comp_companyid,
    comp_name,
    comp_website,

    -- Owner email from denormalised Companies join (used for parent tiebreaker)
    "companies.owner_email"                                 AS icalps_owner_email,

    -- Load-status watermark — carried through unchanged
    _load_status,
    _first_seen_at,
    _last_modified_at

FROM staging.stg_communication
WHERE comm_communicationid IS NOT NULL
  -- Silver orphan gate: drop communications with no CRM link
  AND (company_id IS NOT NULL OR person_id IS NOT NULL);
