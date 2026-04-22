-- fn_validate_linkedin_url — validate and normalize LinkedIn URLs.
--
-- Lightweight validation: must contain 'linkedin.com' anywhere in the URL
-- (covers linkedin.com/in/*, linkedin.com/company/*, fr.linkedin.com, etc.).
-- Adds https:// if scheme is missing. Returns NULL for non-LinkedIn input.
--
-- Does NOT verify the URL resolves or matches a specific profile-path pattern —
-- IC'ALPS legacy data has many partial/typo'd LinkedIn URLs that HubSpot can
-- still display but stricter validation would drop. The 85% rule applies:
-- normalize the obvious cases; let HubSpot reject the truly malformed ones.
--
-- Called by: stg_contact (icalps_linkedin_url), stg_company (icalps_linkedin_url).
-- Idempotent.
-- See IC_Load_Production_Plan.md §4.1.

CREATE OR REPLACE FUNCTION staging.fn_validate_linkedin_url(url text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    cleaned text;
BEGIN
    IF url IS NULL OR trim(url) = '' THEN
        RETURN NULL;
    END IF;

    cleaned := lower(trim(url));

    -- Add https:// if scheme missing
    IF cleaned !~ '^https?://' THEN
        cleaned := 'https://' || cleaned;
    END IF;

    -- Must contain linkedin.com somewhere
    IF cleaned !~ 'linkedin\.com' THEN
        RETURN NULL;
    END IF;

    RETURN cleaned;
END;
$$;

COMMENT ON FUNCTION staging.fn_validate_linkedin_url(text) IS
'Validate + normalize LinkedIn URL. NULL if URL does not contain linkedin.com.';
