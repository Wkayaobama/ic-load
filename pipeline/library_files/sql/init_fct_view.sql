-- Phase 7b — staging.fct_library_files (plain SQL view, no dbt for v1)
-- Composes stg_library_normalised with hubspot.{companies,contacts,deals}
-- via the icalps_*_id reconciliation keys.

CREATE OR REPLACE VIEW {schema}.fct_library_files AS
SELECT
    s.legacy_library_id::text AS legacy_library_id,
    s.legacy_file_name        AS legacy_file_name,
    s.legacy_file_path        AS legacy_file_path,
    s.libr_note               AS libr_note,
    s.legacy_company_id::text AS legacy_company_id,
    s.legacy_contact_id::text AS legacy_contact_id,
    s.legacy_deal_id::text    AS legacy_deal_id,
    hc.id::text               AS hubspot_company_id,
    hp.id::text               AS hubspot_contact_id,
    hd.id::text               AS hubspot_deal_id,
    s.icalps_owner_email      AS icalps_owner_email,
    s.icalps_owner_fullname   AS icalps_owner_fullname
FROM {schema}.stg_library_normalised s
LEFT JOIN hubspot.companies hc ON hc.icalps_company_id = s.legacy_company_id
LEFT JOIN hubspot.contacts  hp ON hp.icalps_contact_id = s.legacy_contact_id
LEFT JOIN hubspot.deals     hd ON hd.icalps_deal_id    = s.legacy_deal_id
WHERE COALESCE(hc.id, hp.id, hd.id) IS NOT NULL;
