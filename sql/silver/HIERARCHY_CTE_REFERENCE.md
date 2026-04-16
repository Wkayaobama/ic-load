# Hierarchy CTE Reference

Two pg functions handle the hierarchy unflattening at the silver layer.
They share the `silver` schema but do not touch each other.

## Data flow

```
staging.stg_communication_normalised ──┐
staging.stg_contact_normalised ────────┤
staging.stg_company_normalised ────────┘
        │
        ▼
silver.fn_build_communication_hierarchy()
        │
        ▼
silver.communication_hierarchy
  ├── depth 0: Company nodes
  ├── depth 1: Person nodes (company-scoped)
  └── depth 2: Communication nodes (leaf)
        │
        ▼
dbt fct_communication_* marts read from silver.communication_hierarchy


staging.v_company_with_parent ─────────┐  (view resolving parent_company_id)
        │                              │
        ▼                              │
silver.fn_build_company_tree() ────────┘
        │
        ▼
silver.company_tree
  ├── depth 0: Root companies (no parent or orphaned parent)
  ├── depth N: Subsidiaries, with is_cycle flag on loops
  └── ancestors[]: full path from root to node
```

---

## A. Communication hierarchy — `fn_build_communication_hierarchy`

### Column mapping

The function reads from `stg_communication_normalised` and JOINs for names:

| Hierarchy column | Source table | Source column | Notes |
|---|---|---|---|
| `company_id` (entity_id at depth 0) | stg_communication_normalised | `company_id` | FK to Company |
| Company name (node_name at depth 0) | stg_company_normalised | `comp_name` | LEFT JOIN on `comp_companyid = company_id` |
| `person_id` (entity_id at depth 1) | stg_communication_normalised | `person_id` | FK to Contact |
| Person name (node_name at depth 1) | stg_contact_normalised | `pers_firstname \|\| ' ' \|\| pers_lastname` | LEFT JOIN on `pers_personid = person_id` |
| `comm_communicationid` (comm_id at depth 2) | stg_communication_normalised | `comm_communicationid` | PK |
| `comm_subject` (node_name at depth 2) | stg_communication_normalised | `comm_subject` | Falls back to `'Communication #' \|\| id` if blank |
| `comm_type` | stg_communication_normalised | `comm_type` | |
| `comm_action` | stg_communication_normalised | `comm_action` | |
| `comm_status` | stg_communication_normalised | `comm_status` | |

### Node key stability

Each level computes its offset from the prior level's `MAX(node_key)`:

```
Level 0 (companies):      1 … N_companies           = row_number() OVER (ORDER BY company_id)
Level 1 (persons):        N+1 … N+M                 = N + row_number() OVER (ORDER BY company_id, person_id)
Level 2 (communications): N+M+1 … N+M+P             = N+M + row_number() OVER (ORDER BY comm_communicationid)
```

No global sequence — no lock contention, deterministic across re-runs.

### Path key design

`path_key` uses IDs only (never labels):

```
depth 0:  "42"                      → company_id = 42
depth 1:  "42|117"                  → company 42, person 117
depth 2:  "42|117|90001"            → company 42, person 117, comm 90001
```

A pipe character inside a company name or subject line CANNOT corrupt the
path because the path is built from numeric IDs. `path_label` is display
text and may contain pipes — it is never used for joins.

### Person scoping

A person appearing at two companies gets two separate depth-1 nodes. This
is intentional: the hierarchy is company-scoped. Person 117 at Company 42
and Person 117 at Company 55 are different hierarchy branches with
different `path_key` values (`"42|117"` vs `"55|117"`).

### Prerequisites (import order)

The function JOINs against:
- `stg_company_normalised` (for company names) → Company entity must be loaded first
- `stg_contact_normalised` (for person names) → Contact entity must be loaded first

Import order `Company → Contact → Communication` guarantees both are available.

---

## B. Company tree — `fn_build_company_tree`

### The parent_company_id dependency

`stg_company_normalised` does NOT have a `parent_company_id` column. The
parent-child relationship comes from:

1. **Sibling company pipeline** (create_company_hierarchy.py) — the domain-trick
   algorithm identifies parent companies by domain grouping, creates native
   COMPANY records in HubSpot, and registers company-to-company associations
   (typeId 269 "Is subsidiary of" / 270 "Has subsidiary").

2. **HubSpot associations** — StackSync mirrors these to Postgres but as
   association rows, not as a column on the company table.

**To use this function**, create a view that resolves the parent:

