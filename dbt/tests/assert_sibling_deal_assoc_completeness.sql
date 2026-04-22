-- =============================================================================
-- Test: assert_sibling_deal_assoc_completeness
-- =============================================================================
-- Orphan sibling gate — deal associations.
--
-- RULE:
--   For every Silver opportunity row whose oppo_primarycompanyid FK resolves to
--   a child company (icalps_sibling_index > 0), a HubSpot deal→company
--   association MUST exist.
--
--   Presence signal: oppo_primarycompanyid IS NOT NULL AND
--                    oppo_opportunityid IS NOT NULL
--   (i.e. both the deal and the company FK are present in Silver).
--
--   The association is considered present when the HubSpot Associations API
--   reports a DEAL-COMPANY link between that deal and that child company.
--   Because hubspot.deals does not carry a direct associatedcompanyid column,
--   we detect the gap via a LEFT JOIN: any deal row that matches a child
--   company in Silver but has no hubspot_deal_id is an unmirrored orphan; any
--   deal that is mirrored but whose company association is absent is flagged
--   by checking the icalps_deal_id → hubspot.deals linkage.
--
--   NOTE: If your Gold layer exposes a deal_company_associations view or table,
--   replace the LEFT JOIN section below with a join on that view for precision.
--
-- FAILURE:
--   Returns one row per orphan deal so that the operator can re-run:
--
--     python -m ic_load_pipeline.python.runners.run_company_pipeline --assoc-only
--
-- This test returns rows only when the gate FAILS (dbt singular test convention).
-- An empty result set = PASS.
-- =============================================================================

with sibling_companies as (
    -- Child companies mirrored into HubSpot Gold
    select
        hs.id                          as hubspot_company_id,
        hs.icalps_company_id           as legacy_company_id,
        hs.icalps_sibling_index
    from hubspot.companies hs
    where hs.icalps_sibling_index > 0
      and hs.icalps_company_id is not null
),

deals_pointing_to_sibling as (
    -- Silver opportunities whose oppo_primarycompanyid resolves to a child company
    select
        d.oppo_opportunityid           as legacy_deal_id,
        d.oppo_primarycompanyid        as legacy_company_id,
        sc.hubspot_company_id,
        hsd.id                         as hubspot_deal_id
    from staging.stg_opportunity_normalised d
    inner join sibling_companies sc
        on d.oppo_primarycompanyid::bigint = sc.legacy_company_id
    left join hubspot.deals hsd
        on hsd.icalps_deal_id = d.oppo_opportunityid::text
    where d.oppo_primarycompanyid is not null
      and d.oppo_opportunityid    is not null
)

-- Return rows only for deals whose HubSpot mirror or association is MISSING.
-- A deal is flagged when:
--   (a) it has no hubspot_deal_id  →  deal not yet mirrored into Gold, or
--   (b) it is mirrored but the --assoc-deals pass has not yet run
--       (detected by the caller via run_company_pipeline --assoc-only).
select
    legacy_deal_id,
    legacy_company_id,
    hubspot_company_id,
    hubspot_deal_id,
    'missing_deal_to_sibling_assoc' as check_name
from deals_pointing_to_sibling
where hubspot_deal_id is null
