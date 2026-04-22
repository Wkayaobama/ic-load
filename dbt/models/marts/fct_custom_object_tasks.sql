-- Custom Object Tasks Fact Table
-- Source: stg_custom_object_tasks (loaded from silver.custom_object_tasks via load_custom_object_tasks.py)
--
-- WHY THIS IS SEPARATE FROM fct_communication_tasks:
--   fct_communication_tasks (~145 rows) sources from int_communication_reconciled
--   where Comm_Action = 'ToDo'. These are standard IC'ALPS task records.
--
--   This model sources the full custom object export (~6,654 tasks + ~1,918 notes + ~40 appts)
--   via a separate Silver table. The two pipelines write to different unique_id prefixes:
--     standard : icalps_{communication_id}
--     custom   : icalps_co_{communication_id}
--
-- Associations use icalps_company_id / icalps_contact_id FKs (not StackSync UUIDs)
-- because the custom object export does not carry StackSync UUIDs.
-- create_associations.py uses Pass B (legacy ID fallback) for these records.
--
-- Benchmark:
--   task_count       >= 6,000
--   note_count       >= 1,800
--   appointment_count >= 30
--   owner_null_pct   <= 10%
{{ config(materialized='table', schema='staging') }}

with base as (
    select
        icalps_communication_id,
        engagement_type,
        hs_task_subject,
        hs_task_body,
        hs_task_status,
        hs_task_priority,
        hs_task_due_date,
        hubspot_owner_id,
        icalps_company_id,
        icalps_contact_id,
        icalps_deal_id,
        _source,
        _loaded_at

    from {{ ref('stg_custom_object_tasks') }}
),

-- Enrich with HubSpot entity IDs for StackSync association building
with_company as (
    select
        b.*,
        c.id                             as hubspot_company_id,
        c.stacksync_record_id_9vpp8v     as associated_company_id,
        c.name                           as hubspot_company_name

    from base b
    left join {{ source('hubspot', 'companies') }} c
        on b.icalps_company_id::text = c.icalps_company_id::text
),

with_contact as (
    select
        w.*,
        ct.id                            as hubspot_contact_id,
        ct.stacksync_record_id_nd85zc    as associated_contact_id,
        ct.firstname || ' ' || ct.lastname as hubspot_contact_name

    from with_company w
    left join {{ source('hubspot', 'contacts') }} ct
        on w.icalps_contact_id::text = ct.icalps_contact_id::text
)

select
    icalps_communication_id,
    engagement_type,

    -- HubSpot engagement fields
    hs_task_subject,
    hs_task_body,
    hs_task_status,
    hs_task_priority,
    hs_task_due_date                   as hs_timestamp,      -- due date (Comm_ToDateTime)
    hubspot_owner_id,

    -- Resolved HubSpot entity IDs (for StackSync association bridge)
    associated_company_id,
    associated_contact_id,
    null::bigint                        as associated_deal_id,   -- deal FK not in custom object export

    -- Legacy IDs (Pass B fallback in create_associations.py)
    icalps_company_id                  as legacy_company_id,
    icalps_contact_id                  as legacy_contact_id,
    icalps_deal_id                     as legacy_deal_id,

    -- Resolved entity context
    hubspot_company_name,
    hubspot_contact_name,

    -- Reconciliation flags
    (associated_company_id is not null) as has_company_match,
    (associated_contact_id is not null) as has_contact_match,

    -- Source metadata
    _source,
    _loaded_at,
    current_timestamp                  as dbt_loaded_at

from with_contact
