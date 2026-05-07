-- HubSpot Notes schema
-- Source: EmailOut/EmailIn activities from IC'ALPS (~11,981 records)
{{ config(materialized='table', schema='staging') }}

select
    communication_id as icalps_communication_id,

    -- HubSpot Note properties
    activity_body as hs_note_body,
    activity_datetime as hs_timestamp,
    activity_subject as hs_note_subject,

    -- Email metadata (preserved for context)
    email_direction,
    comm_action as source_comm_action,

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
where hubspot_activity_type = 'NOTE'
