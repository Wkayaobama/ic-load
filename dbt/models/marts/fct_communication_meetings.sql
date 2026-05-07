-- HubSpot Meetings schema
-- Source: Meeting activities from IC'ALPS (~59,038 records)
{{ config(materialized='table', schema='staging') }}

select
    communication_id as icalps_communication_id,

    -- HubSpot Meeting properties
    activity_subject as hs_meeting_title,
    activity_body as hs_meeting_body,
    activity_datetime as hs_meeting_start_time,
    original_to_datetime as hs_meeting_end_time,
    'SCHEDULED' as hs_meeting_outcome,
    'default' as hs_meeting_source,

    -- Duration calculation (if end time available)
    case
        when original_to_datetime is not null and activity_datetime is not null
        then extract(epoch from (original_to_datetime - activity_datetime)) / 60
        else null
    end as hs_meeting_duration_minutes,

    -- Associations (HubSpot Record IDs for StackSync)
    hubspot_company_record_id as associated_company_id,
    hubspot_contact_record_id as associated_contact_id,
    hubspot_deal_record_id as associated_deal_id,

    -- Legacy IDs for reference
    legacy_company_id,
    legacy_contact_id,
    legacy_deal_id,
    legacy_case_id,

    -- HubSpot resolved entities
    hubspot_company_name,
    hubspot_contact_name,
    hubspot_contact_email,
    hubspot_deal_name,

    -- Reconciliation metadata
    reconciliation_status,
    has_company_match,
    has_contact_match,
    has_deal_match,

    -- dbt metadata
    current_timestamp as dbt_loaded_at

from {{ ref('int_communication_reconciled') }}
where hubspot_activity_type = 'MEETING'
