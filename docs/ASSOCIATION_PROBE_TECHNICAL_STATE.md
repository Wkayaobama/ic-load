# Association Probe Technical State

## Purpose

This document is the technical state checkpoint before any realistic
association-step probe against the live Silver or staging side of the shared
PostgreSQL instance.

It overlaps with [salvation.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/salvation.md),
but the focus here is narrower and more technical:

- what functionality has been recovered
- what modeling rules are now explicit
- what was proven against the live `staging.*` relations
- why the association layer is now understandable enough to probe
- what still remains blocked before any `hubspot.*` write

This file should be read before any future work that attempts:

- post-Gold StackSync sync checks
- mirrored association-table inserts
- communication association repair
- company hierarchy association repair

## Current Runtime Boundary

The current clean runner is intentionally narrower than the historical
production path.

Historical production path:

1. validation or approval gate
2. Bronze-approved extracts into `staging.*`
3. Silver normalization
4. Silver validation gate
5. dbt `staging -> intermediate -> marts`
6. Gold upsert into mirrored `hubspot.*`
7. StackSync bidirectional sync
8. association bridge into mirrored association tables

Current clean-runner path:

1. Bronze load or staging ownership
2. Silver normalization
3. Silver validation
4. dbt boundary
5. optional probe-only dedupe stage
6. explicit Gold validation gate
7. Gold upsert

Important:

- `GOLD_VALIDATE` is required before any live Gold write.
- `GOLD_UPSERT` is the default terminal stage.
- `STACKSYNC_SYNC` and `ASSOC_VALIDATE` remain preserved in code and in SQL,
  but they are not part of the default live path.
- `DEDUPE_GUARD` is preserved for probe or calibration only and is not
  production-active.

See:

- [pipeline/state.py](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/pipeline/state.py)
- [pipeline/runner.py](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/pipeline/runner.py)

## Recovery Timeline

The current technical state was built in stages.

### 1. Repo Separation And Canonical Boundary

The first step was to separate `ic-load` from the old mixed workspace and define
the runtime boundary as its own project.

Key commits:

- `984afa2` bootstrap clean repo
- `7a1e2bf` canonical execution spec and coverage matrix
- `3db4df9` sync and context packaging clarification
- `dad5071` re-entry file

Core outcome:

- `ic-load` became the clean rescue target
- the runtime boundary was described explicitly instead of inferred from the
  legacy workspace
- Gomplate and Repomix were narrowed to their intended roles

### 2. Architecture And Runnable Spine

The second step was to define a minimal structure and implement the salvage
runtime spine.

Key commits:

- `a56cb91` target architecture and import map
- `fe33a21` salvage runtime spine and orchestration probe

Core outcome:

- `context/`, `pipeline/`, `sql/`, `dbt/`, `tests/`, and `docs/` became the
  explicit clean repo surfaces
- the state machine and runner contract moved into `ic-load`
- the orchestration probe proved stage ordering without touching production

### 3. Remote And Codespaces Hardening

The third step was to make the clean repo less machine-specific.

Key commits:

- `8eeadc6` Codespaces hardening
- `aca02ab` WSL path discipline

Core outcome:

- the repo gained a smoke path suitable for remote execution
- path assumptions were pushed toward repo-relative behavior
- Windows remained the primary supported runtime path

Important limitation:

- second-machine portability is improved but not yet at the 85% confidence bar
- the devcontainer still needs path cleanup
- the Repomix config still depends on legacy-parent paths

### 4. Staging-Only Functional Probes

The fourth step was to validate the clean understanding against the real shared
PostgreSQL staging contract without touching `hubspot.*`.

Key commit:

- `e20b9ec` staging-only probes and shared normalization contract

Core outcome:

- the clean repo stopped being purely documentary
- the staging contract was profiled against the live instance
- translation and normalization became evidence-backed rather than assumed

### 5. Skill And Guardrail Clarification

The fifth step was to turn the rescue method itself into a reusable skill while
keeping immature protection logic out of production.

Key commits:

- `0b5ed05` initial skill and hierarchy guardrails
- `79b6951` explicit Gold approval and dedupe guardrail
- `3eb1501` dedupe guardrail moved back to probe-only
- `1b856a1` generalized pipeline-salvation skill

Core outcome:

- explicit Gold approval is now enforced
- the dedupe guardrail is preserved as research or probe logic, not
  production-active behavior
- the broader rescue method is now reusable outside `ic-load`

### 6. Association Probe Completion (this branch)

The sixth step addresses the critical misalignments discovered during the
association probe review and completes the algorithm documentation.

Key changes on branch `w/assoc-probe-completion`:

- `association_bridge.sql.tmpl` corrected from single-pass to two-pass
  (M1 — template was not reproducible against the rendered SQL it supposedly produced)
- `unflatten_hierarchy.py` credentials replaced with env var reads
  (M2 — hardcoded credentials removed, matching `context/config.py` contract)
