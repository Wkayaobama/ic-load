# Entity Card Schema

Each entity card is a YAML file loaded by `context/config.py` via `load_entity_card(entity)`.

Cards are the serialized medallion state for a single entity. They are consumed by:
- Prompt files (`GomplateRepoMix/prompts/*.txt`) to enforce entity lineage at pipe time
- The runner to resolve FK import order, dedup thresholds, and association patterns
- The dedup guardrail to know which fields to score and which reference columns to check

## Fields

```yaml
entity:          # Entity name (Company / Contact / Opportunity / Communication / Case)
object_type:     # HubSpot object type (companies / contacts / deals / engagements / tickets)
medallion:
  bronze:        # staging table name (pre-normalization)
  silver:        # normalized staging table name
  gold:          # hubspot.* target table
primary_key:
  source:        # IC'ALPS source column (e.g. Comp_CompanyId)
  canonical:     # Gold match key (e.g. icalps_company_id)
stacksync:
  record_id_column:  # stacksync_record_id_* column name in gold table
fk_dependencies:   # list of entities that must be upserted BEFORE this entity
  - entity: Company
    violation_policy: REJECT | WARN
    staging_fk: <column>
    gold_references: hubspot.companies.icalps_company_id
cardinality:
  - relation: "Company → Contact"
    type: 1:N
    description: "One company has many contacts"
associations:
  direct:        # StackSync-governed direct associations
    - target: Company
      mechanism: <description>
      fk: <staging column>
  engagement:    # Communication bridge associations
    - comm_type: Calls
      target: company
      association_type_id: 182
      assoc_table: hubspot.associations_calls_company
dedup:
  thresholds:
    review_score_min: float
    block_score_min: float
  key_fields:    # Fields used to compute identity signature for dedup
    - field: <name>
      weight: float
      strategy: exact | levenshtein | domain | email | digits
  intra_candidate_checks:
    - type: duplicate_primary_key | duplicate_identity_signature
silver_validation:
  stop_checks:   # list of check names that block the pipeline
  warn_checks:   # list of check names that warn but continue
pipeline_status:
  live_push_ready: true | false
  blockers:      # list of strings explaining why not ready (if false)
  runner_entity_arg: company | contact | opportunity | communication | case
```
