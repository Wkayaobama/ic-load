-- =============================================================================
-- Case / Ticket — Assessment Probe
-- Compare staging.stg_case_v2 (new Silver) vs staging.stg_case (live Silver)
--
-- Run AFTER 02_stg_case_v2_materialize.sql
-- Returns:
--   • per-column mismatch counts and % — columns >5% flagged as high residual
--   • overall row match rate (target: >95%, i.e. ≥56/58)
--   • improvement delta vs baseline 43/58 (74.1%)
-- =============================================================================

-- ─── 1. Per-column mismatch report ───────────────────────────────────────────
WITH
live    AS (SELECT * FROM staging.stg_case),
v2      AS (SELECT * FROM staging.stg_case_v2),
joined  AS (
    SELECT
        l.icalps_ticket_id,
        -- subject
        CASE WHEN l.subject                  IS DISTINCT FROM v.subject                  THEN 1 ELSE 0 END AS mm_subject,
        -- hs_pipeline_stage
        CASE WHEN l.hs_pipeline_stage        IS DISTINCT FROM v.hs_pipeline_stage        THEN 1 ELSE 0 END AS mm_hs_pipeline_stage,
        -- hs_ticket_priority
        CASE WHEN l.hs_ticket_priority       IS DISTINCT FROM v.hs_ticket_priority       THEN 1 ELSE 0 END AS mm_hs_ticket_priority,
        -- createdate
        CASE WHEN l.createdate               IS DISTINCT FROM v.createdate               THEN 1 ELSE 0 END AS mm_createdate,
        -- closed_date
        CASE WHEN l.closed_date              IS DISTINCT FROM v.closed_date              THEN 1 ELSE 0 END AS mm_closed_date,
        -- icalps_case_status
        CASE WHEN l.icalps_case_status       IS DISTINCT FROM v.icalps_case_status       THEN 1 ELSE 0 END AS mm_icalps_case_status,
        -- icalps_case_stage
        CASE WHEN l.icalps_case_stage        IS DISTINCT FROM v.icalps_case_stage        THEN 1 ELSE 0 END AS mm_icalps_case_stage,
        -- icalps_assigned_user_id
        CASE WHEN l.icalps_assigned_user_id  IS DISTINCT FROM v.icalps_assigned_user_id  THEN 1 ELSE 0 END AS mm_icalps_assigned_user_id,
        -- icalps_company_id
        CASE WHEN l.icalps_company_id        IS DISTINCT FROM v.icalps_company_id        THEN 1 ELSE 0 END AS mm_icalps_company_id,
        -- icalps_company_name
        CASE WHEN l.icalps_company_name      IS DISTINCT FROM v.icalps_company_name      THEN 1 ELSE 0 END AS mm_icalps_company_name,
        -- icalps_contact_id
        CASE WHEN l.icalps_contact_id        IS DISTINCT FROM v.icalps_contact_id        THEN 1 ELSE 0 END AS mm_icalps_contact_id,
        -- icalps_contact_email
        CASE WHEN l.icalps_contact_email     IS DISTINCT FROM v.icalps_contact_email     THEN 1 ELSE 0 END AS mm_icalps_contact_email,
        -- icalps_contact_firstname
        CASE WHEN l.icalps_contact_firstname IS DISTINCT FROM v.icalps_contact_firstname THEN 1 ELSE 0 END AS mm_icalps_contact_firstname,
        -- icalps_contact_lastname
        CASE WHEN l.icalps_contact_lastname  IS DISTINCT FROM v.icalps_contact_lastname  THEN 1 ELSE 0 END AS mm_icalps_contact_lastname
    FROM live l
    INNER JOIN v2 v USING (icalps_ticket_id)
),
total AS (SELECT COUNT(*) AS n FROM joined)

SELECT
    col.column_name,
    col.mismatch_count,
    total.n                                                   AS total_rows,
    ROUND(col.mismatch_count::numeric / total.n * 100, 1)   AS mismatch_pct,
    CASE WHEN col.mismatch_count::numeric / total.n > 0.05
         THEN 'HIGH RESIDUAL — requires investigation'
         ELSE 'ok'
    END                                                       AS flag
FROM (
    SELECT 'subject'                  AS column_name, SUM(mm_subject)                  FROM joined UNION ALL
    SELECT 'hs_pipeline_stage',                       SUM(mm_hs_pipeline_stage)        FROM joined UNION ALL
    SELECT 'hs_ticket_priority',                      SUM(mm_hs_ticket_priority)       FROM joined UNION ALL
    SELECT 'createdate',                              SUM(mm_createdate)               FROM joined UNION ALL
    SELECT 'closed_date',                             SUM(mm_closed_date)              FROM joined UNION ALL
    SELECT 'icalps_case_status',                      SUM(mm_icalps_case_status)       FROM joined UNION ALL
    SELECT 'icalps_case_stage',                       SUM(mm_icalps_case_stage)        FROM joined UNION ALL
    SELECT 'icalps_assigned_user_id',                 SUM(mm_icalps_assigned_user_id)  FROM joined UNION ALL
    SELECT 'icalps_company_id',                       SUM(mm_icalps_company_id)        FROM joined UNION ALL
    SELECT 'icalps_company_name',                     SUM(mm_icalps_company_name)      FROM joined UNION ALL
    SELECT 'icalps_contact_id',                       SUM(mm_icalps_contact_id)        FROM joined UNION ALL
    SELECT 'icalps_contact_email',                    SUM(mm_icalps_contact_email)     FROM joined UNION ALL
    SELECT 'icalps_contact_firstname',                SUM(mm_icalps_contact_firstname) FROM joined UNION ALL
    SELECT 'icalps_contact_lastname',                 SUM(mm_icalps_contact_lastname)  FROM joined
) col(column_name, mismatch_count)
CROSS JOIN total
ORDER BY col.mismatch_count DESC;

