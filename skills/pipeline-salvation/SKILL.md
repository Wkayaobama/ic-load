---
name: pipeline-salvation
description: Rescue buried but still-functional CRM, ETL, sync-heavy, or data-pipeline codebases by isolating the minimal runnable core, separating critical files from noise, packaging non-negotiable algorithms with Repomix, limiting Gomplate to reusable SQL rendering, hardening devcontainer or Codespaces portability, and advancing through staged probes with explicit confidence thresholds before any live write, sync, or association step. Use when a codebase is messy, partially understood, shared-infrastructure backed, or needs iterative salvation rather than a rewrite.
---

# Pipeline Salvation

Recover the working core of a messy pipeline without pretending the right answer is a rewrite.

## Core Stance

- Optimize for salvation, not perfection.
- Preserve proven business behavior before cleaning style.
- Treat confidence thresholds as first-class deliverables.
- Keep the clean repo smaller than the legacy workspace.
- Refuse live writes until the runnable boundary and the evidence threshold are both explicit.

## Salvation Loop

1. Freeze the success threshold first.
   Define what counts as enough functionality to save.
   Measure coverage by working behavior, not by percentage of files copied.

2. Restate the real execution boundary in plain language.
   Name each step in order.
   Separate validation, staging, normalization, dbt, upsert, sync, and association behavior instead of collapsing them into one blur.

3. Separate the codebase into four buckets.
   Keep: directly powers the runnable core.
   Rewrite-minimal: needed, but only for boundary cleanup, import cleanup, or packaging cleanup.
   Defer: useful later, not required for the first confidence threshold.
   Drop: noise, historical artifacts, exports, UI sidecars, and dead branches.

4. Extract a thin runnable spine before cleaning details.
   Move the orchestration boundary, state tracking, and runtime contracts first.
   Leave working transformation logic in place unless there is a compelling reason to rewrite.

5. Externalize the repetitive and fragile parts.
   Use Gomplate for reusable SQL shapes only.
   Use Repomix for the narrow context bundle that preserves the non-negotiable execution logic.

6. Build proof in ascending risk order.
   Start with local contract tests.
   Then run staging-only probes.
   Then run read-only live metadata or schema probes.
   Only then consider approved live execution.

7. Reassess when a guardrail overreaches.
   If a protective mechanism blocks too much of the core path, downgrade it to probe-only, recalibrate it, and keep moving.
   Do not force an immature guardrail into production just because its logic sounds correct.

8. Commit recovery checkpoints.
   Save the repo after each stable boundary so context can be recovered quickly later.

For the iterative loop in more detail, read [references/salvation-loop.md](references/salvation-loop.md).

## What To Preserve

Preserve these kinds of assets aggressively:

- stage boundaries and runner contracts
- schema contracts and threshold rules
- entity configuration and legacy-to-canonical mapping
- non-negotiable algorithms such as hierarchy reconstruction, reconciliation, or classification
- idempotent SQL patterns
- smoke probes and assessment artifacts that prove the contract

Treat these as likely noise unless proven otherwise:

- raw archives that are only historical evidence
- dashboards, workbook front-ends, and reporting shells
- one-off repair scripts with no surviving business role
- instance-specific exports copied into the runtime repo
- convenience wrappers that hide the real execution order

## Gomplate And Repomix Rules

Use Gomplate for:

- entity upserts
- engagement upserts
- association bridge SQL
- other repetitive SQL patterns where idempotency and schema constants matter

Do not use Gomplate for:

- Python normalization logic
- dbt model logic
- orchestration logic
- business-rule inference

Use Repomix to preserve:

- rendered SQL
- schema and run context
- validation and threshold rules
- core mapping contracts
- non-negotiable algorithm sources
- minimal benchmark or target-shape references needed to reconstruct behavior correctly

Do not let Repomix depend on a wider parent workspace once the clean repo is meant to travel.

For packaging and second-machine discipline, read [references/packaging-and-portability.md](references/packaging-and-portability.md).

## Probe Discipline

Use probes to turn ambiguity into evidence.

Progress in this order:

1. Local unit or contract tests
2. Generated artifacts and rendered output
3. Staging-only probes
4. Read-only live metadata probes
5. Approved live execution

At each layer, ask:

- Does the output match the target contract?
- Does the boundary still match the real production path?
- Is the result portable to a second machine?
- Is confidence increasing or are we hiding uncertainty behind structure?

If you need confidence thresholds or calibration gates, read [references/thresholds-and-proof.md](references/thresholds-and-proof.md).

## Non-Negotiable Rules

- Keep business fields separate from resolution infrastructure such as sync IDs.
- Treat UTF-8 or mojibake cleanup and deterministic date serialization as cross-entity concerns when the codebase shows that pattern.
- Treat hierarchy logic as one package when sibling inference depends on parent selection or common-root matching.
- Treat communication unflattening or equivalent structural normalization as first-class logic, not optional commentary.
- Require explicit approval before any live production write.
- Prefer probe-only guardrails over premature production guardrails.

## Reuse Pattern

When applying this skill to a new project:

1. Create or open a re-entry file.
2. Write the canonical execution path.
3. Define the first confidence threshold.
4. Build the minimal spine that can prove that threshold.
5. Package the critical context so another agent can pick the work back up.
6. Only then widen the executable boundary.

## Read Next

- Use [references/source-reading-order.md](references/source-reading-order.md) to rebuild context.
- Use [references/dedupe-guardrails.md](references/dedupe-guardrails.md) only when duplicate prevention is part of the active rescue path.
