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

        -- Close date: strip time component
        CAST(
            CASE
                WHEN oppo_closedate::text LIKE '%T%'
                    THEN SPLIT_PART(oppo_closedate::text, 'T', 1)
                ELSE oppo_closedate::text
            END
        AS date)                                                AS icalps_closedate,

        CAST(
            CASE
                WHEN oppo_openeddate::text LIKE '%T%'
                    THEN SPLIT_PART(oppo_openeddate::text, 'T', 1)
                ELSE oppo_openeddate::text
            END
        AS date)                                                AS icalps_opendate,

        -- Cost: strip currency symbols, normalise decimal
        staging.fn_normalize_currency(oppo_cost::text)          AS icalps_cost,

        -- Forecast and certainty
        CAST(oppo_forecast AS double precision)                 AS icalps_forecast,
        CAST(oppo_certainty AS double precision)                AS icalps_certainty,

        -- Computed columns
        CAST(oppo_forecast AS double precision)
            * CAST(oppo_certainty AS double precision) / 100.0  AS cc_weighted,

        CAST(oppo_forecast AS double precision)
            - COALESCE(staging.fn_normalize_currency(oppo_cost::text)::double precision, 0.0)
                                                                AS cc_net,

        -- HubSpot stage mapping (pre-computed at Bronze extraction)
        hubspot_dealstage_name,
        hubspot_pipeline_id,

        -- Denormalised
        company_name,
        company_language,
        person_firstname,
        person_lastname,
        person_email,
        user_fullname,
        user_email,

        -- Load-status watermark — carried through unchanged
        _load_status,
        _first_seen_at,
        _last_modified_at,

        -- Deduplication: keep latest per opportunity
        ROW_NUMBER() OVER (
            PARTITION BY oppo_opportunityid
            ORDER BY oppo_updateddate DESC NULLS LAST
        )                                                       AS _dedup_rank

    FROM staging.stg_opportunity
    WHERE oppo_opportunityid IS NOT NULL
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
    cc_net * icalps_certainty / 100.0                           AS cc_net_weighted,
    hubspot_dealstage_name,
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
