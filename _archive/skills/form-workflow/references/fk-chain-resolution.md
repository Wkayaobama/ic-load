# FK Chain Resolution Pattern

Extracted from `custom_objects/contact_company_assoc_stacksync_plan.md`. This is the generic pattern used by all form workflow association resolution.

## The Chain

```
staging.stg_{source}_normalised
    │
    │  {source_fk} (e.g. pers_companyid)
    ▼
hubspot.{target_table}
    │  {target_canonical_key} = {source_fk}  (e.g. icalps_company_id)
    │
    │  → resolves to hubspot.{target_table}.id
    ▼
hubspot.{source_table}.{association_column} = resolved.id::text
```

## SQL Pattern

```sql
-- Preview (dry run) — run this first to verify expected associations
SELECT
    src_hs.id              AS source_hs_id,
    resolved.id            AS target_hs_id,
    resolved.name          AS target_name,
    src.{source_fk}        AS source_fk_value
FROM staging.stg_{source}_normalised src
JOIN hubspot.{source_table} src_hs
    ON src_hs.{source_canonical_key} = src.{source_pk}::text
JOIN hubspot.{target_table} resolved
    ON resolved.{target_canonical_key} = src.{source_fk}::text
WHERE src_hs.{association_column} IS DISTINCT FROM resolved.id::text;

-- Apply — UPDATE the association column
UPDATE hubspot.{source_table} src_hs
SET    {association_column} = resolved.id::text
FROM   staging.stg_{source}_normalised src
JOIN   hubspot.{target_table} resolved
    ON resolved.{target_canonical_key} = src.{source_fk}::text
WHERE  src_hs.{source_canonical_key} = src.{source_pk}::text
  AND  src_hs.{association_column} IS DISTINCT FROM resolved.id::text;
```

## Concrete Instances

### Contact → Company
```sql
UPDATE hubspot.contacts hsc
SET    associatedcompanyid = hscomp.id::text
FROM   staging.stg_contact_normalised c
JOIN   hubspot.companies hscomp
    ON hscomp.icalps_company_id = c.pers_companyid::text
WHERE  hsc.icalps_contact_id = c.pers_personid::text
  AND  hsc.associatedcompanyid IS DISTINCT FROM hscomp.id::text;
```

### Deal → Company
```sql
UPDATE hubspot.deals hsd
SET    associations_company = hscomp.id::text
FROM   staging.stg_opportunity_normalised d
JOIN   hubspot.companies hscomp
    ON hscomp.icalps_company_id = d.oppo_primarycompanyid::text
WHERE  hsd.icalps_deal_id = d.oppo_opportunityid::text
  AND  hsd.associations_company IS DISTINCT FROM hscomp.id::text;
```

**Note:** `associations_company` column name must be confirmed against actual `hubspot.deals` schema. Run:
```sql
SELECT column_name FROM information_schema.columns
WHERE table_schema='hubspot' AND table_name='deals' AND column_name LIKE '%company%';
```

## Critical Detail: `IS DISTINCT FROM`

Standard `!=` treats NULL as unknown — `NULL != 'abc'` is NULL (falsy), so already-NULL rows are never updated. `IS DISTINCT FROM` treats NULL as a value — `NULL IS DISTINCT FROM 'abc'` is TRUE, so unset association columns are populated.

Conversely, `'abc' IS DISTINCT FROM 'abc'` is FALSE — already-correct rows are skipped. This prevents StackSync from emitting spurious outgoing syncs for unchanged records.
