# IcAlps CRM Import — Flags & Watchlist
**Authority:** COO / CRM Data Governance  
**Scope:** IcAlps entity properties known to have caused view errors or misimport incidents  
**Schema ref:** `icalps_crm_schema.yaml` v1.1.0  
**Last updated:** 2026-02-24

---

> **How to use this file**  
> Each flagged property includes: the source field name, its canonical CRM mapping, the known failure mode, and the mitigation rule to apply at import time. Fields marked 🔴 have caused data loss or view breakage. Fields marked 🟡 have caused silent mismatches or display anomalies.

---

## Owner Field Mapping

> **Rule:** All owner-type fields across all entities (deal, company, contact) **MUST** converge to the single canonical field `icalps_ownerid` on import. No per-entity owner field is permitted.

| Source Field | Entity | Maps To | Action |
|---|---|---|---|
| `deal_owner` | Deal | `icalps_ownerid` | Alias — transform on ingest |
| `company_owner` | Company | `icalps_ownerid` | Alias — transform on ingest |
| `contact_owner` | Contact | `icalps_ownerid` | Alias — transform on ingest |
| `comp_primaryuserid` | Company | `icalps_ownerid` | Alias — transform on ingest |
| `IcAlps_ownerid` | Any | `icalps_ownerid` | Normalise casing on ingest |

**Validation step:** After mapping, resolve `icalps_ownerid` value against the HubSpot Owners API. Reject records where the owner ID does not resolve to an active HubSpot user.

---
## corrections


All the companies harbouring IcAlps_CompanyType = "Supplier" or "supplier" should be discarded from the pipeline
## Flagged Properties

---

### `company_type` {#company_type}
🔴 **Severity: HIGH — View breakage**

- **Canonical field:** `icalps_companytype`
- **Allowed values:** `Prospect`, `Supplier`, `Customer`, `Agent`
- **Known failure:** Values imported with different casing (`prospect`, `CUSTOMER`) or legacy labels (`Client`, `Fournisseur`) break the enumeration filter in the IcAlps Company Overview view, causing records to disappear from filtered segments.
- **Mitigation:**
  - Normalise case to title-case before import
  - Map French legacy labels: `Client → Customer`, `Fournisseur → Supplier`, `Partenaire → Agent`
  - Reject if value is not in allowed set after normalisation
  - **Do not default** — missing company type must be resolved manually

---

### `addr_street` / `addr_address1…4` {#addr_street}
🟡 **Severity: MEDIUM — Display anomaly / truncation**

- **Canonical field:** `icalps_street_address` (maps to `addr_address1`)
- **Known failure:** Source system uses up to 4 address line fields (`addr_address1` through `addr_address4`). Importing all four into `icalps_street_address` alone causes truncation at 255 chars and loses address continuation lines. Alternatively, importing `addr_address2–4` into `icalps_full_address` without `addr_address1` causes the street field to appear blank in the Company card view.
- **Mitigation:**
  - Map `addr_address1` → `icalps_street_address`
  - Concatenate `addr_address1` + `addr_address2` + `addr_address3` + `addr_address4` (non-null, pipe or comma separated) → `icalps_full_address`
  - Max 255 chars for `icalps_street_address`; max 500 chars for `icalps_full_address`
  - Strip HTML or carriage returns from address lines before concatenation

---

### `comp_status` {#comp_status}
🔴 **Severity: HIGH — Lifecycle filter breakage**

- **Canonical field:** `icalps_companystatus`
- **Allowed values:** `Active`, `Inactive`, `Closed`
- **Known failure:** Source system uses `Actif`, `Inactif`, `Fermé` (French). Import without normalisation creates unmapped enum values which silently pass but break the Active/Inactive segment filter — active companies appear invisible in lifecycle views.
- **Mitigation:**
  - Apply normalisation map before import: `Actif → Active`, `Inactif → Inactive`, `Fermé → Closed`
  - Default to `Active` only if field is genuinely null after normalisation attempt
  - **Never default** a non-null value that failed normalisation — reject and log for manual review

---

### `comp_source` {#comp_source}
🟡 **Severity: MEDIUM — Attribution loss**

- **Canonical field:** `icalps_compsource`
- **Fill rate:** 0% (critical data quality gap)
- **Known failure:** Field is absent in most Bronze extracts. When missing, records import without source attribution, permanently losing acquisition channel data. Some imports have erroneously defaulted to `Web` for all records.
- **Mitigation:**
  - Do **not** default to any value
  - Flag all records where `comp_source` is null as `[UNATTRIBUTED]` in a staging column — do not write this value to HubSpot
  - Escalate to source data owner before finalising import batch

