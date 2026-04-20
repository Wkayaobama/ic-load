-- ═══════════════════════════════════════════════════════════════════════════
-- Silver Layer — Hierarchy Schema + Tables
--
-- Creates the `silver` schema and the two hierarchy target tables:
--   silver.communication_hierarchy  — Company → Person → Communication
--   silver.company_tree             — self-referential Company → Subsidiary
--
-- Run ONCE before any fn_build_* invocation. Idempotent (IF NOT EXISTS).
-- See IC_Load_Production_Plan.md §5.2 (ENTITY_POSTPROCESS entries).
-- ═══════════════════════════════════════════════════════════════════════════

-- Required by pipeline.dedupe for Levenshtein scoring. Needs superuser on
-- first install; IF NOT EXISTS makes subsequent runs by the pipeline role safe.
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;

CREATE SCHEMA IF NOT EXISTS silver;


-- ── A. Communication hierarchy ────────────────────────────────────────────
--    Three depth levels:
--      0 = Company  (root, parent_key IS NULL)
--      1 = Person   (scoped per company via path_key)
--      2 = Communication (leaf)
--
--    path_key  : pipe-delimited numeric ID path → "3|4|1"
--    path_label: pipe-delimited name path      → "Acme|Wim VOS|Suivi Vos"
--    path_array: generated column split of path_key (for ANY / @> queries)

CREATE TABLE IF NOT EXISTS silver.communication_hierarchy (
    node_key    bigint      PRIMARY KEY,
    node_name   text        NOT NULL,
    parent_key  bigint,
    depth       integer     NOT NULL DEFAULT 0,
    path_key    text        NOT NULL UNIQUE,
    path_label  text,
    node_type   text        NOT NULL,
    entity_id   bigint,                     -- company_id or person_id; NULL for comms
    comm_id     bigint,                     -- comm_communicationid; populated at depth=2
    comm_type   text,
    comm_action text,
    comm_status text,
    path_array  text[]
        GENERATED ALWAYS AS (string_to_array(path_key, '|')) STORED,
    loaded_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_ch_parent FOREIGN KEY (parent_key)
        REFERENCES silver.communication_hierarchy (node_key)
        DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT chk_ch_node_type
        CHECK (node_type IN ('company', 'person', 'communication'))
);

CREATE INDEX IF NOT EXISTS idx_ch_parent   ON silver.communication_hierarchy (parent_key);
CREATE INDEX IF NOT EXISTS idx_ch_path_key ON silver.communication_hierarchy (path_key);
CREATE INDEX IF NOT EXISTS idx_ch_type     ON silver.communication_hierarchy (node_type);
CREATE INDEX IF NOT EXISTS idx_ch_entity   ON silver.communication_hierarchy (entity_id);
CREATE INDEX IF NOT EXISTS idx_ch_comm     ON silver.communication_hierarchy (comm_id);
CREATE INDEX IF NOT EXISTS idx_ch_depth    ON silver.communication_hierarchy (depth);


-- ── B. Company self-referential hierarchy ─────────────────────────────────
--    A company may appear on multiple paths (DAG, not pure tree).
--    PRIMARY KEY on (company_id, path_key) allows the same company
--    to appear on N distinct paths without collision.
--    is_cycle = true flags rows where the algorithm detected a cycle
--    in the source data (logged, not fatal).

CREATE TABLE IF NOT EXISTS silver.company_tree (
    node_key            bigint      NOT NULL,
    company_id          bigint      NOT NULL,
    company_name        text        NOT NULL,
    parent_company_id   bigint,
    depth               integer     NOT NULL DEFAULT 0,
    path_key            text        NOT NULL,
    path_label          text,
    ancestors           bigint[]    NOT NULL DEFAULT '{}',
    is_cycle            boolean     NOT NULL DEFAULT false,
    loaded_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, path_key)
);

CREATE INDEX IF NOT EXISTS idx_ct_company ON silver.company_tree (company_id);
CREATE INDEX IF NOT EXISTS idx_ct_parent  ON silver.company_tree (parent_company_id);
CREATE INDEX IF NOT EXISTS idx_ct_path    ON silver.company_tree (path_key);
CREATE INDEX IF NOT EXISTS idx_ct_cycle   ON silver.company_tree (is_cycle) WHERE is_cycle;
