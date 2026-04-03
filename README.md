# ic-load

This is the extracted repository for the reusable IC'ALPS load pipeline contract.

It is intentionally separate from `IC-D-LOAD`.

## Scope

- Shared pipeline contract for the StackSync-backed load flow
- Fixed schema context and variable run context
- Gomplate templates for SQL upsert and association bridge patterns
- Narrow Repomix bundle inputs for LLM review
- Devcontainer bootstrap for consistent collaborator setup

## Explicit Boundary

Validation and approval happen before this project boundary.

This repo covers:
- PostgreSQL load/upsert patterns
- dbt-adjacent SQL contract inputs
- association bridge SQL
- collaborator environment standardization

This repo does not cover:
- Snakemake rule authoring
- dbt model authoring
- ad hoc Python transformation logic from the larger legacy workspace

## Local Status

The repo was created locally from the reusable salvage work.

GitHub remote creation was not completed from this shell because `gh auth status`
shows the configured token is invalid for account `Wkayaobama`.

When auth is fixed, create/push the remote with:

```powershell
gh auth login -h github.com
gh repo create ic-load --private --source . --remote origin --push
```