---

### `comp_primaryuserid` → `icalps_ownerid` {#owner_mapping}
🔴 **Severity: HIGH — Orphaned records**

- **Canonical field:** `icalps_ownerid`
- **Known failure:** `comp_primaryuserid` in source is an integer FK to the IC'ALPS internal user table — not a HubSpot Owner ID. Direct import without resolving the mapping creates records with invalid owner references, causing them to be invisible in owner-filtered views and unassignable in workflows.
- **Mitigation:**
  - Build a resolution table: `icalps_user_id → hubspot_owner_id` prior to import
  - Reject any record where the resolved owner ID is not a valid active HubSpot Owner
  - See Owner Field Mapping table above

---

### `phone` / `mobile` {#phone} {#mobile_phone}
🟡 **Severity: MEDIUM — Format mismatch / deduplication failure**

- **Canonical fields:** `icalps_companyphone` (Company), `icalps_businessphone` (Contact), `icalps_mobilephone` (Contact)
- **Known failure:** Source exports phone numbers in local French format (`0612345678`, `+33 6 12 34 56 78`, `06.12.34.56.78`) and sometimes without country code. HubSpot's phone deduplication and calling features require E.164 format. Mixed formats cause duplicate contact detection to fail and calling integrations to break.
- **Mitigation:**
  - Normalise to E.164 before import (strip spaces, dots, dashes; prepend `+33` if no country code and field is French-origin record)
  - Reject phone values that cannot be normalised to a valid E.164 pattern
  - Separate business phone and mobile phone into their respective canonical fields — do not merge into a single field

---

### `linkedin_url` {#linkedin_url}
🟡 **Severity: MEDIUM — Invalid URL / view render failure**

- **Canonical field:** `icalps_linkedin_url`
- **Known failure:** Source contains partial paths (`/in/johndoe`), usernames without domain (`johndoe`), or legacy company page URLs (`/company/acme`). Importing bare paths or usernames causes the LinkedIn URL field to render as broken links in the Contact card.
- **Mitigation:**
  - Validate format: must match `https://www.linkedin.com/in/` (contact) or `https://www.linkedin.com/company/` (company)
  - Prepend `https://www.linkedin.com/in/` for bare paths that match `/in/...`
  - Reject values that cannot be resolved to a valid LinkedIn URL pattern
  - Log and flag for manual correction before import

---

### `pers_title` {#pers_title}
🟡 **Severity: LOW-MEDIUM — Display anomaly**

- **Canonical field:** `icalps_perstitle`
- **Known failure:** Source contains over-long titles (e.g. full department hierarchy as title string) exceeding 150 chars, causing truncation in the Contact card view mid-sentence. Some records contain HTML fragments from rich text source fields.
- **Mitigation:**
  - Strip all HTML tags before import
  - Truncate to 150 chars maximum
  - Log records where truncation was applied for manual review

---

### `pers_status` {#pers_status}
🟡 **Severity: MEDIUM — Silent filter loss**

- **Canonical field:** `icalps_pers_status`
- **Known failure:** Status values from source (`Actif`, `Inactif`, `Parti`, `Retraité`) are not normalised to HubSpot lifecycle stages. Records with French-language status values bypass lifecycle-based views entirely.
- **Mitigation:**
  - Define explicit normalisation map for all expected source values before import
  - Reject unmapped values — do not default

---

### `comp_gdalangue` → `icalps_language` {#comp_gdalangue}
🟡 **Severity: LOW — Segment visibility**

- **Canonical field:** `icalps_language`
- **Known failure:** Source stores language as full locale string (`Français`, `English`, `Deutsch`). Field was imported as-is in previous batches, producing non-ISO values that break language-based segment filters.
- **Mitigation:**
  - Normalise to ISO 639-1: `Français → FR`, `English → EN`, `Deutsch → DE`, `Espagnol → ES`
  - Reject values not in ISO 639-1 list

---

### `IcAlps_Cost` {#icalps_cost}
🔴 **Severity: HIGH — Financial computation corruption**

