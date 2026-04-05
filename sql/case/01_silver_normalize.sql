-- =============================================================================
-- Case / Ticket — Bronze → Silver normalization CTE
-- Source:  staging.stg_cases  (Bronze raw, legacy preservation)
-- Target:  staging.stg_case_v2  (via 02_stg_case_v2_materialize.sql)
--
-- Fixes applied vs live staging.stg_case (assessed 2026-04-05):
--   1. icalps_case_stage   — NULLIF(TRIM(case_stage),'') — eliminates 'nan'/empty; 12 rows
--   2. hs_pipeline_stage   — derived from stage CASE map; NULL where stage is NULL
--   3. icalps_contact_id   — FLOOR(case_primarypersonid::numeric)::bigint; fixes float cast
--   4. createdate          — FLOOR(case_createdate::numeric)::bigint where non-null
--   5. icalps_company_name — TRIM() — removes trailing whitespace artefact
--   6. icalps_contact_email— NULLIF(TRIM(person_emailaddress),'') — no more 'nan'
--   7. icalps_assigned_user_email — NEW column from assigned_useremail (Bronze had it, Silver missed it)
--
-- hs_pipeline_stage mapping (verified from matched rows in live stg_case):
--   Solved        → 2   (confirmed from assessment rows 2,3,5…)
--   Investigating → 1   (PLACEHOLDER — confirm from HubSpot portal 9201667 before live push)
--   Confirmed     → 4   (confirmed from assessment rows 1,4,6…)
--   NULL          → NULL
-- =============================================================================

