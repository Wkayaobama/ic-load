-- =============================================================================
-- Test: assert_silver_company_reconciliation_gate
-- =============================================================================
-- Post-Phase-2 gate: company FK match rate must be ≥ 85%.
--
-- Pre-Phase-2 baseline: ~60% (child companies missing from hubspot.companies).
-- Post-Phase-2 + StackSync mirror: 293 child companies in Gold →
--   every legacy Company_Id FK that belongs to a child company can now resolve.
--   Expected rate: ≥ 85%.
--
-- Tighten to 92% after Phase 3a (contact enrichment via StackSync) completes:
--   the remaining gap is contacts whose company_id points to a parent company
--   that was never mirrored into hubspot.companies (edge-case orphan parents).
--
-- This test returns rows only when the gate FAILS (dbt singular test convention).
-- An empty result set = PASS.
-- =============================================================================

with rate as (
    select
        count(*) as total_with_company_fk,
        count(*) filter (where hubspot_company_id is not null) as matched,
        round(
            100.0 * count(*) filter (where hubspot_company_id is not null) / nullif(count(*), 0),
            1
        ) as match_pct
    from pg_hubspot.staging.communications_reconciliation
    where legacy_company_id is not null
)

select
    match_pct,
    total_with_company_fk,
    matched,
    85.0 as threshold_pct,
    'company_gate_below_85pct' as check_name
from rate
where match_pct < 85.0
   or match_pct is null   -- null = zero rows in source = pipeline data issue
