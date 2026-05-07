-- =============================================================================
-- Test: assert_communication_at_least_one_association
-- =============================================================================
-- Fails if ANY record in int_communication_reconciled has reconciliation_status
-- = 'reconciled' but ALL three association FKs (company, contact, deal) are NULL.
--
-- A "reconciled" communication MUST resolve to at least one HubSpot object.
-- Records that pass the reconciled gate but carry no IDs cannot be synced to
-- HubSpot engagements and represent a data-quality hole.
-- =============================================================================

select
    communication_id,
    comm_action,
    legacy_company_id,
    legacy_contact_id,
    legacy_deal_id,
    reconciliation_status,
    'reconciled_but_no_associations' as check_name

from {{ ref('int_communication_reconciled') }}

where reconciliation_status = 'reconciled'
  and hubspot_company_record_id is null
  and hubspot_contact_record_id is null
  and hubspot_deal_record_id    is null
