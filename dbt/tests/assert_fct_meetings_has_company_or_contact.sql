-- =============================================================================
-- Test: assert_fct_meetings_has_company_or_contact
-- =============================================================================
-- Meetings are the largest activity type (59,038 records). A meeting with no
-- resolved company or contact association cannot be pinned to a HubSpot
-- record and will appear as an orphaned engagement.
-- =============================================================================

select
    icalps_communication_id,
    hs_meeting_title,
    legacy_company_id,
    legacy_contact_id,
    associated_company_id,
    associated_contact_id,
    reconciliation_status,
    'meeting_no_associations' as check_name

from {{ ref('fct_communication_meetings') }}

where associated_company_id is null
  and associated_contact_id is null
