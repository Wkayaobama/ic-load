-- Staging model for HubSpot deals (Gold layer)
-- CRITICAL: icalps_deal_id is VARCHAR in HubSpot - must CAST + regex guard

select
    id as hubspot_deal_id,
    cast(icalps_deal_id as integer) as legacy_deal_id,
    stacksync_record_id_87b7vd as hubspot_deal_record_id,
    dealname as deal_name
from {{ source('hubspot', 'deals') }}
where id is not null
  and icalps_deal_id is not null
  and icalps_deal_id ~ '^\d+$'
