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

The first probe is intentionally orchestration-focused. It proves stage sequencing and boundary clarity without requiring live production writes.

## Verification

The current salvage spine is covered by:

```powershell
pytest tests -q -p no:cacheprovider
```

## Local Status

The repo was created locally from the reusable salvage work.

GitHub remote creation was not completed from this shell because `gh auth status`
shows the configured token is invalid for account `Wkayaobama`.

When auth is fixed, create/push the remote with:

```powershell
gh auth login -h github.com
gh repo create ic-load --private --source . --remote origin --push
```
