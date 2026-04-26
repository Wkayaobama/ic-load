-- =============================================================================
-- Test: assert_sibling_contact_assoc_completeness
-- =============================================================================
-- Orphan sibling gate — contact associations.
--
-- RULE:
--   For every Silver contact row whose pers_companyid FK resolves to a child
--   company (icalps_sibling_index > 0), a HubSpot contact→company association
--   MUST exist.
--
--   Presence signal: pers_companyid IS NOT NULL AND pers_personid IS NOT NULL
--   (i.e. both the contact and the company FK are present in Silver).
--
--   The association is considered present when hubspot.contacts has
--   associatedcompanyid populated with the HubSpot company id of that child.
--
-- FAILURE:
--   Returns one row per orphan contact (pers_personid, child company id, etc.)
--   so that the operator can re-run:
--
--     python -m ic_load_pipeline.python.runners.run_company_pipeline --assoc-only
--
-- This test returns rows only when the gate FAILS (dbt singular test convention).
-- An empty result set = PASS.
-- =============================================================================

with sibling_companies as (
    -- Child companies that have been mirrored into HubSpot Gold
    select
        hs.id                          as hubspot_company_id,
        hs.icalps_company_id           as legacy_company_id,
        hs.icalps_sibling_index
    from pg_hubspot.hubspot.companies hs
    where hs.icalps_sibling_index > 0
      and hs.icalps_company_id is not null
),

contacts_pointing_to_sibling as (
    -- Silver contacts whose icalps_company_id resolves to a child company
    select
        c.icalps_contact_id            as legacy_contact_id,
        c.icalps_company_id            as legacy_company_id,
        sc.hubspot_company_id,
        hsc.id                         as hubspot_contact_id,
        hsc.associatedcompanyid        as associated_company_id
    from pg_hubspot.staging.stg_contact_normalised c
    inner join sibling_companies sc
        on c.icalps_company_id::bigint = sc.legacy_company_id
    left join pg_hubspot.hubspot.contacts hsc
        on hsc.icalps_contact_id = c.icalps_contact_id::text
    where c.icalps_company_id is not null
      and c.icalps_contact_id is not null
)

-- Return rows only for contacts whose HubSpot association is MISSING
select
    legacy_contact_id,
    legacy_company_id,
    hubspot_company_id,
    hubspot_contact_id,
    'missing_contact_to_sibling_assoc' as check_name
from contacts_pointing_to_sibling
where
    -- No HubSpot contact record at all (contact not yet mirrored)
    hubspot_contact_id is null
    -- Contact exists but its associatedcompanyid does not match the child company
    or associated_company_id is null
    or associated_company_id::bigint != hubspot_company_id
