-- fn_normalize_employee_range — IC'ALPS employee range → HubSpot enum.
--
-- HubSpot's `numberofemployees` property accepts specific string values
-- (numeric ranges). IC'ALPS stores the same information with whitespace
-- variations ('1-10', '1 - 10', '1- 10') and French locale variants
-- ('Plus de 10000'). Normalize to the canonical HubSpot strings.
--
-- Returns NULL for unmapped ranges — the operator sees the NULL in the
-- silver fact and can add the mapping if needed. Pass-through is unsafe
-- here because HubSpot rejects unknown enum values.
--
-- Called by: stg_company (comp_employees → numberofemployees).
-- Idempotent.
-- See IC_Load_Production_Plan.md §4.1.

CREATE OR REPLACE FUNCTION staging.fn_normalize_employee_range(raw text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN raw IS NULL OR trim(raw) = '' THEN NULL
        -- Canonical HubSpot values — pass through
        WHEN raw IN ('1-10', '11-50', '51-100', '101-250',
                     '251-500', '501-1000', '1001-5000',
                     '5001-10000', '10000+') THEN raw
        -- IC'ALPS whitespace variants
        WHEN regexp_replace(raw, '\s+', '', 'g') = '1-10' THEN '1-10'
        WHEN regexp_replace(raw, '\s+', '', 'g') = '11-50' THEN '11-50'
        WHEN regexp_replace(raw, '\s+', '', 'g') = '51-100' THEN '51-100'
        WHEN regexp_replace(raw, '\s+', '', 'g') = '101-250' THEN '101-250'
        WHEN regexp_replace(raw, '\s+', '', 'g') = '251-500' THEN '251-500'
        WHEN regexp_replace(raw, '\s+', '', 'g') = '501-1000' THEN '501-1000'
        WHEN regexp_replace(raw, '\s+', '', 'g') = '1001-5000' THEN '1001-5000'
        WHEN regexp_replace(raw, '\s+', '', 'g') = '5001-10000' THEN '5001-10000'
        -- French variants for "more than 10000"
        WHEN lower(trim(raw)) IN ('10000+', '>10000', '> 10000',
                                   'plus de 10000', 'plusde10000') THEN '10000+'
        ELSE NULL
    END
$$;

COMMENT ON FUNCTION staging.fn_normalize_employee_range(text) IS
'Normalize IC''ALPS employee range strings to HubSpot numberofemployees enum values.';
