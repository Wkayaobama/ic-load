# StackSync Workflow Anatomy

Conventions derived from `custom_objects/sibling_workflow.yaml` (the 7-node reference artifact) and StackSync documentation at `https://docs.stacksync.com/workflow-automation`.

## Structure

A StackSync workflow YAML has three top-level keys:

```yaml
edges:                                  # directed transitions between nodes
modules:                                # the nodes themselves (trigger, actions, summary)
return_workflow_module_instance_ids:     # which node(s) return the final response
workflow_execution_timeout: 120         # seconds
workflow_module_execution_timeout: 120  # per-node timeout
```

## Edges

Each edge connects a source node to a target node. No conditional branching in our workflows — linear pipelines only.

```yaml
edges:
  - edge_id: post_trigger-resolve_fk
    source:
      handle_id: null
      workflow_module_instance_id: post_trigger
    target:
      handle_id: null
      workflow_module_instance_id: resolve_fk
```

`handle_id: null` is standard for single-output nodes (no branching).

## Module Types Used

### 1. Webhook Trigger (`system-webhook_trigger-1`)

Entry point. Receives HTTP request with query parameters.

```yaml
- module_id: system-webhook_trigger-1
  workflow_module_instance_id: post_trigger
  properties:
    method: GET
    query_parameters:
      data:
        - key: entity_type
          required: true
          type: string
        - key: record_id
          required: false
          type: string
        - key: dry_run
          required: false
          type: string
```

**Trigger URL pattern:**
```
https://besg.api.workflows.stacksync.com/workspaces/{workspace_id}/workflows/{workflow_id}:latest_draft/triggers/post_trigger/run_wait_result?entity_type=contact&dry_run=true
```

### 2. Postgres Query (`postgres-query-2`)

Executes SQL against the managed Postgres instance. This is the workhorse — all FK resolution, association UPDATEs, and seed table JOINs run here.

```yaml
- module_id: postgres-query-2
  workflow_module_instance_id: resolve_fk
  properties:
    postgres_connection:
      connection_app_type: postgres_heroku
      connection_management_type: managed
      connection_name: revops
    query: >-
      SELECT * FROM staging.fn_resolve_association(
        '{{ input.query_parameters.entity_type }}',
        'company',
        {{ input.query_parameters.dry_run | default: 'false' }}
      )
  error_handling_strategy:
    type: stop_on_error
```

**Key properties:**
- `connection_name: revops` — the StackSync-managed Postgres instance
- `connection_management_type: managed` — StackSync handles credentials
- `error_handling_strategy: stop_on_error` — workflow stops on SQL error (safety)

### 3. Summary / Return (`system-input-1`)

Returns the workflow result. Uses Liquid template syntax to reference prior node outputs.

```yaml
- module_id: system-input-1
  workflow_module_instance_id: summary
  properties:
    return_value: >-
      {
        "entity_type": "{{ input.query_parameters.entity_type }}",
        "dry_run": "{{ input.query_parameters.dry_run }}",
        "rows_updated": "{{ resolve_fk.rows | length }}",
        "status": "complete"
      }
```

## Naming Conventions

| Convention | Example | Rule |
|---|---|---|
| `workflow_module_instance_id` | `resolve_fk`, `post_trigger`, `summary` | Snake case, describes action |
| `module_id` | `postgres-query-2`, `system-input-1` | StackSync library ID with version suffix |
| `edge_id` | `post_trigger-resolve_fk` | `{source}-{target}` |
| `connection_name` | `revops` | Matches StackSync managed connection name |

## Error Handling

Two strategies used:

```yaml
# Stop the workflow on error (for data-critical nodes)
error_handling_strategy:
  type: stop_on_error

# No error handling (for informational nodes like summary)
error_handling_strategy: null
```

The form workflows use `stop_on_error` on all `postgres-query` nodes. If `fn_resolve_association()` fails (e.g., FK column not found, staging table empty), the workflow stops and the error is visible in StackSync's execution log.

## Execution Model

1. Webhook triggers the workflow
2. Nodes execute sequentially following edges
3. Each `postgres-query` node opens a fresh transaction on the managed Postgres
4. StackSync execution log shows per-node status, input/output, duration, errors
5. `return_workflow_module_instance_ids` nodes return the HTTP response to the trigger caller

---

## End-to-End Example: Form Submission → Association Resolution

This example walks through the full chain: creating a form locally, connecting it to a StackSync workflow, and verifying the association resolution fires.

### Phase A — Create the form locally (code)

The form is created via HubSpot Forms API using a script. This runs once per form — it's configuration, not data flow.

