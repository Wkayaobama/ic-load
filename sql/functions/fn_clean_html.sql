-- fn_clean_html — strip HTML tags and named entities from text.
--
-- Translated from dbt_communication/macros/clean_html.sql macro.
-- Removes <tag> constructs and &name; entities. Does NOT decode numeric
-- entities (&#39;) — those are rare in IC'ALPS and require a lookup table.
--
-- Called by: stg_communication for comm_note, comm_subject when the source
-- is a rich-text field (HubSpot activity notes, legacy CRM notes).
--
-- Idempotent.
-- See IC_Load_Production_Plan.md §4.1.

CREATE OR REPLACE FUNCTION staging.fn_clean_html(txt text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $$
    SELECT
        regexp_replace(
            regexp_replace(txt, '<[^>]+>', '', 'g'),
            '&[a-zA-Z]+;', '', 'g'
        )
$$;

COMMENT ON FUNCTION staging.fn_clean_html(text) IS
'Strip HTML tags and named entities. NULL-safe, idempotent.';
