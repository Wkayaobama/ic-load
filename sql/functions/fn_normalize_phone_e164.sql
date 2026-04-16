-- fn_normalize_phone_e164 — normalize phone numbers to E.164 format.
--
-- Translated from silver_normalise.py::_normalise_phone.
-- Handles: already-E.164 (+33..), 0033 prefix, French local 0X-10digit,
-- bare 9-digit (dropped leading 0). Default country code is +33 (France),
-- matching IC'ALPS origin. Strip spaces / dots / dashes / parentheses / slashes
-- before analysis.
--
-- Returns NULL for input shorter than 7 digits after cleanup — better to drop
-- a garbage phone than to emit a malformed one to HubSpot.
--
-- Called by: stg_contact (icalps_businessphone, icalps_mobilephone),
-- stg_company (icalps_companyphone).
--
-- Idempotent.
-- See IC_Load_Production_Plan.md §4.1.

CREATE OR REPLACE FUNCTION staging.fn_normalize_phone_e164(
    raw text,
    country_code text DEFAULT '+33'
)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    digits text;
BEGIN
    IF raw IS NULL OR trim(raw) = '' THEN
        RETURN NULL;
    END IF;

    -- Strip everything except digits and leading +
    digits := regexp_replace(trim(raw), '[\s.\-()/]', '', 'g');

    IF digits IS NULL OR digits = '' THEN
        RETURN NULL;
    END IF;

    -- Already E.164 (starts with +)
    IF digits LIKE '+%' THEN
        RETURN CASE WHEN length(digits) >= 8 THEN digits ELSE NULL END;
    END IF;

    -- 0033... prefix (France international)
    IF digits LIKE '0033%' THEN
        RETURN '+' || substring(digits FROM 3);
    END IF;

    -- French local 0X-then-9-digits (10 total)
    IF substring(digits FROM 1 FOR 1) = '0' AND length(digits) = 10 THEN
        RETURN '+33' || substring(digits FROM 2);
    END IF;

    -- Bare 9-digit (leading 0 already stripped)
    IF length(digits) = 9 AND substring(digits FROM 1 FOR 1) ~ '[1-9]' THEN
        RETURN country_code || digits;
    END IF;

    -- Fallback: pass-through if long enough to be plausible
    RETURN CASE WHEN length(digits) >= 7 THEN digits ELSE NULL END;
END;
$$;

COMMENT ON FUNCTION staging.fn_normalize_phone_e164(text, text) IS
'Normalize French/international phone to E.164. Returns NULL for malformed input.';