WITH bronze_source AS (
    SELECT
        -- ── Primary key ──────────────────────────────────────────────────────
        icalps_ticket_id::bigint                                        AS icalps_ticket_id,

        -- ── Ticket subject / content ─────────────────────────────────────────
        -- direct field: ticket_description doubles as both subject and content
        TRIM(COALESCE(ticket_description, ''))                         AS subject,
        TRIM(COALESCE(ticket_description, ''))                         AS content,

        -- ── HubSpot pipeline metadata ─────────────────────────────────────────
        -- 'external' is the pipeline name in the existing live stg_case
        'external'::text                                                AS hs_pipeline,

        -- Stage ID mapping — confirmed from matched rows in live stg_case
        -- PLACEHOLDER: verify Investigating→1 from portal before live push
        CASE TRIM(NULLIF(case_stage, ''))
            WHEN 'Solved'        THEN '2'
            WHEN 'Investigating' THEN '1'   -- CONFIRM FROM PORTAL
            WHEN 'Confirmed'     THEN '4'
            ELSE NULL
        END                                                             AS hs_pipeline_stage,

        -- ── Priority ─────────────────────────────────────────────────────────
        -- direct field: map 'Normal' → 'MEDIUM' to match HubSpot enum
        CASE UPPER(TRIM(COALESCE(case_priority, '')))
            WHEN 'HIGH'     THEN 'HIGH'
            WHEN 'MEDIUM'   THEN 'MEDIUM'
            WHEN 'LOW'      THEN 'LOW'
            WHEN 'NORMAL'   THEN 'MEDIUM'   -- IC'ALPS 'Normal' maps to HubSpot MEDIUM
            ELSE            'MEDIUM'
        END                                                             AS hs_ticket_priority,

        -- ── Dates: epoch milliseconds (bigint) or NULL ────────────────────────
        -- FIX: was producing string float '1591142400000.0'; now cast to bigint
        CASE
            WHEN NULLIF(TRIM(CAST(case_createdate AS text)), '') IS NULL THEN NULL
            ELSE FLOOR(CAST(case_createdate AS numeric))::bigint
        END                                                             AS createdate,

        CASE
            WHEN NULLIF(TRIM(CAST(case_closedate AS text)), '') IS NULL THEN NULL
            ELSE FLOOR(CAST(case_closedate AS numeric))::bigint
        END                                                             AS closed_date,

        -- ── IC'ALPS legacy status / stage ─────────────────────────────────────
        NULLIF(TRIM(COALESCE(case_status, '')), '')                    AS icalps_case_status,

        -- FIX: was producing Python 'nan' for empty case_stage rows; 12 rows affected
        NULLIF(TRIM(COALESCE(case_stage, '')), '')                     AS icalps_case_stage,

        NULLIF(TRIM(COALESCE(case_priority, '')), '')                  AS icalps_case_priority,

        -- ── Owner / assignee ──────────────────────────────────────────────────
        -- direct field: integer user ID from IC'ALPS
        CASE
            WHEN NULLIF(TRIM(CAST(assigned_userid AS text)), '') IS NULL THEN NULL
            ELSE FLOOR(CAST(assigned_userid AS numeric))::bigint
        END                                                             AS icalps_assigned_user_id,

        -- NEW: owner email — was in Bronze CSV but not captured in first Silver run
        NULLIF(LOWER(TRIM(COALESCE(assigned_useremail, ''))), '')      AS icalps_assigned_user_email,

        -- Convenience: owner name for lineage diagnostics
        NULLIF(TRIM(CONCAT_WS(' ',
            NULLIF(TRIM(assigned_userfirstname), ''),
            NULLIF(TRIM(assigned_userlastname), '')
        )), '')                                                         AS icalps_assigned_user_name,

        -- ── FK: Company ───────────────────────────────────────────────────────
        -- direct field
        CASE
            WHEN NULLIF(TRIM(CAST(case_primarycompanyid AS text)), '') IS NULL THEN NULL
            ELSE FLOOR(CAST(case_primarycompanyid AS numeric))::bigint
        END                                                             AS icalps_company_id,

        -- FIX: strip trailing whitespace (1 row: 'Neurallys ' vs 'Neurallys')
        NULLIF(TRIM(COALESCE(company_name, '')), '')                   AS icalps_company_name,
        NULLIF(TRIM(COALESCE(company_website, '')), '')                AS icalps_company_website,

        -- ── FK: Contact ───────────────────────────────────────────────────────
        -- FIX: was producing '4686.0' string-float; nullable integer cast
        CASE
            WHEN NULLIF(TRIM(CAST(case_primarypersonid AS text)), '') IS NULL THEN NULL
            WHEN TRIM(CAST(case_primarypersonid AS text)) = 'nan'     THEN NULL
            ELSE FLOOR(CAST(REPLACE(CAST(case_primarypersonid AS text), '.0', '') AS numeric))::bigint
        END                                                             AS icalps_contact_id,

        -- FIX: 'nan' string from missing JOIN → proper NULL
        NULLIF(TRIM(COALESCE(person_firstname, '')), '')               AS icalps_contact_firstname,
        NULLIF(TRIM(COALESCE(person_lastname, '')), '')                AS icalps_contact_lastname,
        NULLIF(LOWER(TRIM(COALESCE(person_emailaddress, ''))), '')     AS icalps_contact_email,

        -- ── Provenance metadata ───────────────────────────────────────────────
        'IC''ALPS Legacy CRM'::text                                    AS source,
        'silver'::text                                                 AS data_layer,
        'legacy_only'::text                                            AS reconciliation_status

    FROM staging.stg_cases
    WHERE icalps_ticket_id IS NOT NULL  -- guard: no orphan rows
),

-- Dedup within Bronze: keep the row with the most non-null metadata per ticket
-- (prefer_record_with_most_metadata pattern — same as company/contact/opportunity)
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY icalps_ticket_id
            ORDER BY (
                (CASE WHEN icalps_case_stage         IS NOT NULL THEN 1 ELSE 0 END) +
                (CASE WHEN icalps_assigned_user_email IS NOT NULL THEN 1 ELSE 0 END) +
                (CASE WHEN icalps_contact_id         IS NOT NULL THEN 1 ELSE 0 END) +
                (CASE WHEN icalps_contact_email      IS NOT NULL THEN 1 ELSE 0 END) +
                (CASE WHEN createdate               IS NOT NULL THEN 1 ELSE 0 END) +
                (CASE WHEN icalps_company_id         IS NOT NULL THEN 1 ELSE 0 END)
            ) DESC,
            icalps_ticket_id ASC          -- tie-break: lower ID wins
        ) AS _rank
    FROM bronze_source
)

SELECT
    icalps_ticket_id,
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
    icalps_assigned_user_email,    -- NEW column — owner lineage
    icalps_assigned_user_name,     -- NEW column — owner lineage display
    icalps_company_id,
    icalps_company_name,
    icalps_company_website,
    icalps_contact_id,
    icalps_contact_firstname,
    icalps_contact_lastname,
    icalps_contact_email,
    source,
    data_layer,
    reconciliation_status
FROM ranked
WHERE _rank = 1;