- `ASSOCIATION_PROBE_TECHNICAL_STATE.md` completed with algorithm descriptions,
  full association map, StackSync timing model, and missing-file flags
- `repomix.config.json` path note and new docs added
- `schema_context.yaml` Meetings deferral documented
- `render_associations.sh` concrete Gomplate execution script added
- `salvation.md` iteration status updated

## Functional Model Recovered So Far

### Shared Layer Model

The recovered model is now:

- `legacy__*`
  Raw CRM extract shape or benchmark extract shape
- `silver__*`
  Canonical staging fields
- `gold__*`
  HubSpot-shaped target properties or engagement payloads
- `resolution__*`
  StackSync and reverse-lookup metadata only

This segmentation became necessary because the legacy workspace mixed business
fields and resolution mechanics too freely.

Critical rule:

- `stacksync_record_id_*` fields are never business metadata
- they are resolution infrastructure only

See:

- [docs/AD_HOC_TRANSFORM_CONTEXT.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/AD_HOC_TRANSFORM_CONTEXT.md)
- [pipeline/staging_resolution_probe.py](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/pipeline/staging_resolution_probe.py)

### Universal Normalization Rules

These rules are now treated as cross-entity pipeline behavior:

- UTF-8 or mojibake cleanup
- deterministic date serialization
- strict separation of business fields and resolution fields

This came from inspecting the legacy Silver path and from the Case/Ticket
translation work.

See:

- [pipeline/text_normalization.py](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/pipeline/text_normalization.py)
- [pipeline/raw_to_staging_snippet.py](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/pipeline/raw_to_staging_snippet.py)
- [docs/RAW_CSV_TO_STAGING_SNIPPET.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/RAW_CSV_TO_STAGING_SNIPPET.md)

### Non-Negotiable Algorithm Packages

The following survive cleanup as context packages and are not treated as
optional:

- communication unflattening and hierarchy reconstruction
- company parent-child plus sibling inference plus common-root grouping
- deal stage mapping

This matters because association behavior depends on these upstream modeling
decisions.

See:

- [docs/AD_HOC_TRANSFORM_CONTEXT.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/AD_HOC_TRANSFORM_CONTEXT.md)
- [GomplateRepoMix/repomix.config.json](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/GomplateRepoMix/repomix.config.json)

## Communication Unflattening Algorithm

### What The Algorithm Does

`unflatten_hierarchy.py` implements a reverse-depth-first hierarchy build over
communication data. This is not the production write path, but it captures the
canonical mental model of the communication object and enables ad-hoc QA
without touching Gold.

Source table: `staging.raw_stg_communication` (77,100 rows)

Hierarchy levels:

```
Level_000 = Company_Name
            fillna("Unknown Company")

Level_001 = Person_FirstName + " " + Person_LastName
            fillna("Unknown Person")

Level_002 = Comm_Subject[:50] + " (#Comm_CommunicationId)"
            or "Communication #<id>" when subject is empty
```

### Algorithm Steps (Reverse-Depth-First)

```
1. Load flattened rows from staging.raw_stg_communication
2. Derive Level_000, Level_001, Level_002 columns (see above)
3. For level N in [0, 1, 2]:
     a. Select rows where Level_N is not null
     b. Build path = [Level_000, ..., Level_N] for each row
     c. Serialize path to NodeKey = "|".join(path)
     d. Deduplicate: skip NodeKey already in node_lookup
     e. For new NodeKey:
          - NodeName = path[-1]
          - Depth    = N
          - ParentKey = node_lookup[ "|".join(path[:-1]) ]
                        or None if N == 0
          - Emit node record, store in node_lookup
4. Collect all node records into hierarchy_df
```

### Outputs

```
hierarchy_communication.csv  — flat table: NodeKey, NodeName, ParentKey, Depth
hierarchy_tree.json          — nested tree (max_depth=2 for performance)

Metadata:
  TotalNodes  — total unique nodes emitted
  MaxDepth    — 3 (levels 0..2)
  RootCount   — count of Level_000 (company) nodes
```

### Why This Matters For Association Work

- Communication is not a flat engagement stream only
- Parent-child structure can be reconstructed from staging without touching Gold
- The Company → Person → Communication chain is the same FK chain that the
  association bridge later uses to link engagements to their parent entities
- Understanding this shape prevents association misfires where a communication
  is linked to the wrong company or person due to a broken hierarchy assumption

## Company Hierarchy Algorithm

### What The Algorithm Does

`create_company_hierarchy.py` (930 lines) implements native HubSpot COMPANY
hierarchy using a domain trick. This is the authoritative parent-child
resolution logic for all downstream company association work.

Source: `staging.stg_company_normalised`

### Domain Trick

Child companies receive a synthetic domain encoding their position:

