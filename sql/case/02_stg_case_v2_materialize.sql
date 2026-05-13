-- =============================================================================
-- Materialize staging.stg_case_v2
--
-- Design choice: regular TABLE (not MATERIALIZED VIEW)
--   Reason: Silver is an iterative assessment surface — stg_cases (Bronze) is
--   still being actively shaped. A regular table allows:
--     • row-level diffs between assessment runs (03_assessment_probe.sql)
--     • _assessed_at timestamp for traceability
--     • TRUNCATE+INSERT pattern for clean idempotent re-runs
--     • no REFRESH MATERIALIZED VIEW dependency chain
--
-- Idempotency: DROP + CREATE on first run; subsequent runs use TRUNCATE + INSERT.
-- =============================================================================

-- ─── Create table shell (idempotent: DROP IF EXISTS + CREATE) ─────────────────
DROP TABLE IF EXISTS staging.stg_case_v2;

CREATE TABLE staging.stg_case_v2 (
    -- ── Retained existing columns ─────────────────────────────────────────────
    subject                         text,
    content                         text,
    hs_pipeline                     text,
    hs_pipeline_stage               text,
    hs_ticket_priority              text,
    createdate                      bigint,     -- epoch ms, NULL when source is NULL
    closed_date                     bigint,     -- epoch ms
    icalps_case_status              text,
    icalps_case_stage               text,
    icalps_case_priority            text,
    icalps_assigned_user_id         bigint,
    icalps_assigned_user_name       text,
    icalps_company_website          text,
    source                          text,
    data_layer                      text,
    reconciliation_status           text,
    -- ── Mapped columns (HubSpot property name conventions) ───────────────────
    icalps_ticketid                 bigint          PRIMARY KEY,
    hubspot_owner_id                text,
    icalps_companyid                bigint,
    hs_created_by_user_id           text,
    icalps_solutionnote             text,
    icalps_ticket_referenceid       text,
    icalps_ticketassigneduserid     bigint,
    icalps_ticketcasetype           text,
    icalps_ticketcompanyname        text,
    icalps_ticketpersonemailaddress text,
    icalps_ticketpersonfirstname    text,
    icalps_ticketpersonid           bigint,
    icalps_ticketpersonlastname     text,
    icalps_ticketsource             text,
    icalps_ticketstage              text,
    icalps_problemnote              text,
    -- ── Metadata ──────────────────────────────────────────────────────────────
    _assessed_at                    timestamptz     DEFAULT now()
);

-- ─── Populate from Silver normalization CTE ───────────────────────────────────
-- Source: sql/case/01_silver_normalize.sql (inlined below for single-shot execution)

INSERT INTO staging.stg_case_v2 (
    -- retained existing
    subject, content,
    hs_pipeline, hs_pipeline_stage, hs_ticket_priority,
    createdate, closed_date,
    icalps_case_status, icalps_case_stage, icalps_case_priority,
    icalps_assigned_user_id, icalps_assigned_user_name,
    icalps_company_website,
    source, data_layer, reconciliation_status,
    -- mapped columns
    icalps_ticketid, hubspot_owner_id, icalps_companyid,
    hs_created_by_user_id, icalps_solutionnote, icalps_ticket_referenceid,
    icalps_ticketassigneduserid, icalps_ticketcasetype, icalps_ticketcompanyname,
    icalps_ticketpersonemailaddress, icalps_ticketpersonfirstname,
    icalps_ticketpersonid, icalps_ticketpersonlastname,
    icalps_ticketsource, icalps_ticketstage, icalps_problemnote
)
WITH bronze_source AS (
    SELECT
        icalps_ticket_id::bigint                                        AS icalps_ticket_id,
        NULLIF(TRIM(COALESCE(case_description, '')), '')               AS subject,
        NULLIF(TRIM(COALESCE(case_description, '')), '')               AS content,
        'external'::text                                                AS hs_pipeline,
        CASE TRIM(NULLIF(case_stage, ''))
            WHEN 'Solved'        THEN '2'
            WHEN 'Investigating' THEN '1'
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
    -- retained existing
    subject, content,
    hs_pipeline, hs_pipeline_stage, hs_ticket_priority,
    createdate, closed_date,
    icalps_case_status, icalps_case_stage, icalps_case_priority,
    icalps_assigned_user_id, icalps_assigned_user_name,
    icalps_company_website,
    source, data_layer, reconciliation_status,
    -- mapped columns
    icalps_ticketid, hubspot_owner_id, icalps_companyid,
    hs_created_by_user_id, icalps_solutionnote, icalps_ticket_referenceid,
    icalps_ticketassigneduserid, icalps_ticketcasetype, icalps_ticketcompanyname,
    icalps_ticketpersonemailaddress, icalps_ticketpersonfirstname,
    icalps_ticketpersonid, icalps_ticketpersonlastname,
    icalps_ticketsource, icalps_ticketstage, icalps_problemnote
FROM ranked
WHERE _rank = 1;

-- ─── Verification counts ──────────────────────────────────────────────────────
SELECT
    COUNT(*)                                                               AS total_rows,
    COUNT(icalps_case_stage)                                               AS rows_with_stage,
    COUNT(*) - COUNT(icalps_case_stage)                                    AS rows_null_stage,
    COUNT(hubspot_owner_id)                                                AS rows_with_owner_email,
    COUNT(icalps_ticketpersonid)                                           AS rows_with_contact,
    COUNT(icalps_ticketpersonemailaddress)                                 AS rows_with_contact_email,
    COUNT(createdate)                                                      AS rows_with_createdate,
    ROUND(COUNT(icalps_case_stage)::numeric / COUNT(*) * 100, 1)           AS stage_coverage_pct,
    -- new mapped column coverage
    COUNT(icalps_ticketstage)                                              AS rows_with_ticketstage,
    COUNT(hs_created_by_user_id)                                           AS rows_with_createdby,
    COUNT(icalps_solutionnote)                                             AS rows_with_solutionnote,
    COUNT(icalps_ticketsource)                                             AS rows_with_source,
    COUNT(icalps_problemnote)                                              AS rows_with_problemnote
FROM staging.stg_case_v2;
