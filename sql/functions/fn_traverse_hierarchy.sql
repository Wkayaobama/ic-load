-- fn_traverse_hierarchy — recursive CTE navigation over built hierarchy.
--
-- Use AFTER fn_build_communication_hierarchy has populated
-- silver.communication_hierarchy. This function reads the already-built
-- table and walks it from a given root node.
--
-- Args
--   p_root_node_key : start node; NULL = all root companies
--   p_max_depth     : relative depth limit; NULL = no limit
--
-- Returns relative_depth so callers can measure distance from the
-- query root independently of the absolute depth column.
--
-- Performance: this is a read-only CTE traversal — O(n) where n is
-- the size of the subtree. For bulk export use this with a LIMIT.
-- For spot-checking a single tree, fn_get_hierarchy_json gives JSONB.

CREATE OR REPLACE FUNCTION silver.fn_traverse_hierarchy(
    p_root_node_key bigint  DEFAULT NULL,
    p_max_depth     integer DEFAULT NULL
)
RETURNS TABLE (
    node_key       bigint,
    node_name      text,
    parent_key     bigint,
    depth          integer,
    relative_depth integer,
    path_key       text,
    path_label     text,
    node_type      text,
    comm_type      text,
    comm_status    text
)
LANGUAGE sql
STABLE
AS $$
WITH RECURSIVE traverse AS (
    SELECT
        ch.node_key, ch.node_name, ch.parent_key, ch.depth,
        0          AS relative_depth,
        ch.path_key, ch.path_label, ch.node_type, ch.comm_type, ch.comm_status
    FROM silver.communication_hierarchy ch
    WHERE CASE
        WHEN p_root_node_key IS NULL THEN ch.parent_key IS NULL
        ELSE ch.node_key = p_root_node_key
    END

    UNION ALL

    SELECT
        c.node_key, c.node_name, c.parent_key, c.depth,
        t.relative_depth + 1,
        c.path_key, c.path_label, c.node_type, c.comm_type, c.comm_status
    FROM silver.communication_hierarchy c
    JOIN traverse t ON c.parent_key = t.node_key
    WHERE p_max_depth IS NULL
       OR t.relative_depth + 1 <= p_max_depth
)
SELECT * FROM traverse
ORDER BY depth, path_key
$$;

COMMENT ON FUNCTION silver.fn_traverse_hierarchy(bigint, integer) IS
'Walk the communication hierarchy from a root node with optional depth limit. Read-only CTE.';
