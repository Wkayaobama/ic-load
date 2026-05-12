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

CREATE OR REPLACE VIEW {schema}.fct_cleanup_companies AS
SELECT id::text                AS hubspot_id,
       icalps_company_id::text AS legacy_id,
       name                    AS label
FROM hubspot.companies
WHERE icalps_company_id IS NOT NULL
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
WHERE icalps_contact_id IS NOT NULL
  AND icalps_contact_id <> '';

CREATE OR REPLACE VIEW {schema}.fct_cleanup_deals AS
SELECT id::text             AS hubspot_id,
       icalps_deal_id::text AS legacy_id,
       dealname             AS label
FROM hubspot.deals
WHERE icalps_deal_id IS NOT NULL
  AND icalps_deal_id <> '';
