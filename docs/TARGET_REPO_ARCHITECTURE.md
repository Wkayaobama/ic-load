# Target Repo Architecture

## Purpose

This document defines the landing zone for the first real runtime extraction.

It answers one question:

Where does each surviving part of the canonical pipeline live in `ic-load`?

The answer must stay aligned with the agreed production flow:

1. approved Bronze extracts enter `staging.*`
2. Silver normalization runs
3. Silver validation gates the run
4. dbt transforms `staging -> intermediate -> marts`
5. SQL upserts write to `hubspot.*`
6. StackSync bidirectionally syncs records and hydrates CRM IDs
7. association bridge SQL runs after sync

## Design Rules

- Keep only runtime-critical modules in the repo surface.
- Keep Bronze logic, but do not carry Bronze payload archives into Codespaces.
- Keep dbt as its own boundary. Do not reimplement dbt logic in Python or Gomplate.
- Keep SQL repetition in Gomplate templates, not in copied scripts.
- Keep post-upsert StackSync sync as an explicit stage in the architecture.
- Keep Repomix as the narrow packaging layer for later implementation phases.

## Top-Level Structure

### `context/`

Fixed and variable runtime contract.

Owns:
- schema loaders and validators
- run context loaders and serializers
- environment and connection contract
- stage/threshold lookup helpers

Expected contents:
- `schema_context.yaml`
- `run_context.yaml`
- Python helpers that read these files

### `pipeline/`

Imperative runtime orchestration.

Owns:
- stage enum and transition history
- runner entrypoints
- Bronze-to-staging load orchestration
- Silver normalize/validate orchestration
- dbt trigger boundary
- post-dbt Gold write orchestration
- explicit StackSync wait/checkpoint stage
- association bridge trigger

Expected module split:
- `state.py`
- `runner.py`
- `bronze.py`
- `silver.py`
- `gold.py`
- `sync.py`
- `associations.py`

### `sql/`

Schema-governed SQL assets only.

Owns:
- Gomplate SQL templates
- rendered SQL artifacts
- SQL execution wrappers only where needed

Expected structure:
- `templates/`
- `rendered/`
- `README.md`

`sql/` is where idempotent upsert and association patterns live.
This is the main anti-sprawl layer.

### `dbt/`

dbt project boundary only.

Owns:
- dbt models
- dbt tests
- dbt project config

Rules:
- unflattening/classification logic that already belongs in dbt stays here
- Gomplate must not generate dbt models
- Python should trigger dbt, not reproduce dbt

### `tests/`

High-signal verification only.

Owns:
- state-machine tests
- config/schema validation tests
- SQL render sanity checks
- one minimal orchestration smoke path

First-wave tests should prove:
- pipeline transition safety
- idempotent SQL rendering inputs
- sync-before-association ordering

### `docs/`

Operator and architecture documentation.

Owns:
- execution spec
- coverage matrix
- context packaging process
- architecture and import map
- recovery/runbook material

## Stage-to-Folder Ownership

| Stage | Owner |
| --- | --- |
| Bronze approved extract -> `staging.*` | `pipeline/bronze.py` + `context/` |
| Silver normalization | `pipeline/silver.py` |
| Silver validation gate | `pipeline/silver.py` + `context/` |
| dbt build/test trigger | `pipeline/runner.py` calling `dbt/` |
| Gold entity upserts | `pipeline/gold.py` + `sql/rendered/` |
| StackSync bidirectional sync checkpoint | `pipeline/sync.py` |
| Engagement upserts | `pipeline/gold.py` + `sql/rendered/` |
| Association bridge | `pipeline/associations.py` + `sql/rendered/` |
| Repomix handoff bundle | `GomplateRepoMix/` plus docs/validation assets |

## Explicit Non-Goals

These do not get first-class runtime space in `ic-load`:

- Bronze CSV archives
- benchmark exports
- `memory/` dumps
- dashboard and xlwings utilities
- ad hoc repair notebooks
- old one-off migration scripts with hardcoded secrets

## First Extraction Order

The runtime extraction should happen in this order:

1. `context/`
   Stabilize schema context, run context, and connection contract.

2. `pipeline/state.py`
   Move the state-machine contract first because every later stage depends on it.

3. `pipeline/silver.py`
   Preserve the blocking validation boundary before downstream writes.

4. `sql/templates/` and `sql/rendered/`
   Move entity upsert and association bridge patterns into the idempotent SQL layer.

5. `pipeline/gold.py` and `pipeline/associations.py`
   Keep the write path explicit:
   upsert -> sync checkpoint -> associations

6. `tests/`
   Port the highest-signal tests before broad cleanup.

## Codespaces Outcome

The repo is ready for a clean Codespace only when:

- the top-level structure above exists
- legacy runtime logic has a clear landing zone
- Bronze source payloads are absent from the repo
- environment resolution does not depend on local absolute paths
- the minimal smoke path runs from inside the devcontainer
