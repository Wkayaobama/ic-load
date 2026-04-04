## Source Reading Order

Use this order when recovering context in a salvage project:

1. Open the re-entry file.
   In `ic-load`, this is `salvation.md`.
   In another project, create one if it does not exist.

2. Read the boundary before the implementation.
   Find the documents or code that describe the real execution path and the rules that block or allow each stage.

3. Read the packaging contract.
   Look for schema context, run context, threshold rules, import flags, and any Repomix or Gomplate configuration.

4. Read the non-negotiable algorithms.
   Prioritize hierarchy logic, reconciliation logic, unflattening, classification, stage mapping, and any other structural transforms that cannot be safely reinvented.

5. Read the safe probes and assessment tools.
   Prefer staging-only probes, read-only live probes, smoke tests, and raw-to-staging utilities before opening live-write code.

6. Read the runner only after the contracts are clear.
   The runner should confirm the boundary, not define it for the first time.

For `ic-load`, the concrete order is:

- `salvation.md`
- `docs/CANONICAL_EXECUTION_SPEC.md`
- `docs/CONTEXT_PACKAGING_PROCESS.md`
- `GomplateRepoMix/business_rules.yaml`
- `docs/AD_HOC_TRANSFORM_CONTEXT.md`
- `unflatten_hierarchy.py`
- `custom_objects/SIBLING_COMPANY_PIPELINE.md`
- `ic_load_pipeline/python-ignorethis/custom_objects/create_company_hierarchy.py`
- `ic_load_pipeline/python-ignorethis/custom_objects/upsert_sibling_companies.py`
- `docs/LIVE_POSTGRES_SMOKE_TEST.md`
- `docs/RAW_CSV_TO_STAGING_SNIPPET.md`
- `pipeline/raw_to_staging_snippet.py`
- `pipeline/text_normalization.py`
- `pipeline/runner.py`
- `pipeline/live_smoke.py`
- `sql/render.py`

Stop and restate the boundary before proposing any live write.