```sql
CREATE OR REPLACE VIEW staging.v_company_with_parent AS
SELECT
    c.comp_companyid     AS company_id,
    c.comp_name          AS company_name,
    -- Resolve parent from the subsidiary association (typeId 269)
    a.from_object_id     AS parent_company_id
FROM staging.stg_company_normalised c
LEFT JOIN hubspot.associations a
    ON  a.to_object_id           = c.comp_companyid
    AND a.association_type_id    = 269;
```

Adjust the join logic if your association table has different column names.
Then call:

```sql
SELECT * FROM silver.fn_build_company_tree('staging', 'v_company_with_parent', true);
```

### Cycle guard

The cycle guard is **soft by design**:

- **Detection**: `is_cycle = true` when `company_id` already appears in the
  `ancestors[]` of the current path.
- **Prevention**: `WHERE NOT (child.company_id = ANY(ct.ancestors))` stops
  only the offending path, not the whole recursion. Other paths through the
  same company (multi-domain siblings) continue normally.
- **Visibility**: cycles are queryable:

```sql
SELECT company_id, company_name, parent_company_id, path_label, ancestors
FROM silver.company_tree
WHERE is_cycle
ORDER BY company_id;
```

### Root detection

A company is a root if:
- `parent_company_id IS NULL` (no parent declared), OR
- Its parent does not exist in the source table (orphaned reference)

This is tolerant — it won't fail on inconsistent upstream data.

---

## Verification queries

Run after `fn_build_communication_hierarchy` completes:

### Summary per company (root nodes)

```sql
SELECT
    root.node_key,
    root.node_name                       AS company,
    COUNT(*) FILTER (WHERE ch.depth = 1) AS person_count,
    COUNT(*) FILTER (WHERE ch.depth = 2) AS comm_count
FROM silver.communication_hierarchy root
JOIN silver.communication_hierarchy ch
    ON ch.path_array[1] = root.node_key::text
WHERE root.depth = 0
GROUP BY root.node_key, root.node_name
ORDER BY comm_count DESC;
```

### Traverse from a specific company

```sql
SELECT
    lpad('', relative_depth * 4, ' ') || node_name AS indented_name,
    node_type, comm_type, comm_status, path_label
FROM silver.fn_traverse_hierarchy(
    p_root_node_key => 3,
    p_max_depth     => NULL
);
```

### JSON lineage for one company

```sql
SELECT jsonb_pretty(silver.fn_get_hierarchy_json(3));
```

### Communications for a specific person (path scan)

```sql
SELECT node_key, node_name AS communication, comm_type, comm_action, path_label
FROM silver.communication_hierarchy
WHERE depth = 2 AND path_key LIKE '3|4|%'
ORDER BY node_key;
```

### Orphaned communications (data quality signal)

Communications in staging that failed to join to a person node — run after
every load as the primary QC check:

```sql
SELECT
    b.comm_communicationid,
    b.company_id,
    b.person_id,
    b.comm_subject
FROM staging.stg_communication_normalised b
WHERE NOT EXISTS (
    SELECT 1
    FROM silver.communication_hierarchy ch
    WHERE ch.comm_id = b.comm_communicationid
);
```

If this returns rows, investigate:
- `person_id IS NULL` → communication has no person link in the source
- `company_id IS NULL` → communication has no company link
- Both populated → the JOIN in Level 1 or Level 2 failed; check data types

### Company tree cycle report

```sql
SELECT company_id, company_name, path_label, ancestors
FROM silver.company_tree WHERE is_cycle ORDER BY company_id;
```

### Full company lineage with depth indicator

```sql
SELECT
    lpad('', depth * 4, ' ') || company_name AS indented_name,
    path_label, depth, ancestors
FROM silver.company_tree ORDER BY path_key;
```

---

## Performance notes

| Function | Complexity | Safe for bulk? |
|---|---|---|
| `fn_build_communication_hierarchy` | O(n) — three sequential passes over the flat table | Yes. Temp table + indexes make Level 1/2 joins efficient. |
| `fn_build_company_tree` | O(n * d) where d = max depth — recursive CTE | Yes. Company trees are typically shallow (depth < 5). |
| `fn_traverse_hierarchy` | O(subtree size) — CTE over built table | Yes with LIMIT. Without LIMIT on large trees, cap p_max_depth. |
| `fn_get_hierarchy_json` | O(subtree) with recursive PL/pgSQL per node | No. QA only. For bulk, use fn_traverse_hierarchy + LIMIT. |
