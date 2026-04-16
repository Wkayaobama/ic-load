-- fn_map_contact_status — French contact status → English.
--
-- Translated from silver_normalise.py::CONTACT_STATUS_MAP.
--
-- Called by: stg_contact (pers_status → hubspot contact_status).
-- Idempotent.
-- See IC_Load_Production_Plan.md §4.1.

CREATE OR REPLACE FUNCTION staging.fn_map_contact_status(raw text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN raw IS NULL THEN NULL
        WHEN trim(raw) = 'Actif'             THEN 'Active'
        WHEN trim(raw) = 'Inactif'           THEN 'Inactive'
        WHEN trim(raw) = 'Parti'             THEN 'Left'
        WHEN trim(raw) = E'Retrait\u00E9'    THEN 'Retired'  -- Retraité
        ELSE raw
    END
$$;

COMMENT ON FUNCTION staging.fn_map_contact_status(text) IS
'French IC''ALPS contact status → English. Pass-through for unmapped.';