```
parent:  domain = "{clean_domain}"              icalps_sibling_index = 0
child 1: domain = "1.{clean_domain}"            icalps_sibling_index = 1
child 2: domain = "2.{clean_domain}"            icalps_sibling_index = 2
...
child N: domain = "{N}.{clean_domain}"          icalps_sibling_index = N
```

`icalps_real_domain` (custom HubSpot property) stores the actual business
domain for reporting. `icalps_sibling_index` stores the position.

### Parent Selection Rule (Deterministic, 3-Tier)

```
1. Group stg_company_normalised by cleaned domain.
   Only groups where COUNT(*) > 1 are processed.

2. Among rows already in hubspot.companies (Gold-matched):
     → pick the row with the highest contact_count
     → tie-break: minimum comp_companyid

3. If no Gold-matched row exists in the group:
     → mark group as unresolved
     → skip entirely (no partial mutation)
```

This is a hard rule. Unresolved groups are excluded rather than partially
assigned.

### Child Assignment

```
Remaining rows in the group (after parent selection):
  → sorted by comp_companyid ASC
  → assigned sibling_index 1..N in that order
  → domain = "{sibling_index}.{clean_domain}"
```

### HubSpot Write Sequence

```
Phase 1 — hierarchy creation (no assoc flags needed):
  1. batch/create child company records in HubSpot
  2. Register COMPANY-COMPANY USER_DEFINED association
     typeId 269 ("Is subsidiary of")
     typeId 270 ("Has subsidiary")
     body pattern: [{"associationCategory":"USER_DEFINED","associationTypeId":269}]
     (typeId in body, NOT in URL path — v4 API requirement)

Phase 2 — post-StackSync association (requires --assoc-contacts or --assoc-deals):
  --assoc-contacts:
     Join stg_contact_normalised.pers_companyid
     → hubspot.companies.icalps_company_id
     → hubspot.companies.id
     Update hubspot.contacts.associatedcompanyid = child company id
     StackSync outgoing sync picks up the change and pushes to HubSpot API

  --assoc-deals:
     Join stg_opportunity_normalised.oppo_primarycompanyid
     → hubspot.companies.icalps_company_id
     → hubspot.companies.id
     Associate deal to child company record
```

### Live Run Result (2026-03-11)

```
Raw candidates:    504
Plural-domain groups: 151
Parent companies:  156
Child companies:   293
Siblings created:  348
Unresolved groups:   0
Errors:              0
```

### Cardinality

```
1 parent ↔ N children
sibling_index 0 = parent
sibling_index 1..N = children (sorted by comp_companyid ASC)
```

### Association Type IDs For Hierarchy

```
typeId 269  "Is subsidiary of"    (child → parent direction)
typeId 270  "Has subsidiary"      (parent → child direction)
```

These are USER_DEFINED association labels, registered once at schema setup.
They are NOT part of the standard HubSpot association type enumeration.

## StackSync Bidirectional Sync Timing Model

This model is critical for understanding why the two-pass association bridge
exists and when it is safe to run.

### Write Sequence

```
Step 1  GOLD_UPSERT
        INSERT/UPDATE rows in hubspot.* tables via SQL.
        At this point:
          - icalps_*_id columns are populated (set during upsert)
          - stacksync_record_id_* columns may be stale or NULL for new rows

Step 2  STACKSYNC_SYNC checkpoint
        StackSync detects changed rows in hubspot.* (outgoing sync trigger).
        StackSync pushes changes to the HubSpot API.
        StackSync pulls API-confirmed state back into hubspot.* (incoming sync).
        After this step:
          - stacksync_record_id_* columns are refreshed with live HubSpot IDs

Step 3  ASSOC_VALIDATE
        Association bridge SQL now has valid stacksync_record_id_* to join on.
        Pass A (UUID join) becomes reliable.
        Pass B (legacy ID fallback) remains for any rows not yet synced.
```

### Why The Two-Pass Fallback Exists

`stacksync_record_id_*` columns are populated BY StackSync after sync.
They are NOT available before `STACKSYNC_SYNC` completes.

In practice:

- newly upserted rows may not have a StackSync UUID yet
- incremental sync windows mean some records lag behind
- the legacy ID (`icalps_*_id`) is always available after `GOLD_UPSERT`

The two-pass strategy is therefore not defensive complexity. It is required
to cover the realistic timing gap between upsert and full sync propagation.

Pass A succeeds for records that have completed the StackSync round-trip.
Pass B covers the remainder.

### StackSync Resolution Constants

```
company_record_id_column:  stacksync_record_id_9vpp8v
contact_record_id_column:  stacksync_record_id_nd85zc
deal_record_id_column:     stacksync_record_id_87b7vd
```

These column names are fixed. They do not change per run and are not
configurable. They are registered in `schema_context.yaml` and must be treated
as constants in any SQL that touches association resolution.

## Complete Association Map

