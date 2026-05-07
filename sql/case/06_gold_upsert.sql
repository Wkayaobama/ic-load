-- =============================================================================
-- Case / Ticket — Gold Upsert
-- Target:  hubspot.tickets
--
-- ⚠️  PRODUCTION GATE — DO NOT EXECUTE WITHOUT:
--   1. sql/case/03_assessment_probe.sql confirms match_rate >= 95% (≥56/58 rows)
--   2. sql/case/04_silver_validate.sql shows zero STOP failures
--   3. hs_pipeline_stage value for 'Investigating' confirmed from HubSpot portal 9201667
--      (currently mapped to '1' as placeholder — verify before pushing)
--   4. stacksync_record_id_* column name for hubspot.tickets confirmed from portal
--   5. Existing HubSpot tickets have been deleted by operator
--   6. User has passed --approve-gold to the runner CLI
--
-- This file is rendered to sql/rendered/upsert_case.sql by gold.py.
-- The runner will not execute it unless --approve-gold is set AND
-- the entity's live_push_ready flag has been promoted to true in context/cards/case.yaml.
--
-- Conflict key:  icalps_ticket_id  (maps to Case_CaseId from IC'ALPS)
-- Load filter:   _load_status IN ('NEW', 'MODIFIED')  [not yet implemented for case —
--                all 58 rows treated as NEW on first push]
-- Excluded from UPDATE SET:  createdate (set by HubSpot on first insert),
--                             stacksync_record_id_TBD (managed by StackSync, never overwrite)
--
-- Owner resolution:
--   icalps_assigned_user_email → GET /crm/v3/owners?email= → hubspot_owner_id
--   Fallback: icalps_assigned_user_name → name match against owner list
--   The owner ID column in hubspot.tickets is hubspot_owner_id (confirm column name from portal)
-- =============================================================================

INSERT INTO hubspot.tickets (
    icalps_ticket_id,           -- reconciliation key: Case_CaseId
    subject,                    -- Ticket name
    content,                    -- Ticket description (long-form, UTF-8 cleaned)
    hs_pipeline,                -- 'external'
    hs_pipeline_stage,          -- '2' Solved / '4' Confirmed / '1' Investigating (CONFIRM)
    hs_ticket_priority,         -- HIGH / MEDIUM / LOW
    createdate,                 -- epoch ms — set on first insert, EXCLUDED from UPDATE
    closed_date,                -- epoch ms
    icalps_case_status,         -- IC'ALPS status label (Closed / Open / etc.)
    icalps_case_stage,          -- IC'ALPS stage label (Solved / Confirmed / Investigating)
    icalps_case_priority,       -- IC'ALPS priority label (Normal / High / Low)
    icalps_assigned_user_id,    -- IC'ALPS integer user ID
    icalps_assigned_user_email, -- owner email for HubSpot owner resolution
    icalps_company_id,          -- FK → hubspot.companies.icalps_company_id
    icalps_contact_id           -- FK → hubspot.contacts.icalps_contact_id
)
SELECT
    v2.icalps_ticket_id,
    v2.subject,
    v2.content,
    v2.hs_pipeline,
    v2.hs_pipeline_stage,
    v2.hs_ticket_priority,
    v2.createdate,
    v2.closed_date,
    v2.icalps_case_status,
    v2.icalps_case_stage,
    v2.icalps_case_priority,
    v2.icalps_assigned_user_id,
    v2.icalps_assigned_user_email,
    v2.icalps_company_id,
    v2.icalps_contact_id
FROM staging.stg_case_v2 AS v2
-- All 58 rows are NEW on first push (no _load_status watermark yet for case)
-- Once StackSync mirrors tickets back, add:  WHERE v2._load_status IN ('NEW', 'MODIFIED')
ON CONFLICT (icalps_ticket_id) DO UPDATE
SET
    subject                    = EXCLUDED.subject,
    content                    = EXCLUDED.content,
    hs_pipeline                = EXCLUDED.hs_pipeline,
    hs_pipeline_stage          = EXCLUDED.hs_pipeline_stage,
    hs_ticket_priority         = EXCLUDED.hs_ticket_priority,
    -- createdate intentionally excluded: set by HubSpot on first insert, never overwritten
    closed_date                = EXCLUDED.closed_date,
    icalps_case_status         = EXCLUDED.icalps_case_status,
    icalps_case_stage          = EXCLUDED.icalps_case_stage,
    icalps_case_priority       = EXCLUDED.icalps_case_priority,
    icalps_assigned_user_id    = EXCLUDED.icalps_assigned_user_id,
    icalps_assigned_user_email = EXCLUDED.icalps_assigned_user_email,
    icalps_company_id          = EXCLUDED.icalps_company_id,
    icalps_contact_id          = EXCLUDED.icalps_contact_id;
    -- stacksync_record_id_TBD intentionally excluded: managed by StackSync after sync


-- ─── Post-upsert verification ────────────────────────────────────────────────
-- Run this SELECT after the INSERT to confirm row count and owner coverage:
SELECT
    COUNT(*)                                                  AS rows_upserted,
    COUNT(icalps_assigned_user_email)                         AS rows_with_owner_email,
    COUNT(icalps_company_id)                                  AS rows_with_company_fk,
    COUNT(icalps_contact_id)                                  AS rows_with_contact_fk,
    COUNT(hs_pipeline_stage)                                  AS rows_with_stage_mapped,
    COUNT(*) - COUNT(hs_pipeline_stage)                       AS rows_stage_null
FROM hubspot.tickets
WHERE icalps_ticket_id IS NOT NULL;
