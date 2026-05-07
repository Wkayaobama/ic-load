# dbt Communication Pipeline — DuckDB/PostgreSQL Architecture & Mart Creation

## Overview

This document explains the dual-engine architecture of the `ic_load_communication` dbt project,
the process used to create a new Bronze-sourced mart (`fct_communication_email_meetings`),
and the errors encountered with their root causes and fixes.

---

## Engine Architecture

### DuckDB + PostgreSQL Attach Pattern

The project uses **DuckDB as the execution engine** with a **PostgreSQL database attached** as
an external alias. This is defined in `profiles.yml`:

```yaml
ic_load_duckdb_postgres:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: ':memory:'          # DuckDB runs fully in-memory
      attach:
        - path: "postgres://postgres:***@<host>:5432/postgres"
          type: postgres
          alias: pg_hubspot      # All PostgreSQL tables are accessed via this alias
      extensions:
        - postgres_scanner       # DuckDB extension that enables PostgreSQL reads
      threads: 4
```

**What this means in practice:**

| Concern | Resolution |
|---|---|
| DuckDB default database | `"memory"` — in-process, ephemeral |
| PostgreSQL access | Via `pg_hubspot` alias (DuckDB `postgres_scanner` extension) |
| Mart materialization target | `pg_hubspot.staging.*` (defined in `dbt_project.yml`) |
| Source tables read by models | Must be explicitly routed to `pg_hubspot` when not in DuckDB memory |

### Model Materialization Config (`dbt_project.yml`)

```yaml
models:
  ic_load_communication:
    staging:
      +materialized: view        # staging models = DuckDB views (in-memory)
    intermediate:
      +materialized: ephemeral   # intermediate = inlined CTEs, never persisted
    marts:
      +materialized: table
      +database: pg_hubspot      # mart tables are written to PostgreSQL
      +schema: staging           # under the staging schema
```

All `marts/` models are **created as physical tables in `pg_hubspot.staging.*`**. This means:
- The mart SQL executes inside DuckDB
- DuckDB reads source data (from PostgreSQL via `postgres_scanner`)
- DuckDB writes the result back to PostgreSQL via the attached connection

---

## Source Registration: Two Namespaces

The project has two distinct source namespaces for staging data:

### `staging` source — DuckDB memory / Silver-normalised

Defined without a `database` override, so dbt resolves it to DuckDB's in-memory `"memory"` database:

```yaml
- name: staging
  schema: staging
  tables:
    - name: stg_communication_normalised   # loaded into DuckDB memory by the pipeline
    - name: stg_company_normalised
    ...
```

These tables are pre-loaded into DuckDB memory by `silver_normalise.py` before `dbt run` is invoked.

### Direct PostgreSQL reference — Bronze tables not in DuckDB memory

For Bronze tables that exist only in PostgreSQL and are not pre-loaded into DuckDB memory,
the dbt source macro is bypassed entirely. The table is referenced directly using the
attached database alias from `profiles.yml`:

```sql
from "pg_hubspot"."staging"."stg_communication"
```

DuckDB resolves `pg_hubspot` to the attached PostgreSQL connection via `postgres_scanner`.
No `sources.yml` entry is required — the reference is self-contained in the model SQL.

**Why not use `{{ source(...) }}`?**
The dbt source macro requires a registered source entry. Adding a new source with
`database: pg_hubspot` at the source level works (see Error 3 below for the table-level
mistake), but it introduces a maintenance entry for a single Bronze table that is only
accessed by one model. The direct reference `"pg_hubspot"."staging"."stg_communication"`
is simpler, more transparent, and consistent with how DuckDB attached databases work.

---

## Building `fct_communication_email_meetings`

### Motivation

The Silver view `stg_communication_normalised` (6,127 rows) excludes any communication record
that lacks **both** a Company_Id **and** Person_Id anchor. This drops a large portion of
email/meeting records that have a contact but no company.

To capture all Email and Meeting activities with a resolved person, we must source from the
Bronze table `staging.stg_communication` (29,150 rows) directly.

