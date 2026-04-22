# StackSync Upsert Plan — Email & Meeting Engagements

## Current State

`staging.fct_communication_email_meetings` is materialized and clean:
- HTML-stripped body, entity-decoded
- Thread dedup via normalized `norm_subject` + `legacy_contact_id`
- Mass-outreach filter (>5 identical subjects excluded)
- Explicit exclusions: "armed approved design partner", "semicon europa"
- StackSync FK columns resolved: `hubspot_contact_record_id`, `hubspot_company_record_id`

**Awaiting user approval before any write to `hubspot.*` tables.**

---

## Pathway: StackSync-Native

```
staging.fct_communication_email_meetings   (cleaned mart — current)
    │
    ├── [Step 1] dbt split models
    │       fct_comm_emails_ready    → hubspot.emails    (EmailOut + EmailIn)
    │       fct_comm_meetings_ready  → hubspot.meetings  (Meeting)
    │
    ├── [Step 2] StackSync outgoing sync
    │       Detects new rows in hubspot.emails / hubspot.meetings
    │       Pushes to HubSpot Engagements API automatically
    │
    └── [Step 3] Association bridge
            Batch engagement API: link each engagement → contact + company
            Uses hubspot_contact_record_id + hubspot_company_record_id
            from the resolved FK columns
```

**Why StackSync, not API-native:**
- Emails/meetings reference contacts and companies already mirrored by StackSync
- `hubspot.*` Postgres tables contain valid `stacksync_record_id_*` columns → join available
- StackSync handles idempotency, retry, and audit trail in UI
- No local ledger table needed (StackSync `unique_id` is the dedup key)

---

## Step 1 — Split dbt Models

### A. `fct_comm_emails_ready.sql`

```sql
{{ config(materialized='table', schema='staging') }}

select
    -- HubSpot Email engagement properties
    icalps_communication_id,
    'icalps_email_' || icalps_communication_id::text   as unique_id,
    comm_subject_raw                                   as hs_email_subject,
    activity_body                                      as hs_email_text,
    case comm_action
        when 'EmailOut' then 'EMAIL'
        when 'EmailIn'  then 'INCOMING_EMAIL'
    end                                                as hs_email_direction,
    activity_datetime                                  as hs_timestamp,
    -- Associations
    hubspot_contact_record_id                          as associated_contact_id,
    hubspot_company_record_id                          as associated_company_id,
    legacy_contact_id,
    legacy_company_id,
    legacy_deal_id,
    -- Owner passthrough
    person_email_address,
    dbt_loaded_at

from {{ ref('fct_communication_email_meetings') }}
where comm_action in ('EmailOut', 'EmailIn')
  and hubspot_contact_record_id is not null    -- only push if contact resolved
```

### B. `fct_comm_meetings_ready.sql`

```sql
{{ config(materialized='table', schema='staging') }}

select
    icalps_communication_id,
    'icalps_mtg_' || icalps_communication_id::text     as unique_id,
    comm_subject_raw                                   as hs_meeting_title,
    activity_body                                      as hs_meeting_body,
    activity_datetime                                  as hs_meeting_start_time,
    original_to_datetime                               as hs_meeting_end_time,
    'SCHEDULED'                                        as hs_meeting_outcome,
    -- Associations
    hubspot_contact_record_id                          as associated_contact_id,
    hubspot_company_record_id                          as associated_company_id,
    legacy_contact_id,
    legacy_company_id,
    legacy_deal_id,
    person_email_address,
    dbt_loaded_at

from {{ ref('fct_communication_email_meetings') }}
where comm_action = 'Meeting'
  and hubspot_contact_record_id is not null
```

---

## Step 2 — StackSync Table Mapping

StackSync must have an outgoing sync mapping for:

| Postgres table | HubSpot object | StackSync sync direction |
|---|---|---|
| `hubspot.emails` | Engagement (EMAIL) | Outgoing |
| `hubspot.meetings` | Engagement (MEETING) | Outgoing |

**Pre-condition check before writing:**
```sql
-- Verify StackSync has these tables mapped
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'hubspot'
  AND table_name IN ('emails', 'meetings');
```

If `hubspot.emails` or `hubspot.meetings` do not exist → StackSync has not registered
them as sync targets. In that case, fall back to the **API-native pathway** using
`pipeline/emails.py` (same pattern as `pipeline/projects.py`).

