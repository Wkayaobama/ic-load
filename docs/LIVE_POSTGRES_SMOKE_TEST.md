# Live Postgres Smoke Test

This is the first non-assumptive validation layer for the clean `ic-load` repo.

It exists to prevent a "pretty repo, absent functionality" outcome.

## Why This Matters

The clean repo already proves:
- orchestration stage boundaries
- SQL rendering shape
- idempotency contract shape

It still must prove:
- the actual shared PostgreSQL staging table structure
- the real communication reconciliation columns in `staging.fct_communication_*`
- the plural-domain pressure in `staging.stg_company_normalised`

That is what this smoke-test layer covers.

## Recommendation

Use a single safe path:

1. `inspect_staging_contract()` read-only preview

This keeps us honest without turning the clean repo into an unsafe write surface.

## Pros Of Real Testing Now

- catches schema drift that docs and YAML miss
- validates the staging-side reverse-lookup readiness against the actual shared instance
- confirms the communication marts still expose the columns the association bridge depends on
- confirms plural-domain sibling logic still has a live candidate surface
- reduces the risk of carrying the wrong table or column names into Codespaces

## Cons / Risks

- shared infrastructure means mistakes have blast radius
- StackSync sync itself is asynchronous and outside the scope of this safe smoke path
- direct Gold-layer probing can create false confidence before the clean repo is ready

## Safe Interpretation

The staging smoke is not a full production run.

It is a controlled proof that:
- the live staging relations exist
- the communication marts still expose reconciliation columns
- the sibling-company candidate surface still exists in staging
- the clean repo is grounded in the real transformation contract

## Commands

Read-only staging contract and algorithm preview:

```powershell
python -m pipeline.live_smoke --sample-limit 5
```

## Success Criteria

We consider the smoke pass successful when:

- required `staging.*` relations exist
- required communication reconciliation columns exist
- live row counts are coherent with the historical pipeline
- plural-domain groups exist in staging and can be profiled safely

## Current Known Guardrail

The clean schema contract originally carried the wrong deal StackSync column.

Correct live contract:
- company: `stacksync_record_id_9vpp8v`
- contact: `stacksync_record_id_nd85zc`
- deal: `stacksync_record_id_87b7vd`

Current operational rule:
- do not read from or write to `hubspot.*` in the clean-repo smoke path
