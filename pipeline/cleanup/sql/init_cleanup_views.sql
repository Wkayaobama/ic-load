-- Cleanup selection views (Phase B input sources).
--
-- These three views feed `pipeline.cleanup.runner snapshot --source-view ...`,
-- which copies their rows into staging.fct_cleanup_manifest. The view shape
-- (hubspot_id, legacy_id, label) is the exact contract enforced by
-- pipeline/cleanup/selection.py:plan_from_view -- three text columns, in that
-- order, no extras.
--
-- Predicate: "has an IC'ALPS reconciliation key." This selects 100% of
-- HubSpot records that carry an icalps_*_id. Operators sharpen the predicate
-- by editing this file (e.g. add a lastmodifieddate cutoff) before re-running
-- the bootstrap, or by passing --where to the snapshot command.
--
-- StackSync mirrors icalps_*_id as VARCHAR; use IS NOT NULL AND <> '' to
-- catch both NULL and empty string. The earlier project assumption that these
-- were BIGINT was wrong -- see pipeline/library_files/sql/init_fct_view.sql
-- for the discovery and the bigint->text cast fix.
--
-- Schema name is substituted by the Python loader against a strict allowlist
-- (regex ^[a-z_][a-z0-9_]*$).

-- `id IS NOT NULL` defensive filter: StackSync mirrors some IC'ALPS-tagged
-- rows with NULL hubspot.{type}.id (orphan stubs). Those cannot be archived
-- via REST (no id to send) so they must be excluded — otherwise the snapshot
-- step UPSERTs them into staging.fct_cleanup_manifest which has a NOT NULL
-- constraint on hubspot_id and crashes mid-batch. Verified against prod
-- postgres: 36 NULL-id calls + 10 NULL-id notes + 100 NULL-id companies +
-- 29 NULL-id contacts + 114 NULL-id deals get excluded by this guard.

CREATE OR REPLACE VIEW {schema}.fct_cleanup_companies AS
SELECT id::text                AS hubspot_id,
       icalps_company_id::text AS legacy_id,
       name                    AS label
FROM hubspot.companies
WHERE id IS NOT NULL
  AND icalps_company_id IS NOT NULL
  AND icalps_company_id <> '';

CREATE OR REPLACE VIEW {schema}.fct_cleanup_contacts AS
SELECT id::text                AS hubspot_id,
       icalps_contact_id::text AS legacy_id,
       CONCAT_WS(
           ' ',
           firstname,
           lastname,
           CASE WHEN email IS NOT NULL AND email <> ''
                THEN '(' || email || ')'
           END
       )                       AS label
FROM hubspot.contacts
WHERE id IS NOT NULL
  AND icalps_contact_id IS NOT NULL
  AND icalps_contact_id <> '';

CREATE OR REPLACE VIEW {schema}.fct_cleanup_deals AS
SELECT id::text             AS hubspot_id,
       icalps_deal_id::text AS legacy_id,
       dealname             AS label
FROM hubspot.deals
WHERE id IS NOT NULL
  AND icalps_deal_id IS NOT NULL
  AND icalps_deal_id <> '';

-- Per-engagement-type selection views (calls / notes / tasks).
--
-- Each filters to IC'ALPS-tagged engagements via unique_id LIKE 'icalps_%'
-- (StackSync convention for IC'ALPS-origin records) and gdpr_deleted IS NOT
-- TRUE. The notes view additionally strips HTML and requires a non-empty body
-- (86% of icalps-tagged notes have empty bodies — pure clutter).
--
-- Meetings deliberately omitted: 3,558 of 3,680 meetings have unique_id set,
-- but the format is Microsoft Outlook calendar GUIDs (AAMkADIz...,
-- AQMkADUx...), not 'icalps_*'. Meetings were ingested via Outlook calendar
-- sync, not from IC'ALPS. No legacy meeting record maps to a hubspot.meetings
-- row today. Adding a fct_cleanup_meetings view with the same filter would
-- return 0 rows; deferred until/unless an IC'ALPS-meeting reconciliation
-- exists.

CREATE OR REPLACE VIEW {schema}.fct_cleanup_calls AS
SELECT id::text AS hubspot_id,
       regexp_replace(unique_id::text, '^icalps_', '') AS legacy_id,
       COALESCE(NULLIF(TRIM(call_title), ''), '(untitled call)') AS label
FROM hubspot.calls
WHERE id IS NOT NULL
  AND unique_id LIKE 'icalps_%'
  AND gdpr_deleted IS NOT TRUE;

CREATE OR REPLACE VIEW {schema}.fct_cleanup_notes AS
SELECT id::text AS hubspot_id,
       regexp_replace(unique_id::text, '^icalps_', '') AS legacy_id,
       LEFT(regexp_replace(note_body::text, '<[^>]+>', '', 'g'), 80) AS label
FROM hubspot.notes
WHERE id IS NOT NULL
  AND unique_id LIKE 'icalps_%'
  AND gdpr_deleted IS NOT TRUE
  AND COALESCE(TRIM(regexp_replace(note_body::text, '<[^>]+>', '', 'g')), '') <> '';

CREATE OR REPLACE VIEW {schema}.fct_cleanup_tasks AS
SELECT id::text AS hubspot_id,
       regexp_replace(unique_id::text, '^icalps_', '') AS legacy_id,
       COALESCE(NULLIF(TRIM(task_title), ''), '(untitled task)') AS label
FROM hubspot.tasks
WHERE id IS NOT NULL
  AND unique_id LIKE 'icalps_%'
  AND gdpr_deleted IS NOT TRUE;