**Write mechanism (StackSync path):**
```sql
-- INSERT new rows only (idempotency via unique_id)
INSERT INTO hubspot.emails (
    unique_id, hs_email_subject, hs_email_text,
    hs_email_direction, hs_timestamp,
    associated_contact_id, associated_company_id
)
SELECT
    unique_id, hs_email_subject, hs_email_text,
    hs_email_direction, hs_timestamp,
    associated_contact_id, associated_company_id
FROM staging.fct_comm_emails_ready
WHERE unique_id NOT IN (SELECT unique_id FROM hubspot.emails WHERE unique_id LIKE 'icalps_email_%');
```

StackSync detects the INSERT → pushes to HubSpot → writes back `stacksync_record_id_*`.

---

## Step 3 — Association Bridge

After StackSync sync completes (stacksync_record_id columns populated),
run the two-pass association bridge for each engagement.

### Association Type IDs (to confirm from HubSpot portal)

| Engagement | Target | typeId | Status |
|---|---|---|---|
| Email → Contact | Contact | TBC | needs portal lookup |
| Email → Company | Company | TBC | needs portal lookup |
| Meeting → Contact | Contact | TBC | needs portal lookup |
| Meeting → Company | Company | TBC | needs portal lookup |

**Lookup command:**
```
GET /crm/v4/associations/EMAIL/CONTACT/labels
GET /crm/v4/associations/EMAIL/COMPANY/labels
GET /crm/v4/associations/MEETING/CONTACT/labels
GET /crm/v4/associations/MEETING/COMPANY/labels
```

### Two-Pass Bridge SQL (same pattern as calls/notes)

```sql
-- Pass A: UUID join (preferred — StackSync record ID available)
INSERT INTO hubspot.associations_emails_contact (email_id, contact_id, association_type_id)
SELECT
    e.stacksync_record_id,
    c.stacksync_record_id_nd85zc,
    <typeId>
FROM hubspot.emails e
JOIN staging.fct_comm_emails_ready r ON e.unique_id = r.unique_id
JOIN hubspot.contacts c ON r.associated_contact_id = c.stacksync_record_id_nd85zc
WHERE r.associated_contact_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM hubspot.associations_emails_contact a
      WHERE a.email_id = e.stacksync_record_id
        AND a.contact_id = c.stacksync_record_id_nd85zc
  )

UNION

-- Pass B: legacy ID fallback (when UUID not yet available)
SELECT
    e.stacksync_record_id,
    c.stacksync_record_id_nd85zc,
    <typeId>
FROM hubspot.emails e
JOIN staging.fct_comm_emails_ready r ON e.unique_id = r.unique_id
JOIN hubspot.contacts c ON r.legacy_contact_id = cast(c.icalps_contact_id as bigint)
WHERE r.associated_contact_id IS NULL
  AND r.legacy_contact_id IS NOT NULL
  AND c.stacksync_record_id_nd85zc IS NOT NULL
  AND NOT EXISTS (...)
```

---

## Execution Gates

| Gate | Condition | Who approves |
|---|---|---|
| `hubspot.emails` / `hubspot.meetings` exist | StackSync table check | Auto (probe) |
| Association type IDs confirmed | Portal lookup | User |
| Row counts acceptable | Review query output | **User approval required** |
| Write to `hubspot.*` | Any INSERT | **User approval required** |
| Association bridge run | After StackSync sync | **User approval required** |

---

## Pre-Write Review Query

Run this before any production write and share with user:

```sql
SELECT
    comm_action,
    COUNT(*)                                AS total,
    COUNT(hubspot_contact_record_id)        AS contact_resolved,
    COUNT(hubspot_company_record_id)        AS company_resolved,
    ROUND(100.0 * COUNT(hubspot_contact_record_id) / COUNT(*), 1) AS contact_pct,
    ROUND(100.0 * COUNT(hubspot_company_record_id) / COUNT(*), 1) AS company_pct
FROM staging.fct_communication_email_meetings
GROUP BY comm_action
ORDER BY comm_action;
```

Expected: contact resolution ≥ 85%. If below, investigate unresolved
`legacy_contact_id` values before proceeding.

---

## Files to Create (pending user approval)

| File | Purpose |
|---|---|
| `models/marts/fct_comm_emails_ready.sql` | Email engagement split model |
| `models/marts/fct_comm_meetings_ready.sql` | Meeting engagement split model |
| `sql/emails/01_stacksync_write_emails.sql` | Gated INSERT → hubspot.emails |
| `sql/emails/02_stacksync_write_meetings.sql` | Gated INSERT → hubspot.meetings |
| `sql/emails/03_association_bridge_emails.sql` | Two-pass association bridge |
| `sql/emails/04_post_run_verification.sql` | Count parity check |
| `context/cards/emails.yaml` | Entity card (association type IDs, sync status) |
