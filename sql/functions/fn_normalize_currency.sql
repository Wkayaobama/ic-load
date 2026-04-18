-- fn_normalize_currency — strip currency symbols and normalise decimal separator.
--
-- Translated from silver_normalise.py::normalise_opportunity inline SQL.
-- Strips €, $, £, spaces; converts comma decimal separator → period.
-- Returns NULL for empty/NULL input or values that cannot be cast to numeric.
--
-- Called by: normalise_opportunity.sql (Oppo_Cost → icalps_cost).
-- Idempotent.

CREATE OR REPLACE FUNCTION staging.fn_normalize_currency(raw text)
RETURNS numeric
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CAST(
        NULLIF(
            REPLACE(
                REPLACE(
                    REGEXP_REPLACE(COALESCE(raw, ''), '[€$£\s]', '', 'g'),
                    ',', '.'
                ),
                ' ', ''
            ),
            ''
        )
    AS numeric)
$$;

COMMENT ON FUNCTION staging.fn_normalize_currency(text) IS
'Strip currency symbols (€$£) and normalise comma decimal separator. Returns NULL for unparseable input.';
