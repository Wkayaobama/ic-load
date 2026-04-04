# Context Packaging Process

## Why This Exists

We are not just shrinking the codebase.
We are preserving the contextual engineering needed for the next phase after salvage.

That means packaging is a first-class process, not an afterthought.

## Principle

The future implementation agent should receive:
- the smallest possible bundle
- the highest-signal contract files
- no instance-specific noise

## Process

1. Canonicalize the runtime contract.
   Inputs:
   - execution spec
   - schema context
   - run context
   - FK cascade graph

2. Render SQL patterns with Gomplate.
   Scope:
   - entity upsert SQL
   - association bridge SQL

3. Bundle the schema contract plus the minimum non-SQL algorithm context with Repomix.
   Include:
   - rendered SQL
   - schema context
   - run context
   - validation rules
   - FK cascade graph
   - communication unflattening context
   - sibling-company disambiguation context
   - staging-only metadata snapshot

4. Exclude operational noise.
   Exclude:
   - Bronze CSVs
   - benchmark exports
   - memory dumps
   - logs
   - parquet artifacts
   - historical notebooks or ad hoc scripts

5. Use the bundle as the handoff context for the next build phase.

## File Selection Policy

### Always Include

- `GomplateRepoMix/schema_context.yaml`
- `GomplateRepoMix/run_context.yaml`
- `GomplateRepoMix/staging_metadata_snapshot.json`
- `GomplateRepoMix/templates/*.sql.tmpl`
- rendered SQL outputs
- `ValidationRules/icalps_crm_schema.yaml`
- `ValidationRules/icalps_import_flags.md`
- FK cascade graph
- canonical execution docs
- `docs/AD_HOC_TRANSFORM_CONTEXT.md`
- `unflatten_hierarchy.py`
- `upsert_sibling_companies.py`
- `SIBLING_COMPANY_PIPELINE.md`

### Never Include

- `bronze_layer/**`
- `gold_layer/**`
- `memory/**`
- `benchmark/**`
- `artifacts/**`
- `hubspot/**` data exports
- large run outputs
- transient sync data

## Idempotency Strategy

Gomplate and Repomix support idempotency in different ways.

### Gomplate

Gomplate prevents drift by forcing repetitive SQL to be rendered from:
- one schema contract
- one run contract
- one template per pattern

This reduces manual copy/paste divergence.

### Repomix

Repomix prevents context drift by ensuring the next build phase sees:
- the same contract files
- the same rendered SQL outputs
- the same narrow schema bundle
- the same non-negotiable transformation algorithms for communication hierarchy and sibling-company logic

This reduces prompt/context pollution and helps the next iteration stay reproducible.

## Codespaces Rule

The Codespace should contain the runtime repo, not the historical warehouse of salvage material.

So the default Codespace/devcontainer surface must remain:
- minimal
- fast to index
- low-noise
- centered on runnable core functionality

Smoke validation from the clean repo must remain staging-only until the
functionality threshold is high enough to justify Gold-layer verification.
