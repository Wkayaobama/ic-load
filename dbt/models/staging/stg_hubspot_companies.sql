-- Staging model for HubSpot companies (Gold layer)
-- CRITICAL: icalps_company_id is VARCHAR in HubSpot - must CAST + regex guard

select
    id as hubspot_company_id,
    cast(icalps_company_id as integer) as legacy_company_id,
    stacksync_record_id_9vpp8v as hubspot_company_record_id,
    name as company_name,
    domain as company_domain,
    website as company_website
from {{ source('hubspot', 'companies') }}
where id is not null
  and icalps_company_id is not null
  and icalps_company_id ~ '^\d+$'
