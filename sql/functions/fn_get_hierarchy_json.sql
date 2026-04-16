-- fn_get_hierarchy_json — nested JSONB tree for visual lineage inspection.
--
-- Uses a private recursive helper (_fn_node_to_jsonb) that walks the
-- hierarchy bottom-up one node at a time. Intended for QA / spot-checking.
--
-- PERFORMANCE WARNING: recursive PL/pgSQL with per-node correlated
-- subquery. Fine for single-tree inspection; NOT for bulk export.
-- For large trees, use fn_traverse_hierarchy with a LIMIT instead.
--
-- Args
--   p_root_node_key : NULL = all root companies as a JSON array
--                     bigint = subtree rooted at that node

-- Private recursive helper (underscore prefix = internal)
CREATE OR REPLACE FUNCTION silver._fn_node_to_jsonb(p_node_key bigint)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_node     silver.communication_hierarchy%ROWTYPE;
    v_children jsonb;
BEGIN
    SELECT * INTO v_node
    FROM silver.communication_hierarchy
    WHERE node_key = p_node_key;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT COALESCE(
        jsonb_agg(
            silver._fn_node_to_jsonb(c.node_key)
            ORDER BY c.node_key
        ),
        '[]'::jsonb
    )
    INTO v_children
    FROM silver.communication_hierarchy c
    WHERE c.parent_key = p_node_key;

    RETURN jsonb_build_object(
        'node_key',    v_node.node_key,
        'node_name',   v_node.node_name,
        'depth',       v_node.depth,
        'node_type',   v_node.node_type,
        'path_key',    v_node.path_key,
        'path_label',  v_node.path_label,
        'comm_type',   v_node.comm_type,
        'comm_action', v_node.comm_action,
        'comm_status', v_node.comm_status,
        'children',    v_children
    );
END;
$$;

-- Public entry point
CREATE OR REPLACE FUNCTION silver.fn_get_hierarchy_json(
    p_root_node_key bigint DEFAULT NULL
)
RETURNS jsonb
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE(
        jsonb_agg(
            silver._fn_node_to_jsonb(node_key)
            ORDER BY node_key
        ),
        '[]'::jsonb
    )
    FROM silver.communication_hierarchy
    WHERE CASE
        WHEN p_root_node_key IS NULL THEN parent_key IS NULL
        ELSE node_key = p_root_node_key
    END
$$;

COMMENT ON FUNCTION silver.fn_get_hierarchy_json(bigint) IS
'Nested JSONB tree for QA. NOT for bulk export — use fn_traverse_hierarchy + LIMIT instead.';
