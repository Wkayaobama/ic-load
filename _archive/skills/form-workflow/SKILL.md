# Skill: Form-Driven CRM Workflow

Use when building or extending event-driven CRM automation where a HubSpot form submission triggers entity creation, association resolution, and pipeline/stage assignment — all through the StackSync-managed Postgres database, without direct HubSpot API calls in the data path.

---

## 1. Synced Postgres as Integration Surface

The StackSync-managed Postgres instance is a bidirectional mirror of HubSpot. Writing to `hubspot.*` tables in Postgres is equivalent to writing to HubSpot — StackSync's outgoing sync propagates changes within ~1 minute.

This means:
- **Entity creation** = INSERT into `hubspot.deals` / `hubspot.contacts` / `hubspot.companies` → StackSync creates the HubSpot record
- **Association resolution** = UPDATE `hubspot.contacts.associatedcompanyid = <resolved_company_id>` → StackSync creates the contact↔company association in HubSpot
- **Property enrichment** = UPDATE any column on `hubspot.*` → StackSync syncs the property value

Direct HubSpot API calls are used ONLY for one-time configuration operations (form creation, property creation) — never for data flow. The `hubspot-client/` package handles these config operations via `requests` + Bearer token.

**Why this matters:** SQL UPDATE + StackSync outgoing sync replaces per-record API calls, retry logic, rate limiting, and authentication token management. One SQL statement, one commit, StackSync handles the rest.

---

## 2. Form → Workflow → Association Chain

The event-driven flow for a single form submission:

```
Manager submits HubSpot form
    │  (internal tooling — not customer-facing)
    ▼
StackSync Workflow triggers (webhook on managed endpoint)
    │
    ▼
postgres-query module executes fn_resolve_association()
    │  on managed Postgres (server-side, no external calls)
    │
    ├── contact→company: pers_companyid → icalps_company_id → companies.id
    ├── deal→company: oppo_primarycompanyid → icalps_company_id → companies.id
    └── opportunity: + JOIN staging.seed_deal_stage_map for pipeline/stage
    │
    ▼
StackSync outgoing sync pushes UPDATE to HubSpot (~1 min)
    │
    ▼
Manager verifies in HubSpot filtered view:
    deal created, company associated, pipeline/stage set
```

**All workflows use `postgres-query` modules only.** No custom connectors, no HTTP modules, no API proxy, no external services. Everything executes server-side on managed Postgres.

---

## 3. Entity-Agnostic FK Chain Resolution

The same SQL pattern resolves any entity pair. The function `fn_resolve_association(source_entity, target_entity, dry_run)` handles:

```sql
UPDATE hubspot.{target} t
SET {association_column} = resolved.id::text
FROM staging.stg_{source}_normalised s
JOIN hubspot.{target_table} resolved
    ON resolved.{target_canonical_key} = s.{source_fk}::text
WHERE t.{source_canonical_key} = s.{source_pk}::text
  AND t.{association_column} IS DISTINCT FROM resolved.id::text
```

`IS DISTINCT FROM` is critical — it prevents writing unchanged rows, which would trigger spurious StackSync outgoing syncs. Only actually-changed rows are committed, so StackSync only pushes real changes to HubSpot.

**FK chains (hardcoded per entity pair):**

| Source → Target | FK Column | Canonical Key | Resolves To |
|---|---|---|---|
| Contact → Company | `pers_companyid` | `icalps_company_id` | `hubspot.companies.id` |
| Deal → Company | `oppo_primarycompanyid` | `icalps_company_id` | `hubspot.companies.id` |
| Opportunity → Company | same as deal | same | same + seed table JOIN for pipeline/stage |

---

## 4. Deal Stage Mapping via Seed Table

The batch pipeline uses `deal_stage_mapper.py` (Python) which raises `ValueError` on unmapped pipeline/stage/outcome combinations. This safety contract cannot run inside a `postgres-query` module.

The form workflow translates this to SQL:

- `staging.seed_deal_stage_map` table holds the same mapping as the Python dict
- The workflow SQL JOINs against it
- NULL result on unmapped combination = row excluded from the UPDATE
- The workflow summary node reports `unmapped_count` so the operator knows to add the missing mapping

| Concern | Batch pipeline | Form workflow |
|---|---|---|
| Source | `deal_stage_mapper.py` dict | `staging.seed_deal_stage_map` table |
| Safety | `raise ValueError` → FAILED | NULL excluded → summary reports unmapped count |
| Fix | Edit Python dict, re-run | Add row to seed table, re-trigger workflow |
| Authority | Python dict is authoritative; seed table is derived from it |

---

## 5. When to Use What

| Mechanism | Use for | Example |
|---|---|---|
| **StackSync Sync** (continuous bulk) | Ongoing bidirectional data sync | `hubspot.companies` ↔ HubSpot Companies |
| **StackSync Workflow** (event-triggered) | Form submission → association resolution | `fn_resolve_association()` via `postgres-query` module |
| **Python script** (one-time config) | Form creation, property creation | `hubspot-client/create_form.py --mode create` |
| **Batch pipeline** (runner) | Bronze → Silver → Gold scheduled ETL | `python -m pipeline.runner --entity company` |

The form workflow and the batch pipeline are **parallel systems**. The batch pipeline handles bulk data loads on a schedule. The form workflow handles event-driven record creation + association in real time. They share the same Postgres tables but do not depend on each other at runtime.

---

## 6. User Experience

The primary user is a **manager-operator** who submits forms, makes calls, and monitors tasks — all within HubSpot. No separate UI.

**After form submission, the manager expects:**
1. Deal appears in HubSpot with correct pipeline/stage (~1 min via StackSync)
2. Company association resolved automatically (no manual linking)
3. Task appears in task queue (if workflow creates one)
4. All form field values landed on the record

**Failure is silent.** The manager discovers issues only by checking filtered views. The workflow summary node and `unmapped_count` metric are the builder's diagnostic — not the manager's.

---

## 7. Files in This Feature

```
skills/form-workflow/
├── SKILL.md                              ← this file
└── references/
    ├── fk-chain-resolution.md            ← generic FK pattern
    └── stacksync-workflow-anatomy.md      ← edge/module/trigger conventions

hubspot-client/                            ← separate package, no pipeline deps
├── config.py                              ← HUBSPOT_ACCESS_TOKEN, HUBSPOT_PORTAL_ID
├── forms.py                               ← form CRUD (migrated from legacy)
├── create_form.py                         ← form creation + CSV schema + preflight
├── requirements.txt                       ← requests only
└── reference/create-form.js               ← JS reference (not deployed)

sql/functions/fn_resolve_association.sql    ← entity-agnostic FK resolver
sql/seeds/seed_deal_stage_map.sql          ← deal stage mapping (from Python dict)

workflows/
├── contact_company_enrichment.yaml        ← Contact → Company association
├── deal_company_enrichment.yaml           ← Deal → Company association
├── opportunity_intake_workflow.yaml        ← Deal creation + stage + association
└── form_association_workflow.yaml          ← Generic entity dispatch
```
