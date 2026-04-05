-- =============================================================================
-- Case / Ticket — Silver Validation
-- Source:  staging.stg_case_v2
--
-- Returns one row per check:
--   check_name | passed | severity | row_count_failing | notes
--
-- Run AFTER 02_stg_case_v2_materialize.sql
-- STOP failures must be zero before any Gold upsert is attempted.
-- WARN failures are logged but do not block Silver promotion.
-- =============================================================================

WITH

-- ── STOP: no duplicate icalps_ticket_id ──────────────────────────────────────
dup_pk AS (
    SELECT COUNT(*) AS failing
    FROM (
        SELECT icalps_ticket_id, COUNT(*) AS n
        FROM staging.stg_case_v2
        GROUP BY icalps_ticket_id
        HAVING COUNT(*) > 1
    ) dupes
),

-- ── STOP: no null icalps_ticket_id ───────────────────────────────────────────
null_pk AS (
    SELECT COUNT(*) AS failing
    FROM staging.stg_case_v2
    WHERE icalps_ticket_id IS NULL
),

-- ── WARN: icalps_case_stage only contains known values ───────────────────────
-- Known values confirmed from Bronze: Open, Closed, In Progress, Pending,
-- Escalated (IC'ALPS status), Solved, Confirmed, Investigating (IC'ALPS stage)
-- NULL is acceptable — 12 source rows have no stage.
bad_stage AS (
    SELECT COUNT(*) AS failing
    FROM staging.stg_case_v2
    WHERE icalps_case_stage IS NOT NULL
      AND icalps_case_stage NOT IN ('Solved', 'Confirmed', 'Investigating')
      -- extend this list once case_stage_mapper is implemented and portal stages confirmed
),

-- ── WARN: hs_pipeline_stage NULL where icalps_case_stage is not NULL ─────────
-- If stage is known, pipeline_stage must resolve. NULLs here mean the CASE map
-- is missing a value — indicates a new stage label in source not yet mapped.
unmapped_pipeline_stage AS (
    SELECT COUNT(*) AS failing
    FROM staging.stg_case_v2
    WHERE icalps_case_stage IS NOT NULL
      AND hs_pipeline_stage IS NULL
),

-- ── WARN: FK — icalps_company_id exists in hubspot.companies ─────────────────
fk_company AS (
    SELECT COUNT(*) AS failing
    FROM staging.stg_case_v2 c
    WHERE c.icalps_company_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM hubspot.companies h
          WHERE h.icalps_company_id = c.icalps_company_id
      )
),

-- ── WARN: FK — icalps_contact_id exists in hubspot.contacts ──────────────────
fk_contact AS (
    SELECT COUNT(*) AS failing
    FROM staging.stg_case_v2 c
    WHERE c.icalps_contact_id IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM hubspot.contacts h
          WHERE h.icalps_contact_id = c.icalps_contact_id
      )
),

-- ── WARN: createdate is bigint (epoch ms) or NULL — never a string/float ─────
-- After fix this should always be 0. Any non-zero means Bronze re-introduced
-- the string-float format.
bad_createdate AS (
    SELECT COUNT(*) AS failing
    FROM staging.stg_case_v2
    WHERE createdate IS NOT NULL
      AND createdate <= 0  -- epoch ms must be positive
),

-- ── WARN: owner email captured (coverage metric, not a hard requirement) ─────
no_owner_email AS (
    SELECT COUNT(*) AS failing
    FROM staging.stg_case_v2
    WHERE icalps_assigned_user_id IS NOT NULL   -- has an assignee
      AND icalps_assigned_user_email IS NULL    -- but email not captured
),

-- ── WARN: contact_email populated where contact_id is set ────────────────────
missing_contact_email AS (
    SELECT COUNT(*) AS failing
    FROM staging.stg_case_v2
    WHERE icalps_contact_id IS NOT NULL
      AND icalps_contact_email IS NULL
)

-- ── Final result set ─────────────────────────────────────────────────────────
SELECT 'no_duplicate_icalps_ticket_id'   AS check_name,
       (failing = 0)                      AS passed,
       'STOP'                             AS severity,
       failing                            AS row_count_failing,
       'Duplicate PK in stg_case_v2 must be zero before Gold upsert' AS notes
FROM dup_pk

UNION ALL
SELECT 'no_null_icalps_ticket_id',
       (failing = 0), 'STOP', failing,
       'NULL primary key rows cannot be upserted'
FROM null_pk

UNION ALL
SELECT 'icalps_case_stage_valid_values',
       (failing = 0), 'WARN', failing,
       'Stage values outside known set — extend CASE map in 01_silver_normalize.sql'
FROM bad_stage

UNION ALL
SELECT 'hs_pipeline_stage_resolves_from_stage',
       (failing = 0), 'WARN', failing,
       'Unmapped stage: icalps_case_stage present but hs_pipeline_stage is NULL — CONFIRM Investigating→1 from portal 9201667'
FROM unmapped_pipeline_stage

UNION ALL
SELECT 'fk_icalps_company_id_in_hubspot_companies',
       (failing = 0), 'WARN', failing,
       'Company FK violation — ticket references company not yet in hubspot.companies'
FROM fk_company

UNION ALL
SELECT 'fk_icalps_contact_id_in_hubspot_contacts',
       (failing = 0), 'WARN', failing,
       'Contact FK violation — ticket references contact not yet in hubspot.contacts'
FROM fk_contact

UNION ALL
SELECT 'createdate_serialization_consistent',
       (failing = 0), 'WARN', failing,
       'createdate must be positive bigint epoch ms or NULL — no string-float artefacts'
FROM bad_createdate

UNION ALL
SELECT 'owner_email_coverage',
       (failing = 0), 'WARN', failing,
       'Assigned rows missing icalps_assigned_user_email — owner HubSpot resolution will fall back to name match'
FROM no_owner_email

UNION ALL
SELECT 'contact_email_when_contact_id_set',
       (failing = 0), 'WARN', failing,
       'Contact email missing despite contact_id present — dedup scorer will lose email signal'
FROM missing_contact_email

ORDER BY severity DESC, passed ASC;
