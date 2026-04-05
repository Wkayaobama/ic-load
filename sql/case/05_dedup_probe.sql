-- =============================================================================
-- Case / Ticket — Dedup Probe  (READ-ONLY, never blocks execution)
-- Source:  staging.stg_case_v2  (candidate frame)
-- Reference: hubspot benchmark export (IcAlps_TicketID column)
--
-- Thresholds (from context/cards/case.yaml):
--   review  ≥ 0.65  — flag for operator review, do not auto-block
--   block   ≥ 0.82  — auto-block (requires operator override to proceed)
--
-- Primary signal: subject (Levenshtein, weight 0.45)
-- Secondary:      icalps_company_id (exact, weight 0.20)
--                 icalps_contact_email (email, weight 0.15)
--                 icalps_case_stage (exact, weight 0.10)
--                 icalps_case_status (exact, weight 0.05)
--                 hs_ticket_priority (exact, weight 0.05)
--
-- PostgreSQL note: requires pg_trgm extension for similarity().
-- Pure Levenshtein requires levenshtein() from fuzzystrmatch extension.
-- Both are standard PostgreSQL contrib extensions.
-- =============================================================================

-- ─── 1. Intra-candidate duplicates (within stg_case_v2) ──────────────────────
-- Detect rows that share the same subject + company — these are structural
-- duplicates that the prefer_record_with_most_metadata dedup step should have
-- already eliminated. Any survivors here indicate a shaping bug.

SELECT
    'intra_duplicate_identity_signature' AS probe_type,
    a.icalps_ticket_id                   AS ticket_id_a,
    b.icalps_ticket_id                   AS ticket_id_b,
    a.subject                            AS subject_a,
    b.subject                            AS subject_b,
    a.icalps_company_id                  AS company_id_a,
    b.icalps_company_id                  AS company_id_b,
    NULL::float                          AS weighted_score,
    'BLOCK — same subject+company, different ticket IDs in stg_case_v2' AS decision
FROM staging.stg_case_v2 a
JOIN staging.stg_case_v2 b
    ON a.icalps_ticket_id < b.icalps_ticket_id   -- each pair once
    AND a.icalps_company_id IS NOT NULL
    AND a.icalps_company_id = b.icalps_company_id
    AND LOWER(TRIM(a.subject)) = LOWER(TRIM(b.subject))

UNION ALL

-- ─── 2. Cross-candidate Levenshtein similarity (review/block candidates) ──────
-- Compare every pair of tickets in the same company where subjects are similar.
-- Expected outcome for "Questionnaire de satisfaction" variants:
--   • score ≥ 0.65 → REVIEW (different companies, or slight subject variation)
--   • score ≥ 0.82 → BLOCK  (strong match + same company)
--
-- The composite weighted score formula:
--   score = (subject_sim * 0.45)
--         + (company_exact * 0.20)
--         + (email_exact   * 0.15)
--         + (stage_exact   * 0.10)
--         + (status_exact  * 0.05)
--         + (priority_exact* 0.05)

SELECT
    'cross_candidate_similarity'         AS probe_type,
    a.icalps_ticket_id                   AS ticket_id_a,
    b.icalps_ticket_id                   AS ticket_id_b,
    a.subject                            AS subject_a,
    b.subject                            AS subject_b,
    a.icalps_company_id                  AS company_id_a,
    b.icalps_company_id                  AS company_id_b,
    ROUND(weighted_score::numeric, 3)    AS weighted_score,
    CASE
        WHEN weighted_score >= 0.82 THEN 'BLOCK — auto-block, operator override required'
        WHEN weighted_score >= 0.65 THEN 'REVIEW — flag for operator, not auto-blocked'
        ELSE                             'SAFE'
    END                                  AS decision
