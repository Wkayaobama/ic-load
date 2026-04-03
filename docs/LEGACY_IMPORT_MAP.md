# Legacy Import Map

## Purpose

This map tells us what to salvage from `ic_load_pipeline/python-ignorethis` and where it should land in `ic-load`.

The goal is not to preserve file names.
The goal is to preserve the canonical runtime behavior with less surface area.

## Decision Labels

- `keep-and-adapt`: move the behavior into the new repo with cleanup
- `template-and-render`: preserve the pattern through Gomplate SQL
- `defer`: useful later, but not required for first-wave 85% runtime coverage
- `drop`: keep out of the clean runtime repo

## Core Runtime Modules

| Legacy source | Decision | New home | Notes |
| --- | --- | --- | --- |
| `pipeline_state.py` | keep-and-adapt | `pipeline/state.py` | Becomes the canonical state machine and run artifact contract. |
| `runners/run_company_pipeline.py` | keep-and-adapt | `pipeline/runner.py` | Keep explicit stage orchestration, but insert a named sync checkpoint between Gold write and associations. |
| `pipeline_config.py` | keep-and-adapt | `context/config.py` | Fold entity metadata and path/env helpers into one cleaned config surface. |
| `db.py` | keep-and-adapt | `context/db.py` | Keep connection helpers, but remove hardcoded environment ambiguity. |
| `silver_normalise.py` | keep-and-adapt | `pipeline/silver.py` | Preserve entity cleaning/dedup logic while shrinking legacy branching. |
| `validate_silver.py` | keep-and-adapt | `pipeline/silver.py` | Validation remains a blocking stage owned by the Silver boundary. |
| `deal_stage_mapper.py` | keep-and-adapt | `pipeline/silver.py` or `context/mappings.py` | Survives because stage mapping mistakes were a real historical failure mode. |
| `prepare_for_upsert.py` | keep-and-adapt | `pipeline/gold.py` | Keep only if it still owns pre-upsert shaping not already covered by dbt. |
| `upsert_to_gold.py` | template-and-render | `sql/templates/` + `pipeline/gold.py` | Rewrite hardcoded SQL into Gomplate-rendered upsert patterns executed by a thin runner. |
| `engagement/upsert_engagements.py` | template-and-render | `sql/templates/` + `pipeline/gold.py` | Same rule: preserve logic, but move repetitive SQL into templates and keep Python thin. |
| `engagement/create_associations.py` | template-and-render | `sql/templates/` + `pipeline/associations.py` | Preserve two-pass reverse lookup and `NOT EXISTS` idempotency guard. |
| `custom_objects/create_company_hierarchy.py` | keep-and-adapt | `pipeline/associations.py` | Keep only the sibling/company association behavior that remains part of the supported runtime. |
| `tests/test_pipeline_transitions.py` | keep-and-adapt | `tests/test_pipeline_state.py` | First test to port. |
| `tests/test_communication_reconciliation.py` | keep-and-adapt | `tests/test_communication_pipeline.py` | Port after the dbt boundary and communication runner contract are stabilized. |

## dbt Boundary

| Legacy source | Decision | New home | Notes |
| --- | --- | --- | --- |
| `run_silver_pipeline.py` | defer | `pipeline/runner.py` or `docs/` | Mine for orchestration hints only if it adds value beyond the current runner. |
| `process_silver_layer.py` | defer | `dbt/` or `pipeline/silver.py` | Re-evaluate only if it owns logic not already captured in dbt or Silver normalize. |
| `process_opportunities.py` | defer | `pipeline/silver.py` | Likely folded into entity-specific Silver behavior if still needed. |

The key rule is:
if communication unflattening/classification already lives in dbt, it stays in `dbt/`.
We do not migrate that into Gomplate or Python unless the legacy record proves it lives elsewhere.

## Modules To Keep Out Of The Clean Runtime Repo

| Legacy source | Decision | Reason |
| --- | --- | --- |
| `export_to_xlsx.py` | drop | manual review/export UI is outside the runtime core |
| `export_staging_for_manual_review.py` | drop | review package generation belongs to pre-runtime validation workflow |
| `add_missing_pending_tasks.py` | defer | useful repair utility, not first-wave core |
| `create_associations.py` at root | defer | superseded by engagement-focused association path unless a missing use case is confirmed |
| `engagement/recover_orphan_associations.py` | defer | second-wave repair tooling |
| `engagement/recover_notes_company_associations.py` | defer | second-wave repair tooling |
| `engagement/ft_orphan_resolution.py` | defer | likely useful, but not required for first working minimal runtime |
| `engagement/build_inference_table.py` | defer | analytics/repair sidecar, not core path |
| `engagement/load_custom_object_tasks.py` | defer | custom-object path is valuable but should not block the core repack |
| `engagement/owner_map.py` | defer | pull in later only if not subsumed by Silver mapping |
| `CLAUDE.md`, `SKILL.md`, `ADHOC_API_REFERENCE.md`, `orphan-resolution.md`, reporting notes | drop | reference material, not runtime code |

## Migration Pattern

When importing behavior from legacy into `ic-load`, use this sequence:

1. isolate the business rule
2. decide whether it belongs to `context/`, `pipeline/`, `sql/`, or `dbt/`
3. convert repetitive SQL into Gomplate templates
4. keep Python orchestration thin and explicit
5. add or port a focused test
6. document the boundary if it is easy to get wrong

## First Files To Port

These are the first practical extraction targets:

1. `pipeline_state.py`
2. `runners/run_company_pipeline.py`
3. `validate_silver.py`
4. `silver_normalise.py`
5. SQL patterns now represented in `upsert_to_gold.py`
6. SQL patterns now represented in `engagement/upsert_engagements.py`
7. SQL patterns now represented in `engagement/create_associations.py`
8. `tests/test_pipeline_transitions.py`

## Contract Reminder

No migration is complete unless it preserves this order:

1. Silver gate
2. dbt boundary
3. Gold upsert
4. StackSync bidirectional sync checkpoint
5. association bridge

If a salvaged module collapses or obscures that ordering, it needs to be redesigned before import.
