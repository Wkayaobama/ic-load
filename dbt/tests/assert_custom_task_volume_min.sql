-- =============================================================================
-- Test: assert_custom_task_volume_min
-- =============================================================================
-- Fails if the custom object task pipeline produced fewer than 6,000 task rows.
--
-- WHY 6,000 (not 6,654):
--   The ~6,654 figure is the PQ benchmark against the FULL name_communications
--   export. The short verified subset (bronze-task-to-hubspot_short.csv) has 245
--   rows. Setting the gate at 6,000 leaves a 10% tolerance below the full target
--   so the test passes even on a partial run, while still catching a complete
--   pipeline failure (e.g. wrong CSV path, filter logic regression).
--
-- If running against the short subset only, override the threshold or skip this
-- test until the full export is in place.
-- =============================================================================

with task_count as (

    select
        count(*) as actual_count,
        6000      as minimum_count

    from {{ ref('fct_custom_object_tasks') }}
    where engagement_type = 'task'

),

violation as (

    select
        actual_count,
        minimum_count,
        minimum_count - actual_count as shortfall,
        'custom_task_volume_below_6000' as check_name
    from task_count
    where actual_count < minimum_count

)

select * from violation