This section documents all associations governed by the StackSync-mirrored
PostgreSQL database, both direct entity associations and communication
engagement associations.

### Direct Entity Associations (StackSync-Governed)

These associations are maintained via the `hubspot.*` mirrored tables and are
resolved at upsert or post-StackSync time.

#### Contact → Company

```
Mechanism:  hubspot.contacts.associatedcompanyid = hubspot.companies.id
Resolution: stg_contact_normalised.pers_companyid
            → hubspot.companies.icalps_company_id
            → hubspot.companies.id

Write path: UPDATE hubspot.contacts
            SET associatedcompanyid = hs_company.id::text
            FROM hubspot.companies AS hs_company
            INNER JOIN staging.stg_contact_normalised AS stg
              ON stg.pers_companyid = hs_company.icalps_company_id
            WHERE hubspot.contacts.icalps_contact_id = stg.pers_personid

Timing:     After GOLD_UPSERT for both Company and Contact entities.
            StackSync outgoing sync propagates the change to HubSpot API.
            Prerequisite: child companies must already exist in hubspot.companies
            (Phase 2 of create_company_hierarchy.py must have completed).

Filter:     Target child companies only with domain ~ '^[0-9]+\.'
            to avoid misassociating contacts to parent records.
```

#### Deal → Company

```
Mechanism:  hubspot.deals associated to hubspot.companies
            via stg_opportunity_normalised.oppo_primarycompanyid FK

Resolution: stg_opportunity_normalised.oppo_primarycompanyid
            → hubspot.companies.icalps_company_id
            → hubspot.companies.id

Write path: create_company_hierarchy.py --assoc-deals flag
            Associates each deal to its resolved child company record.

Timing:     Post-StackSync (child company ids must be in hubspot.companies).
```

#### Deal → Contact

```
Mechanism:  hubspot.deals associated to hubspot.contacts
            via stg_opportunity_normalised.oppo_primarypersonid FK

Resolution: stg_opportunity_normalised.oppo_primarypersonid
            → hubspot.contacts.icalps_contact_id
            → hubspot.contacts.id

Write path: Silver FK validation gate ensures this FK is populated.
            Gold upsert or post-StackSync association step.
```

#### Child Company → Parent Company

```
Mechanism:  USER_DEFINED COMPANY-COMPANY association
            typeId 269 ("Is subsidiary of") child → parent
            typeId 270 ("Has subsidiary")   parent → child

Resolution: create_company_hierarchy.py parent selection algorithm
            (see Company Hierarchy Algorithm section above)

Write path: v4 batch association API
            Body: [{"associationCategory":"USER_DEFINED","associationTypeId":269}]
            typeId in request BODY, not URL path.
            Idempotency: clear_subsidiary_associations() clears stale
            USER_DEFINED 269/270 before re-association on each run.
```

### Communication Engagement Associations (Two-Pass Bridge)

These associations link engagement records (Calls, Notes, Tasks) to their
parent entities (Company, Contact, Deal) via the mirrored association tables.

#### Two-Pass Resolution

```
Pass A — UUID join (preferred):
  fct.associated_*_id  →  target.stacksync_record_id_*
  Requires STACKSYNC_SYNC to have completed.

Pass B — legacy ID fallback:
  fct.legacy_*_id  →  target.icalps_*_id
  Used when fct.associated_*_id IS NULL.
  Always available after GOLD_UPSERT.

Both passes use NOT EXISTS idempotency guard.
UNION (not UNION ALL) between passes.
```

#### Supported Association Patterns And Type IDs

```
comm_type  target    association_type_id  assoc_table
─────────  ────────  ───────────────────  ─────────────────────────────────
Calls      company   182                  hubspot.associations_calls_company
Calls      contact   194                  hubspot.associations_calls_contact
Notes      company   190                  hubspot.associations_notes_company
Notes      contact   202                  hubspot.associations_notes_contact
Notes      deal      214                  hubspot.associations_notes_deal
Tasks      company   192                  hubspot.associations_tasks_company
Tasks      contact   204                  hubspot.associations_tasks_contact
```

#### Meetings — Explicit Deferral

Meetings exist in `staging.fct_communication_meetings` (59,043 rows) but are
explicitly deferred from the association bridge.

Reasons:

- 58,581 of 59,043 rows (99.2%) have no UUID anchor in live staging
- association type IDs for meetings are not yet registered in `schema_context.yaml`
- unreconciled meetings cannot safely use the legacy fallback path at scale

Meetings must not be added to `association_bridge.supported_patterns` until:

1. reconciliation quality improves significantly above current 0.8% UUID rate
2. association type IDs for meetings_company and meetings_contact are confirmed
3. a separate reconciliation improvement pass is completed on the meetings mart

#### Rendered SQL Files

