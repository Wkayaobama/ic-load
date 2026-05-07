-- ============================================================================
-- docs/diagnostic_queries.sql
-- Diagnostic SQL snippets for the IC_Load pipeline.
--
-- Usage with Database Client VS Code extension (cweijan.vscode-database-client2):
--   1. Open this file.
--   2. Right-click a query block → "Run on connection" → ic-load-staging.
--   3. Or highlight the query text + Cmd+Shift+E → "Run SQL".
--
-- Each section maps to a PipelineStage debugging procedure in
-- docs/TRACEABILITY.md §2. Replace {entity} placeholders with the
-- entity name before running.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- PG_FUNCTIONS_INSTALL — verify all installed pg functions
-- ----------------------------------------------------------------------------
SELECT routine_name, routine_type, external_language
FROM information_schema.routines
WHERE routine_schema = 'staging'
  AND routine_name LIKE 'fn_%'
ORDER BY routine_name;


-- ----------------------------------------------------------------------------
-- BRONZE_EXPORT — compare bronze → staging row count parity
-- (Run after bronze completes; expect match with log's `row_count` field.)
-- ----------------------------------------------------------------------------
-- company
SELECT 'company' AS entity, COUNT(*) AS staging_rows FROM staging.stg_company;
-- contact
SELECT 'contact' AS entity, COUNT(*) AS staging_rows FROM staging.stg_contact;
-- opportunity
SELECT 'opportunity' AS entity, COUNT(*) AS staging_rows FROM staging.stg_opportunity;
-- communication
SELECT 'communication' AS entity, COUNT(*) AS staging_rows FROM staging.stg_communication;
-- case
SELECT 'case' AS entity, COUNT(*) AS staging_rows FROM staging.stg_case;


-- ----------------------------------------------------------------------------
-- SILVER_NORMALISE — verify normalisation produced the expected normalised rows
-- ----------------------------------------------------------------------------
SELECT
    'company' AS entity,
    (SELECT COUNT(*) FROM staging.stg_company) AS bronze_rows,
    (SELECT COUNT(*) FROM staging.stg_company_normalised) AS normalised_rows,
    (SELECT COUNT(*) FROM staging.stg_company)
      - (SELECT COUNT(*) FROM staging.stg_company_normalised) AS delta;


-- ----------------------------------------------------------------------------
-- SILVER_VALIDATE — reconciliation coverage per entity
-- (Matches ValidationRules/icalps_crm_schema.yaml reconciliation checks.)
-- ----------------------------------------------------------------------------
-- company reconciliation
SELECT
    'company' AS entity,
    (SELECT COUNT(*) FROM staging.stg_company_normalised) AS staging_rows,
    (SELECT COUNT(*)
       FROM staging.stg_company_normalised stg
       JOIN hubspot.companies hs ON stg.comp_companyid = hs.icalps_company_id) AS matched,
    ROUND(100.0 * (SELECT COUNT(*)
       FROM staging.stg_company_normalised stg
       JOIN hubspot.companies hs ON stg.comp_companyid = hs.icalps_company_id)
       / NULLIF((SELECT COUNT(*) FROM staging.stg_company_normalised), 0), 2) AS match_pct;

-- contact reconciliation
SELECT
    'contact' AS entity,
    (SELECT COUNT(*) FROM staging.stg_contact_normalised) AS staging_rows,
    (SELECT COUNT(*)
       FROM staging.stg_contact_normalised stg
       JOIN hubspot.contacts hs ON stg.pers_personid = hs.icalps_contact_id) AS matched,
    ROUND(100.0 * (SELECT COUNT(*)
       FROM staging.stg_contact_normalised stg
       JOIN hubspot.contacts hs ON stg.pers_personid = hs.icalps_contact_id)
       / NULLIF((SELECT COUNT(*) FROM staging.stg_contact_normalised), 0), 2) AS match_pct;

-- opportunity reconciliation
SELECT
    'opportunity' AS entity,
    (SELECT COUNT(*) FROM staging.stg_opportunity_normalised) AS staging_rows,
    (SELECT COUNT(*)
       FROM staging.stg_opportunity_normalised stg
       JOIN hubspot.deals hs ON stg.oppo_opportunityid = hs.icalps_deal_id) AS matched,
    ROUND(100.0 * (SELECT COUNT(*)
       FROM staging.stg_opportunity_normalised stg
       JOIN hubspot.deals hs ON stg.oppo_opportunityid = hs.icalps_deal_id)
       / NULLIF((SELECT COUNT(*) FROM staging.stg_opportunity_normalised), 0), 2) AS match_pct;


-- ----------------------------------------------------------------------------
-- GOLD_UPSERT — #1 failure cause: duplicate reconciliation keys in silver
-- ----------------------------------------------------------------------------
-- company duplicates
SELECT comp_companyid, COUNT(*) AS duplicate_count
FROM staging.stg_company_normalised
GROUP BY comp_companyid
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 20;

-- contact duplicates
SELECT pers_personid, COUNT(*) AS duplicate_count
FROM staging.stg_contact_normalised
GROUP BY pers_personid
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 20;

-- opportunity duplicates
SELECT oppo_opportunityid, COUNT(*) AS duplicate_count
FROM staging.stg_opportunity_normalised
GROUP BY oppo_opportunityid
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 20;


-- ----------------------------------------------------------------------------
-- GOLD_UPSERT — NULL values in columns HubSpot requires
-- ----------------------------------------------------------------------------
-- company required fields
SELECT
    COUNT(*) FILTER (WHERE comp_companyid IS NULL) AS null_comp_companyid,
    COUNT(*) FILTER (WHERE comp_name IS NULL) AS null_comp_name,
    COUNT(*) AS total_rows
FROM staging.stg_company_normalised;


-- ----------------------------------------------------------------------------
-- STACKSYNC_SYNC — UUID coverage per entity
-- (Run after GOLD_UPSERT + brief wait. Low coverage expected immediately post-run.)
-- ----------------------------------------------------------------------------
SELECT
    entity,
    total_rows,
    with_stacksync_uuid,
    ROUND(100.0 * with_stacksync_uuid / NULLIF(total_rows, 0), 2) AS uuid_coverage_pct
FROM (
    SELECT 'company' AS entity,
           COUNT(*) AS total_rows,
           COUNT(stacksync_record_id_9vpp8v) AS with_stacksync_uuid
    FROM hubspot.companies
    UNION ALL
    SELECT 'contact',
           COUNT(*),
           COUNT(stacksync_record_id_nd85zc)
    FROM hubspot.contacts
    UNION ALL
    SELECT 'deal',
           COUNT(*),
           COUNT(stacksync_record_id)
    FROM hubspot.deals
) t
ORDER BY entity;


-- ----------------------------------------------------------------------------
-- ASSOC_VALIDATE — association row counts per bridge table
-- ----------------------------------------------------------------------------
SELECT
    table_name AS association_bridge,
    (xpath('/row/c/text()',
           query_to_xml(format('SELECT COUNT(*) AS c FROM %I.%I', table_schema, table_name),
                        false, false, '')))[1]::text::bigint AS row_count
FROM information_schema.tables
WHERE table_schema = 'hubspot'
  AND table_name LIKE 'associations_%'
ORDER BY table_name;


-- ----------------------------------------------------------------------------
-- POST_RUN_VERIFY — overall pipeline health snapshot
-- ----------------------------------------------------------------------------
SELECT
    'staging row counts' AS metric,
    (SELECT COUNT(*) FROM staging.stg_company) AS company,
    (SELECT COUNT(*) FROM staging.stg_contact) AS contact,
    (SELECT COUNT(*) FROM staging.stg_opportunity) AS opportunity,
    (SELECT COUNT(*) FROM staging.stg_communication) AS communication;

SELECT
    'hubspot row counts' AS metric,
    (SELECT COUNT(*) FROM hubspot.companies) AS company,
    (SELECT COUNT(*) FROM hubspot.contacts) AS contact,
    (SELECT COUNT(*) FROM hubspot.deals) AS opportunity;

SELECT
    'reconciliation match_pct' AS metric,
    ROUND(100.0 * (SELECT COUNT(*)
       FROM staging.stg_company_normalised stg
       JOIN hubspot.companies hs ON stg.comp_companyid = hs.icalps_company_id)
       / NULLIF((SELECT COUNT(*) FROM staging.stg_company_normalised), 0), 2) AS company_pct,
    ROUND(100.0 * (SELECT COUNT(*)
       FROM staging.stg_contact_normalised stg
       JOIN hubspot.contacts hs ON stg.pers_personid = hs.icalps_contact_id)
       / NULLIF((SELECT COUNT(*) FROM staging.stg_contact_normalised), 0), 2) AS contact_pct,
    ROUND(100.0 * (SELECT COUNT(*)
       FROM staging.stg_opportunity_normalised stg
       JOIN hubspot.deals hs ON stg.oppo_opportunityid = hs.icalps_deal_id)
       / NULLIF((SELECT COUNT(*) FROM staging.stg_opportunity_normalised), 0), 2) AS opportunity_pct;
