# salvation.md

This is the quick re-entry file for the `ic-load` repacking effort.

If the context window is tight, start here first.

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
6. SQL upserts write to `hubspot.*`
7. **bidirectional StackSync sync** hydrates CRM IDs and synced record IDs back into PostgreSQL
8. association bridge SQL runs **after sync**

Important:
- the Gold upsert is not the end of the write path
- the sync checkpoint is a real stage, not an implementation detail
- association creation depends on post-sync IDs

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
- non-negotiable algorithm context for communication unflattening and sibling-company logic

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

1. [docs/CANONICAL_EXECUTION_SPEC.md](CANONICAL_EXECUTION_SPEC.md)
2. [docs/FUNCTIONALITY_COVERAGE_MATRIX.md](FUNCTIONALITY_COVERAGE_MATRIX.md)
3. [docs/CONTEXT_PACKAGING_PROCESS.md](CONTEXT_PACKAGING_PROCESS.md)
4. [docs/TARGET_REPO_ARCHITECTURE.md](TARGET_REPO_ARCHITECTURE.md)
5. [docs/LEGACY_IMPORT_MAP.md](LEGACY_IMPORT_MAP.md)

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
- Gold upsert patterns
- bidirectional StackSync sync checkpoint
- engagement upsert
- association bridge
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

### Next Approved Iteration

Start the **second extraction pass** around the proven salvage spine.

Priority order:
- replace remaining legacy Silver wrappers with local extracted modules where safe
- decide whether sibling/parent company association handling belongs in the supported core
- wire optional live DB/dbt hooks behind the existing thin runtime boundary
- tighten Repomix bundle generation around the rendered SQL outputs
- push the local salvage history to the GitHub remote and verify Codespaces boot there

## Resume Instruction

When resuming work, say:

`Open salvation.md and continue with the next approved iteration for ic-load.`

That should be enough to recover the right project, the right boundary, and the right process quickly.
