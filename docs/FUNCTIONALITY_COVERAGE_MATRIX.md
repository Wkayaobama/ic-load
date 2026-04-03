# Functionality Coverage Matrix

## Goal

The repacking target is **85% functionality coverage** with a minimal codebase.

This is not file-count coverage.
It measures whether a new collaborator can run the core business flow safely and repeatably.

## Scoring Rule

Each capability is scored:
- `Keep`: preserve directly
- `Rewrite`: rebuild in smaller form
- `Defer`: known gap, not required for 85%
- `Drop`: not part of minimal core

Coverage counts toward the 85% target only when the capability is either:
- fully kept, or
- rewritten and verified in the new repo

## Matrix

| Capability | Legacy Source | Decision | Required for 85% | Notes |
|---|---|---:|---:|---|
| Bronze CSV -> staging load | `workflowv2.md`, `bronze_loader.py` | Keep | Yes | Core ingestion boundary |
| `_load_status` watermarking | `bronze_loader.py`, `workflowv2.md` | Keep | Yes | Important for idempotent upsert behavior |
| Silver normalization | `silver_normalise.py`, `workflowv2.md` | Rewrite | Yes | Needs smaller, explicit module surface |
| Silver validation gate | `validate_silver.py`, `workflowv2.md`, `workflowv3.md` | Keep | Yes | Blocking quality gate |
| FK import order | `Workflow_20260225.md`, schema docs | Keep | Yes | Company -> Contact -> Deal -> Communication |
| dbt communication lineage | `workflowv2.md`, `WORKFLOW_FULL_PIPELINE.md` | Keep | Yes | Must remain a separate boundary |
| Entity gold upsert | `upsert_to_gold.py`, memory notes | Rewrite | Yes | Reduce to idempotent SQL patterns |
| Bidirectional StackSync sync checkpoint | `Workflow_20260225.md`, `workflowv2.md` | Keep | Yes | Required between upsert and association bridge |
| Deal stage ID mapping | memory, `silver_layer_processing_plan.md` | Rewrite | Yes | Needed to prevent broken deal loads |
| Contact/company dedup rules | memory, silver plan | Rewrite | Yes | Needed to reduce void/duplicate records |
| Engagement upsert | `WORKFLOW_COMMUNICATION_PIPELINE_STATUS.md`, `WORKFLOW_FULL_PIPELINE.md` | Keep | Yes | Calls, notes, tasks; meetings conditional |
| Association bridge | `create_associations.py`, workflow docs | Keep | Yes | Core CRM linkage layer |
| Two-pass association fallback | `workflowv2.md` | Rewrite | Yes | Legacy ID fallback is a must-have pattern |
| Shared StackSync record ID contract | schema docs, memory | Keep | Yes | Constant, not run-variable |
| Gomplate SQL rendering discipline | user requirement, `GomplateRepoMix` | Keep | Yes | Prevents hand-copied SQL drift |
| Repomix contextual packaging discipline | user requirement, `GomplateRepoMix` | Keep | Yes | Preserves canonical context for later phases |
| Devcontainer local bootstrap | new `ic-load` assets | Keep | Yes | Needed for clean collaborator onboarding |
| Codespaces secret-based bootstrap | user requirement, devcontainer docs | Rewrite | Yes | Needed for remote clean-room setup |
| Canonical schema context | validation rules + new context | Keep | Yes | One source of truth |
| Canonical run context | delta/workflow docs + new context | Keep | Yes | One per-run source of truth |
| State machine orchestration | `workflowv3.md`, `run_company_pipeline.py` | Rewrite | Yes | Minimal explicit orchestration model |
| Gold layer deduplication research pipeline | `WORKFLOW_FULL_PIPELINE.md` Task 2 | Drop | No | Historical migration support, not core runtime |
| FastAPI/xlwings extraction UI | `workflowv2.md` tool stack | Drop | No | Useful operationally, not core package target |
| Power Query operator workbooks | memory plans | Drop | No | Keep as references, not runtime |
| Benchmark repair workflow | `workflowv2.md` Plan C | Defer | No | Good second-wave capability |
| Pre-2026 enrichment path | `COMMUNICATION_OWNER_MAPPING_PLAN.md` | Defer | No | Valuable but not first-wave minimal core |
| Missing communications special table | `BRONZE_TASK_TO_HUBSPOT_STACKSYNC.md` | Defer | No | Special-case extension |
| Bronze payload archives inside runtime repo | legacy workspace | Drop | No | Must stay out of Codespace/runtime surface |
| Raw memory/reference dumps inside runtime repo | legacy workspace | Drop | No | Reference only, not packaged runtime context |
| Full dashboard/reporting artifacts | legacy docs | Drop | No | Outside minimal repack scope |

## Coverage Summary

### Must-Have Capabilities

There are 22 capabilities required for the 85% threshold.

Current target state after this first planning iteration:
- clearly identified
- boundary-normalized
- not yet all implemented

### What Must Be Built Next

To hit the threshold, the next implementation waves should cover:

1. minimal runtime module layout
2. Bronze loader import into new repo
3. Silver normalization/validation path
4. dbt boundary packaging
5. gold upsert plus bidirectional sync checkpoint
6. association bridge execution path
7. Gomplate and Repomix packaging workflow
8. clean devcontainer/Codespaces flow
9. smoke tests and operator docs

## Iterative Delivery Order

### Iteration 1

- canonical execution spec
- coverage matrix

### Iteration 2

- target repo architecture
- import map from legacy -> new modules

### Iteration 3

- extract runtime core
- preserve schema/run context

### Iteration 4

- package dbt boundary
- package SQL upsert, sync checkpoint, and association execution path

### Iteration 5

- package Gomplate/Repomix workflow and file-selection rules
- clean Codespaces/devcontainer onboarding
- smoke tests

### Iteration 6

- 85% score review
- defer/drop list frozen

## Defer List

These are explicitly not required for the first 85%:
- benchmark-driven association repair
- full pre-2026 enrichment workflow
- Power Query task import side-channel
- full dashboard extraction stack
- historical gold deduplication migration artifacts
- Bronze payload storage inside the new repo
- raw memory/reference dumps inside the new repo

## Acceptance Signal

We can call the repack successful when a collaborator in a fresh Codespace can:

1. open the repo
2. load secrets
3. validate schema/run context
4. render SQL/context bundles with Gomplate and Repomix
5. run the core Bronze -> Silver -> dbt -> upsert -> sync -> association path
6. understand failures from one operator-facing runbook
