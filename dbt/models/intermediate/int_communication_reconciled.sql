-- Join with HubSpot IDs for reconciliation
-- Links legacy IC'ALPS IDs to HubSpot record IDs (stacksync_record_id_* format)
-- These resolved IDs enable StackSync to create associations when syncing engagements

select
    c.*,

    -- Company reconciliation
    comp.hubspot_company_id,
    comp.hubspot_company_record_id,
    comp.company_name as hubspot_company_name,

    -- Contact reconciliation
    cont.hubspot_contact_id,
    cont.hubspot_contact_record_id,
    cont.contact_fullname as hubspot_contact_name,
    cont.contact_email as hubspot_contact_email,

    -- Deal reconciliation
    deal.hubspot_deal_id,
    deal.hubspot_deal_record_id,
    deal.deal_name as hubspot_deal_name,

    -- Reconciliation status flags
    case
        when comp.hubspot_company_id is not null
          or cont.hubspot_contact_id is not null
          or deal.hubspot_deal_id is not null
        then 'reconciled'
        else 'unreconciled'
    end as reconciliation_status,

    case when comp.hubspot_company_id is not null then true else false end as has_company_match,
    case when cont.hubspot_contact_id is not null then true else false end as has_contact_match,
    case when deal.hubspot_deal_id is not null then true else false end as has_deal_match

from {{ ref('int_communication_classified') }} c

left join {{ ref('stg_hubspot_companies') }} comp
    on c.legacy_company_id = comp.legacy_company_id

left join {{ ref('stg_hubspot_contacts') }} cont
    on c.legacy_contact_id = cont.legacy_contact_id

left join {{ ref('stg_hubspot_deals') }} deal
    on c.legacy_deal_id = deal.legacy_deal_id
