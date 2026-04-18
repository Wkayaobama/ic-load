# Ad-Hoc Transform Context

## Purpose

This document widens the Repomix bundle just enough to preserve three critical
forms of context that are easy to lose in cleanup:

- communication hierarchy unflattening
- sibling-company parent/sibling disambiguation
- deal stage mapping business rules
- legacy-to-Silver-to-HubSpot translation exemplars
- universal UTF-8/mojibake cleanup rules

Gomplate remains SQL-only.
Repomix must carry these algorithms as context because they explain how the
staging tables are shaped before or alongside the canonical SQL patterns.

## Non-Negotiable Sources

These source artifacts must be part of the Repomix bundle during salvage:

- `../../unflatten_hierarchy.py`
- `../../ic_load_pipeline/python-ignorethis/custom_objects/upsert_sibling_companies.py`
- `../../custom_objects/SIBLING_COMPANY_PIPELINE.md`
- `context/algorithms/deal_stage_mapper.py`
- `../../DEAL_STAGE_MAPPING_VISUAL.md`

For communication lineage context, also include:

- `../../ic_load_pipeline/dbt_communication/models/intermediate/int_communication_classified.sql`
- `../../ic_load_pipeline/dbt_communication/models/intermediate/int_communication_reconciled.sql`
- `../../ic_load_pipeline/dbt_communication/models/marts/fct_communication_calls.sql`

For translation-boundary validation, also include these selected benchmark
reference extracts:

- `../../benchmark/benchmark_hubspot-crm-exports-icalps-companies-2026-03-07.csv`
- `../../benchmark/benchmark_hubspot-crm-exports-icalps_contact-2026-03-07.csv`
- `../../benchmark/benchmark_hubspot-crm-exports-icalps_deals-2026-03-07.csv`
- `../../benchmark/hubspot-crm-exports-all-tickets-2026-04-04-1.csv`

For shared text-cleaning context, also include:

- `../pipeline/text_normalization.py`
- `GomplateRepoMix/text_normalization_rules.yaml`
- `../../ic_load_pipeline/python-ignorethis/process_silver_layer.py`
- `../../ic_load_pipeline/python-ignorethis/process_opportunities.py`

## Communication Unflattening

### What it does

`unflatten_hierarchy.py` implements a reverse-depth-first hierarchy build over
communication data.

Source table:
- `staging.raw_stg_communication`

Hierarchy levels:
- `Level_000 = Company_Name`
- `Level_001 = Person_FirstName + Person_LastName`
- `Level_002 = Comm_Subject or Comm_CommunicationId`

Algorithm steps:

1. load flattened communication rows from `staging.raw_stg_communication`
2. build level columns for company, person, and communication
3. traverse levels in order and create one node per unique path
4. assign `NodeKey`, `NodeName`, `ParentKey`, `Depth`
5. emit both a flat hierarchy table and a tree JSON

### Why it matters

This algorithm is not the main production write path, but it captures the
mental model of the communication object:

- Company -> Person -> Communication
- communication is not treated as a flat engagement stream only
- parent-child structure can be reconstructed from staging without touching Gold

That context is valuable for future ad-hoc transformation, QA, and retrieval.

## Communication dbt Lineage

The production communication path around that hierarchy is:

1. `staging.raw_stg_communication`
2. `staging.stg_communication`
3. `staging.stg_communication_normalised`
4. `int_communication_classified`
5. `int_communication_reconciled`
6. `staging.fct_communication_{calls,notes,tasks,meetings}`

Key behaviors:

- `int_communication_classified` maps `Comm_Action` to HubSpot activity class
- `int_communication_reconciled` attaches resolved HubSpot record IDs through
  legacy-ID reconciliation
- `fct_communication_*` marts expose both:
  - `associated_*_id` as StackSync UUIDs
  - `legacy_*_id` as fallback join anchors

This is why the association bridge can use a two-pass strategy later without
encoding the full dbt logic inside Gomplate.

## Live Staging Baseline

The staging-only smoke baseline from `2026-04-04` is stored in
`GomplateRepoMix/staging_metadata_snapshot.json`.

High-signal facts from that snapshot:

- `raw_stg_communication`: 77,100 rows
- `stg_communication`: 29,150 rows
- `stg_communication_normalised`: 6,127 rows
- `fct_communication_calls`: 5,959 rows
- `fct_communication_notes`: 11,994 rows
- `fct_communication_tasks`: 145 rows
- `fct_communication_meetings`: 59,043 rows
- `stg_company_normalised`: 2,910 rows
- plural-domain groups in company staging: 151 groups / 499 rows

