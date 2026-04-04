# ic-load

This is the extracted repository for the reusable IC'ALPS load pipeline contract and first runnable salvage spine.

It is intentionally separate from `IC-D-LOAD`.

## Scope

- Shared pipeline contract for the StackSync-backed load flow
- Fixed schema context and variable run context
- Thin runtime spine for Bronze -> Silver -> dbt -> Gold -> StackSync -> associations
- SQL rendering for entity upserts, engagement upserts, and association bridge patterns
- Narrow Repomix bundle inputs for LLM review
- Devcontainer bootstrap for consistent collaborator setup

## Explicit Boundary

Validation and approval happen before this project boundary.

This repo covers:
- PostgreSQL Bronze load/watermark orchestration
- Silver gate orchestration
- dbt as an external boundary
- Gold upsert and communication engagement SQL rendering
- explicit StackSync sync checkpoint
- association bridge SQL
- collaborator environment standardization

This repo does not cover:
- Snakemake rule authoring
- dbt model authoring
- Bronze payload archives, benchmark dumps, or `memory/`
- extraction-side workbook/UI tooling

## Runtime Entry Points

- `python -m pipeline.runner --probe-mode --entity company --bronze-csv-override probe.csv`
- `python -m pipeline.probe --entity company`
- `python -m pipeline.probe --entity communication`

The first probe is intentionally orchestration-focused. It proves stage sequencing and boundary clarity without requiring live production writes.

## Codespaces / Remote Use

The repo is now set up so a fresh Codespace can validate the salvage spine without a local env-file.

- install uses [requirements.txt](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/requirements.txt)
- post-create runs [scripts/codespace-smoke.sh](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/scripts/codespace-smoke.sh)
- repository-level Codespaces secrets should provide live PostgreSQL credentials when needed
- the default remote-safe path remains the orchestration probe, not live production writes

## WSL / Folder Layout

The runtime should also stay executable from WSL or VS Code Remote Development.

- preferred Codespaces path: `/workspaces/icalps`
- preferred WSL clone path: `/home/<user>/src/ic-load` or another Linux-side workspace
- acceptable Windows-mounted WSL path for quick inspection: `/mnt/c/.../IC_Load/ic-load`

For active development, prefer the Linux filesystem inside WSL over `/mnt/c/...` because Python tooling, Git, and file watching are usually more reliable there.

The intended repo-root layout is:

- `context/`
- `pipeline/`
- `sql/`
- `dbt/`
- `tests/`
- `ValidationRules/`
- `GomplateRepoMix/`

All runtime code should resolve paths from the repo root rather than from user-specific absolute paths.

## Verification

The current salvage spine is covered by:

```powershell
pytest tests -q -p no:cacheprovider
```

## Repository Status

The clean salvage repo now lives at `https://github.com/Wkayaobama/ic-load.git`.

Use the remote repo as the collaboration anchor, and treat local Windows, WSL,
and Codespaces checkouts as interchangeable working copies of the same
repo-root layout.
