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
        "Oppo_OpportunityId"                                        AS icalps_deal_id,
        "Oppo_Description"                                          AS dealname,
        "Oppo_Type"                                                 AS icalps_dealtype,
        NULL                                                        AS oppo_category,
        "Oppo_Stage"                                                AS icalps_stage,
        "Oppo_Status"                                               AS icalps_dealstatus,
        "Oppo_AssignedUserId"                                       AS hubspot_owner_id,
        "Oppo_Note"                                                 AS icalps_dealnotes,
        NULL                                                        AS oppo_deleted,
        "Oppo_PrimaryCompanyId"                                     AS icalps_company_id,
        "Oppo_PrimaryPersonId"                                      AS icalps_contact_id,
        "Oppo_CreatedDate"                                          AS createdate,
        "Oppo_UpdatedDate"                                          AS lastmodifieddate,

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
        staging.fn_normalize_currency("Oppo_Cost"::text)            AS ic_alps_cost,

        -- Forecast and certainty (source is absolute €; divide by 1000 → k€ per schema contract)
        CAST("Oppo_Forecast" AS double precision) / 1000.0          AS amount,
        CAST("Oppo_Certainty" AS double precision) / 100.0          AS icalps_oppocertainty,

        -- Computed columns
        CAST("Oppo_Forecast" AS double precision)
            * CAST("Oppo_Certainty" AS double precision) / 100.0    AS ccicalps_weightedamount,

        CAST("Oppo_Forecast" AS double precision)
            - COALESCE(staging.fn_normalize_currency("Oppo_Cost"::text)::double precision, 0.0)
                                                                    AS ccicalps_netamount,

        -- HubSpot stage: derive name from pre-computed ID (extraction CASE, Apr 2026)
        CASE "HubSpot_Dealstage_ID"::text
            WHEN '1116419649' THEN 'Closed Won'
            WHEN '1116419650' THEN 'Closed Dead'
            WHEN '1313738265' THEN 'Closed Lost'
            WHEN '1116419644' THEN 'Identified'
            WHEN '1116419645' THEN 'Qualified'
            WHEN '1116419646' THEN 'Design In'
            WHEN '1116419647' THEN 'Design Win'
            WHEN '1116652341' THEN 'On-Hold'
            ELSE NULL
        END                                                         AS hubspot_dealstage_name,
        "HubSpot_Dealstage_ID"                                      AS dealstage,
        "HubSpot_Pipeline_ID"                                       AS pipeline,

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
    icalps_deal_id,
    dealname,
    icalps_dealtype,
    oppo_category,
    icalps_stage,
    icalps_dealstatus,
    hubspot_owner_id,
    icalps_dealnotes,
    oppo_deleted,
    icalps_company_id,
    icalps_contact_id,
    createdate,
    lastmodifieddate,
    icalps_closedate,
    icalps_opendate,
    ic_alps_cost,
    amount,
    icalps_oppocertainty,
    ccicalps_weightedamount,
    ccicalps_netamount,
    ccicalps_netamount * icalps_oppocertainty                       AS ccicalps_netweightedamount,
    hubspot_dealstage_name,
    dealstage,
    pipeline,
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