-- ─── 2. Overall row match rate ────────────────────────────────────────────────
-- A row "matches" if ALL shared columns are identical between v2 and live stg_case
WITH
live    AS (SELECT * FROM staging.stg_case),
v2      AS (SELECT * FROM staging.stg_case_v2),
row_verdict AS (
    SELECT
        l.icalps_ticket_id,
        CASE WHEN
            l.subject                  IS NOT DISTINCT FROM v.subject                  AND
            l.hs_pipeline_stage        IS NOT DISTINCT FROM v.hs_pipeline_stage        AND
            l.hs_ticket_priority       IS NOT DISTINCT FROM v.hs_ticket_priority       AND
            l.createdate               IS NOT DISTINCT FROM v.createdate               AND
            l.closed_date              IS NOT DISTINCT FROM v.closed_date              AND
            l.icalps_case_status       IS NOT DISTINCT FROM v.icalps_case_status       AND
            l.icalps_case_stage        IS NOT DISTINCT FROM v.icalps_case_stage        AND
            l.icalps_assigned_user_id  IS NOT DISTINCT FROM v.icalps_assigned_user_id  AND
            l.icalps_company_id        IS NOT DISTINCT FROM v.icalps_company_id        AND
            l.icalps_company_name      IS NOT DISTINCT FROM v.icalps_company_name      AND
            l.icalps_contact_id        IS NOT DISTINCT FROM v.icalps_contact_id        AND
            l.icalps_contact_email     IS NOT DISTINCT FROM v.icalps_contact_email     AND
            l.icalps_contact_firstname IS NOT DISTINCT FROM v.icalps_contact_firstname AND
            l.icalps_contact_lastname  IS NOT DISTINCT FROM v.icalps_contact_lastname
        THEN 1 ELSE 0 END AS exact_match
    FROM live l
    INNER JOIN v2 v USING (icalps_ticket_id)
)
SELECT
    COUNT(*)                                                           AS total_rows,
    SUM(exact_match)                                                   AS exact_matches,
    COUNT(*) - SUM(exact_match)                                        AS mismatches,
    ROUND(SUM(exact_match)::numeric / COUNT(*) * 100, 1)              AS match_pct,
    43                                                                 AS baseline_matches,
    ROUND(43.0 / COUNT(*) * 100, 1)                                   AS baseline_pct,
    SUM(exact_match) - 43                                             AS improvement_delta,
    CASE WHEN SUM(exact_match)::numeric / COUNT(*) >= 0.95
         THEN 'PASS — promotion eligible (>=95%)'
         ELSE 'FAIL — below 95% threshold'
    END                                                                AS promotion_gate
FROM row_verdict;

-- ─── 3. Rows that still differ in v2 vs live ─────────────────────────────────
WITH
live    AS (SELECT * FROM staging.stg_case),
v2      AS (SELECT * FROM staging.stg_case_v2),
row_verdict AS (
    SELECT
        l.icalps_ticket_id,
        l.subject,
        CASE WHEN l.icalps_case_stage  IS DISTINCT FROM v.icalps_case_stage  THEN '['||COALESCE(l.icalps_case_stage,'NULL')||' vs '||COALESCE(v.icalps_case_stage,'NULL')||']' END AS stage_diff,
        CASE WHEN l.createdate         IS DISTINCT FROM v.createdate         THEN '['||COALESCE(l.createdate::text,'NULL')||' vs '||COALESCE(v.createdate::text,'NULL')||']' END AS createdate_diff,
        CASE WHEN l.hs_pipeline_stage  IS DISTINCT FROM v.hs_pipeline_stage  THEN '['||COALESCE(l.hs_pipeline_stage,'NULL')||' vs '||COALESCE(v.hs_pipeline_stage,'NULL')||']' END AS pipeline_stage_diff,
        CASE WHEN l.icalps_contact_id  IS DISTINCT FROM v.icalps_contact_id  THEN '['||COALESCE(l.icalps_contact_id::text,'NULL')||' vs '||COALESCE(v.icalps_contact_id::text,'NULL')||']' END AS contact_id_diff,
        CASE WHEN l.icalps_contact_email IS DISTINCT FROM v.icalps_contact_email THEN 'DIFFERS' END AS email_diff,
        CASE WHEN l.icalps_company_name IS DISTINCT FROM v.icalps_company_name THEN '['||COALESCE(l.icalps_company_name,'NULL')||' vs '||COALESCE(v.icalps_company_name,'NULL')||']' END AS company_name_diff
    FROM live l
    INNER JOIN v2 v USING (icalps_ticket_id)
)
SELECT * FROM row_verdict
WHERE  stage_diff IS NOT NULL
    OR createdate_diff IS NOT NULL
    OR pipeline_stage_diff IS NOT NULL
    OR contact_id_diff IS NOT NULL
    OR email_diff IS NOT NULL
    OR company_name_diff IS NOT NULL
ORDER BY icalps_ticket_id;