```
sql/rendered/association_calls_company.sql
sql/rendered/association_calls_contact.sql
sql/rendered/association_notes_company.sql
sql/rendered/association_notes_contact.sql
sql/rendered/association_notes_deal.sql
sql/rendered/association_tasks_company.sql
sql/rendered/association_tasks_contact.sql
```

All rendered files implement the two-pass pattern. The Gomplate template
`GomplateRepoMix/templates/association_bridge.sql.tmpl` now also produces this
pattern after the M1 fix in this branch.

### Case Or Ticket Associations

Case/Ticket associations are not yet part of the mirrored association bridge.

Current state of Case/Ticket:

- `staging.stg_case` is the ticket-shaped cleaned surface (58 rows)
- Bronze-to-staging shaping is 43/58 rows exact match against live
- no HubSpot Ticket → Company, Ticket → Contact, or Ticket → Deal
  association patterns have been validated yet

This is deferred, not dropped. The staging surface exists. The association
type IDs must be confirmed before bridge patterns are added.

## Entity Modeling State

### Company

Recovered canonical path:

- Bronze: `Comp_CompanyId`
- Silver raw: `staging.stg_company`
- Silver normalized: `staging.stg_company_normalised`
- Gold match key: `icalps_company_id`
- StackSync resolution column: `stacksync_record_id_9vpp8v`

Observed live pressure:

- plural-domain groups still exist in `staging.stg_company_normalised`
- `151` plural-domain groups covering `499` rows were observed in the
  staging-only snapshot

Interpretation:

- company hierarchy and sibling logic are still materially relevant
- company association probing cannot ignore parent selection and sibling
  grouping

### Contact

Recovered canonical path:

- Bronze: `Pers_PersonId`
- Silver raw: `staging.stg_contact`
- Silver normalized: `staging.stg_contact_normalised`
- Gold match key: `icalps_contact_id`
- StackSync resolution column: `stacksync_record_id_nd85zc`

Interpretation:

- contact association repair depends on exact contact resolution rather than
  fuzzy identity guesses

### Opportunity

Recovered canonical path:

- Bronze: `Oppo_OpportunityId`
- Silver raw: `staging.stg_opportunity`
- Silver normalized: `staging.stg_opportunity_normalised`
- Gold match key: `icalps_deal_id`
- StackSync resolution column: `stacksync_record_id_87b7vd`

Critical rule:

- deal stage mapping is not cosmetic
- plain text stage labels are not safe Gold targets
- `deal_stage_mapper.py` resolves `pipeline + stage + outcome` → HubSpot
  pipeline ID and stage ID before any Gold write

### Communication

Recovered canonical path:

- Bronze raw communication extract
- `staging.raw_stg_communication`
- `staging.stg_communication`
- `staging.stg_communication_normalised`
- dbt:
  - `int_communication_classified`
  - `int_communication_reconciled`
  - `fct_communication_calls`
  - `fct_communication_notes`
  - `fct_communication_tasks`
  - `fct_communication_meetings`

Critical invariants:

- deterministic engagement key:
  `unique_id = 'icalps_' || icalps_communication_id`
- `fct_communication_*` expose both:
  - `associated_*_id` as UUID-style resolution anchors
  - `legacy_*_id` as integer fallback anchors
- communication without both company and person anchors does not survive the
  useful CRM path

Observed staging counts:

- `raw_stg_communication = 77100`
- `stg_communication = 29150`
- `stg_communication_normalised = 6127`
- `fct_communication_calls = 5959`
- `fct_communication_notes = 11994`
- `fct_communication_tasks = 145`
- `fct_communication_meetings = 59043`

Observed anchor summary on `stg_communication_normalised`:

- total rows: `6127`
- rows with company: `2440`
- rows with person: `5532`
- rows without company and without person: `0`

Interpretation:

- the communication path is structurally understood enough to probe
- the biggest unknown is no longer table shape, but association readiness and
  reconciliation quality by communication type

### Case Or Ticket

Recovered current interpretation:

- `staging.stg_cases` is closer to the raw or legacy preservation layer
- `staging.stg_case` is the ticket-shaped cleaned surface

Generated assessment:

- [stg_case_from_bronze.csv](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/artifacts/assessment/stg_case_from_bronze.csv)
- [stg_case_from_bronze_assessment.json](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/artifacts/assessment/stg_case_from_bronze_assessment.json)

Observed result:

- `58` source rows
- `22` shaped columns
- `43/58` rows match live `staging.stg_case` exactly
- most columns match at `56-58 / 58`
- residual mismatches are concentrated in:
  - `createdate`
  - `icalps_case_stage`
  - a small number of contact and text fields

Interpretation:

- the Case-to-Ticket mapping is now real enough to stage and inspect
- it is not yet a live push candidate

## Association Model Recovered So Far

### Core Association Hypothesis

The mirrored association path no longer rests on assumption alone.

The current recovered model is:

