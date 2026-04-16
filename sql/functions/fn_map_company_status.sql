-- fn_map_company_status — French company status → English.
--
-- Translated from silver_normalise.py::COMPANY_STATUS_MAP.
-- Pass-through (return unchanged) for unmapped values — HubSpot's property
-- is free-text, so unknown status values won't be rejected.
--
-- Called by: stg_company (comp_status → hubspot company_status).
-- Idempotent.
-- See IC_Load_Production_Plan.md §4.1.

CREATE OR REPLACE FUNCTION staging.fn_map_company_status(raw text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN raw IS NULL THEN NULL
        WHEN trim(raw) = 'Actif'   THEN 'Active'
        WHEN trim(raw) = 'Inactif' THEN 'Inactive'
        WHEN trim(raw) = E'Ferm\u00E9' THEN 'Closed'  -- Fermé
        ELSE raw
    END
$$;

COMMENT ON FUNCTION staging.fn_map_company_status(text) IS
'French IC''ALPS company status → English. Pass-through for unmapped.';