```javascript
// create-form.js — reference from hubspot-client/reference/
const portalId = process.argv[2];
const token = process.env.HUBSPOT_SANDBOX_TOKEN || process.env.HUBSPOT_ACCESS_TOKEN;

const payload = {
  name: `IC ALPS Deal Intake ${new Date().toISOString().replace(/[:.]/g, "-")}`,
  submitText: "Submit",
  notifyRecipients: "",
  formFieldGroups: [
    {
      fields: [
        { name: "firstname", label: "First name", type: "string", fieldType: "text", required: false },
        { name: "lastname", label: "Last name", type: "string", fieldType: "text", required: false },
        { name: "email", label: "Email", type: "string", fieldType: "text", required: true }
      ]
    }
  ]
};

const response = await fetch(
  `https://api.hubapi.com/forms/v2/forms?portalId=${portalId}`,
  {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  }
);
const data = await response.json();
// data.guid → the form ID used to connect the webhook trigger
```

The Python equivalent (`hubspot-client/create_form.py`) does the same with `requests` and adds CSV-driven field population.

### Phase B — Connect form to workflow (HubSpot UI — manual)

This is done by the operator in HubSpot, not by code:

1. **HubSpot UI → Automation → Workflows → Create workflow**
2. **Enrollment trigger:** "Form submission" → select the form created in Phase A
3. **Action:** "Send webhook" → paste the StackSync workflow trigger URL:
   ```
   https://besg.api.workflows.stacksync.com/workspaces/2219/workflows/{workflow_id}:latest_draft/triggers/post_trigger/run_wait_result?entity_type=opportunity
   ```
4. Save and activate

**Why UI, not code:** The HubSpot workflow builder's form trigger enrollment and webhook action are native UI features. Automating them via API adds significant complexity (Workflows API v4, enrollment criteria objects, action definitions) for a one-time setup step. The operator configures this once and it runs continuously.

### Phase C — StackSync workflow fires (managed, automatic)

When a form is submitted:

1. HubSpot workflow fires the webhook → StackSync endpoint
2. StackSync starts `opportunity_intake_workflow`
3. `postgres-query` module runs on managed Postgres:
   ```sql
   SELECT * FROM staging.fn_resolve_association('opportunity', 'company', false)
   ```
4. The function JOINs `staging.seed_deal_stage_map` for pipeline/stage
5. UPDATEs `hubspot.deals` with company association + pipeline/stage
6. StackSync outgoing sync pushes the changes to HubSpot

### Phase D — Verify locally (code)

After submission, run the dry-run query against managed Postgres to confirm:

```sql
SELECT * FROM staging.fn_resolve_association('opportunity', 'company', true);
-- Returns: source_hs_id, target_hs_id, updated (preview, no writes)
```

Or check directly:
```sql
SELECT id, dealname, associations_company, pipeline, dealstage
FROM hubspot.deals
WHERE icalps_deal_id = '<the_submitted_deal_id>';
```

---

## What's Code vs What's HubSpot UI

The pipeline is already complex. These items are explicitly **HubSpot UI configuration** — not code, not automated, not added to the pipeline. The operator sets them up once through the HubSpot interface.

| Item | Where | Why not code |
|---|---|---|
| **Form webhook trigger** | HubSpot Workflows UI | Native enrollment trigger. API equivalent (Workflows API v4) is disproportionately complex for a one-time setup. |
| **Form field adjustments** | HubSpot Forms UI (drag-and-drop) | Post-session-A refinements are faster in the UI than re-running create_form.py. |
| **Aircall tag → property mapping** | Aircall integration settings | Third-party integration UI. No API exposure. |
| **Follow-up workflow enrollment** | HubSpot Workflows UI | Enrollment criteria ("last call tag = follow-up") are native workflow builder features. |
| **Custom task status values** | HubSpot Settings → Tasks | One-time config. No API needed. |
| **Filtered views** | HubSpot object list UI | Verification views scoped by team/pipeline. Faster to build in UI. |
| **Test pipeline + stages** | HubSpot Settings → Sales → Pipelines | Pipeline/stage IDs recorded into seed table. UI creation, SQL consumption. |

| Item | Where | Why code |
|---|---|---|
| **Initial form creation** | `hubspot-client/create_form.py` | CSV-driven field population from schema. Faster than manual for 20+ fields. |
| **fn_resolve_association** | `sql/functions/` → managed Postgres | Core data flow. Must be version-controlled, testable, idempotent. |
| **Seed table** | `sql/seeds/` → managed Postgres | Deal stage mapping. Version-controlled CSV, deployed as SQL. |
| **Workflow YAMLs** | `workflows/` → StackSync import | Defines the node graph. Version-controlled, imported via StackSync UI. |

**Rule of thumb:** if it runs once during setup → HubSpot UI. If it runs on every form submission → code (SQL on managed Postgres). If it's between the two, lean toward UI to keep pipeline complexity flat.

---

## Docs

- Workflow overview: `https://docs.stacksync.com/workflow-automation`
- Custom connectors: `https://docs.stacksync.com/workflow-automation/developers/build-a-custom-connector`
- API proxy (not used for data flow): `https://docs.stacksync.com/api-proxy/hubspot`
