-- =============================================================================
-- Test: assert_communication_contact_reconciliation_rate
-- =============================================================================
-- Fails if fewer than 60% of communications with a Person_Id FK have a
-- confirmed HubSpot contact match (has_contact_match = true).
--
-- IC'ALPS has 80 contacts in HubSpot (benchmark 2026-03-07) vs. a larger
-- legacy person base. Threshold set conservatively at 60%.
-- =============================================================================

with reconciliation as (

    select
        count(*)                                                          as total_with_contact_fk,
        count(*) filter (where has_contact_match)                        as matched,
        round(
            100.0 * count(*) filter (where has_contact_match)
            / nullif(count(*), 0),
            1
        )                                                                 as match_rate_pct

    from {{ ref('int_communication_reconciled') }}
    where legacy_contact_id is not null

),

violation as (

    select
        total_with_contact_fk,
        matched,
        match_rate_pct,
        60.0 as threshold_pct,
        'contact_reconciliation_below_threshold' as check_name
    from reconciliation
    where match_rate_pct < 60.0

)

select * from violation
