-- fn_map_company_type — French company type → English.
--
-- Translated from silver_normalise.py::COMPANY_TYPE_MAP.
--
-- Called by: stg_company (comp_type → hubspot company_type, also
-- feeds fn_map_lifecycle_stage for lifecyclestage derivation).
-- Idempotent.
-- See IC_Load_Production_Plan.md §4.1.

CREATE OR REPLACE FUNCTION staging.fn_map_company_type(raw text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN raw IS NULL THEN NULL
        WHEN trim(raw) = 'Client'      THEN 'Customer'
        WHEN trim(raw) = 'Fournisseur' THEN 'Supplier'
        WHEN trim(raw) = 'Partenaire'  THEN 'Agent'
        ELSE raw
    END
$$;

COMMENT ON FUNCTION staging.fn_map_company_type(text) IS
'French IC''ALPS company type → English. Pass-through for unmapped.';
