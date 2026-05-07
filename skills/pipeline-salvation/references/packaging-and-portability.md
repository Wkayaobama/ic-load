## Packaging And Portability

Treat second-machine portability as a proof surface, not a finishing touch.

## Gomplate

Use Gomplate only for repetitive SQL or other highly structured text rendering.

Good fits:

- idempotent upsert SQL
- association bridge SQL
- repetitive SQL fragments driven by schema constants

Bad fits:

- Python transformation logic
- dbt model logic
- orchestration

## Repomix

Repomix should preserve enough context to rebuild the rescued behavior without dragging the entire legacy workspace along.

Include:

- rendered SQL
- schema and run context
- business rules and thresholds
- critical mapping artifacts
- non-negotiable algorithm files
- only the benchmark or target-shape files needed to reconstruct behavior correctly

Exclude:

- raw archives unless they are needed for one active probe
- logs and artifacts
- broad exports copied for convenience
- production table dumps

Critical rule:

- once the clean repo is meant to travel, Repomix paths must resolve inside that repo or against explicitly versioned dependencies

## Devcontainer Or Codespaces

Before claiming portability, verify:

- the workspace path is repo-relative rather than folder-name specific
- the bootstrap script does not assume the parent workspace exists
- required tools are installed deterministically
- secrets are injected through the remote platform rather than local machine assumptions
- the smoke path does not require live writes

Red flags:

- hardcoded `/workspaces/<old-name>` paths
- references to files that only exist in a sibling legacy repo
- hidden dependence on local env files
- smoke scripts that only succeed on the original machine