### Source Table: `staging.stg_communication`

Confirmed column shape via probe (mixed-case original IC'ALPS names):

```
Comm_CommunicationId  bigint    — primary key
Comm_Action           text      — Meeting | EmailOut | EmailIn | PhoneOut | ToDo
Comm_Subject          text      — email/meeting subject
Comm_Note             text      — email body or notes
Comm_Email            text      — communication-level email address
Comm_DateTime         text      — activity datetime (cast to timestamp in model)
Comm_OriginalDateTime text      — start datetime
Comm_OriginalToDateTime text    — end datetime
Person_Id             text      — FK to Person (legacy contact ID)
Person_FirstName      text      — denormalised from Bronze JOIN
Person_LastName       text      — denormalised from Bronze JOIN
Person_EmailAddress   text      — contact email address (denormalised)
Company_Id            text      — FK to Company (legacy company ID)
Company_Name          text      — denormalised from Bronze JOIN
Comm_OpportunityId    text      — FK to Opportunity
Comm_CaseId           text      — FK to Case
```

**Key insight:** Person and Company fields are already denormalised in this table — no
additional JOIN is required. The person name, email, and company name are columns in Bronze.

### Filtering Logic

```
Comm_Action IN ('Meeting', 'EmailOut', 'EmailIn')   →  26,972 of 29,150 rows
AND Person_Id IS NOT NULL                           →   3,894 rows
```

No MailChimp filter was needed — probe confirmed `Comm_Note` contains no MailChimp patterns
in the filtered subset (after_mailchimp count = with_person count = 3,894).

### Deduplication Strategy

Raw 3,894 rows contain email thread duplicates: the same conversation appears as multiple rows
with subjects like `RE: Offre de réponses`, `RE: RE: Offre de réponses`, etc.

**Dedup key:** Normalised `Comm_Subject` per person.

1. Strip leading thread prefixes (case-insensitive, repeated):
   `Re:`, `Fw:`, `Fwd:`, `Tr:`, `Ref:`, `Réf:`, `Rép:`, `Rep:` and variants
2. `DISTINCT ON (norm_subject, legacy_contact_id)` — one canonical row per thread per contact
3. `ORDER BY icalps_communication_id ASC` — keeps the **earliest** message in the thread

### Final Model SQL

File: `models/marts/fct_communication_email_meetings.sql`

```sql
{{ config(materialized='table', schema='staging') }}

with base as (
    select
        "Comm_CommunicationId"                            as icalps_communication_id,
        "Comm_Action"                                     as comm_action,
        "Comm_Subject"                                    as comm_subject_raw,
        "Comm_Note"                                       as activity_body,
        "Comm_Email"                                      as comm_email,
        cast("Comm_DateTime"           as timestamp)      as activity_datetime,
        cast("Comm_OriginalDateTime"   as timestamp)      as original_datetime,
        cast("Comm_OriginalToDateTime" as timestamp)      as original_to_datetime,
        cast("Person_Id"               as integer)        as legacy_contact_id,
        "Person_FirstName"                                as person_firstname,
        "Person_LastName"                                 as person_lastname,
        "Person_EmailAddress"                             as person_email_address,
        cast("Company_Id"              as integer)        as legacy_company_id,
        "Company_Name"                                    as company_name,
        cast(nullif("Comm_OpportunityId", '') as integer) as legacy_deal_id,
        cast(nullif("Comm_CaseId", '')        as integer) as legacy_case_id
    from {{ source('pg_staging', 'stg_communication') }}
    where "Comm_Action" in ('Meeting', 'EmailOut', 'EmailIn')
      and "Person_Id" is not null
      and "Person_Id" != ''
),

normalised as (
    select *,
        trim(regexp_replace(
            lower(trim(coalesce(comm_subject_raw, ''))),
            '^((re|fw|fwd|tr|ref|réf|rép|rep)(\s*:\s*))+', '', 'gi'
        )) as norm_subject
    from base
),

deduped as (
    select distinct on (norm_subject, legacy_contact_id) *
    from normalised
    order by norm_subject, legacy_contact_id, icalps_communication_id asc
)

select *, current_timestamp as dbt_loaded_at
from deduped
```

### Downstream Usage

The `legacy_contact_id` and `legacy_company_id` integer columns are consumed by
`pipeline/emails.py` (API-native pathway):

- FK resolution: `POST /crm/v3/objects/{type}/search` by `icalps_*_id` property
- No StackSync tables read — Projects/Emails not yet mirrored
- Idempotency: local ledger table `staging.fct_emails_posted`

---

## Errors Encountered and Fixes

### Error 1 — Missing source `silver.custom_object_tasks`

**Symptom:**
```
Compilation Error
  Model 'stg_custom_object_tasks' depends on a source named 'silver.custom_object_tasks'
  which was not found
```

**Root cause:** `models/staging/stg_custom_object_tasks.sql` references
`{{ source('silver', 'custom_object_tasks') }}` but no source named `silver` was registered
in `sources.yml`.

**Fix:** Added a `silver` source stub to `sources.yml`:

```yaml
- name: silver
  schema: silver
  tables:
    - name: custom_object_tasks
      description: "Loaded by load_custom_object_tasks.py — source for stg_custom_object_tasks only"
```

This unblocks dbt parsing without affecting the model's runtime behaviour (the table either
exists or the model errors at runtime, not at compile time).