FROM (
    SELECT
        a.icalps_ticket_id                           AS ticket_id_a,
        b.icalps_ticket_id                           AS ticket_id_b,
        a.subject                                    AS subject_a,
        b.subject                                    AS subject_b,
        a.icalps_company_id                          AS company_id_a,
        b.icalps_company_id                          AS company_id_b,
        -- subject Levenshtein similarity (weight 0.45)
        -- Uses similarity() from pg_trgm as a proxy.
        -- Replace with levenshtein()-based expression if fuzzystrmatch is available:
        --   1.0 - levenshtein(lower(a.subject), lower(b.subject))::float /
        --         NULLIF(greatest(length(a.subject), length(b.subject)), 0)
        similarity(lower(COALESCE(a.subject,'')), lower(COALESCE(b.subject,''))) * 0.45
        -- company exact match (weight 0.20)
        + CASE WHEN a.icalps_company_id IS NOT NULL
                AND a.icalps_company_id = b.icalps_company_id THEN 0.20 ELSE 0.0 END
        -- contact email exact match (weight 0.15)
        + CASE WHEN a.icalps_contact_email IS NOT NULL
                AND a.icalps_contact_email = b.icalps_contact_email THEN 0.15 ELSE 0.0 END
        -- stage exact match (weight 0.10)
        + CASE WHEN a.icalps_case_stage IS NOT NULL
                AND a.icalps_case_stage = b.icalps_case_stage THEN 0.10 ELSE 0.0 END
        -- status exact match (weight 0.05)
        + CASE WHEN a.icalps_case_status IS NOT NULL
                AND a.icalps_case_status = b.icalps_case_status THEN 0.05 ELSE 0.0 END
        -- priority exact match (weight 0.05)
        + CASE WHEN a.hs_ticket_priority IS NOT NULL
                AND a.hs_ticket_priority = b.hs_ticket_priority THEN 0.05 ELSE 0.0 END
        AS weighted_score
    FROM staging.stg_case_v2 a
    JOIN staging.stg_case_v2 b
        ON a.icalps_ticket_id < b.icalps_ticket_id
) scored
WHERE weighted_score >= 0.65   -- only surface review and block candidates
ORDER BY weighted_score DESC, ticket_id_a;

-- ─── 3. Summary counts ───────────────────────────────────────────────────────
-- Expected result for this dataset:
--   • Many REVIEW candidates (same subject variant, different companies → correct behavior)
--   • Zero BLOCK candidates (different company_ids → weighted_score capped at 0.45+0.10+0.05 = 0.60 < 0.82)
--   • Zero intra-duplicates (dedup in step 02 should have caught them)

WITH scored AS (
    SELECT
        similarity(lower(COALESCE(a.subject,'')), lower(COALESCE(b.subject,''))) * 0.45
        + CASE WHEN a.icalps_company_id IS NOT NULL AND a.icalps_company_id = b.icalps_company_id THEN 0.20 ELSE 0.0 END
        + CASE WHEN a.icalps_contact_email IS NOT NULL AND a.icalps_contact_email = b.icalps_contact_email THEN 0.15 ELSE 0.0 END
        + CASE WHEN a.icalps_case_stage IS NOT NULL AND a.icalps_case_stage = b.icalps_case_stage THEN 0.10 ELSE 0.0 END
        + CASE WHEN a.icalps_case_status IS NOT NULL AND a.icalps_case_status = b.icalps_case_status THEN 0.05 ELSE 0.0 END
        + CASE WHEN a.hs_ticket_priority IS NOT NULL AND a.hs_ticket_priority = b.hs_ticket_priority THEN 0.05 ELSE 0.0 END
        AS weighted_score
    FROM staging.stg_case_v2 a
    JOIN staging.stg_case_v2 b ON a.icalps_ticket_id < b.icalps_ticket_id
)
SELECT
    COUNT(*)                                              AS total_pairs_evaluated,
    SUM(CASE WHEN weighted_score >= 0.82 THEN 1 ELSE 0 END) AS block_candidates,
    SUM(CASE WHEN weighted_score >= 0.65
              AND weighted_score < 0.82 THEN 1 ELSE 0 END) AS review_candidates,
    SUM(CASE WHEN weighted_score < 0.65 THEN 1 ELSE 0 END)  AS safe_pairs,
    CASE WHEN SUM(CASE WHEN weighted_score >= 0.82 THEN 1 ELSE 0 END) = 0
         THEN 'PASS — no auto-block candidates'
         ELSE 'WARN — block candidates found, operator review required'
    END                                                   AS guardrail_verdict
FROM scored;
