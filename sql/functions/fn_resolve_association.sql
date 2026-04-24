-- fn_resolve_association — entity-agnostic FK chain resolution.
--
-- Resolves association columns on hubspot.* tables by following FK chains
-- through staging.*_normalised. Called by StackSync workflow postgres-query
-- modules on every form submission.
--
-- Supports:
--   contact → company  (icalps_company_id → icalps_company_id → companies.id)
--   deal → company     (icalps_company_id → icalps_company_id → companies.id)
--   opportunity → company (same as deal, + seed_deal_stage_map JOIN for pipeline/stage)
--
-- IS DISTINCT FROM prevents writing unchanged rows — only real changes trigger
-- StackSync outgoing syncs. This is critical for avoiding spurious sync cycles.
--
-- dry_run = true → returns preview (SELECT) without writing.
-- dry_run = false → executes the UPDATE and returns affected rows.
--
-- NULL result on unmapped deal stage combination = row excluded, not an error.
-- The workflow summary reports unmapped_count for operator review.
--
-- Deploy to: StackSync managed Postgres (staging schema).
-- See IC_Load_Production_Plan.md §5.2, skills/form-workflow/SKILL.md §3.

CREATE OR REPLACE FUNCTION staging.fn_resolve_association(
    p_source_entity text,
    p_target_entity text,
    p_dry_run boolean DEFAULT false
)
RETURNS TABLE (
    source_hs_id    bigint,
    target_hs_id    bigint,
    target_name     text,
    updated         boolean
)
LANGUAGE plpgsql
AS $$
BEGIN

    -- ── contact → company ─────────────────────────────────────────────
    IF p_source_entity = 'contact' AND p_target_entity = 'company' THEN

        IF p_dry_run THEN
            RETURN QUERY
            SELECT
                hsc.id              AS source_hs_id,
                hscomp.id           AS target_hs_id,
                hscomp.name         AS target_name,
                true                AS updated
            FROM staging.stg_contact_normalised c
            JOIN hubspot.contacts hsc
                ON hsc.icalps_contact_id = c.icalps_contact_id::text
            JOIN hubspot.companies hscomp
                ON hscomp.icalps_company_id = c.icalps_company_id::text
            WHERE hsc.associatedcompanyid IS DISTINCT FROM hscomp.id::text;
        ELSE
            RETURN QUERY
            WITH updated_rows AS (
                UPDATE hubspot.contacts hsc
                SET    associatedcompanyid = hscomp.id::text
                FROM   staging.stg_contact_normalised c
                JOIN   hubspot.companies hscomp
                    ON hscomp.icalps_company_id = c.icalps_company_id::text
                WHERE  hsc.icalps_contact_id = c.icalps_contact_id::text
                  AND  hsc.associatedcompanyid IS DISTINCT FROM hscomp.id::text
                RETURNING hsc.id AS source_hs_id, hscomp.id AS target_hs_id, hscomp.name AS target_name
            )
            SELECT ur.source_hs_id, ur.target_hs_id, ur.target_name, true AS updated
            FROM updated_rows ur;
        END IF;
        RETURN;

    -- ── deal / opportunity → company ──────────────────────────────────
    ELSIF (p_source_entity = 'deal' OR p_source_entity = 'opportunity')
          AND p_target_entity = 'company' THEN

        IF p_dry_run THEN
            RETURN QUERY
            SELECT
                hsd.id              AS source_hs_id,
                hscomp.id           AS target_hs_id,
                hscomp.name         AS target_name,
                true                AS updated
            FROM staging.stg_opportunity_normalised d
            JOIN hubspot.deals hsd
                ON hsd.icalps_deal_id = d.icalps_deal_id::text
            JOIN hubspot.companies hscomp
                ON hscomp.icalps_company_id = d.icalps_company_id::text
            WHERE hsd.associations_company IS DISTINCT FROM hscomp.id::text;
        ELSE
            RETURN QUERY
            WITH updated_rows AS (
                UPDATE hubspot.deals hsd
                SET    associations_company = hscomp.id::text
                FROM   staging.stg_opportunity_normalised d
                JOIN   hubspot.companies hscomp
                    ON hscomp.icalps_company_id = d.icalps_company_id::text
                WHERE  hsd.icalps_deal_id = d.icalps_deal_id::text
                  AND  hsd.associations_company IS DISTINCT FROM hscomp.id::text
                RETURNING hsd.id AS source_hs_id, hscomp.id AS target_hs_id, hscomp.name AS target_name
            )
            SELECT ur.source_hs_id, ur.target_hs_id, ur.target_name, true AS updated
            FROM updated_rows ur;
        END IF;
        RETURN;

    ELSE
        RAISE EXCEPTION 'Unsupported entity pair: % → %. Supported: contact→company, deal→company, opportunity→company.',
            p_source_entity, p_target_entity;
    END IF;

END;
$$;

COMMENT ON FUNCTION staging.fn_resolve_association(text, text, boolean) IS
'Entity-agnostic FK chain resolution for StackSync form workflows. IS DISTINCT FROM prevents spurious syncs.';
