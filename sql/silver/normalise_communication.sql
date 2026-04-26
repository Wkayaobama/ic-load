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
    "Comm_CommunicationId"                                   AS comm_communicationid,
    "Comm_Action"                                            AS comm_action,
    "Comm_Type"                                              AS comm_type,
    "Comm_Status"                                            AS comm_status,
    "Comm_Priority"                                          AS comm_priority,

    -- Strip HTML from subject and note
    staging.fn_clean_html("Comm_Subject")                    AS comm_subject,
    staging.fn_clean_html("Comm_Note")                       AS comm_note,

    "Comm_Email"                                             AS comm_email,

    -- Timestamps (UTC conversion is a Gold-layer concern)
    "Comm_DateTime"                                          AS comm_datetime,
    "Comm_OriginalDateTime"                                  AS comm_originaldatetime,
    "Comm_OriginalToDateTime"                                AS comm_originaltodatetime,

    -- Linkage
    "Person_Id"                                              AS person_id,
    "Company_Id"                                             AS company_id,
    "Comm_OpportunityId"                                     AS comm_opportunityid,
    "Comm_CaseId"                                            AS comm_caseid,

    -- Denormalised (column names from vCalendarCommunication view)
    "Person_EmailAddress"                                    AS person_email,
    CONCAT_WS(' ', NULLIF("Person_FirstName", ''),
                   NULLIF("Person_LastName", ''))            AS person_name,
    "Company_Id"                                             AS comp_companyid,
    "Company_Name"                                           AS comp_name,
    NULL                                                     AS comp_website,

    COALESCE("Comm_OwnerEmail", 'thierry.villard@icalps.com') AS icalps_owner_email,

    -- Load-status watermark — carried through unchanged
    _load_status,
    _first_seen_at,
    _last_modified_at

FROM staging.stg_communication
WHERE "Comm_CommunicationId" IS NOT NULL
  -- Silver orphan gate: drop communications with no CRM link
  AND ("Company_Id" IS NOT NULL OR "Person_Id" IS NOT NULL);
