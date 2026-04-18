-- fn_map_language_iso — French language name → ISO 639-1 code.
--
-- Translated from silver_normalise.py::LANGUAGE_ISO_MAP.
-- Pass-through NULL for unmapped values.
--
-- Called by: normalise_company.sql (Comp_Language → icalps_language).
-- Idempotent.

CREATE OR REPLACE FUNCTION staging.fn_map_language_iso(raw text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN raw IS NULL THEN NULL
        WHEN trim(raw) IN ('Français', E'Fran\u00E7ais') THEN 'FR'
        WHEN trim(raw) = 'English'  THEN 'EN'
        WHEN trim(raw) = 'Deutsch'  THEN 'DE'
        WHEN trim(raw) = 'Espagnol' THEN 'ES'
        WHEN trim(raw) IN ('Italian', 'Italiano') THEN 'IT'
        ELSE NULL
    END
$$;

COMMENT ON FUNCTION staging.fn_map_language_iso(text) IS
'French/native language name → ISO 639-1 code. NULL for unmapped values.';
