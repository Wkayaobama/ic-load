-- fn_map_lifecycle_stage — company type → HubSpot lifecyclestage.
--
-- HubSpot lifecyclestage is a picklist with fixed internal values
-- (lowercase strings). This function maps the English company type
-- (output of fn_map_company_type) to the corresponding lifecycle.
--
-- Unmapped types default to 'lead' — the lowest-commitment lifecycle
-- stage that doesn't imply a business relationship.
--
-- Called by: stg_company (icalps_companytype → hubspot_lifecyclestage).
-- Idempotent.
-- See IC_Load_Production_Plan.md §4.1.

CREATE OR REPLACE FUNCTION staging.fn_map_lifecycle_stage(company_type text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN company_type IS NULL THEN NULL
        -- English values (post fn_map_company_type)
        WHEN trim(company_type) = 'Customer'  THEN 'customer'
        WHEN trim(company_type) = 'Supplier'  THEN 'other'
        WHEN trim(company_type) = 'Agent'     THEN 'salesqualifiedlead'
        -- French originals (pre fn_map_company_type — defensive)
        WHEN trim(company_type) = 'Client'      THEN 'customer'
        WHEN trim(company_type) = 'Fournisseur' THEN 'other'
        WHEN trim(company_type) = 'Partenaire'  THEN 'salesqualifiedlead'
        ELSE 'lead'
    END
$$;

COMMENT ON FUNCTION staging.fn_map_lifecycle_stage(text) IS
'Company type → HubSpot lifecyclestage enum. Unmapped defaults to lead.';
