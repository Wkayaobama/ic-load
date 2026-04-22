-- =============================================================================
-- Test: assert_fct_calls_has_company_or_contact
-- =============================================================================
-- Fails if any Call record in fct_communication_calls has BOTH
-- associated_company_id AND associated_contact_id as NULL.
--
-- A call with no upstream CRM association cannot be linked to any HubSpot
-- record on sync, making it effectively orphaned. Every call MUST have at
-- least one resolved association ID.
-- =============================================================================

select
    icalps_communication_id,
    hs_call_title,
    legacy_company_id,
    legacy_contact_id,
    associated_company_id,
    associated_contact_id,
    reconciliation_status,
    'call_no_associations' as check_name

from {{ ref('fct_communication_calls') }}

where associated_company_id is null
  and associated_contact_id is null