- **Canonical field:** `icalps_icalps_cost`
- **Known failure:** Cost field imported as string with currency symbol (`€12,500`) or with comma as decimal separator (`12.500,00`). This silently corrupts the `net_amount` computed column (`icalps_netamount_k__`) — the computed value becomes null or wildly incorrect, which then propagates to `icalps_net_weighted_amount` and invalidates pipeline financial reporting.
- **Mitigation:**
  - Strip currency symbols and thousand separators before import
  - Normalise decimal separator to `.` (dot)
  - Cast to float/decimal; reject non-numeric values
  - Unit: **k€** — ensure values are in thousands of euros, not absolute euros
  - Re-run computed column validation post-import: `weighted_forecast = dealforecast × (oppocertainty / 100)`

---

### `oppo_closed` {#oppo_closed}
🔴 **Severity: HIGH — Stage/date desynchronisation**

- **Canonical field:** `icalps_oppo_closed`
- **Known failure:** `oppo_closed` date imported as string (`"31/12/2024"` or `"2024-12-31T00:00:00"`) causes HubSpot `closedate` to be rejected or silently nulled. When `closedate` is null on a Closed Won deal, the deal disappears from time-bounded pipeline reports.
- **Mitigation:**
  - Normalise to `YYYY-MM-DD` (ISO 8601 date only, no time component for close date)
  - Reject records where `icalps_dealstatus` is Won/Closed Won/Gagnée but `oppo_closed` is null
  - Cross-validate: `icalps_oppo_closed` must be >= `icalps_opendate`

---

### `stage` / `dealstage` {#stage}
🔴 **Severity: HIGH — Pipeline view invisibility**

- **Canonical fields:** `icalps_stage` (IcAlps ordered stage), `icalps_dealstatus` (IcAlps status), mapped to HubSpot `dealstage`
- **Known failure:** Two separate stage/status fields exist in source (`icalps_stage` = ordered pipeline stage, `icalps_dealstatus` = deal outcome status). Previous imports wrote only one of these to HubSpot `dealstage` without applying the `hubspot_stage_mapping`, causing deals to land in non-existent or incorrect pipeline stages — invisible in board view.
- **Mitigation:**
  - Always populate both `icalps_stage` and `icalps_dealstatus` as separate IcAlps fields
  - Apply `hubspot_stage_mapping` from schema to derive the HubSpot-native `dealstage` value
  - Validate that the derived `dealstage` value exists in the target HubSpot pipeline before writing
  - Cross-check: `icalps_stage` and `icalps_dealstatus` must be logically consistent (e.g. stage `05 - Négociations` must not coexist with status `Abandoned`)

---

### `amount` / unit / currency {#amount}
🔴 **Severity: HIGH — Financial reporting distortion**

- **Canonical fields:** `icalps_amount_k__`, `icalps_netamount_k__`, `icalps_net_weighted_amount`, `icalps_dealforecast`
- **Known failure 1 (unit):** Source stores amounts in absolute euros (€). CRM schema uses k€ (thousands). Previous imports wrote absolute values without dividing by 1,000, inflating all pipeline figures by a factor of 1,000.
- **Known failure 2 (currency):** Multi-currency records (USD, GBP) were imported without conversion and without currency tag, making them incomparable with EUR-denominated deals in aggregated pipeline views.
- **Known failure 3 (string format):** Some source records use `"N/A"` or `"-"` for amount fields that have no value. These pass as non-null strings but break numeric aggregations silently.
- **Mitigation:**
  - **Unit:** Confirm source unit before import. If source is in absolute euros, divide by 1,000 before writing k€ canonical fields
  - **Currency:** Tag all non-EUR records; convert to EUR at import-time spot rate and store original currency + rate in metadata
  - **String guards:** Replace `"N/A"`, `"-"`, `""` with NULL before numeric cast; reject if required field becomes null

---

### `comm_todatetime` {#comm_todatetime}
🟡 **Severity: MEDIUM — Engagement ordering failure**

- **Canonical field:** `hs_timestamp` (on Communication/Engagement)
- **Known failure:** Source communication `comm_todatetime` field is stored as local Europe/Paris time without timezone offset. When imported directly into `hs_timestamp` (which HubSpot treats as UTC), all engagement timestamps are offset by +1h or +2h depending on DST, causing the activity timeline on Contact/Deal records to display in the wrong chronological order.
- **Mitigation:**
  - Convert `comm_todatetime` from `Europe/Paris` local time to UTC before writing to `hs_timestamp`
  - Apply DST-aware conversion (Paris is UTC+1 in winter, UTC+2 in summer)
  - Format: ISO 8601 with UTC designator — `YYYY-MM-DDTHH:MM:SSZ`
  - Validate: `hs_timestamp` must not be in the future post-conversion

