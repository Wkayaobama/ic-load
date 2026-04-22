-- =============================================================================
-- Test: assert_custom_task_owner_coverage
-- =============================================================================
-- Fails if more than 10% of custom object tasks have a NULL hubspot_owner_id.
--
-- Owner mapping uses the static 3-owner dict in owner_map.py, resolved from
-- created_by_email in the custom object CSV. A null rate above 10% indicates:
--   - The CSV has rows with email addresses not in OWNER_EMAIL_MAP (new owners)
--   - The created_by_email column was not present or populated in the export
--   - A CSV encoding issue stripped or mangled the email values
--
-- Resolution:
--   1. Run load_custom_object_tasks.py --phase 0 to inspect owner coverage via probe
--   2. If new owners are present, update OWNER_EMAIL_MAP in owner_map.py
--   3. Re-run the pipeline with --execute
-- =============================================================================

with owner_rates as (

    select
        count(*)                                                       as total_tasks,
        count(*) filter (where hubspot_owner_id is null)               as owner_null_count,
        count(*) filter (where hubspot_owner_id is not null)           as owner_resolved_count,
        round(
            100.0 * count(*) filter (where hubspot_owner_id is null)
            / nullif(count(*), 0),
        1) as owner_null_pct,
        10.0 as max_allowed_null_pct

    from {{ ref('fct_custom_object_tasks') }}
    where engagement_type = 'task'

),

violation as (

    select
        total_tasks,
        owner_null_count,
        owner_resolved_count,
        owner_null_pct,
        max_allowed_null_pct,
        'owner_null_rate_above_10pct' as check_name
    from owner_rates
    where owner_null_pct > max_allowed_null_pct

)

select * from violation
