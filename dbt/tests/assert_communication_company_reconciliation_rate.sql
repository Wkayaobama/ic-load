-- =============================================================================
-- Test: assert_communication_company_reconciliation_rate
-- =============================================================================
-- Fails if fewer than 70% of communications with a Company_Id FK have a
-- confirmed HubSpot company match (has_company_match = true).
--
-- Pre-Phase-2 baseline was ~60% (child companies missing from Gold).
-- Post-Phase-2 + StackSync mirror, the threshold MUST reach ≥70%.
-- Raise to 90% once child-company StackSync sync is confirmed complete.
--
-- A non-empty result = test FAIL. dbt treats rows returned = failures.
-- =============================================================================

with reconciliation as (

    select
        count(*)                                                          as total_with_company_fk,
        count(*) filter (where has_company_match)                        as matched,
        round(
            100.0 * count(*) filter (where has_company_match)
            / nullif(count(*), 0),
            1
        )                                                                 as match_rate_pct

    from {{ ref('int_communication_reconciled') }}
    where legacy_company_id is not null

),

violation as (

    select
        total_with_company_fk,
        matched,
        match_rate_pct,
        70.0 as threshold_pct,
        'company_reconciliation_below_threshold' as check_name
    from reconciliation
    where match_rate_pct < 70.0

)

select * from violation
