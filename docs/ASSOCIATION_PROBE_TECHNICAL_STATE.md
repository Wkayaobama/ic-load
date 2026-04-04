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
5. Meetings last

This ordering is driven by live reconciliation evidence, not by aesthetics.

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

This means the next step is no longer "understand the entire pipeline." It is
"probe the association mechanism carefully against the live Silver or staging
side, using the now-stable UUID plus fallback model."

## What Must Happen Before Any Real Association Insert

Do all of the following first:

1. finish second-machine portability cleanup for devcontainer and Repomix
2. keep the association probe read-only until the exact target pattern is
   chosen
3. pick the first association family based on live reconciliation strength,
   likely calls or notes contact
4. confirm the target mirrored association table exists for that family
5. confirm the UUID path and legacy fallback path with staging-side examples
6. restate the exact insertion SQL and the exact stop conditions
7. get explicit user confirmation before any write

## Recommended Reading Before Association Work

Read in this order:

1. [salvation.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/salvation.md)
2. [docs/CANONICAL_EXECUTION_SPEC.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/CANONICAL_EXECUTION_SPEC.md)
3. [docs/AD_HOC_TRANSFORM_CONTEXT.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/AD_HOC_TRANSFORM_CONTEXT.md)
4. [docs/LIVE_POSTGRES_SMOKE_TEST.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/LIVE_POSTGRES_SMOKE_TEST.md)
5. [pipeline/live_smoke.py](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/pipeline/live_smoke.py)
6. [pipeline/staging_resolution_probe.py](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/pipeline/staging_resolution_probe.py)
7. [sql/render.py](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/sql/render.py)
8. [GomplateRepoMix/staging_metadata_snapshot.json](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/GomplateRepoMix/staging_metadata_snapshot.json)

## One-Sentence State Summary

The repo is now technically grounded enough to probe the association mechanism
against the live Silver or staging side, but not yet justified to insert into
mirrored association tables or read from `hubspot.*` without another explicit
confidence step.
