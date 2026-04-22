-- Clean and type-cast Bronze Communication data
-- Source: staging.stg_communication_normalised (Silver-normalised; HTML-stripped subject/note)
-- NOTE: macro calls (parse_timestamp, clean_html, clean_french_utf8) removed — Silver already applied them.
-- Silver quality gate: records with no Company_Id AND no Person_Id are excluded here (CRM-orphans).

select
    cast("Comm_CommunicationId" as integer) as communication_id,
    coalesce(trim("Comm_Action"), 'Unknown') as comm_action,
    cast("Comm_DateTime" as timestamp) as activity_datetime,
    "Comm_Note" as activity_body,
    trim("Comm_Subject") as activity_subject,
    trim("Comm_Status") as activity_status,
    cast("Person_Id" as integer) as legacy_contact_id,
    cast("Company_Id" as integer) as legacy_company_id,
    cast("Comm_OpportunityId" as integer) as legacy_deal_id,
    cast("Comm_CaseId" as integer) as legacy_case_id,
    cast("Comm_OriginalDateTime" as timestamp) as original_datetime,
    cast("Comm_OriginalToDateTime" as timestamp) as original_to_datetime
from {{ source('staging', 'stg_communication_normalised') }}
where "Comm_CommunicationId" is not null
  and ("Company_Id" is not null or "Person_Id" is not null)
