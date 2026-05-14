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
        "Case_CaseId"::bigint                                           AS icalps_ticket_id,
        NULLIF(TRIM(COALESCE("Case_Description", '')), '')             AS subject,
        NULLIF(TRIM(COALESCE("Case_Description", '')), '')             AS content,
        'external'::text                                                AS hs_pipeline,
        CASE TRIM(NULLIF("Case_Stage", ''))
            WHEN 'Solved'        THEN '2'
            WHEN 'Investigating' THEN '1'   -- CONFIRM from portal 9201667 before live push
            WHEN 'Confirmed'     THEN '4'
            ELSE NULL
        END                                                             AS hs_pipeline_stage,
        CASE UPPER(TRIM(COALESCE("Case_Priority", '')))
            WHEN 'HIGH'   THEN 'HIGH'
            WHEN 'MEDIUM' THEN 'MEDIUM'
            WHEN 'LOW'    THEN 'LOW'
            ELSE               'MEDIUM'
        END                                                             AS hs_ticket_priority,
        CASE
            WHEN NULLIF(TRIM("Case_CreatedDate"::text), '') IS NULL THEN NULL
            ELSE (EXTRACT(EPOCH FROM "Case_CreatedDate"::text::timestamp) * 1000)::bigint
        END                                                             AS createdate,
        CASE
            WHEN NULLIF(TRIM("Case_CloseDate"::text), '') IS NULL THEN NULL
            ELSE (EXTRACT(EPOCH FROM "Case_CloseDate"::text::timestamp) * 1000)::bigint
        END                                                             AS closed_date,
        NULLIF(TRIM(COALESCE("Case_Status", '')), '')                  AS icalps_case_status,
        NULLIF(TRIM(COALESCE("Case_Stage", '')), '')                   AS icalps_case_stage,
        NULLIF(TRIM(COALESCE("Case_Priority", '')), '')                AS icalps_case_priority,
        CASE
            WHEN NULLIF(TRIM(CAST("Assigned_UserId" AS text)), '') IS NULL THEN NULL
            ELSE FLOOR(CAST("Assigned_UserId" AS numeric))::bigint
        END                                                             AS icalps_assigned_user_id,
        NULLIF(TRIM(CONCAT_WS(' ',
            NULLIF(TRIM("Assigned_UserFirstName"), ''),
            NULLIF(TRIM("Assigned_UserLastName"), '')
        )), '')                                                         AS icalps_assigned_user_name,
        NULLIF(TRIM(COALESCE("Company_WebSite", '')), '')              AS icalps_company_website,
        'IC''ALPS Legacy CRM'::text                                    AS source,
        'silver'::text                                                 AS data_layer,
        'legacy_only'::text                                            AS reconciliation_status,
        -- ── NEW MAPPED COLUMNS ────────────────────────────────────────────────
        FLOOR(CAST("Case_CaseId" AS numeric))::bigint                      AS icalps_ticketid,
        NULLIF(LOWER(TRIM(COALESCE("Assigned_UserEmail", ''))), '')        AS hubspot_owner_id,
        CASE
            WHEN NULLIF(TRIM(CAST("Case_PrimaryCompanyId" AS text)), '') IS NULL THEN NULL
            ELSE FLOOR(CAST("Case_PrimaryCompanyId" AS numeric))::bigint
        END                                                                AS icalps_companyid,
        NULLIF(TRIM(COALESCE("Case_CreatedBy", '')), '')                   AS hs_created_by_user_id,
        NULLIF(TRIM(COALESCE("Case_SolutionNote", '')), '')                AS icalps_solutionnote,
        NULLIF(TRIM(COALESCE("Case_CustomerRef", '')), '')                 AS icalps_ticket_referenceid,
        CASE
            WHEN NULLIF(TRIM(CAST("Case_AssignedUserId" AS text)), '') IS NULL THEN NULL
            WHEN TRIM(CAST("Case_AssignedUserId" AS text)) = 'nan'         THEN NULL
            ELSE FLOOR(CAST("Case_AssignedUserId" AS numeric))::bigint
        END                                                                AS icalps_ticketassigneduserid,
        NULLIF(TRIM(COALESCE("Case_ProblemType", '')), '')                 AS icalps_ticketcasetype,
        NULLIF(TRIM(COALESCE("Company_Name", '')), '')                     AS icalps_ticketcompanyname,
        NULLIF(LOWER(TRIM(COALESCE("Person_EmailAddress", ''))), '')       AS icalps_ticketpersonemailaddress,
        NULLIF(TRIM(COALESCE("Person_FirstName", '')), '')                 AS icalps_ticketpersonfirstname,
        CASE
            WHEN NULLIF(TRIM(CAST("Case_PrimaryPersonId" AS text)), '') IS NULL THEN NULL
            WHEN TRIM(CAST("Case_PrimaryPersonId" AS text)) = 'nan'        THEN NULL
            ELSE FLOOR(CAST(REPLACE(CAST("Case_PrimaryPersonId" AS text), '.0', '') AS numeric))::bigint
        END                                                                AS icalps_ticketpersonid,
        NULLIF(TRIM(COALESCE("Person_LastName", '')), '')                  AS icalps_ticketpersonlastname,
        NULLIF(TRIM(COALESCE("Case_Source", '')), '')                      AS icalps_ticketsource,
        NULLIF(CONCAT_WS(' - ',
            NULLIF(TRIM(COALESCE("Case_Status", '')), ''),
            NULLIF(TRIM(COALESCE("Case_Stage",  '')), '')
        ), '')                                                             AS icalps_ticketstage,
        NULLIF(TRIM(COALESCE("Case_ProblemNote", '')), '')                 AS icalps_problemnote
    FROM staging.stg_cases
    WHERE "Case_CaseId" IS NOT NULL
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
