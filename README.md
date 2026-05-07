# ic-load

**Repo:** `https://github.com/Wkayaobama/ic-load`

Reusable IC'ALPS load pipeline contract and salvage spine. Covers the full
Bronze → Silver → dbt → Gold → StackSync → Association bridge lifecycle for
five CRM entities: Company, Contact, Opportunity, Communication, and Case/Ticket.

Intentionally separate from `IC-D-LOAD`. This repo is the collaboration and
Codespaces anchor; local Windows, WSL, and Codespaces checkouts are
interchangeable working copies of the same repo-root layout.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Entity Import Order and FK Cascade](#entity-import-order-and-fk-cascade)
3. [Medallion Positions](#medallion-positions)
4. [Pipeline Stages and Runner](#pipeline-stages-and-runner)
5. [Runtime Entry Points](#runtime-entry-points)
6. [context/algorithms Package](#contextalgorithms-package)
7. [context/cards — Entity Cards](#contextcards--entity-cards)
8. [GomplateRepoMix — SQL Rendering Bundle](#gomplaterepomix--sql-rendering-bundle)
9. [pipeline/ — Stage Executors](#pipeline--stage-executors)
10. [sql/rendered — Pre-rendered SQL](#sqlrendered--pre-rendered-sql)
11. [StackSync Bidirectional Sync Timing Model](#stacksync-bidirectional-sync-timing-model)
12. [Two-Pass Association Bridge](#two-pass-association-bridge)
13. [Deduplication Strategy](#deduplication-strategy)
14. [Text Normalization](#text-normalization)
15. [dbt Boundary](#dbt-boundary)
16. [Entity Live-Push Status](#entity-live-push-status)
17. [Known Blockers (Codespaces / Remote)](#known-blockers-codespaces--remote)
18. [Verification](#verification)
19. [Codespaces / Remote Use](#codespaces--remote-use)
20. [Repomix Rule](#repomix-rule)
21. [Explicit Boundary](#explicit-boundary)

---

## Architecture Overview

```
SQL Server IC'ALPS (Legacy CRM)
    │
    ▼  Bronze extraction (pyodbc / pandas)
staging.stg_*                        ← Bronze layer (raw, legacy preservation)
    │
    ▼  Silver normalization (silver.py → silver_normalise.py)
staging.stg_*_normalised             ← Silver layer (shaped, FK-resolved)
    │
    ▼  dbt (external boundary — int_* + fct_* models)
staging.fct_communication_*          ← communication bridge tables
    │
    ▼  Gold upsert (gold.py — INSERT … ON CONFLICT DO UPDATE)
hubspot.companies / contacts / deals / calls / notes / tasks
    │
    ▼  STACKSYNC_SYNC checkpoint (sync.py)
stacksync_record_id_* columns populated by StackSync after outgoing+incoming sync
    │
    ▼  Association bridge (associations.py — two-pass UUID + legacy)
hubspot.associations_*               ← idempotent bridge rows (NOT EXISTS guard)
```

**StackSync resolution columns:**

| Entity     | stacksync_record_id column   |
|------------|------------------------------|
| Company    | `stacksync_record_id_9vpp8v` |
| Contact    | `stacksync_record_id_nd85zc` |
| Deal       | `stacksync_record_id_87b7vd` |
| Engagement | `unique_id` (`icalps_` prefix) |

**HubSpot portal ID:** `9201667`

---

## Entity Import Order and FK Cascade

Entities must be upserted in this order — a child entity must not be promoted
before its parent exists in `hubspot.*`:

```
1. Company       (no FK dependencies)
2. Contact       → Company (REJECT on missing)
3. Opportunity   → Company (REJECT), Contact (WARN)
4. Communication → Company (WARN), Contact (WARN), Deal (WARN)
5. Case/Ticket   → Company (WARN), Contact (WARN)  [NOT YET LIVE]
```

FK cascade graph: [`GomplateRepoMix/fk_cascade_graph.mmd`](GomplateRepoMix/fk_cascade_graph.mmd)

---

## Medallion Positions

| Entity        | Bronze                       | Silver                              | dbt models                                            | Gold                         | live_push_ready |
|---------------|------------------------------|-------------------------------------|-------------------------------------------------------|------------------------------|-----------------|
| Company       | `staging.stg_company`        | `staging.stg_company_normalised`    | —                                                     | `hubspot.companies`          | **true**        |
| Contact       | `staging.stg_contact`        | `staging.stg_contact_normalised`    | —                                                     | `hubspot.contacts`           | **true**        |
| Opportunity   | `staging.stg_opportunity`    | `staging.stg_opportunity_normalised`| —                                                     | `hubspot.deals`              | **true**        |
| Communication | `staging.stg_communication`  | `staging.stg_communication_normalised` | `int_communication_classified`, `int_communication_reconciled`, `fct_communication_*` | `hubspot.calls/notes/tasks` | upsert **true** — associations opt-in |
| Case/Ticket   | `staging.stg_cases`          | `staging.stg_case`                  | —                                                     | `hubspot.tickets` (NOT LIVE) | **FALSE**       |

---

## Pipeline Stages and Runner

The runner (`pipeline/runner.py`) executes a named sequence of `PipelineStage` checkpoints:

```
BRONZE_EXTRACT → BRONZE_LOAD → SILVER_NORMALISE → SILVER_VALIDATE
→ DBT_BUILD → DEDUPE_PROBE → GOLD_VALIDATE → GOLD_UPSERT
→ STACKSYNC_SYNC → ASSOC_VALIDATE → POST_GOLD_COMPLETE
```

**Key flags:**

| Flag | Effect |
|------|--------|
| `--entity <name>` | Select entity: `company`, `contact`, `opportunity`, `communication` |
| `--probe-mode` | Dry-run through all stages, no writes |
| `--dry-run` | Skip write operations in each stage |
| `--approve-gold` | Unlock `GOLD_UPSERT` (required unless `--dry-run`) |
| `--assoc-only` | Start from `ASSOC_VALIDATE`, skip all upstream stages |
| `--enable-post-gold` | Enable `STACKSYNC_SYNC` + `ASSOC_VALIDATE` after Gold upsert |
| `--bronze-csv-override <file>` | Use CSV file instead of live Bronze extraction |

The runner requires explicit `--approve-gold` before any `hubspot.*` write.
Post-Gold StackSync sync and association bridge are behind `--enable-post-gold`.

---

## Runtime Entry Points

```bash
# Orchestration probe (dry-run, no writes)
python -m pipeline.runner --probe-mode --entity company --bronze-csv-override probe.csv

# Staging-only smoke (validates PostgreSQL contract, no hubspot.* access)
python -m pipeline.live_smoke --sample-limit 5

# Dedupe probe (read-only, never participates in live execution)
python -m pipeline.dedupe_probe --entity company

# Staging resolution probe
python -m pipeline.staging_resolution_probe

# Raw CSV → staging table shaping snippet
python -m pipeline.raw_to_staging_snippet bronze.csv staging_table --output-csv artifacts/assessment/sample.csv

# Full Company run with hierarchy + contacts association
python -m pipeline.runner --entity company --approve-gold --enable-post-gold

# Full Communication run — engagement upsert only
python -m pipeline.runner --entity communication --approve-gold

# Full Communication run — with associations
python -m pipeline.runner --entity communication --approve-gold --enable-post-gold

# Association-only run (parent entities already synced)
python -m pipeline.runner --entity communication --assoc-only

# Full Opportunity run with Notes→Deal association
python -m pipeline.runner --entity opportunity --approve-gold --enable-post-gold

# Full Contact run (owner resolution in warn mode)
python -m pipeline.runner --entity contact --approve-gold --owner-resolution-mode warn
```

---

## context/algorithms Package

Importable Python modules encoding non-negotiable pipeline logic.
All modules are deterministic and raise `ValueError` on any unknown input —
never silently producing a wrong mapping.

```
context/algorithms/
    __init__.py              — exports all public symbols
    levenshtein.py           — Wagner-Fischer edit distance + injectable scorer
    company_siblings.py      — domain hack + 3-tier parent selection
    deal_stage_mapper.py     — IC'ALPS → HubSpot stage ID mapping (authoritative)
    _stubs.py                — M4 stubs with actionable error messages
```

### levenshtein.py

True Levenshtein edit distance (Wagner-Fischer O(m×n), O(min(m,n)) space).
Used by the dedup guardrail instead of `SequenceMatcher.ratio()`.

```python
from context.algorithms.levenshtein import (
    edit_distance,      # int: minimum single-char edits
    similarity,         # float: 1 - edit_distance / max(len(a), len(b))
    LevenshteinScorer,  # default scorer class
    MCPScorer,          # injectable MCP fallback (falls back to Levenshtein if unavailable)
    get_scorer,         # → current module-level scorer
    set_scorer,         # inject a custom scorer for this process
)
```

**Scorer protocol** — any class with `.score(left, right, **kwargs) → float` satisfies
`SimilarityScorer`. Inject `MCPScorer` for communications; `LevenshteinScorer` is the
default for all other entities.

### company_siblings.py

Implements the domain-hack algorithm that creates parent/child company hierarchies.

```python
from context.algorithms.company_siblings import (
    clean_domain,               # strips https://, www., path, numeric sibling prefix
    company_root,               # tokenise name, remove stopwords
    find_plural_domain_groups,  # groups where count > 1 in staging
    select_canonical_parent,    # 3-tier rule: Gold match → highest contact_count → min comp_companyid
    assign_sibling_indices,     # parent=0, children=1..N sorted by comp_companyid ASC
    detect_all_sibling_groups,  # full pass: returns (resolved, unresolved)
    flag_cross_group_candidates,# Levenshtein across different domains ≥ 0.80
)
```

**Domain hack:** child companies receive synthetic domain `{N}.{clean_domain}` (e.g.
`1.gehealthcare.fr`). `icalps_real_domain` stores the actual business domain.
Parent keeps `clean_domain` with `icalps_sibling_index=0`.

**Unresolved groups** (no Gold-matched row) are skipped entirely — never partially mutated.

Live run baseline: 293 children, 156 parents, 151 domains, 0 errors (2026-03-10).

### deal_stage_mapper.py

The only authority for IC'ALPS stage label → HubSpot stage ID conversion.
Never call stage IDs directly in SQL; always call `map_deal_stage()`.

```python
from context.algorithms.deal_stage_mapper import (
    map_deal_stage,     # (pipeline, stage, outcome) → DealStageResult; raises ValueError
    list_all_mappings,  # → list of all 25 combinations as dicts
    normalize_stage,    # French + English normalization
    normalize_outcome,
    HUBSPOT_HARDWARE_PIPELINE_ID,  # 766126206
    HARDWARE_STAGE_IDS,            # dict: stage_name → int HubSpot ID
)
```

Supported pipeline: **Hardware** (`id=766126206`).
Stage IDs: `Identified=85103752`, `Qualified=85103753`, `Design In=85103754`,
`Design Win=85103756`, `Closed Won=85103757`, `Closed Lost=85103758`.

---

## context/cards — Entity Cards

Machine-readable YAML files encoding each entity's current medallion state.
Loaded at the top of every `GomplateRepoMix/prompts/*.txt` file before any SQL
is rendered. This prevents context drift when piping prompts from the command line.

```
context/cards/
    _schema.md          — field definitions for all YAML keys
    company.yaml        — import_order=1, live_push_ready=true
    contact.yaml        — import_order=2, live_push_ready=true
    opportunity.yaml    — import_order=3, live_push_ready=true
    communication.yaml  — import_order=4, upsert ready / associations opt-in
    case.yaml           — import_order=5, live_push_ready=FALSE (4 blockers)
```

**Card schema fields:**

| Field | Description |
|-------|-------------|
| `entity` | Canonical entity name |
| `medallion.*` | bronze/silver/gold table names |
| `primary_key` | Source PK column → target icalps_*_id column |
| `stacksync_resolution_column` | Which `stacksync_record_id_*` column drives Pass A |
| `fk_dependencies` | Parent entities with severity (REJECT / WARN) |
| `import_order` | Upsert sequence position (1–5) |
| `cardinality` | Relationship cardinalities |
| `dedup.*` | scorer, key_fields with weights, thresholds (review / block) |
| `associations.*` | type_ids and assoc_tables for this entity's bridge rows |
| `pipeline_status` | `live_push_ready`, blockers list |

**Prompt pipe usage:**

```bash
claude -p < GomplateRepoMix/prompts/company_hierarchy.txt > output/company_hierarchy.txt
claude -p < GomplateRepoMix/prompts/opportunity_association.txt > output/opportunity_assoc.txt
```

---

## GomplateRepoMix — SQL Rendering Bundle

Gomplate-based SQL rendering system. Template files → rendered SQL files via
`render_associations.sh`. **Gomplate stays SQL-only** — no Python logic in templates.

```
GomplateRepoMix/
    schema_context.yaml         — entity config, association type IDs, StackSync columns
    run_context.yaml            — per-run overrides (entity, dry_run, watermark)
    business_rules.yaml         — dedup thresholds, hierarchy rules, stage mapper authority
    text_normalization_rules.yaml
    fk_cascade_graph.mmd        — Mermaid FK dependency graph
    staging_metadata_snapshot.json
    render_associations.sh      — concrete render script (loops Calls/Notes/Tasks × targets)
    repomix.config.json         — Repomix packaging config (⚠ ../../ paths require IC_Load workspace)
    Makefile

    templates/
        association_bridge.sql.tmpl  — two-pass UUID + legacy fallback (M1 FIXED)
        upsert_entity.sql.tmpl

    prompts/
        company_hierarchy.txt        — ENTITY CARD LOAD → company.yaml
        contact_owner_lineage.txt    — ENTITY CARD LOAD → contact.yaml
        opportunity_association.txt  — ENTITY CARD LOAD → opportunity.yaml
        communication_association.txt — ENTITY CARD LOAD → communication.yaml
        case_stage_ticket.txt        — ENTITY CARD LOAD → case.yaml
```

**Render all association SQL:**

```bash
cd GomplateRepoMix
bash render_associations.sh
# Produces: sql/rendered/association_{type}_{target}.sql for all 7 patterns
# Verifies: each output contains both "-- Pass A:" and "-- Pass B:" markers
```

**Rendered patterns** (7 total):

| Comm type | Target  | assoc_type_id |
|-----------|---------|---------------|
| Calls     | company | 182           |
| Calls     | contact | 194           |
| Notes     | company | 190           |
| Notes     | contact | 202           |
| Notes     | deal    | 214           |
| Tasks     | company | 192           |
| Tasks     | contact | 204           |

**Meetings:** DEFERRED — 99.2% unreconciled (58,581/59,043 rows); type IDs not confirmed.

> **Note on `repomix.config.json`:** `../../` include paths (e.g.
> `../../ic_load_pipeline/python-ignorethis/...`) are workspace-relative and
> require the full `IC_Load/` workspace checkout. They resolve correctly from
> `C:\...\AnthonySalesOps\Codebase\IC_Load\ic-load\` but break in a fresh
> Codespaces clone of this repo alone.

---

## pipeline/ — Stage Executors

```
pipeline/
    runner.py               — PipelineHooks, run(), all stage dispatch, CLI entry
    state.py                — PipelineStage enum, PipelineContext
    bronze.py               — BRONZE_EXTRACT + BRONZE_LOAD
    silver.py               — SILVER_NORMALISE (thin wrapper → importlib → python-ignorethis)
    gold.py                 — GOLD_UPSERT: routes entity → SQL rendering function
    sync.py                 — StackSyncCheckpoint.wait() (dry_run/poller/assumed modes)
    associations.py         — AssociationBridgeExecutor reads schema_context.yaml patterns
    dedupe.py               — DedupeGuardrail; uses get_scorer() from context.algorithms.levenshtein
    dedupe_probe.py         — CLI wrapper for dedupe probe (read-only)
    probe.py                — orchestration probe (all stages, no writes)
    live_smoke.py           — staging-only smoke (no hubspot.* access)
    staging_resolution_probe.py
    raw_to_staging_snippet.py
    text_normalization.py   — universal cross-entity text cleanup
```

---

## sql/rendered — Pre-rendered SQL

Pre-rendered output of `render_associations.sh`. Checked in as reference;
re-rendering from `GomplateRepoMix/templates/` must produce identical output.

```
sql/rendered/
    upsert_company.sql
    upsert_person.sql
    upsert_opportunity.sql
    engagement_calls.sql
    engagement_notes.sql
    engagement_tasks.sql
    engagement_meetings.sql           — shape-only; NOT in association bridge
    association_calls_company.sql     — two-pass (UUID + legacy)
    association_calls_contact.sql
    association_notes_company.sql
    association_notes_contact.sql
    association_notes_deal.sql
    association_tasks_company.sql
    association_tasks_contact.sql
```

---

## StackSync Bidirectional Sync Timing Model

Understanding this model is critical — it explains why the two-pass bridge is
mandatory, not optional.

```
1. GOLD_UPSERT      → INSERT/UPDATE hubspot.* via SQL (stacksync_record_id_* is NULL for new rows)
2. STACKSYNC_SYNC   → StackSync detects changed rows in hubspot.* (outgoing sync trigger)
3.                  → StackSync pushes to HubSpot API
4.                  → StackSync pulls HubSpot API state back into hubspot.*
5.                  → stacksync_record_id_* columns are now populated/refreshed
6. ASSOC_VALIDATE   → association bridge SQL now has valid stacksync_record_id_* to join on
```

**Pass A requires STACKSYNC_SYNC to have completed.** Pass B (legacy ID fallback)
handles records that were not yet synced when the bridge runs.

---

## Two-Pass Association Bridge

Each rendered association SQL uses a UNION of two passes, both with a `NOT EXISTS`
idempotency guard:

```sql
-- Pass A: UUID path (requires StackSync to have populated stacksync_record_id_*)
SELECT DISTINCT <type_id>, target.id, comm.id
FROM hubspot.<comm_table> AS comm
INNER JOIN staging.<fct_table> AS fct ON comm.unique_id = 'icalps_' || fct.icalps_communication_id::text
INNER JOIN hubspot.<target_table> AS target ON fct.associated_<target>_id::text = target.<stacksync_col>::text
WHERE fct.associated_<target>_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM hubspot.<assoc_table> WHERE ...)

UNION

-- Pass B: Legacy ID fallback (for records not yet UUID-reconciled)
SELECT DISTINCT <type_id>, target.id, comm.id
FROM hubspot.<comm_table> AS comm
INNER JOIN staging.<fct_table> AS fct ON comm.unique_id = 'icalps_' || fct.icalps_communication_id::text
INNER JOIN hubspot.<target_table> AS target ON fct.legacy_<target>_id::text = target.icalps_<target>_id::text
WHERE fct.associated_<target>_id IS NULL
  AND fct.legacy_<target>_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM hubspot.<assoc_table> WHERE ...)
```

**UNION (not UNION ALL)** prevents the same pair appearing in both passes.
**NOT EXISTS** prevents duplicate association rows on re-runs.
**`unique_id LIKE 'icalps_%'`** ensures only IC'ALPS-sourced engagements are bridged.

---

## Deduplication Strategy

The dedupe guardrail (`pipeline/dedupe.py`) is **probe-only** — it does not
participate in live execution. Use `python -m pipeline.dedupe_probe` for calibration.

**Scorer:** `context.algorithms.levenshtein.LevenshteinScorer` (Wagner-Fischer edit
distance, O(m×n)). More precise than `SequenceMatcher.ratio()` for short identity
strings at the dedup threshold boundary.

**Injectable MCP scorer:** `MCPScorer` can be injected for semantic similarity cases
(e.g. Communication subject). Falls back to Levenshtein if MCP is unavailable.

```python
from context.algorithms.levenshtein import MCPScorer, set_scorer
set_scorer(MCPScorer(call_fn=my_mcp_client.call))
```

**Per-entity dedup key fields and thresholds:**

| Entity        | Primary signal              | Weight | Review ≥ | Block ≥ |
|---------------|-----------------------------|--------|----------|---------|
| Company       | `comp_website` (domain)     | 0.45   | 0.65     | 0.82    |
| Contact       | `icalps_email` (email)      | 0.65   | 0.60     | 0.80    |
| Opportunity   | `oppo_description` (lev.)   | 0.45   | 0.62     | 0.78    |
| Communication | `unique_id` (exact)         | —      | exact    | exact   |
| Case/Ticket   | `subject` (levenshtein)     | 0.45   | 0.65     | 0.82    |

---

## Text Normalization

Universal cross-entity rule applied at Silver normalization:

- UTF-8 cleaning (mojibake → proper characters)
- Strip unsafe control characters (preserve meaningful line breaks for long-form text)
- Normalize company/contact names
- Deterministic date serialization (ISO-8601, `YYYY-MM-DD`)

Implementation: [`pipeline/text_normalization.py`](pipeline/text_normalization.py)
Contract: [`GomplateRepoMix/text_normalization_rules.yaml`](GomplateRepoMix/text_normalization_rules.yaml)

---

## dbt Boundary

dbt is an **external boundary** for Communication. The runner calls `dbt build` as a
subprocess; `ic-load` does not author dbt models.

**dbt models in scope:**

| Model | Purpose |
|-------|---------|
| `int_communication_classified` | Maps `Comm_Action` → `hubspot_activity_class` (calls/notes/tasks) |
| `int_communication_reconciled` | Attaches resolved `stacksync_record_id_*` UUIDs to each communication row |
| `fct_communication_calls` | Bridge table for Calls associations |
| `fct_communication_notes` | Bridge table for Notes associations |
| `fct_communication_tasks` | Bridge table for Tasks associations |
| `fct_communication_meetings` | Shape-only; excluded from association bridge (deferred) |

**Meetings deferral rule:** Do NOT add Meetings to any SQL, association pattern, or
`schema_context.yaml` entry until: (1) UUID readiness > 50%, (2) type IDs confirmed from portal.
Current state: 99.2% unreconciled (58,581 / 59,043 rows).

---

## Entity Live-Push Status

| Entity        | live_push_ready | Blockers |
|---------------|-----------------|----------|
| Company       | ✅ true         | — |
| Contact       | ✅ true         | — |
| Opportunity   | ✅ true         | — |
| Communication | ✅ upsert true / associations opt-in | Meetings deferred |
| Case/Ticket   | ❌ FALSE        | (1) `case_stage_mapper` module missing; (2) association type IDs not confirmed; (3) staging match rate 74.1% (must reach >95%); (4) `stacksync_record_id_*` column name not confirmed |

---

## Known Blockers (Codespaces / Remote)

**M1 — Gomplate template single-pass:** FIXED. `association_bridge.sql.tmpl` now
emits the correct two-pass UNION pattern.

**M2 — Hardcoded PostgreSQL credentials in `unflatten_hierarchy.py`:** FIXED.
Replaced with `os.environ["ICALPS_DB_*"]` reads matching `context/config.py` contract.

**M3 — `repomix.config.json` uses `../../` paths:** DOCUMENTED (not auto-fixed).
These resolve from the full `IC_Load/` workspace checkout. In a fresh Codespaces
clone of `ic-load` alone they will not resolve. Decision: require full workspace
checkout OR copy non-negotiable algorithm files into `ic-load/context/algorithms/`.

**M4 — `silver.py` loads from sibling workspace path:** `pipeline/silver.py` uses
`importlib` to load `silver_normalise.py` and `validate_silver.py` from
`PROJECT_ROOT.parent / "ic_load_pipeline" / "python-ignorethis"`. This works
locally when `IC_Load/` is the parent directory; breaks in a fresh Codespaces clone.
`context/algorithms/_stubs.py` provides actionable error messages pointing to
the promotion path.

**M5 — Meetings have no association type IDs:** DOCUMENTED. Explicit deferral note
added to `schema_context.yaml` and `context/cards/communication.yaml`.

---

## Verification

```powershell
# From repo root
pytest tests -q -p no:cacheprovider
```

Staging-only assessment artifacts (no `hubspot.*` access):

- `artifacts/assessment/entity_translation_probe_sample.csv`
- `artifacts/assessment/case_ticket_snippet.csv`

Render verification:

```bash
bash GomplateRepoMix/render_associations.sh
# Each output file must contain both "-- Pass A:" and "-- Pass B:" markers
```

---

## Codespaces / Remote Use

1. Install dependencies: `pip install -r requirements.txt`
2. Post-create script: `scripts/codespace-smoke.sh`
3. Required Codespaces secrets:
   - `ICALPS_DB_HOST`
   - `ICALPS_DB_USER`
   - `ICALPS_DB_PASSWORD`
   - `ICALPS_DB_PORT` (default: `5432`)
   - `ICALPS_DB_NAME` (default: `postgres`)
4. Default safe path: orchestration probe + staging-only smoke (no Gold-layer writes)

Layout conventions:

| Environment | Path |
|-------------|------|
| Preferred Codespaces | `/workspaces/icalps` |
| Standard Windows | `C:\...\IC_Load\ic-load` |
| Optional WSL | `/home/<user>/src/ic-load` |

Use the Linux filesystem inside WSL rather than `/mnt/c/...` if using WSL for Python tooling.

---

## Repomix Rule

Gomplate stays SQL-only.

**Include in Repomix bundle:**
- rendered SQL (`sql/rendered/`)
- schema and run context (`GomplateRepoMix/schema_context.yaml`, `run_context.yaml`)
- validation rules (`ValidationRules/`)
- FK cascade graph (`GomplateRepoMix/fk_cascade_graph.mmd`)
- staging metadata snapshot (`GomplateRepoMix/staging_metadata_snapshot.json`)
- text normalization rules (`GomplateRepoMix/text_normalization_rules.yaml`)
- raw-to-staging transformation primitive (`pipeline/raw_to_staging_snippet.py`)
- communication unflattening context (`docs/AD_HOC_TRANSFORM_CONTEXT.md`)
- company hierarchy context (`context/algorithms/company_siblings.py`)
- association probe state (`docs/ASSOCIATION_PROBE_TECHNICAL_STATE.md`)
- functionality coverage matrix (`docs/FUNCTIONALITY_COVERAGE_MATRIX.md`)

**Exclude from Repomix bundle:**
- Bronze payload archives
- `memory/`
- benchmark dumps
- `artifacts/`
- direct `hubspot.*` exports

---

## Explicit Boundary

**This repo covers:**
- PostgreSQL Bronze load/watermark orchestration
- Silver gate orchestration
- dbt as an external boundary
- probe-only dedupe guardrail
- explicit Gold validation gate before any live `hubspot.*` write
- Gold upsert and communication engagement SQL rendering
- optional post-Gold sync/association path (behind `--enable-post-gold`)
- collaborator environment standardization
- non-negotiable algorithm modules (`context/algorithms/`)
- entity state cards (`context/cards/`)

**This repo does not cover:**
- Snakemake rule authoring
- dbt model authoring
- Bronze payload archives, benchmark dumps, or `memory/`
- Extraction-side workbook/UI tooling

---

## Repository

`https://github.com/Wkayaobama/ic-load`