1. communication marts already contain resolved association anchors
2. engagement rows use deterministic `unique_id`
3. target entity rows expose fixed StackSync record-id columns
4. mirrored association SQL performs a two-pass reverse lookup

Pass A:

- join `fct_communication_*`.`associated_*_id`
- to target mirrored table `stacksync_record_id_*`

Pass B:

- if UUID anchor is absent
- join `fct_communication_*`.`legacy_*_id`
- to target mirrored table `icalps_*_id`

Idempotency:

- every association insert pattern uses `NOT EXISTS`

Current rendered patterns in `ic-load`:

- `association_calls_company.sql`
- `association_calls_contact.sql`
- `association_notes_company.sql`
- `association_notes_contact.sql`
- `association_notes_deal.sql`
- `association_tasks_company.sql`
- `association_tasks_contact.sql`

See:

- [sql/render.py](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/sql/render.py)
- [sql/rendered/association_calls_company.sql](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/sql/rendered/association_calls_company.sql)

### Fixed Resolution Constants

Recovered live StackSync record-id columns:

- company: `stacksync_record_id_9vpp8v`
- contact: `stacksync_record_id_nd85zc`
- deal: `stacksync_record_id_87b7vd`

Recovered association type IDs:

- `notes_contact = 202`
- `notes_company = 190`
- `notes_deal = 214`
- `calls_contact = 194`
- `calls_company = 182`
- `tasks_contact = 204`
- `tasks_company = 192`

Hierarchy association type IDs (USER_DEFINED, COMPANY-COMPANY):

- `is_subsidiary_of = 269`
- `has_subsidiary = 270`

### Live Read-Only Reconciliation Evidence

From the staging-only snapshot:

- Calls:
  - total `5959`
  - company UUID `5943`
  - contact UUID `4756`
  - deal UUID `91`
  - unreconciled `16`
- Notes:
  - total `11994`
  - company UUID `1511`
  - contact UUID `8510`
  - deal UUID `246`
  - unreconciled `3200`
- Tasks:
  - total `145`
  - company UUID `25`
  - contact UUID `24`
  - deal UUID `3`
  - unreconciled `120`
- Meetings:
  - total `59043`
  - company UUID `462`
  - contact UUID `375`
  - deal UUID `69`
  - unreconciled `58581`
  - status: DEFERRED (see Meetings — Explicit Deferral above)

Interpretation:

- Calls are closest to association-readiness on the UUID path.
- Notes have meaningful contact readiness but uneven company and deal readiness.
- Tasks are sparse and mostly unreconciled.
- Meetings are numerous but overwhelmingly unreconciled, so they are the least
  safe first association target.

### Practical Association-Probe Conclusion

If and when the association probe is attempted, the safest sequence is:

1. Calls company or contact
2. Notes contact
3. Notes company or deal only after extra review
4. Tasks only after explicit justification
5. Meetings last, after a reconciliation improvement pass

This ordering is driven by live reconciliation evidence, not by aesthetics.

## Critical Misalignments Between Repo And Salvage Contract

These misalignments were discovered by confronting the repo state against
`salvation.md` and the rendered SQL contract.

### M1 — Gomplate Template Was Single-Pass (FIXED)

**What was wrong:**
`GomplateRepoMix/templates/association_bridge.sql.tmpl` performed only a single
legacy-ID join. The rendered SQL files use a two-pass strategy with UUID-first
then legacy fallback.

**Impact:**
The template could not regenerate the rendered SQL it was supposed to produce.
Any Gomplate re-render would have produced incorrect SQL silently.

**Fix applied (this branch):**
Template rewritten to emit the two-pass UNION pattern, matching the rendered
SQL contract and the `sql/render.py` Python implementation.

### M2 — unflatten_hierarchy.py Had Hardcoded Credentials (FIXED)

**What was wrong:**
`unflatten_hierarchy.py` `get_postgres_connection_string()` embedded literal
host, user, and password strings.

**Impact:**
Unusable in Codespaces or any environment without those exact credentials.
Security risk if the file is included in the Repomix bundle.

**Fix applied (this branch):**
Replaced with `os.environ["ICALPS_DB_HOST"]`, `ICALPS_DB_USER`,
`ICALPS_DB_PASSWORD`, `ICALPS_DB_PORT`, `ICALPS_DB_NAME`, matching the env var
contract already defined in `context/config.py`.

### M3 — repomix.config.json Uses `../../` Workspace-Relative Paths (DOCUMENTED)

**What is wrong:**
Paths like `../../ic_load_pipeline/python-ignorethis/...` resolve correctly
from the local IC_Load workspace but fail in a fresh Codespaces clone of
`ic-load` alone.

**Impact:**
Repomix bundle generation fails in Codespaces unless the full IC_Load workspace
is checked out alongside `ic-load`.

**Mitigation documented:**
A note has been added to `repomix.config.json` clarifying the workspace
dependency. The long-term fix is to copy the non-negotiable algorithm files
into `ic-load/context/algorithms/` (deferred — requires user decision on which
files to promote).

