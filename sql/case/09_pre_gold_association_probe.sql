-- =============================================================================
-- Case / Ticket — Pre-Gold Association Probe
--
-- Run this AFTER REFRESH MATERIALIZED VIEW staging.stg_case_v2
-- and BEFORE any INSERT into hubspot.tickets or hubspot.associations_tickets_*.
--
-- Purpose:
--   1. Confirm stg_case_v2 match rate against existing staging.stg_case (Silver baseline).
--      Gate: must be >= 95% (≥56/58 rows) before Gold upsert is approved.
--   2. Confirm FK resolution rate against live Gold tables (hubspot.companies, hubspot.contacts).
--      A ticket with an unresolvable company FK cannot be associated after upsert.
--   3. Confirm owner email coverage — required for hubspot_owner_id resolution.
--   4. Report association readiness per target (company / contact / deal).
--      Mirrors the probe pattern from communication_association.txt Q6.
--
-- All queries are READ-ONLY. No writes to hubspot.* or staging.*.
-- =============================================================================

-- ─── 1. Silver match rate gate ───────────────────────────────────────────────
-- Baseline: 43/58 (74.1%) from first Bronze run.
-- Target:   ≥56/58 (≥95%) before promotion.

WITH row_verdict AS (
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
            l.icalps_contact_email     IS NOT DISTINCT FROM v.icalps_contact_email
        THEN 1 ELSE 0 END AS exact_match
    FROM staging.stg_case    AS l
    INNER JOIN staging.stg_case_v2 AS v USING (icalps_ticket_id)
)
SELECT
    'silver_match_rate'                                               AS probe,
    SUM(exact_match)                                                  AS exact_matches,
    COUNT(*)                                                          AS total_rows,
    ROUND(SUM(exact_match)::numeric / COUNT(*) * 100, 1)             AS match_pct,
    43                                                                AS baseline_matches,
    ROUND(43.0 / COUNT(*) * 100, 1)                                  AS baseline_pct,
    SUM(exact_match) - 43                                            AS improvement_delta,
    CASE WHEN SUM(exact_match)::numeric / COUNT(*) >= 0.95
         THEN 'PASS — Gold upsert gate open'
         ELSE 'BLOCK — below 95% threshold, do not proceed to Gold'
    END                                                               AS gate_verdict
FROM row_verdict;

-- ─── 2. Owner email coverage ─────────────────────────────────────────────────
-- An owner ID is needed for hubspot.tickets.hubspot_owner_id.
-- Email-based resolution is exact. Name-based fallback is fuzzy — flag those rows.

SELECT
    'owner_resolution_readiness'                                      AS probe,
    COUNT(*)                                                          AS total_rows,
    COUNT(icalps_assigned_user_email)                                 AS rows_with_email,
    COUNT(*) - COUNT(icalps_assigned_user_email)                     AS rows_email_missing,
    COUNT(icalps_assigned_user_name)                                  AS rows_with_name_fallback,
    ROUND(COUNT(icalps_assigned_user_email)::numeric / COUNT(*) * 100, 1) AS email_coverage_pct,
    CASE WHEN COUNT(icalps_assigned_user_email) = COUNT(icalps_assigned_user_id)
         THEN 'PASS — all assigned rows have email'
         ELSE 'WARN — some rows will fall back to name-based owner resolution'
    END                                                               AS owner_verdict
FROM staging.stg_case_v2
WHERE icalps_assigned_user_id IS NOT NULL;

-- ─── 3. FK resolution rate — Company ─────────────────────────────────────────
-- Tickets with unresolvable company FK will create orphan records in HubSpot.

SELECT
    'ticket_company_fk_resolution'                                    AS probe,
    COUNT(*)                                                          AS tickets_with_company_fk,
    SUM(CASE WHEN h.id IS NOT NULL THEN 1 ELSE 0 END)                AS fk_resolved,
    SUM(CASE WHEN h.id IS NULL THEN 1 ELSE 0 END)                    AS fk_unresolved,
    ROUND(SUM(CASE WHEN h.id IS NOT NULL THEN 1 ELSE 0 END)::numeric
          / NULLIF(COUNT(*), 0) * 100, 1)                             AS resolution_pct,
    SUM(CASE WHEN h.stacksync_record_id_9vpp8v IS NOT NULL THEN 1 ELSE 0 END) AS uuid_ready_count,
    ROUND(SUM(CASE WHEN h.stacksync_record_id_9vpp8v IS NOT NULL THEN 1 ELSE 0 END)::numeric
          / NULLIF(COUNT(*), 0) * 100, 1)                             AS uuid_ready_pct
FROM staging.stg_case_v2 v
LEFT JOIN hubspot.companies h ON v.icalps_company_id::text = h.icalps_company_id::text
WHERE v.icalps_company_id IS NOT NULL;

-- ─── 4. FK resolution rate — Contact ─────────────────────────────────────────

