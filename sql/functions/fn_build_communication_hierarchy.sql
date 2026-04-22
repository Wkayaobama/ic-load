-- ═══════════════════════════════════════════════════════════════════════════
-- fn_build_communication_hierarchy
--
-- Builds a three-level node table from the flat bronze/staging table:
--   Level 0 — unique companies         → root nodes
--   Level 1 — unique (company, person) → person nodes, parent = company
--   Level 2 — each communication row   → comm nodes, parent = person
--
-- Replaces the Python BFS in pipeline/unflatten.py. The fixed 3-level
-- depth means no recursive CTE is needed — three sequential JOIN passes
-- are sufficient and more efficient (set-based vs row-by-row).
--
-- Column adaptation
-- -----------------
-- stg_communication_normalised has person_id but NOT person names.
-- This function JOINs against stg_contact_normalised for pers_firstname +
-- pers_lastname. This requires the contact entity to have been loaded
-- first (guaranteed by the import order: Company → Contact → Communication).
--
-- Node key stability
-- ------------------
-- Each level computes its offset from the prior level's MAX(node_key).
-- Level 0 gets 1…N, Level 1 gets N+1…M, Level 2 gets M+1…P.
-- Deterministic and re-runnable.
--
-- Path design
-- -----------
-- path_key uses IDs ("3|4|1"), never labels — pipe characters in names
-- cannot corrupt the path. path_label is display-only and may contain
-- pipes in company names; it is NOT used for joins.
--
-- Prerequisites
-- -------------
-- - silver schema + tables: run sql/silver/00_hierarchy_schema.sql first
-- - staging.stg_communication_normalised must be populated (post SILVER_NORMALISE)
-- - staging.stg_contact_normalised must be populated (contact entity loaded)
-- - staging.stg_company_normalised must be populated (company entity loaded)
--
-- See IC_Load_Production_Plan.md §5.2 (ENTITY_POSTPROCESS).
-- ═══════════════════════════════════════════════════════════════════════════

