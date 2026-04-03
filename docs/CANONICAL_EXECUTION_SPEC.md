# Canonical Execution Spec

## Purpose

This document is the single execution contract for `ic-load`.

It reconciles the overlapping legacy sources:
- `workflowv2.md`
- `workflowv3.md`
- `WORKFLOW_FULL_PIPELINE.md`
- `Workflow_20260225.md`
- `WORKFLOW_COMMUNICATION_PIPELINE_STATUS.md`
- `memory/`

The goal is to preserve the core functionality while removing legacy sprawl.

## Scope

`ic-load` keeps the shared, reusable core only:
- Bronze to staging load
- Silver normalization and validation gate
- dbt transformation boundary
- Gold upsert patterns
- Engagement upsert patterns
- Association bridge patterns
- Devcontainer and Codespaces setup
- Validation and run context artifacts

`ic-load` does not own:
- Excel/xlwings operator UI
- ad hoc Power Query workbooks
- full dashboard/FastAPI extraction stack
- broad legacy exploration scripts
- gold-layer deduplication research artifacts

## Canonical Boundary

The true pipeline boundary is:

1. Validation and approval gate happens before `ic-load`
2. Bronze loader writes approved extracts to PostgreSQL `staging.*`
3. Silver normalization applies business cleaning and deduplication
4. Silver validation is the blocking quality gate
5. dbt transforms `staging -> intermediate -> marts`
6. SQL upserts write to `hubspot.*` on the shared StackSync PostgreSQL instance
7. StackSync syncs those rows to HubSpot
8. Association bridge SQL creates missing CRM associations

Important:
- Snakemake governs validation/approval orchestration, not dbt or SQL upserts
- dbt stays a separate transformation boundary and must not be reimplemented inside Gomplate
- the shared StackSync PostgreSQL instance is part of the production contract

## Minimal Runtime Flow

### Plan A: Main Entities

1. Bronze load
   Output:
   - `staging.stg_company`
   - `staging.stg_contact`
   - `staging.stg_opportunity`

2. Silver normalize
   Output:
   - `staging.stg_company_normalised`
   - `staging.stg_contact_normalised`
   - `staging.stg_opportunity_normalised`

3. Silver validate
   Blocking gate:
   - stop on schema-breaking failures
   - continue on controlled warnings

4. Gold upsert
   Targets:
   - `hubspot.companies`
   - `hubspot.contacts`
   - `hubspot.deals`

### Plan B: Communications

1. Bronze load
   Output:
   - `staging.stg_communication`

2. Silver normalize
   Output:
   - `staging.stg_communication_normalised`

3. Silver orphan gate
   Rule:
   - communication without company and without person is dropped from the CRM path

4. dbt pipeline
   Canonical lineage:
   - `stg_bronze_communication`
   - `int_communication_classified`
   - `int_communication_reconciled`
   - `fct_communication_calls`
   - `fct_communication_notes`
   - `fct_communication_tasks`
   - `fct_communication_meetings`

5. Engagement upsert
   Targets:
   - `hubspot.calls`
   - `hubspot.tasks`
   - `hubspot.notes`
   - `hubspot.meetings` when provisioned

6. Association bridge
   Targets:
   - notes -> contact/company/deal
   - calls -> contact/company
   - tasks -> contact/company
   - meetings -> contact/company when provisioned

## Canonical Invariants

### IDs and Matching

- Company match key: `Comp_CompanyId -> icalps_company_id`
- Contact match key: `Pers_PersonId -> icalps_contact_id`
- Deal match key: `Oppo_OpportunityId -> icalps_deal_id`
- Engagement idempotency key: `unique_id = 'icalps_' || icalps_communication_id`

### StackSync Record ID Columns

- Company: `stacksync_record_id_9vpp8v`
- Contact: `stacksync_record_id_nd85zc`
- Deal: `stacksync_record_id`

### Association Type IDs

- `notes_contact = 202`
- `notes_company = 190`
- `notes_deal = 214`
- `calls_contact = 194`
- `calls_company = 182`
- `tasks_contact = 204`
- `tasks_company = 192`

### Import / FK Order

1. Company
2. Contact
3. Deal
4. Communication

### Data Quality Rules That Survived Repacking

- filter out supplier companies
- deduplicate contacts by cleaned email, keep most recent
- deduplicate companies by cleaned domain, keep most recent
- clean domains: strip protocol, `www.`, trailing slash, path
- clean emails: strip literal `Email address` prefix, lowercase, validate
- map owner aliases to one canonical owner field
- compute weighted forecast, net amount, net weighted amount for deals
- map deal stage/outcome to real HubSpot stage IDs, never plain text stage names
- use `NOT EXISTS` guard in every association insert pattern

## What the Legacy Record Tells Us to Avoid

- Do not trust raw relative stage labels in HubSpot upserts
- Do not rely on generic association column names
- Do not mix StackSync UUID joins and legacy ID fallback logic accidentally
- Do not allow Bronze extraction gaps to create void records downstream
- Do not let dev environment setup depend on collaborator-specific absolute paths

## Codespaces Requirement

The target end state is a clean GitHub Codespace:
- fixed workspace root
- secrets-driven credential injection
- one bootstrap path
- no local path fallback in core runtime assumptions

That means `ic-load` must converge on:
- one devcontainer
- one environment contract
- one operator runbook
- one minimal test/smoke path
