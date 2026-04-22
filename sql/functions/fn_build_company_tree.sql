-- ═══════════════════════════════════════════════════════════════════════════
-- fn_build_company_tree
--
-- Recursive CTE that traverses the company self-referential hierarchy.
-- Source table must expose: company_id, company_name, parent_company_id.
--
-- IMPORTANT: parent_company_id does NOT exist in stg_company_normalised.
-- It is populated by the sibling-company pipeline (domain-trick) and
-- stored as HubSpot company-to-company associations (typeId 269/270).
-- The caller must pass a view or table that resolves the parent
-- relationship. Example:
--
--   CREATE OR REPLACE VIEW staging.v_company_with_parent AS
--   SELECT
--       c.comp_companyid AS company_id,
--       c.comp_name      AS company_name,
--       a.parent_id      AS parent_company_id
--   FROM staging.stg_company_normalised c
--   LEFT JOIN (
--       SELECT child_id, parent_id
--       FROM hubspot.company_associations
--       WHERE association_type_id = 269
--   ) a ON c.comp_companyid = a.child_id;
--
-- Then call: SELECT * FROM silver.fn_build_company_tree('staging', 'v_company_with_parent');
--
-- Cycle guard (soft)
-- ------------------
-- Detection  : is_cycle flag set TRUE when company_id already appears
--              in the ancestors[] of the current path.
-- Prevention : WHERE NOT (child.company_id = ANY(ct.ancestors)) stops
--              infinite recursion on that path only.
-- Other paths continue — multi-domain siblings (same company under
-- several parents) are handled because each path has its own ancestors[].
-- Cycles are queryable: SELECT * FROM silver.company_tree WHERE is_cycle;
--
-- Root detection
-- --------------
-- A company is a root if parent_company_id IS NULL OR its parent does
-- not exist in the source table (handles orphaned references).
--
-- Prerequisites
-- -------------
-- - silver schema + tables: run sql/silver/00_hierarchy_schema.sql first
-- - Source table/view with columns: company_id, company_name, parent_company_id
--
-- See IC_Load_Production_Plan.md §5.2 (ENTITY_POSTPROCESS).
-- ═══════════════════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION silver.fn_build_company_tree(
    p_source_schema text    DEFAULT 'staging',
    p_source_table  text    DEFAULT 'v_company_with_parent',
    p_truncate      boolean DEFAULT true
)
RETURNS TABLE (
    node_key            bigint,
    company_id          bigint,
    company_name        text,
    parent_company_id   bigint,
    depth               integer,
    path_key            text,
    path_label          text,
    ancestors           bigint[],
    is_cycle            boolean
)
LANGUAGE plpgsql
AS $$
BEGIN
    IF p_truncate THEN
        TRUNCATE silver.company_tree;
    END IF;

    EXECUTE format($sql$
        WITH RECURSIVE company_cte AS (

            -- Base: roots (no parent, or parent missing from table)
            SELECT
                c.company_id,
                c.company_name,
                c.parent_company_id,
                0::integer              AS depth,
                c.company_id::text      AS path_key,
                c.company_name          AS path_label,
                ARRAY[c.company_id]     AS ancestors,
                false                   AS is_cycle
            FROM %1$I.%2$I c
            WHERE c.parent_company_id IS NULL
               OR NOT EXISTS (
                      SELECT 1 FROM %1$I.%2$I p
                      WHERE  p.company_id = c.parent_company_id
                  )

            UNION ALL

            -- Recursive: children
            SELECT
                child.company_id,
                child.company_name,
                child.parent_company_id,
                ct.depth + 1,
                ct.path_key   || '|' || child.company_id::text,
                ct.path_label || '|' || child.company_name,
                ct.ancestors  || child.company_id,
                child.company_id = ANY(ct.ancestors)
            FROM %1$I.%2$I child
            JOIN company_cte ct ON child.parent_company_id = ct.company_id
            WHERE NOT (child.company_id = ANY(ct.ancestors))
        )
        INSERT INTO silver.company_tree (
            node_key, company_id, company_name, parent_company_id,
            depth, path_key, path_label, ancestors, is_cycle
        )
        SELECT
            row_number() OVER (ORDER BY depth, path_key)::bigint,
            company_id, company_name, parent_company_id,
            depth, path_key, path_label, ancestors, is_cycle
        FROM company_cte
    $sql$, p_source_schema, p_source_table);

    RETURN QUERY
    SELECT ct.node_key, ct.company_id, ct.company_name, ct.parent_company_id,
           ct.depth, ct.path_key, ct.path_label, ct.ancestors, ct.is_cycle
    FROM silver.company_tree ct
    ORDER BY ct.depth, ct.path_key;
END;
$$;

COMMENT ON FUNCTION silver.fn_build_company_tree(text, text, boolean) IS
'Recursive company hierarchy builder with soft cycle detection. Source must expose company_id, company_name, parent_company_id.';
