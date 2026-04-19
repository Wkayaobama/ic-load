-- normalise_opportunity.sql
-- Replaces silver_normalise.py::SilverNormaliser.normalise_opportunity()
--
-- Reads:  staging.stg_opportunity  (written by BRONZE_EXPORT)
-- Writes: staging.stg_opportunity_normalised
--
-- Deduplicates by oppo_opportunityid keeping the latest by oppo_updateddate.
-- All transformation logic delegated to staging.fn_* UDFs installed by
-- PG_FUNCTIONS_INSTALL. Run order: PG_FUNCTIONS_INSTALL → BRONZE_EXPORT → this script.

DROP TABLE IF EXISTS staging.stg_opportunity_normalised CASCADE;

CREATE TABLE staging.stg_opportunity_normalised AS
WITH ranked AS (
    SELECT
        "Oppo_OpportunityId"                                        AS oppo_opportunityid,
        "Oppo_Description"                                          AS oppo_description,
        "Oppo_Type"                                                 AS oppo_type,
        NULL                                                        AS oppo_category,
        "Oppo_Stage"                                                AS oppo_stage,
        "Oppo_Status"                                               AS oppo_status,
        "Oppo_AssignedUserId"                                       AS oppo_assigneduserid,
        "Oppo_Note"                                                 AS oppo_notes,
        NULL                                                        AS oppo_deleted,
        "Oppo_PrimaryCompanyId"                                     AS oppo_primarycompanyid,
        "Oppo_PrimaryPersonId"                                      AS oppo_primarypersonid,
        "Oppo_CreatedDate"                                          AS oppo_createddate,
        "Oppo_UpdatedDate"                                          AS oppo_updateddate,

        -- Close date: strip time component
        CAST(
            CASE
                WHEN "Oppo_CloseDate"::text LIKE '%T%'
                    THEN SPLIT_PART("Oppo_CloseDate"::text, 'T', 1)
                ELSE "Oppo_CloseDate"::text
            END
        AS date)                                                    AS icalps_closedate,

        CAST(
            CASE
                WHEN "Oppo_Opened"::text LIKE '%T%'
                    THEN SPLIT_PART("Oppo_Opened"::text, 'T', 1)
                ELSE "Oppo_Opened"::text
            END
        AS date)                                                    AS icalps_opendate,

        -- Cost: strip currency symbols, normalise decimal
        staging.fn_normalize_currency("Oppo_Cost"::text)            AS icalps_cost,

        -- Forecast and certainty
        CAST("Oppo_Forecast" AS double precision)                   AS icalps_forecast,
        CAST("Oppo_Certainty" AS double precision)                  AS icalps_certainty,

        -- Computed columns
        CAST("Oppo_Forecast" AS double precision)
            * CAST("Oppo_Certainty" AS double precision) / 100.0    AS cc_weighted,

        CAST("Oppo_Forecast" AS double precision)
            - COALESCE(staging.fn_normalize_currency("Oppo_Cost"::text)::double precision, 0.0)
                                                                    AS cc_net,

        -- HubSpot stage: derive name from pre-computed ID (extraction CASE, Feb 2026)
        -- 396 NULLs expected: Lost/Abandonne/NoGo + unmatched Negotiating records
        CASE "HubSpot_Dealstage_ID"::text
            WHEN '1116419649' THEN 'Closed Won'
            WHEN '1116419644' THEN 'Identified'
            WHEN '1116419645' THEN 'Qualified'
            WHEN '1116419646' THEN 'Design In'
            WHEN '1116419647' THEN 'Design Win'
            WHEN '1116652341' THEN 'On-Hold'
            ELSE NULL
        END                                                         AS hubspot_dealstage_name,
        "HubSpot_Dealstage_ID"                                      AS hubspot_dealstage_id,
        "HubSpot_Pipeline_ID"                                       AS hubspot_pipeline_id,

        -- Denormalised
        "Company_Name"                                              AS company_name,
        "Company_Language"                                          AS company_language,
        "Person_FirstName"                                          AS person_firstname,
        "Person_LastName"                                           AS person_lastname,
        "Person_Email"                                              AS person_email,
        "User_FullName"                                             AS user_fullname,
        "User_Email"                                                AS user_email,

        -- Load-status watermark — carried through unchanged
        _load_status,
        _first_seen_at,
        _last_modified_at,

        -- Deduplication: keep latest per opportunity
        ROW_NUMBER() OVER (
            PARTITION BY "Oppo_OpportunityId"
            ORDER BY "Oppo_UpdatedDate" DESC NULLS LAST
        )                                                           AS _dedup_rank

    FROM staging.stg_opportunity
    WHERE "Oppo_OpportunityId" IS NOT NULL
)
SELECT
    oppo_opportunityid,
    oppo_description,
    oppo_type,
    oppo_category,
    oppo_stage,
    oppo_status,
    oppo_assigneduserid,
    oppo_notes,
    oppo_deleted,
    oppo_primarycompanyid,
    oppo_primarypersonid,
    oppo_createddate,
    oppo_updateddate,
    icalps_closedate,
    icalps_opendate,
    icalps_cost,
    icalps_forecast,
    icalps_certainty,
    cc_weighted,
    cc_net,
    cc_net * icalps_certainty / 100.0                               AS cc_net_weighted,
    hubspot_dealstage_name,
    hubspot_dealstage_id,
    hubspot_pipeline_id,
    company_name,
    company_language,
    person_firstname,
    person_lastname,
    person_email,
    user_fullname,
    user_email,
    _load_status,
    _first_seen_at,
    _last_modified_at
FROM ranked
WHERE _dedup_rank = 1;