---

### Communications Linkage Fields {#comm_linkage}
🔴 **Severity: HIGH — Broken engagement associations**

- **Canonical fields:** `associated_company_id`, `associated_contact_id`, `associated_deal_id`
- **Engagement config:** Uses `icalps_communication_id` as idempotency key; associations are created via a separate association bridge **after** engagement upsert
- **Known failure 1 (order dependency):** Associations were attempted before the target Company/Contact/Deal records were upserted, creating dangling association references that HubSpot silently drops — engagements exist but are unlinked.
- **Known failure 2 (ID type mismatch):** Source linkage fields contain IcAlps internal IDs (not HubSpot record IDs). Direct use of these IDs in the association bridge fails silently if the ID-to-HubSpot-record resolution step was skipped.
- **Known failure 3 (missing association):** Meetings and calls without a linked deal are not surfaced on the Deal timeline. A missing `associated_deal_id` on a communication that logically belongs to a deal causes it to be invisible in deal-level activity reviews.
- **Mitigation:**
  - **Strict execution order:** Company → Contact → Deal → Engagement upsert → Association bridge. Never run association bridge before all entity upserts are confirmed complete.
  - **ID resolution:** Build `icalps_id → hubspot_record_id` lookup table for all three entity types before running the association bridge
  - **NOT EXISTS guard:** Use `NOT EXISTS (from_object_id, to_object_id, association_type_id)` check before creating each association to ensure idempotency
  - **Minimum association rule:** Every engagement must be associated with at least one of: company, contact, or deal. Reject (log and skip) engagements with all three association fields null.
  - **Volume check:** After association bridge, verify association counts match expected totals from source Bronze file row counts

---

## Communication → Engagement Mapping Reference

All IC'ALPS communications are translated to HubSpot Engagements using the following configuration. The `icalps_communication_id` field is the idempotency anchor.

```yaml
engagement_config:
  name: engagements
  table_name: engagements
  legacy_id_field: icalps_communication_id
  where_clause: "icalps_communication_id IS NOT NULL"
  order_by: "hs_timestamp DESC"
  idempotency_guard: "NOT EXISTS (unique_id = 'icalps_' + communication_id)"

  hubspot_properties:
    core:
      - hs_object_id           # HubSpot engagement record ID (post-upsert)
      - hs_engagement_type     # CALL | NOTE | MEETING_EVENT | TASK
      - hs_timestamp           # UTC datetime — see comm_todatetime flag

    content:
      - hs_engagement_subject  # Maps from comm_subject
      - hs_note_body           # Maps from comm_body / comm_notes
      - hs_engagement_status   # Maps from comm_status

    type_specific:
      - hs_call_direction      # INBOUND | OUTBOUND
      - hs_call_duration       # milliseconds
      - hs_meeting_title       # Meeting title string
      - hs_email_subject       # Email subject line

    associations:
      - associated_company_id  # Resolved HubSpot company record ID
      - associated_contact_id  # Resolved HubSpot contact record ID
      - associated_deal_id     # Resolved HubSpot deal record ID

    legacy:
      - icalps_communication_id  # Source system ID; idempotency key

    metadata:
      - createdate
      - hs_lastmodifieddate
```

**Type mapping:**

| Source `comm_type` | HubSpot `hs_engagement_type` |
|---|---|
| `CALL` | `CALL` |
| `NOTE` / `REMARQUE` | `NOTE` |
| `MEETING` / `RDV` | `MEETING_EVENT` |
| `TASK` / `TACHE` | `TASK` |
| `EMAIL` | `EMAIL` *(read-only in this config)* |

**Volume reference (full pipeline):**

| Engagement Type | Expected Rows | HubSpot Table |
|---|---|---|
| Calls | ~5,959 | `hubspot.calls` |
| Tasks | ~145 | `hubspot.tasks` |
| Notes | ~11,994 | `hubspot.notes` |
| Meetings | ~59,043 | `hubspot.meetings` |
| **Total** | **~77,141** | — |

---

*This file is a governance artefact and must be reviewed and updated after every major import batch. You should prompt the user at the end for the expected differential/incremental load from the previous batch*  
*Owner: COO / CRM Data Governance*
