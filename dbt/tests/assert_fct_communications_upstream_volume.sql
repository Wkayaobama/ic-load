-- =============================================================================
-- Test: assert_fct_communications_upstream_volume
-- =============================================================================
-- Verifies that the four mart tables together account for at least 95% of
-- the source records in int_communication_reconciled.
--
-- This catches silent row-drops caused by incorrect WHERE filters on
-- hubspot_activity_type in fct_communication_*.sql (e.g. a new Comm_Action
-- value that maps to 'NOTE' but doesn't appear in fct_communication_notes
-- because the classification is wrong).
--
-- Source total: derived at runtime from int_communication_reconciled.
-- Mart total:   UNION ALL of all four fact table IDs.
-- =============================================================================

with source_count as (

    select count(*) as n
    from {{ ref('int_communication_reconciled') }}

),

mart_count as (

    select count(*) as n from (

        select icalps_communication_id from {{ ref('fct_communication_calls') }}
        union all
        select icalps_communication_id from {{ ref('fct_communication_meetings') }}
        union all
        select icalps_communication_id from {{ ref('fct_communication_notes') }}
        union all
        select icalps_communication_id from {{ ref('fct_communication_tasks') }}

    ) all_marts

),

coverage as (

    select
        s.n                                           as source_total,
        m.n                                           as mart_total,
        round(100.0 * m.n / nullif(s.n, 0), 1)       as coverage_pct,
        95.0                                          as threshold_pct
    from source_count s
    cross join mart_count m

),

violation as (

    select
        source_total,
        mart_total,
        coverage_pct,
        threshold_pct,
        'mart_coverage_below_threshold' as check_name
    from coverage
    where coverage_pct < threshold_pct

)

select * from violation
