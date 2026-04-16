-- fn_extract_domain — strip protocol, www, path, query, fragment from a URL.
--
-- Translated from custom_objects/upsert_sibling_companies.py::_clean_domain.
-- Returns the bare domain (host only, lowercased) suitable for dedup comparison
-- and HubSpot `domain` column population.
--
-- Examples:
--   'https://www.Acme.com/contact?x=1'  → 'acme.com'
--   'HTTP://site.co.uk'                  → 'site.co.uk'
--   'mailto:x@y.com'                     → 'mailto:x@y.com'  (unchanged — no scheme strip match)
--   NULL / '' / 'N/A'                    → NULL
--
-- Called by: stg_company (comp_website → domain for reconciliation).
-- Idempotent.
-- See IC_Load_Production_Plan.md §4.1.

CREATE OR REPLACE FUNCTION staging.fn_extract_domain(url text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    lowered text;
BEGIN
    IF url IS NULL OR trim(url) = '' OR trim(url) = 'N/A' THEN
        RETURN NULL;
    END IF;

    lowered := lower(trim(url));

    -- Strip scheme
    IF lowered LIKE 'https://%' THEN
        lowered := substring(lowered FROM 9);
    ELSIF lowered LIKE 'http://%' THEN
        lowered := substring(lowered FROM 8);
    END IF;

    -- Strip www. prefix
    IF lowered LIKE 'www.%' THEN
        lowered := substring(lowered FROM 5);
    END IF;

    -- Strip path / query / fragment — split on first /, ?, or # and take first part
    lowered := split_part(lowered, '/', 1);
    lowered := split_part(lowered, '?', 1);
    lowered := split_part(lowered, '#', 1);
    lowered := trim(lowered);

    IF lowered = '' THEN
        RETURN NULL;
    END IF;

    RETURN lowered;
END;
$$;

COMMENT ON FUNCTION staging.fn_extract_domain(text) IS
'Normalize website URL to bare domain. NULL for empty / invalid input.';
