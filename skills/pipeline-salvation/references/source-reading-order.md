## Source Reading Order

Use this order when recovering context in a salvage project:

1. Open the re-entry file.
   In `ic-load`, this is `salvation.md`.

2. Read the execution boundary and packaging contract:
   - `docs/CANONICAL_EXECUTION_SPEC.md`
   - `docs/CONTEXT_PACKAGING_PROCESS.md`
   - `GomplateRepoMix/business_rules.yaml`

3. Read the ad-hoc algorithm context:
   - `docs/AD_HOC_TRANSFORM_CONTEXT.md`
   - `unflatten_hierarchy.py`
   - `custom_objects/SIBLING_COMPANY_PIPELINE.md`
   - `ic_load_pipeline/python-ignorethis/custom_objects/create_company_hierarchy.py`
   - `ic_load_pipeline/python-ignorethis/custom_objects/upsert_sibling_companies.py`

4. Read the safe execution and staging tools:
   - `docs/LIVE_POSTGRES_SMOKE_TEST.md`
   - `docs/RAW_CSV_TO_STAGING_SNIPPET.md`
   - `pipeline/raw_to_staging_snippet.py`
   - `pipeline/text_normalization.py`

5. Read the live runner boundary only after the contracts are clear:
   - `pipeline/runner.py`
   - `pipeline/live_smoke.py`
   - `sql/render.py`

Stop and restate the boundary before proposing any live write.