### M4 — silver.py Loads Legacy Modules Via Sibling Path (DOCUMENTED, NOT FIXED)

**What is wrong:**
`pipeline/silver.py` uses `importlib` to load `silver_normalise.py` and
`validate_silver.py` from `PROJECT_ROOT.parent / "ic_load_pipeline" /
"python-ignorethis"`.

**Impact:**
Works locally when `ic-load` sits inside `IC_Load/`. Fails in Codespaces or
any standalone checkout.

**Current state:**
The legacy modules are not copied into `ic-load`. This is a conscious salvage
decision — the wrapper pattern was chosen to avoid duplicating large modules.
But the path dependency must be resolved before Codespaces becomes the primary
execution environment.

**What must happen before this is fixed:**
Decide whether to copy `silver_normalise.py` and `validate_silver.py` into
`ic-load` or replace them with clean rewrites. Until then, Codespaces execution
remains blocked for Silver normalization.

### M6 — Ticket Association SQL Written By Hand, Bypassing Gomplate (SELF-CORRECTED 2026-04-05)

**What happened:**
During the Case/Ticket pipeline implementation, `sql/case/07_association_ticket_company.sql`
and `sql/case/08_association_ticket_contact.sql` were authored as raw SQL files instead of
being rendered from `association_bridge.sql.tmpl`. This created a second source of truth:
the template system would not regenerate these files on `bash render_associations.sh`, and
any future schema_context.yaml change (e.g. confirmed association type IDs) would silently
diverge from the hand-authored SQL.

**Root cause:**
The existing Gomplate template (`association_bridge.sql.tmpl`) is parameterized for the
Communication entity pattern (`fct_communication_*` bridge tables, `unique_id LIKE 'icalps_%'`).
Ticket associations use a different source pattern: `stg_case_v2` direct FK join on
`icalps_ticket_id`, with no `fct_*` bridge table. Rather than extending the template
system, the instinct was to write SQL directly — breaking idempotency.

**Self-correction applied:**
1. The two hand-written files were deleted immediately.
2. A new template `association_object.sql.tmpl` was created to cover direct-FK entities
   (Ticket, and in future any entity with a direct PK join rather than a communication bridge).
3. `schema_context.yaml` extended with a new `association_object_bridge` block covering
   Ticket→Company, Ticket→Contact, Ticket→Deal (type IDs TBD from portal).
4. `render_associations.sh` extended with a second loop over `association_object_bridge`
   patterns, using the new template.
5. All Ticket association SQL now lives exclusively in `sql/rendered/` as rendered output.

**Key distinction captured in template design:**
- `association_bridge.sql.tmpl` → Communication engagements (calls/notes/tasks): source is
  `fct_communication_*`, joined via `unique_id = 'icalps_' || icalps_communication_id::text`
- `association_object.sql.tmpl` → Direct-FK entities (tickets, future objects): source is
  `hubspot.<object_table>`, joined via `icalps_<entity>_id = stg_<entity>.icalps_<entity>_id`

**Idempotency guarantee restored:**
Re-running `bash GomplateRepoMix/render_associations.sh` now regenerates ALL association SQL
(both communication and object-type) from a single source of truth. Any schema_context.yaml
update (e.g. confirmed type IDs) propagates automatically on next render.

### M5 — Meetings Have No Association Type IDs (DOCUMENTED)

**What is wrong:**
`schema_context.yaml` `association_type_ids` has no `meetings_*` entries.
`fct_communication_meetings` is not in `association_bridge.supported_patterns`.

**Impact:**
59,043 meeting rows cannot be associated even after reconciliation improves.

**Fix applied (this branch):**
Explicit deferral note added to `schema_context.yaml`. No type IDs added yet
because the HubSpot-side type IDs for meetings associations have not been
confirmed from the live portal.

## Missing Files That Block Runner In Codespaces

The following files are required by the runner but are not present in the
`ic-load` repo. They exist only in the legacy IC_Load workspace.

```
File                                                          Impact
───────────────────────────────────────────────────────────  ──────────────────────────────────────────
ic_load_pipeline/python-ignorethis/silver_normalise.py       pipeline/silver.py fails on import
ic_load_pipeline/python-ignorethis/validate_silver.py        pipeline/silver.py fails on import
ic_load_pipeline/python-ignorethis/deal_stage_mapper.py      runner metadata will not load stage rules
unflatten_hierarchy.py  (IC_Load root, not in ic-load)       repomix bundle misses it in Codespaces
ic_load_pipeline/dbt_communication/  (full dbt project)      dbt build step fails without path config
```

These are not blocking for local development when the full IC_Load workspace is
present. They are hard blockers for any fresh Codespaces or CI execution.

Resolution paths (in priority order):

