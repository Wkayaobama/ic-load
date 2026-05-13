-- =============================================================================
-- Case / Ticket — staging.stg_case_v2 as a MATERIALIZED VIEW
--
-- Why materialized view (superseding the TABLE approach in 02_stg_case_v2_materialize.sql):
--   • The normalization CTE (01_silver_normalize.sql) is the single source of truth.
--     A TABLE requires TRUNCATE + INSERT on re-run; a MATERIALIZED VIEW requires only
--     REFRESH MATERIALIZED VIEW, which is idempotent and atomic.
--   • REFRESH MATERIALIZED VIEW CONCURRENTLY allows read access during refresh
--     once a UNIQUE index exists on icalps_ticket_id.
--   • Any update to the normalization logic (e.g. adding a new stage value) is
--     applied on the next REFRESH without touching the table DDL.
--   • The view captures the assessed state: the same SQL that will be used for
--     the assessment probe (03_assessment_probe.sql) is the materialized surface.
--
-- Refresh schedule: run after each Bronze load cycle.
-- Command: REFRESH MATERIALIZED VIEW CONCURRENTLY staging.stg_case_v2;
-- =============================================================================

-- ─── 1. Create the materialized view ─────────────────────────────────────────
CREATE MATERIALIZED VIEW IF NOT EXISTS staging.stg_case_v2 AS
WITH bronze_source AS (
    SELECT
        icalps_ticket_id::bigint                                        AS icalps_ticket_id,
        NULLIF(TRIM(COALESCE(case_description, '')), '')               AS subject,
        NULLIF(TRIM(COALESCE(case_description, '')), '')               AS content,
        'external'::text                                                AS hs_pipeline,
        CASE TRIM(NULLIF(case_stage, ''))
            WHEN 'Solved'        THEN '2'
            WHEN 'Investigating' THEN '1'   -- CONFIRM from portal 9201667 before live push
            WHEN 'Confirmed'     THEN '4'
            ELSE NULL
        END                                                             AS hs_pipeline_stage,
        CASE UPPER(TRIM(COALESCE(case_priority, '')))
            WHEN 'HIGH'   THEN 'HIGH'
            WHEN 'MEDIUM' THEN 'MEDIUM'
            WHEN 'LOW'    THEN 'LOW'
            ELSE               'MEDIUM'
        END                                                             AS hs_ticket_priority,
        CASE
            WHEN NULLIF(TRIM(CAST(case_createddate AS text)), '') IS NULL THEN NULL
            ELSE FLOOR(CAST(case_createddate AS numeric))::bigint
        END                                                             AS createdate,
        CASE
            WHEN NULLIF(TRIM(CAST(case_closedate AS text)), '') IS NULL THEN NULL
            ELSE FLOOR(CAST(case_closedate AS numeric))::bigint
        END                                                             AS closed_date,
        NULLIF(TRIM(COALESCE(case_status, '')), '')                    AS icalps_case_status,
        NULLIF(TRIM(COALESCE(case_stage, '')), '')                     AS icalps_case_stage,
        NULLIF(TRIM(COALESCE(case_priority, '')), '')                  AS icalps_case_priority,
        CASE
            WHEN NULLIF(TRIM(CAST(assigned_userid AS text)), '') IS NULL THEN NULL
            ELSE FLOOR(CAST(assigned_userid AS numeric))::bigint
        END                                                             AS icalps_assigned_user_id,
        NULLIF(TRIM(CONCAT_WS(' ',
            NULLIF(TRIM(assigned_userfirstname), ''),
            NULLIF(TRIM(assigned_userlastname), '')
        )), '')                                                         AS icalps_assigned_user_name,
        NULLIF(TRIM(COALESCE(company_website, '')), '')                AS icalps_company_website,
        'IC''ALPS Legacy CRM'::text                                    AS source,
        'silver'::text                                                 AS data_layer,
        'legacy_only'::text                                            AS reconciliation_status,
        -- ── NEW MAPPED COLUMNS ────────────────────────────────────────────────
        FLOOR(CAST(case_caseid AS numeric))::bigint                        AS icalps_ticketid,
        NULLIF(LOWER(TRIM(COALESCE(assigned_useremail, ''))), '')          AS hubspot_owner_id,
        CASE
            WHEN NULLIF(TRIM(CAST(case_primarycompanyid AS text)), '') IS NULL THEN NULL
            ELSE FLOOR(CAST(case_primarycompanyid AS numeric))::bigint
        END                                                                AS icalps_companyid,
        NULLIF(TRIM(COALESCE(case_createdby, '')), '')                     AS hs_created_by_user_id,
        NULLIF(TRIM(COALESCE(case_solutionnote, '')), '')                  AS icalps_solutionnote,
        NULLIF(TRIM(COALESCE(case_referenceid, '')), '')                   AS icalps_ticket_referenceid,
        CASE
            WHEN NULLIF(TRIM(CAST(case_assigneduserid AS text)), '') IS NULL THEN NULL
            WHEN TRIM(CAST(case_assigneduserid AS text)) = 'nan'           THEN NULL
            ELSE FLOOR(CAST(case_assigneduserid AS numeric))::bigint
        END                                                                AS icalps_ticketassigneduserid,
        NULLIF(TRIM(COALESCE(case_problemtype, '')), '')                   AS icalps_ticketcasetype,
        NULLIF(TRIM(COALESCE(company_name, '')), '')                       AS icalps_ticketcompanyname,
        NULLIF(LOWER(TRIM(COALESCE(person_emailaddress, ''))), '')         AS icalps_ticketpersonemailaddress,
        NULLIF(TRIM(COALESCE(person_firstname, '')), '')                   AS icalps_ticketpersonfirstname,
        CASE
            WHEN NULLIF(TRIM(CAST(case_primarypersonid AS text)), '') IS NULL THEN NULL
            WHEN TRIM(CAST(case_primarypersonid AS text)) = 'nan'          THEN NULL
            ELSE FLOOR(CAST(REPLACE(CAST(case_primarypersonid AS text), '.0', '') AS numeric))::bigint
        END                                                                AS icalps_ticketpersonid,
        NULLIF(TRIM(COALESCE(person_lastname, '')), '')                    AS icalps_ticketpersonlastname,
        NULLIF(TRIM(COALESCE(case_source, '')), '')                        AS icalps_ticketsource,
        NULLIF(CONCAT_WS(' - ',
            NULLIF(TRIM(COALESCE(case_status, '')), ''),
            NULLIF(TRIM(COALESCE(case_stage,  '')), '')
        ), '')                                                             AS icalps_ticketstage,
        NULLIF(TRIM(COALESCE(case_problemnote, '')), '')                   AS icalps_problemnote
    FROM staging.stg_cases
    WHERE icalps_ticket_id IS NOT NULL
),
ranked AS (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY icalps_ticket_id
            ORDER BY (
                (CASE WHEN icalps_case_stage               IS NOT NULL THEN 1 ELSE 0 END) +
                (CASE WHEN hubspot_owner_id                IS NOT NULL THEN 1 ELSE 0 END) +
                (CASE WHEN icalps_ticketpersonid           IS NOT NULL THEN 1 ELSE 0 END) +
                (CASE WHEN icalps_ticketpersonemailaddress IS NOT NULL THEN 1 ELSE 0 END) +
                (CASE WHEN createdate                      IS NOT NULL THEN 1 ELSE 0 END) +
                (CASE WHEN icalps_companyid                IS NOT NULL THEN 1 ELSE 0 END)
            ) DESC,
            icalps_ticket_id ASC
        ) AS _rank
    FROM bronze_source
)
SELECT
    -- ── Retained existing columns ─────────────────────────────────────────────
    subject,
    content,
    hs_pipeline,
    hs_pipeline_stage,
    hs_ticket_priority,
    createdate,
    closed_date,
    icalps_case_status,
    icalps_case_stage,
    icalps_case_priority,
    icalps_assigned_user_id,
    icalps_assigned_user_name,
    icalps_company_website,
    source,
    data_layer,
    reconciliation_status,
    -- ── Mapped columns (HubSpot property name conventions) ───────────────────
    icalps_ticketid,
    hubspot_owner_id,
    icalps_companyid,
    hs_created_by_user_id,
    icalps_solutionnote,
    icalps_ticket_referenceid,
    icalps_ticketassigneduserid,
    icalps_ticketcasetype,
    icalps_ticketcompanyname,
    icalps_ticketpersonemailaddress,
    icalps_ticketpersonfirstname,
    icalps_ticketpersonid,
    icalps_ticketpersonlastname,
    icalps_ticketsource,
    icalps_ticketstage,
    icalps_problemnote
FROM ranked
WHERE _rank = 1
WITH DATA;

-- ─── 2. Unique index — required for REFRESH CONCURRENTLY ─────────────────────
CREATE UNIQUE INDEX IF NOT EXISTS stg_case_v2_pk
    ON staging.stg_case_v2 (icalps_ticket_id);

-- ─── 3. Supporting indexes for probe and dedup queries ───────────────────────
CREATE INDEX IF NOT EXISTS stg_case_v2_company_idx
    ON staging.stg_case_v2 (icalps_company_id);

CREATE INDEX IF NOT EXISTS stg_case_v2_contact_idx
    ON staging.stg_case_v2 (icalps_contact_id);

-- ─── 4. Refresh command (run after each Bronze load) ─────────────────────────
-- REFRESH MATERIALIZED VIEW CONCURRENTLY staging.stg_case_v2;
--
-- The CONCURRENTLY keyword requires the unique index above.
-- Without it, use: REFRESH MATERIALIZED VIEW staging.stg_case_v2;
-- (non-concurrent refresh acquires exclusive lock — acceptable during pipeline window)