---

### Error 2 — `database` property not allowed at table level

**Symptom:** IDE diagnostic error 513: `Property database is not allowed` when adding
`database: pg_hubspot` under a specific table entry in `sources.yml`.

**Root cause:** In dbt, the `database` override is only valid at the **source** level
(i.e., on the `- name: <source>` block), not on individual `tables:` entries.

**Fix:** Created a dedicated source block `pg_staging` with `database: pg_hubspot` at the
source level, and registered `stg_communication` under it:

```yaml
- name: pg_staging
  database: pg_hubspot    # ← valid: source-level override
  schema: staging
  tables:
    - name: stg_communication
```

Updated the model to reference `{{ source('pg_staging', 'stg_communication') }}`.

---

### Error 3 — Table resolved to DuckDB `"memory"` instead of PostgreSQL

**Symptom:**
```
Catalog Error: Table with name stg_communication does not exist!
Did you mean "pg_hubspot.staging.stg_communication"?

LINE 56: from "memory"."staging"."stg_communication"
```

**Root cause:** The `staging` source in `sources.yml` has no `database` override, so dbt
resolves it to DuckDB's default in-memory database (`"memory"`). `stg_communication` exists
only in PostgreSQL, not in DuckDB memory. Other `staging` source tables (like
`stg_communication_normalised`) work because they are pre-loaded into DuckDB memory by
`silver_normalise.py` before `dbt run` is called.

**Fix:** Use the `pg_staging` source (Error 2 fix above), which explicitly routes to
`pg_hubspot.staging.*` via the attached PostgreSQL connection.

**Compiled SQL after fix:**
```sql
from "pg_hubspot"."staging"."stg_communication"
```

DuckDB resolves `pg_hubspot` to the attached PostgreSQL instance via `postgres_scanner`.

---

## Run Command

```powershell
cd "c:\Users\ayaobama\Documents\AnthonySalesOps\Codebase\IC_Load\ic_load_pipeline\dbt_communication"
dbt run --select fct_communication_email_meetings --no-partial-parse
```

`--no-partial-parse` forces a full reparse — required after changes to `sources.yml` to
ensure the new `pg_staging` source and `silver` stub are picked up cleanly.

---

## Files Modified / Created

| File | Change |
|---|---|
| `models/marts/fct_communication_email_meetings.sql` | **New** — Bronze-sourced Email+Meeting mart |
| `models/_sources/sources.yml` | Added `pg_staging` source, `silver` stub, `stg_communication` entry |
| `models/marts/_marts__models.yml` | Added model documentation entry with column tests |
| `probe.ps1` (ic-load root) | PowerShell probe used to explore `stg_communication` schema and validate filter counts |