1. Copy `silver_normalise.py` and `validate_silver.py` into
   `ic-load/pipeline/` or `ic-load/context/algorithms/` and update
   `silver.py` imports accordingly.
2. Copy `deal_stage_mapper.py` into `ic-load/context/algorithms/`.
3. Copy `unflatten_hierarchy.py` into `ic-load/context/algorithms/`.
4. Either include the `dbt_communication/` project in `ic-load/dbt/` or
   document the external dbt project path requirement clearly in the
   devcontainer and README.

## What Was Proven Against The Live Silver Or Staging Side

The following are no longer assumptions:

- required `staging.*` relations exist
- required communication reconciliation columns exist
- plural-domain company groups exist in live staging
- communication marts expose UUID-style associated IDs and legacy fallback IDs
- StackSync deal resolution column is `stacksync_record_id_87b7vd`
- `stg_case` exists as the ticket-shaped staging surface
- Bronze-to-staging shaping for Case is mostly reproducible against the live
  staging contract

The following remain blocked or unproven:

- no read from `hubspot.*` as part of the clean smoke path
- no write to `hubspot.*`
- no mirrored association insert
- no proof yet that second-machine devcontainer and Repomix travel cleanly
- no Codespaces execution of Silver normalization (blocked by M4)

## Current Safety Model

### Active Safety Controls

- explicit `GOLD_VALIDATE` gate before live Gold
- default runner stop at `GOLD_UPSERT`
- `DEDUPE_GUARD` preserved as probe-only
- no clean-repo smoke read or write on `hubspot.*`
- post-Gold sync and association logic are opt-in only

### Why The Dedupe Guardrail Was Pulled Back

The original guardrail logic was directionally sound, but too field-hardcoded to
be treated as a production control.

Conclusion reached:

- preserve the idea
- keep the code for calibration and probe work
- do not let it block live execution until it becomes entity-config-wide

This is relevant to future association work because it prevents us from
pretending the contamination guard is stronger than it really is.

## Why We Are Now Close To The Association Probe

We are not ready to write associations yet, but we are close to a realistic
probe because these prerequisites are now met:

- the stage boundary is explicit
- the clean repo can run probes and smoke tests
- the communication model is understood from Bronze through dbt marts
- the entity-resolution constants are identified
- the Case/Ticket shaping work proved that live staging surfaces can be
  reconstructed from legacy extracts with high fidelity
- the company hierarchy package is preserved as context instead of lost in
  cleanup
- the live staging snapshot shows which communication types are most and least
  ready for reverse-lookup association work
- the unflattening and hierarchy algorithms are now fully described, not just
  referenced
- the StackSync timing model is now explicit, explaining why the two-pass
  pattern is required and not optional
- all critical misalignments (M1, M2) have been fixed; M3–M5 are documented
  with explicit resolution paths

This means the next step is no longer "understand the entire pipeline." It is
"probe the association mechanism carefully against the live Silver or staging
side, using the now-stable UUID plus fallback model."

## What Must Happen Before Any Real Association Insert

Do all of the following first:

1. resolve M3 (repomix path dependency) by promoting algorithm files into
   `ic-load/context/algorithms/` or documenting the workspace checkout
   requirement explicitly in the devcontainer
2. resolve M4 (silver.py path dependency) by copying or rewriting
   `silver_normalise.py` and `validate_silver.py` inside `ic-load`
3. keep the association probe read-only until the exact target pattern is
   chosen
4. pick the first association family based on live reconciliation strength,
   likely calls or notes contact
5. confirm the target mirrored association table exists for that family
6. confirm the UUID path and legacy fallback path with staging-side examples
7. restate the exact insertion SQL and the exact stop conditions
8. get explicit user confirmation before any write

## Recommended Reading Before Association Work

Read in this order:

1. [salvation.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/salvation.md)
2. [docs/CANONICAL_EXECUTION_SPEC.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/CANONICAL_EXECUTION_SPEC.md)
3. [docs/AD_HOC_TRANSFORM_CONTEXT.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/AD_HOC_TRANSFORM_CONTEXT.md)
4. [docs/LIVE_POSTGRES_SMOKE_TEST.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/LIVE_POSTGRES_SMOKE_TEST.md)
5. [pipeline/live_smoke.py](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/pipeline/live_smoke.py)
6. [pipeline/staging_resolution_probe.py](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase\IC_Load\ic-load\pipeline\staging_resolution_probe.py)
7. [sql/render.py](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/sql/render.py)
8. [GomplateRepoMix/staging_metadata_snapshot.json](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/GomplateRepoMix/staging_metadata_snapshot.json)

## One-Sentence State Summary

The repo is now technically grounded enough to probe the association mechanism
against the live Silver or staging side, with all critical algorithm logic
documented, two critical misalignments fixed (Gomplate template, hardcoded
credentials), and three remaining path-dependency blockers explicitly flagged
before any Codespaces-safe execution can be declared.
