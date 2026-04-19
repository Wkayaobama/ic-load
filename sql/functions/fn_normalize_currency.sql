-- fn_normalize_currency — strip currency symbols and normalise decimal separator.
--
-- Translated from silver_normalise.py::normalise_opportunity inline SQL.
-- Strips €, $, £, whitespace; detects whether comma is a thousands separator
-- (e.g. 2,500.00) or decimal separator (European format, e.g. 1234,56);
-- converts accordingly. Returns NULL for empty/NULL input or unparseable values.
--
-- Called by: normalise_opportunity.sql (Oppo_Cost → icalps_cost).
-- Idempotent.

CREATE OR REPLACE FUNCTION staging.fn_normalize_currency(raw text)
RETURNS numeric
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
    stripped text;
    cleaned  text;
BEGIN
    -- Strip currency symbols and all whitespace.
    stripped := REGEXP_REPLACE(COALESCE(raw, ''), '[€$£\s]', '', 'g');
    IF stripped = '' THEN RETURN NULL; END IF;

    -- Detect comma role:
    --   thousands separator → comma precedes exactly 3 digits then a comma/period/end
    --     e.g. 2,500.00  →  strip commas  →  2500.00
    --          1,234,567 →  strip commas  →  1234567
    --   decimal separator (European format) → everything else
    --     e.g. 1234,56   →  replace comma →  1234.56
    IF stripped ~ ',\d{3}[,.]' OR stripped ~ ',\d{3}$' THEN
        cleaned := REPLACE(stripped, ',', '');
    ELSE
        cleaned := REPLACE(stripped, ',', '.');
    END IF;

    BEGIN
        RETURN cleaned::numeric;
    EXCEPTION WHEN OTHERS THEN
        RETURN NULL;
    END;
END;
$$;

COMMENT ON FUNCTION staging.fn_normalize_currency(text) IS
'Strip currency symbols (€$£) and normalise decimal separator. Handles both European comma-decimal (1234,56) and US comma-thousands (2,500.00) formats. Returns NULL for unparseable input.';
