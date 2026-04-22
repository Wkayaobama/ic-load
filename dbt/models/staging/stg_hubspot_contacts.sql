-- Staging model for HubSpot contacts (Gold layer)
-- CRITICAL: icalps_contact_id is VARCHAR in HubSpot - must CAST + regex guard

select
    id as hubspot_contact_id,
    cast(icalps_contact_id as integer) as legacy_contact_id,
    stacksync_record_id_nd85zc as hubspot_contact_record_id,
    firstname as contact_firstname,
    lastname as contact_lastname,
    email as contact_email,
    concat(coalesce(firstname, ''), ' ', coalesce(lastname, '')) as contact_fullname
from {{ source('hubspot', 'contacts') }}
where id is not null
  and icalps_contact_id is not null
  and icalps_contact_id ~ '^\d+$'
