---
name: pipeline-salvation
description: Salvage messy CRM, ETL, and sync-heavy data pipelines into a minimal runnable repo without losing business-critical behavior. Use when Codex needs to extract a functional core from a sprawling codebase, make stage boundaries explicit, preserve non-negotiable algorithms with Repomix, keep Gomplate limited to SQL rendering, prepare Codespaces-safe execution, or design staging-first deduplication and smoke-test guardrails before any production upsert or association write.
---

# Pipeline Salvation

Use this skill to recover a working pipeline without pretending the clean repo is a rewrite.

## Core Workflow

1. Open the project's re-entry file first.
   For `ic-load`, start with `salvation.md`.

2. Freeze the real production path before moving code.
   Capture the exact boundary between validation, staging, dbt, Gold upsert, StackSync sync, and post-sync associations.

3. Extract the runnable spine before cleaning details.
   Preserve working business logic wherever possible.
   Prefer import cleanup, boundary cleanup, and packaging cleanup over rewrites.

4. Keep SQL generation and context packaging separate.
   Use Gomplate for repetitive SQL patterns only.
   Use Repomix for the narrow context bundle that explains the runtime.

5. Prove staging and reconciliation contracts before any live write.
   Start with `information_schema` and `staging.*`.
   Treat production-facing writes as blocked until staging, IDs, and reverse-lookup behavior are understood.

6. Add a dedupe guardrail before Gold or association execution.
   Do not rely on `NOT EXISTS` alone.
   Prevent duplicate business objects before they can be linked through mirrored association tables.

## Non-Negotiable Rules

- Preserve business behavior over elegance in the first salvage pass.
- Keep business fields separate from StackSync resolution metadata.
- Treat company hierarchy as one package: parent-child definition, sibling inference, and common-root grouping together.
- Treat communication unflattening as structural logic, not optional context.
- Apply UTF-8/mojibake cleanup and deterministic date serialization before staging normalization.
- Never write to live production tables until the guardrails and the write target are explicitly approved.

## Dedupe Gate

Install a duplicate-prevention gate before:

- Gold upsert
- mirrored association writes

Use three decisions:

- `safe`: allow downstream write
- `review`: materialize for inspection, do not write
- `block`: stop the write path

Use composite matching, not one signal alone:

- canonical ID collisions
- exact identity fields such as email, phone, or domain where applicable
- normalized name similarity
- company hierarchy context and common-root grouping
- corroborating fields such as LinkedIn, address, company linkage, or owner context when available

Important:

- Association idempotency prevents duplicate association rows.
- It does not prevent linking the wrong live entity.
- Mirrored association tables can bypass native CRM friction, so they must inherit the same safety decision as the entity upsert path.

For the current dedupe framing, read [references/dedupe-guardrails.md](references/dedupe-guardrails.md).

## Gomplate And Repomix Discipline

Use Gomplate for:

- entity upserts
- engagement upserts
- association bridge SQL

Do not use Gomplate for:

- dbt model logic
- Python normalization logic
- workflow orchestration

Use Repomix to preserve:

- rendered SQL
- schema and run context
- validation rules
- staging metadata snapshots
- non-negotiable algorithm sources such as company hierarchy and communication unflattening

Do not bundle:

- Bronze payload archives
- memory dumps
- broad benchmark clutter
- production table exports

## Safe Testing Order

1. Validate local contracts and render output.
2. Run staging-only smoke tests.
3. Confirm reverse-lookup ID behavior from staging and metadata.
4. Confirm duplicate-prevention gate behavior.
5. Ask for explicit approval before any production-facing write.

When in doubt, stay on the staging side of the boundary.

## Read Next

When applying this skill to `ic-load`, read [references/source-reading-order.md](references/source-reading-order.md).
