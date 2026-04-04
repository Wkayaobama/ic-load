# ic-load

This is the extracted repository for the reusable IC'ALPS load pipeline contract
and salvage spine.

It is intentionally separate from `IC-D-LOAD`.

## Scope

- shared pipeline contract for the StackSync-backed load flow
- fixed schema context and variable run context
- thin runtime spine for Bronze -> Silver -> dbt -> Gold -> StackSync -> associations
- SQL rendering for entity upserts, engagement upserts, and association bridge patterns
- Repomix packaging for contract files plus non-negotiable algorithm context
- devcontainer bootstrap for consistent collaborator setup

## Explicit Boundary

Validation and approval happen before this project boundary.

This repo covers:
- PostgreSQL Bronze load/watermark orchestration
- Silver gate orchestration
- dbt as an external boundary
- Gold upsert and communication engagement SQL rendering
- explicit StackSync sync checkpoint
- association bridge SQL
- collaborator environment standardization

This repo does not cover:
- Snakemake rule authoring
- dbt model authoring
- Bronze payload archives, benchmark dumps, or `memory/`
- extraction-side workbook/UI tooling

## Runtime Entry Points

- `python -m pipeline.runner --probe-mode --entity company --bronze-csv-override probe.csv`
- `python -m pipeline.probe --entity company`
- `python -m pipeline.probe --entity communication`
- `python -m pipeline.live_smoke --sample-limit 5`
- `python -m pipeline.raw_to_staging_snippet bronze.csv staging_table --output-csv artifacts/assessment/sample.csv`

The orchestration probe proves stage sequencing and boundary clarity without
requiring live production writes.

The live smoke entrypoint is staging-only. It validates the shared PostgreSQL
staging contract, communication reconciliation readiness, and plural-domain
candidate pressure without touching `hubspot.*`.

The raw-to-staging snippet is the reusable primitive for:

- reading legacy CSVs with `utf-8-sig`
- applying the shared UTF-8/mojibake cleanup rule
- serializing dates deterministically
- reshaping columns into a PostgreSQL staging contract
- writing only to the named staging table when explicitly requested

See [docs/RAW_CSV_TO_STAGING_SNIPPET.md](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/docs/RAW_CSV_TO_STAGING_SNIPPET.md).

## Shared Normalization Rules

The clean repo now treats text cleanup as a universal cross-entity rule.

- `pipeline/text_normalization.py` is the runtime implementation
- `GomplateRepoMix/text_normalization_rules.yaml` is the packaging contract
- the rule applies across company, contact, opportunity, communication, and case flows

This is intentionally separate from StackSync resolution metadata.
Business object fields are cleaned and shaped toward the HubSpot object contract.
`stacksync_record_id_*` values remain resolution infrastructure, not business payload metadata.

## Repomix Rule

Gomplate stays SQL-only.

Repomix must include:
- rendered SQL
- schema and run context
- validation rules
- FK cascade graph
- staging metadata snapshot
- text normalization rules
- raw-to-staging transformation primitive
- communication unflattening context
- sibling-company algorithm context

Repomix must exclude:
- Bronze payload archives
- `memory/`
- benchmark dumps
- artifacts
- direct `hubspot.*` exports

## Codespaces / Remote Use

The repo is set up so a fresh Codespace can validate the salvage spine without
a local env-file.

- install uses [requirements.txt](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/requirements.txt)
- post-create runs [scripts/codespace-smoke.sh](c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/scripts/codespace-smoke.sh)
- repository-level Codespaces secrets should provide live PostgreSQL credentials when needed
- the default remote-safe path remains the orchestration probe and staging-only smoke, not Gold-layer writes

## WSL / Folder Layout

The runtime should stay executable for Windows users first, while remaining
portable to Codespaces and optional WSL/VS Code Remote Development setups.

- preferred Codespaces path: `/workspaces/icalps`
- standard Windows checkout: `C:\...\IC_Load\ic-load`
- optional WSL clone path: `/home/<user>/src/ic-load`
- acceptable Windows-mounted WSL path for quick inspection: `/mnt/c/.../IC_Load/ic-load`

If a Windows collaborator prefers WSL for Python tooling or file watching, use
the Linux filesystem inside WSL rather than `/mnt/c/...`. This is only a
development convenience; the functional pipeline must keep working from the
standard Windows checkout as well.

The intended repo-root layout is:

- `context/`
- `pipeline/`
- `sql/`
- `dbt/`
- `tests/`
- `ValidationRules/`
- `GomplateRepoMix/`

All runtime code should resolve paths from the repo root rather than from
user-specific absolute paths.

## Verification

The current salvage spine is covered by:

```powershell
pytest tests -q -p no:cacheprovider
```

The current staging-only assessment artifacts also include:

- `artifacts/assessment/entity_translation_probe_sample.csv`
- `artifacts/assessment/case_ticket_snippet.csv`

These help validate entity translation and staging shaping without promoting any data into `hubspot.*`.

## Repository Status

The clean salvage repo lives at `https://github.com/Wkayaobama/ic-load.git`.

Use the remote repo as the collaboration anchor, and treat local Windows, WSL,
and Codespaces checkouts as interchangeable working copies of the same
repo-root layout.
