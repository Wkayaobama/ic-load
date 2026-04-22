-- Clean and typecast Custom Object Task/Note/Appointment records
-- Source: silver.custom_object_tasks (loaded by load_custom_object_tasks.py)
--
-- NOTE: These records are NOT from stg_communication_normalised.
-- They originate from the name_communications HubSpot custom object export,
-- re-ingested through Silver with owner resolution and due-date correction.
--
-- DEVIATION FROM STANDARD:
--   fct_communication_tasks uses Comm_DateTime (activity 'from' time).
--   This model uses hs_timestamp = Communication_Due_Date (actual due date).
--   HubSpot task UI shows due date, not creation date.
--
-- Benchmark targets:
--   task        : ~6,654 rows (Task + Comm_From=empty/ToDo filter)
--   note        : ~1,918 rows (not-Suivi + Email/Task + Notes non-empty)
--   appointment : ~40 rows   (Appointment + Notes non-boilerplate + CommCompanyID present)
{{ config(materialized='table', schema='staging') }}

select
    icalps_communication_id,
    engagement_type,

    -- HubSpot task/note properties
    hs_task_subject,
    hs_task_body,
    hs_task_status,
    hs_task_priority,
    hs_timestamp                 as hs_task_due_date,    -- Comm_ToDateTime (due), not Comm_DateTime (created)

    -- Owner (resolved from created_by_email via 3-owner static map in owner_map.py)
    hubspot_owner_id::bigint     as hubspot_owner_id,

    -- FK references for association bridge
    icalps_company_id,
    icalps_contact_id,
    icalps_deal_id,

    -- Source metadata
    _source,
    _loaded_at

from {{ source('silver', 'custom_object_tasks') }}
where icalps_communication_id is not null