CREATE OR REPLACE FUNCTION silver.fn_build_communication_hierarchy(
    p_source_schema text    DEFAULT 'staging',
    p_source_table  text    DEFAULT 'stg_communication_normalised',
    p_truncate      boolean DEFAULT true
)
RETURNS TABLE (
    node_key   bigint,
    node_name  text,
    parent_key bigint,
    depth      integer,
    path_key   text,
    path_label text,
    node_type  text,
    entity_id  bigint,
    comm_id    bigint
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = silver, staging, pg_temp
AS $$
DECLARE
    v_company_max bigint := 0;
    v_person_max  bigint := 0;
BEGIN
    IF p_truncate THEN
        TRUNCATE silver.communication_hierarchy;
    END IF;

    DROP TABLE IF EXISTS pg_temp._ch_nodes;
    CREATE TEMP TABLE pg_temp._ch_nodes (
        node_key    bigint,
        node_name   text,
        parent_key  bigint,
        depth       integer,
        path_key    text,
        path_label  text,
        node_type   text,
        entity_id   bigint,
        comm_id     bigint,
        comm_type   text,
        comm_action text,
        comm_status text
    );
    CREATE INDEX ON pg_temp._ch_nodes (path_key);
    CREATE INDEX ON pg_temp._ch_nodes (entity_id, node_type);


    -- ── LEVEL 0 : Companies ───────────────────────────────────────────
    -- One root node per distinct company_id in the communication source.
    -- Company names resolved via JOIN to stg_company_normalised.
    EXECUTE format($sql$
        INSERT INTO pg_temp._ch_nodes
        SELECT
            row_number() OVER (ORDER BY src.company_id),
            COALESCE(comp.comp_name, 'Company #' || src.company_id::text),
            NULL::bigint,
            0,
            src.company_id::text,
            COALESCE(comp.comp_name, 'Company #' || src.company_id::text),
            'company',
            src.company_id,
            NULL, NULL, NULL, NULL
        FROM (
            SELECT DISTINCT company_id
            FROM %I.%I
            WHERE company_id IS NOT NULL
        ) src
        LEFT JOIN staging.stg_company_normalised comp
            ON comp.comp_companyid = src.company_id
    $sql$, p_source_schema, p_source_table);

    SELECT COALESCE(MAX(node_key), 0) INTO v_company_max FROM pg_temp._ch_nodes;


    -- ── LEVEL 1 : Persons (scoped per company) ───────────────────────
    -- One node per unique (company_id, person_id) pair.
    -- Person names resolved via JOIN to stg_contact_normalised.
    -- A person at two companies gets two nodes (company-scoped hierarchy).
    EXECUTE format($sql$
        INSERT INTO pg_temp._ch_nodes
        SELECT
            $1 + row_number() OVER (ORDER BY src.company_id, src.person_id),
            COALESCE(
                NULLIF(trim(cont.pers_firstname || ' ' || cont.pers_lastname), ''),
                'Person #' || src.person_id::text
            ),
            cn.node_key,
            1,
            cn.path_key || '|' || src.person_id::text,
            cn.path_label || '|' || COALESCE(
                NULLIF(trim(cont.pers_firstname || ' ' || cont.pers_lastname), ''),
                'Person #' || src.person_id::text
            ),
            'person',
            src.person_id,
            NULL, NULL, NULL, NULL
        FROM (
            SELECT DISTINCT company_id, person_id
            FROM %I.%I
            WHERE person_id  IS NOT NULL
              AND company_id IS NOT NULL
        ) src
        JOIN pg_temp._ch_nodes cn
            ON  cn.entity_id = src.company_id
            AND cn.node_type = 'company'
        LEFT JOIN staging.stg_contact_normalised cont
            ON cont.pers_personid = src.person_id
    $sql$, p_source_schema, p_source_table)
    USING v_company_max;

    SELECT COALESCE(MAX(node_key), 0) INTO v_person_max FROM pg_temp._ch_nodes;


    -- ── LEVEL 2 : Communications ──────────────────────────────────────
    -- One node per communication row. Parent lookup via path_key = "company_id|person_id"
    -- which is O(log n) via the path_key index on the temp table.
    EXECUTE format($sql$
        INSERT INTO pg_temp._ch_nodes
        SELECT
            $1 + row_number() OVER (ORDER BY src.comm_communicationid),
            COALESCE(
                NULLIF(trim(src.comm_subject), ''),
                'Communication #' || src.comm_communicationid::text
            ),
            pn.node_key,
            2,
            pn.path_key || '|' || src.comm_communicationid::text,
            pn.path_label || '|' || COALESCE(
                NULLIF(trim(src.comm_subject), ''),
                '#' || src.comm_communicationid::text
            ),
            'communication',
            NULL::bigint,
            src.comm_communicationid,
            src.comm_type,
            src.comm_action,
            src.comm_status
        FROM (
            SELECT
                comm_communicationid, comm_subject,
                comm_type, comm_action, comm_status,
                person_id, company_id
            FROM %I.%I
            WHERE comm_communicationid IS NOT NULL
        ) src
        JOIN pg_temp._ch_nodes pn
            ON  pn.path_key  = src.company_id::text || '|' || src.person_id::text
            AND pn.node_type = 'person'
    $sql$, p_source_schema, p_source_table)
    USING v_person_max;


    -- ── Persist to silver (ORDER BY depth → parents inserted first) ──
    INSERT INTO silver.communication_hierarchy (
        node_key, node_name, parent_key, depth,
        path_key, path_label, node_type, entity_id,
        comm_id, comm_type, comm_action, comm_status
    )
    SELECT
        node_key, node_name, parent_key, depth,
        path_key, path_label, node_type, entity_id,
        comm_id, comm_type, comm_action, comm_status
    FROM pg_temp._ch_nodes
    ORDER BY depth, node_key;

    RETURN QUERY
    SELECT n.node_key, n.node_name, n.parent_key, n.depth,
           n.path_key, n.path_label, n.node_type, n.entity_id, n.comm_id
    FROM pg_temp._ch_nodes n
    ORDER BY n.depth, n.path_key;

    DROP TABLE IF EXISTS pg_temp._ch_nodes;

EXCEPTION WHEN OTHERS THEN
    DROP TABLE IF EXISTS pg_temp._ch_nodes;
    RAISE;
END;
$$;

COMMENT ON FUNCTION silver.fn_build_communication_hierarchy(text, text, boolean) IS
'Three-level hierarchy unflattening: Company → Person → Communication. Replaces pipeline/unflatten.py BFS. Idempotent via truncate + rebuild.';
