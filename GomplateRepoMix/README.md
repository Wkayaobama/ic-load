# GomplateRepoMix

This folder is the reusable contract for the shared StackSync pipeline.

What is in scope:
- `schema_context.yaml`: fixed schema contract and execution boundary
- `run_context.yaml`: per-run counts and flags
- `templates/*.sql.tmpl`: SQL upsert and association bridge patterns only
- `repomix.config.json`: narrow review bundle for rendered SQL plus schema artifacts
- `fk_cascade_graph.mmd`: FK cascade contract

What is intentionally out of scope:
- Snakemake rules
- dbt model authoring
- Python transformation logic

The communication unflattening logic is a separate transformation concern. In this repo it sits outside `bronze_loader.py`; dbt handles communication classification/reconciliation after staging, while hierarchy shaping is handled by standalone unflattening logic.
