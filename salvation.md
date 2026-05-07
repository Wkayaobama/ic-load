# salvation.md

This is the quick re-entry file for the `ic-load` repacking effort.

If the context window is tight, start here first.

Reusable skill:
- [skills/pipeline-salvation/SKILL.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/skills/pipeline-salvation/SKILL.md)

## Repo Identity

- Repo name: `ic-load`
- Remote: `https://github.com/Wkayaobama/ic-load.git`
- Purpose: salvage and repack the minimum high-value core of the IC'ALPS load pipeline into a clean, reproducible, Codespaces-ready repo

## What We Agreed

This is **not** `IC-D-LOAD`.
This is a separate project focused on the reusable runtime core.

The core production path is:

1. validation/approval happens before this repo boundary
2. Bronze-approved extracts load into PostgreSQL `staging.*`
3. Silver normalization cleans and deduplicates
4. Silver validation is the blocking gate
5. dbt transforms `staging -> intermediate -> marts`
6. explicit Gold validation is required before any live `hubspot.*` write
7. SQL upserts write to `hubspot.*`

Important:
- the clean runner stops at Gold by default
- Gold itself is not implicit; it needs explicit validation/approval
- the dedupe guardrail is preserved for probe/calibration only and is not production-active
- downstream sync and mirrored association logic stay preserved, but only behind explicit opt-in later
- no post-Gold path should run implicitly

## Architecture Discipline

### Gomplate

Use Gomplate for:
- SQL upsert templates
- association bridge templates
- rendering from `schema_context.yaml` and `run_context.yaml`

Do not use Gomplate for:
- dbt model authoring
- Python transformation logic
- Snakemake orchestration

### Repomix

Use Repomix to preserve the **contextual engineering bundle** for later phases.

The bundle must stay narrow and schema-governed, with one explicit exception:
- non-negotiable algorithm context for communication unflattening and full company-hierarchy logic

Include:
- rendered SQL
- schema context
- run context
- validation rules
- FK cascade graph
- staging-only metadata snapshot
- text normalization rules
- raw-to-staging transformation primitive
- `unflatten_hierarchy.py`
- `create_company_hierarchy.py`
- `upsert_sibling_companies.py`
- `SIBLING_COMPANY_PIPELINE.md`

Exclude:
- Bronze payloads
- benchmark exports
- raw `memory/`
- artifacts and logs
- historical noise
- anything that reads or exports `hubspot.*` data into the bundle

## Shared Cross-Entity Rules

The following rules are now treated as universal salvage constraints:

- UTF-8/mojibake cleaning applies across all entities, not only Silver or Opportunity
- date serialization must be deterministic before a record is considered staging-ready
- business object metadata must stay distinct from StackSync resolution metadata
- no write to `hubspot.*` happens without explicit confirmation
- company hierarchy must be treated as one package:
  parent-child definition first, then sibling/common-root grouping

The reusable implementation lives in:

- [pipeline/text_normalization.py](../pipeline/text_normalization.py)
- [pipeline/raw_to_staging_snippet.py](../pipeline/raw_to_staging_snippet.py)
- [docs/RAW_CSV_TO_STAGING_SNIPPET.md](RAW_CSV_TO_STAGING_SNIPPET.md)

## What Must Stay Out Of Codespaces

Do not package these into the clean repo surface:
- `bronze_layer/`
- `gold_layer/`
- `memory/`
- `benchmark/`
- `artifacts/`

Those may remain in the legacy workspace for reference, but not in the clean runtime repo.

## Remote Path Discipline

Assume the clean repo can be opened from:
- Codespaces: `/workspaces/icalps`
- Windows local checkout: `C:\...\IC_Load\ic-load`
- WSL / remote Linux: `/home/<user>/.../ic-load`

WSL is optional and should only be used when it streamlines development for a
Windows collaborator. It must not introduce path assumptions that break the
standard Windows checkout.

If WSL is used, prefer Linux-side paths for development work.
Do not reintroduce collaborator-specific absolute path assumptions into the runtime.

## Current Baseline Docs

Read these in order:

1. [docs/CANONICAL_EXECUTION_SPEC.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/CANONICAL_EXECUTION_SPEC.md)
2. [docs/ASSOCIATION_PROBE_TECHNICAL_STATE.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/ASSOCIATION_PROBE_TECHNICAL_STATE.md)
3. [docs/FUNCTIONALITY_COVERAGE_MATRIX.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/FUNCTIONALITY_COVERAGE_MATRIX.md)
4. [docs/CONTEXT_PACKAGING_PROCESS.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/CONTEXT_PACKAGING_PROCESS.md)
5. [docs/TARGET_REPO_ARCHITECTURE.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/TARGET_REPO_ARCHITECTURE.md)
6. [docs/LEGACY_IMPORT_MAP.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/LEGACY_IMPORT_MAP.md)

## Commit Anchors

