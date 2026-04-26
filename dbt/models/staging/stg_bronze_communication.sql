-- Clean and type-cast Bronze Communication data
-- Source: staging.stg_communication_normalised (Silver-normalised; HTML-stripped subject/note)
-- NOTE: macro calls (parse_timestamp, clean_html, clean_french_utf8) removed — Silver already applied them.
-- Silver quality gate: records with no Company_Id AND no Person_Id are excluded here (CRM-orphans).

select
    cast(comm_communicationid as bigint) as communication_id,
    coalesce(trim(comm_action), 'Unknown') as comm_action,
    cast(comm_datetime as timestamp) as activity_datetime,
    comm_note as activity_body,
    trim(comm_subject) as activity_subject,
    trim(comm_status) as activity_status,
    cast(person_id as bigint) as legacy_contact_id,
    cast(company_id as bigint) as legacy_company_id,
    cast(comm_opportunityid as bigint) as legacy_deal_id,
    cast(comm_caseid as bigint) as legacy_case_id,
    cast(comm_originaldatetime as timestamp) as original_datetime,
    cast(comm_originaltodatetime as timestamp) as original_to_datetime
from {{ source('staging', 'stg_communication_normalised') }}
where comm_communicationid is not null
  and (company_id is not null or person_id is not null)