SELECT
    'ticket_contact_fk_resolution'                                    AS probe,
    COUNT(*)                                                          AS tickets_with_contact_fk,
    SUM(CASE WHEN h.id IS NOT NULL THEN 1 ELSE 0 END)                AS fk_resolved,
    SUM(CASE WHEN h.id IS NULL THEN 1 ELSE 0 END)                    AS fk_unresolved,
    ROUND(SUM(CASE WHEN h.id IS NOT NULL THEN 1 ELSE 0 END)::numeric
          / NULLIF(COUNT(*), 0) * 100, 1)                             AS resolution_pct,
    SUM(CASE WHEN h.stacksync_record_id_nd85zc IS NOT NULL THEN 1 ELSE 0 END) AS uuid_ready_count,
    ROUND(SUM(CASE WHEN h.stacksync_record_id_nd85zc IS NOT NULL THEN 1 ELSE 0 END)::numeric
          / NULLIF(COUNT(*), 0) * 100, 1)                             AS uuid_ready_pct
FROM staging.stg_case_v2 v
LEFT JOIN hubspot.contacts h ON v.icalps_contact_id::text = h.icalps_contact_id::text
WHERE v.icalps_contact_id IS NOT NULL;

-- ─── 5. Stage mapping coverage ───────────────────────────────────────────────
-- hs_pipeline_stage NULL means the stage value has no mapping.
-- These rows will have NULL stage in HubSpot — operator must confirm before push.

SELECT
    'stage_mapping_coverage'                                          AS probe,
    COUNT(*)                                                          AS total_rows,
    COUNT(hs_pipeline_stage)                                          AS rows_stage_mapped,
    COUNT(*) - COUNT(hs_pipeline_stage)                              AS rows_stage_null,
    ROUND(COUNT(hs_pipeline_stage)::numeric / COUNT(*) * 100, 1)    AS mapping_coverage_pct,
    CASE WHEN COUNT(*) - COUNT(hs_pipeline_stage) = 0
         THEN 'PASS — all rows have a stage mapping'
         ELSE 'WARN — ' || (COUNT(*) - COUNT(hs_pipeline_stage))::text
              || ' rows have NULL hs_pipeline_stage (source stage was empty or unmapped)'
    END                                                               AS stage_verdict
FROM staging.stg_case_v2;

-- ─── 6. Summary gate — all conditions for Gold upsert approval ───────────────
-- This is the single decision row the operator reads before passing --approve-gold.

WITH
match AS (
    SELECT SUM(CASE WHEN l.subject IS NOT DISTINCT FROM v.subject
                    AND l.hs_pipeline_stage IS NOT DISTINCT FROM v.hs_pipeline_stage
                    AND l.icalps_case_stage IS NOT DISTINCT FROM v.icalps_case_stage
                    AND l.icalps_company_id IS NOT DISTINCT FROM v.icalps_company_id
                    AND l.icalps_contact_id IS NOT DISTINCT FROM v.icalps_contact_id
               THEN 1 ELSE 0 END)::numeric / COUNT(*) AS rate
    FROM staging.stg_case l
    INNER JOIN staging.stg_case_v2 v USING (icalps_ticket_id)
),
comp_fk AS (
    SELECT SUM(CASE WHEN h.id IS NOT NULL THEN 1 ELSE 0 END)::numeric / NULLIF(COUNT(*), 0) AS rate
    FROM staging.stg_case_v2 v
    LEFT JOIN hubspot.companies h ON v.icalps_company_id::text = h.icalps_company_id::text
    WHERE v.icalps_company_id IS NOT NULL
),
stage_cov AS (
    SELECT COUNT(hs_pipeline_stage)::numeric / COUNT(*) AS rate
    FROM staging.stg_case_v2
)
SELECT
    CASE WHEN match.rate >= 0.95 THEN '✓' ELSE '✗' END || ' Silver match rate: ' || ROUND(match.rate * 100, 1) || '%  (gate: ≥95%)' AS check_1_silver_gate,
    CASE WHEN comp_fk.rate >= 0.90 THEN '✓' ELSE '✗' END || ' Company FK resolution: ' || ROUND(comp_fk.rate * 100, 1) || '%  (gate: ≥90%)' AS check_2_company_fk,
    CASE WHEN stage_cov.rate >= 0.75 THEN '✓' ELSE '✗' END || ' Stage mapping coverage: ' || ROUND(stage_cov.rate * 100, 1) || '%  (gate: ≥75%)' AS check_3_stage_coverage,
    CASE WHEN match.rate >= 0.95 AND comp_fk.rate >= 0.90 AND stage_cov.rate >= 0.75
         THEN 'ALL GATES PASS — safe to run 06_gold_upsert.sql with --approve-gold'
         ELSE 'ONE OR MORE GATES FAIL — do not proceed to Gold upsert'
    END AS final_verdict
FROM match, comp_fk, stage_cov;