- `984afa2` Bootstrap `ic-load` reusable pipeline repo
- `7a1e2bf` Add canonical execution spec and coverage matrix
- `3db4df9` Clarify sync and context packaging process
- `dad5071` Add salvation re-entry reference

## 85% Target Definition

The target is **85% functionality coverage**, not file coverage.

The must-have runtime core is:
- Bronze loader + watermarking
- Silver normalization + validation
- dbt boundary
- explicit Gold validation gate
- Gold upsert patterns
- schema/run context
- Gomplate/Repomix workflow
- Codespaces/devcontainer bootstrap
- live Postgres smoke testing for staging-only reverse lookup readiness and sibling candidate pressure

## Current Iteration Status

### Completed

- created the standalone `ic-load` repo
- added minimal devcontainer bootstrap
- added schema/run context
- added Gomplate SQL templates
- added narrow Repomix config
- defined canonical execution contract
- defined 85% coverage matrix
- defined packaging process
- defined target repo architecture
- defined legacy import map
- scaffolded the clean runtime directories
- implemented `context/` runtime loaders and DB contract
- implemented `pipeline/state.py` with explicit `GOLD_UPSERT` and `STACKSYNC_SYNC` stages
- implemented thin Gold, sync, and association executors
- preserved `DEDUPE_GUARD` as a probe-only calibration stage
- made `GOLD_VALIDATE` the explicit live-write approval stage
- made `GOLD_UPSERT` the default terminal stage in the clean runner
- implemented deterministic SQL rendering in `sql/`
- implemented the orchestration probe entrypoint
- added passing probe and SQL contract tests
- generated rendered SQL outputs under `sql/rendered/`
- added `requirements.txt` for container/bootstrap reproducibility
- added `pipeline/bronze.py` so the clean runner owns Bronze loading locally
- removed the devcontainer env-file dependency for Codespaces startup
- added `scripts/codespace-smoke.sh` for a remote-safe smoke path
- corrected the live deal StackSync column to `stacksync_record_id_87b7vd`
- added `pipeline.live_smoke` for staging-only Postgres contract probing
- added ad hoc transform context and staging metadata snapshot for Repomix
- promoted UTF-8/mojibake cleaning into a universal packaged rule
- added the reusable raw-CSV-to-staging transformation snippet
- confirmed the clean repo already exposes CLI-style orchestration via `runner`, `probe`, `live_smoke`, and the raw-to-staging snippet
- kept all new validation and assessment work on the safe side of `hubspot.*`
- **association probe completion (branch w/assoc-probe-completion)**:
  - fixed `association_bridge.sql.tmpl` from single-pass to two-pass (M1)
  - removed hardcoded PostgreSQL credentials from `unflatten_hierarchy.py` (M2)
  - documented `../../` path dependency in `repomix.config.json` (M3)
  - documented `silver.py` legacy path dependency as Codespaces blocker (M4)
  - added Meetings deferral note with explicit conditions to `schema_context.yaml` (M5)
  - completed `ASSOCIATION_PROBE_TECHNICAL_STATE.md` with full algorithm descriptions,
    StackSync timing model, complete association map, and missing-file flags
  - added `GomplateRepoMix/render_associations.sh` concrete execution script
  - added entity-level prompt files for Silver pipeline reproducibility fallback

### Known Blockers Before Codespaces Execution

These must be resolved before the clean runner can execute in a fresh Codespaces:

1. `pipeline/silver.py` loads `silver_normalise.py` and `validate_silver.py` from
   `PROJECT_ROOT.parent / "ic_load_pipeline" / "python-ignorethis"` (M4)
   — copy or rewrite both files inside `ic-load`
2. `deal_stage_mapper.py` not in `ic-load` — runner metadata will not load stage rules
3. `unflatten_hierarchy.py` not in `ic-load` — repomix bundle misses it in Codespaces
4. `ic_load_pipeline/dbt_communication/` not in `ic-load/dbt/` — dbt step fails

### Next Approved Iteration

Resolve the Codespaces execution blockers (M3 and M4):

Priority order:
- copy `silver_normalise.py`, `validate_silver.py`, `deal_stage_mapper.py` into
  `ic-load/context/algorithms/` and update `silver.py` to use repo-local paths
- copy `unflatten_hierarchy.py` into `ic-load/context/algorithms/`
- decide whether the full `dbt_communication/` project belongs inside `ic-load/dbt/`
  or whether it stays as an external path requirement in the devcontainer
- merge `w/assoc-probe-completion` to `main` after the above is verified
- push to GitHub remote and verify Codespaces boot end-to-end

## Resume Instruction

When resuming work, say:

`Open salvation.md and continue with the next approved iteration for ic-load.`

Or, when the reusable method matters more than this specific repo state, say:

`Use $pipeline-salvation and reopen salvation.md for ic-load.`

That should be enough to recover the right project, the right boundary, and the right process quickly.
