# Raw CSV To Staging Snippet

This snippet formalizes the reusable path from:

`raw CSV -> universal text cleanup -> date serialization -> staging-shaped frame -> staging table`

Implementation:

- [`raw_to_staging_snippet.py`](/c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/pipeline/raw_to_staging_snippet.py)
- [`text_normalization.py`](/c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/pipeline/text_normalization.py)

## What It Covers

The snippet is intentionally generic and reusable across entities:

1. read CSV with `utf-8-sig`
2. clean selected text fields with the shared UTF-8/mojibake rule
3. serialize selected date fields to:
   `iso_datetime`, `iso_date`, or `epoch_millis`
4. rename columns into the target staging contract
5. add metadata columns
6. lowercase columns for PostgreSQL-friendly staging
7. optionally write to `staging.*`

## CLI

Example:

```powershell
python -m pipeline.raw_to_staging_snippet `
  bronze_layer/Bronze_Case_20260227_143640.csv `
  stg_ticket_snippet `
  --text-field Case_Description `
  --text-field Case_ProblemNote `
  --text-field Case_SolutionNote `
  --date-field Case_CreatedDate:iso_datetime `
  --date-field Case_CloseDate:epoch_millis `
  --rename Case_CaseId=icalps_ticket_id `
  --rename Case_Description=ticket_description `
  --output-csv artifacts/assessment/case_ticket_snippet.csv
```

To actually write to PostgreSQL staging:

```powershell
python -m pipeline.raw_to_staging_snippet ... --write-postgres
```

That write goes only to the table you name, typically under `staging.*`.
It does not write to `hubspot.*`.

## Relationship To The Runner

This snippet is not the full orchestration layer.
It is the reusable transformation primitive that the runner can call when we
need a clean entity-specific staging path such as `Case -> Ticket`.

The existing CLI orchestration entry points remain:

- [`runner.py`](/c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/pipeline/runner.py)
- [`probe.py`](/c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/pipeline/probe.py)
- [`live_smoke.py`](/c:/Users/ayaobama/Documents/AnthonySalesOps/Codebase/IC_Load/ic-load/pipeline/live_smoke.py)