Critical interpretation:

- `stg_communication_normalised` has zero rows without both company and person
  anchors
- reverse-lookup readiness is uneven by engagement type
- meetings are numerous but mostly unreconciled in staging terms

That baseline belongs in the bundle because it explains the practical pressure
points for the next implementation phase.

## Deal Stage Mapping

The business rules in `deal_stage_mapper.py` are non-negotiable constraints.

They are not generic label mapping. They encode:

- pipeline-specific stage IDs
- stage normalization across French and English labels
- outcome normalization across French and English labels
- the requirement to resolve `pipeline + stage + outcome` into a HubSpot-native
  pipeline ID and stage ID

This must survive cleanup because a plain-text stage label is not a valid Gold
write target.

For the salvage bundle:

- treat `deal_stage_mapper.py` as the current authority
- keep `DEAL_STAGE_MAPPING_VISUAL.md` as explanatory context
- carry the constraint into runner metadata through `business_rules.yaml`

## Sibling Company Algorithm

### What it does

`upsert_sibling_companies.py` detects plural-domain company groups in
`staging.stg_company_normalised` and chooses exactly one canonical parent
record per domain group.

Detection rule:
- group by cleaned domain
- only consider groups where count > 1

Parent rule:

1. among rows already represented in `hubspot.companies`, pick the one with the
   highest contact count
2. tie-break on minimum `comp_companyid`
3. if no Gold-matched row exists, mark group unresolved and skip

### Why it matters

Even if we keep custom-object or native-company variants separate in the clean
repo, this rule is non-negotiable business logic:

- plural-domain groups are not random duplicates
- parent selection is deterministic
- unresolved groups are excluded rather than partially mutated

That logic must survive cleanup as context even before we decide which runtime
surface owns it in `ic-load`.

## Translation Boundary

The assessment/probe surface must stay segmented:

- `legacy__*`
  Raw extract fields from IC'ALPS Bronze or benchmark CRM export.
- `silver__*`
  Canonical staging fields that survive the Silver layer and are eligible for
  downstream transformation.
- `gold__*`
  HubSpot-shaped target properties or engagement payload fields.
- `resolution__*`
  StackSync and reverse-lookup metadata only.

Do not mix `resolution__*` fields into the business payload columns. In
particular:

- `stacksync_record_id_*` values are resolution-only metadata
- they are not Silver business fields
- they are not Gold business properties

For standard objects:

- Silver only flows to Gold when it matches HubSpot property shape
- StackSync IDs are only used to resolve native HubSpot IDs later

For communications:

- `stg_communication_normalised` is still not the Gold payload
- dbt classification/reconciliation produces the engagement-specific mart shape
- association repair uses both `associated_*_id` (StackSync UUID) and
  `legacy_*_id` fallback

## Universal Text Normalization

UTF-8/mojibake cleanup is a shared salvage rule across entity types, not a
special-case fix for one object.

Applies to:

- company
- contact
- opportunity
- communication
- case/ticket

The shared contract is captured in:

- `GomplateRepoMix/text_normalization_rules.yaml`
- `pipeline/text_normalization.py`

Required behavior:

- read Bronze and benchmark CSVs with `utf-8-sig`
- repair common mojibake patterns before mapping
- strip unsafe control characters
- preserve meaningful line breaks in long-form note/description fields
- trim and normalize excess whitespace

This rule must be applied before entity-specific mapping into Silver or any
HubSpot-shaped staging surface. It is part of the context bundle because
corrupted text is a cross-entity pipeline risk, not merely a display issue.

## Packaging Rule

Gomplate:
- keep SQL-only

Repomix:
- include canonical SQL bundle
- include selected algorithm sources for communication and sibling transforms
- include staging-only metadata snapshot
- include selected benchmark extracts that show the HubSpot property shape
  without bundling production table dumps
- include the universal text-normalization contract and runtime reference

Do not add:
- Bronze payload archives
- broad benchmark dumps unrelated to the translation boundary
- `memory/`
- run artifacts
- direct `hubspot.*` data exports

## Smoke-Test Rule

Until the repo clears the higher-confidence threshold, smoke tests must stay
within:

- `information_schema`
- `staging.*`

Do not read from or write to `hubspot.*` as part of the clean-repo smoke path.
