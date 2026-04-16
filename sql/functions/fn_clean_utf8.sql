-- fn_clean_utf8 — fix UTF-8 mojibake from French text mis-encoded as Latin-1.
--
-- Translated from dbt_communication/macros/clean_french_utf8.sql macro.
-- Replaces common two-byte mangled sequences (Ã©, Ã¨, etc.) with their
-- correct single-character equivalents (é, è, etc.).
--
-- Called by: dbt staging models on comp_name, pers_firstname, pers_lastname,
-- comm_subject, comm_note, and any other text column extracted from IC'ALPS.
--
-- Idempotent: CREATE OR REPLACE makes repeat installs a no-op.
-- See IC_Load_Production_Plan.md §4.1 — Function Registry.

CREATE OR REPLACE FUNCTION staging.fn_clean_utf8(txt text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT
        replace(
        replace(
        replace(
        replace(
        replace(
        replace(
        replace(
        replace(
        replace(
            txt,
            E'\u00C3\u00A9', E'\u00E9'),  -- Ã© → é
            E'\u00C3\u00A8', E'\u00E8'),  -- Ã¨ → è
            E'\u00C3\u00AA', E'\u00EA'),  -- Ãª → ê
            E'\u00C3 ',      E'\u00E0'),  -- Ã  → à
            E'\u00C3\u00A2', E'\u00E2'),  -- Ã¢ → â
            E'\u00C3\u00AE', E'\u00EE'),  -- Ã® → î
            E'\u00C3\u00B4', E'\u00F4'),  -- Ã´ → ô
            E'\u00C3\u00A7', E'\u00E7'),  -- Ã§ → ç
            E'\u00C3\u00B9', E'\u00F9')   -- Ã¹ → ù
$$;

COMMENT ON FUNCTION staging.fn_clean_utf8(text) IS
'Fix mojibake from IC''ALPS Latin-1→UTF-8 mis-decoding. Idempotent: already-clean text passes through unchanged.';
