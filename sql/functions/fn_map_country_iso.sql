-- fn_map_country_iso — French country name → ISO 3166-1 alpha-2 code.
--
-- Translated from silver_normalise.py::COUNTRY_ISO_MAP.
-- Pass-through for unmapped values — covers already-ISO codes (e.g. "FR")
-- and any country not in the French-origin CRM vocabulary.
--
-- Called by: stg_company (icalps_country → country_iso),
-- stg_contact (icalps_country → country_iso).
-- Idempotent.
-- See IC_Load_Production_Plan.md §4.1.

CREATE OR REPLACE FUNCTION staging.fn_map_country_iso(raw text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT CASE
        WHEN raw IS NULL OR trim(raw) = '' THEN NULL
        WHEN trim(raw) = 'France'             THEN 'FR'
        WHEN trim(raw) = 'Allemagne'          THEN 'DE'
        WHEN trim(raw) = 'Suisse'             THEN 'CH'
        WHEN trim(raw) = 'Royaume-Uni'        THEN 'GB'
        WHEN trim(raw) IN (E'\u00C9tats-Unis', 'Etats-Unis', E'\u00c9tats-Unis') THEN 'US'
        WHEN trim(raw) = 'Belgique'           THEN 'BE'
        WHEN trim(raw) = 'Italie'             THEN 'IT'
        WHEN trim(raw) = 'Espagne'            THEN 'ES'
        WHEN trim(raw) = 'Pays-Bas'           THEN 'NL'
        WHEN trim(raw) = 'Autriche'           THEN 'AT'
        WHEN trim(raw) = 'Danemark'           THEN 'DK'
        WHEN trim(raw) IN (E'Su\u00E8de', E'Su\u00e8de') THEN 'SE'
        WHEN trim(raw) = 'Finlande'           THEN 'FI'
        WHEN trim(raw) IN (E'Norv\u00E8ge', E'Norv\u00e8ge') THEN 'NO'
        WHEN trim(raw) = 'Luxembourg'         THEN 'LU'
        WHEN trim(raw) = 'Portugal'           THEN 'PT'
        WHEN trim(raw) = 'Irlande'            THEN 'IE'
        WHEN trim(raw) = 'Pologne'            THEN 'PL'
        WHEN trim(raw) = 'Canada'             THEN 'CA'
        WHEN trim(raw) = 'Japon'              THEN 'JP'
        WHEN trim(raw) = 'Chine'              THEN 'CN'
        WHEN trim(raw) = 'Israel'             THEN 'IL'
        WHEN trim(raw) = 'Singapour'          THEN 'SG'
        -- Uppercase / alternate variants found in probe data (Apr 2026)
        WHEN trim(raw) = 'FRANCE'             THEN 'FR'
        WHEN trim(raw) = 'TAIWAN'             THEN 'TW'
        WHEN trim(raw) = 'PAYSBAS'            THEN 'NL'
        WHEN trim(raw) = 'ISRAEL'             THEN 'IL'
        WHEN trim(raw) = 'ANGLETERRE'         THEN 'GB'
        WHEN trim(raw) = 'UK'                 THEN 'GB'
        WHEN trim(raw) = 'United Kingdom'     THEN 'GB'
        WHEN trim(raw) = 'allemagne'          THEN 'DE'
        WHEN trim(raw) = 'france'             THEN 'FR'
        ELSE raw  -- pass-through (already ISO or unmapped)
    END
$$;

COMMENT ON FUNCTION staging.fn_map_country_iso(text) IS
'French country name → ISO 3166-1 alpha-2. Pass-through for unmapped / already-ISO.';
