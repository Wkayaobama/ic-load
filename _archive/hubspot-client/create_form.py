"""Create and manage HubSpot forms programmatically.

Migrated from WorkflowStacksync/form_updates/create_form_with_client.py.
MCP client dependency removed — uses direct requests + Bearer token.
CSV schema loading preserved for rapid form property population.

Modes:
  create                        Create a simple form (firstname, lastname, email)
  update-from-csv               Add properties from a CSV schema to an existing form
  build-deal-creation-form-spec Generate a deal-intake form spec from icalps fields
  deal-creation-preflight       Check readiness score (85% threshold) without creating
  deal-creation-form            Interactive deal creation from form spec
  create-deal-native-from-icalps Create a deal with sample values from CSV schema

Usage:
  python create_form.py --mode create --portal-id 9201667
  python create_form.py --mode update-from-csv --portal-id 9201667 --form-guid <guid> --schema-csv path/to/schema.csv
  python create_form.py --mode deal-creation-preflight --portal-id 9201667 --schema-csv path/to/schema.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import sys
from datetime import datetime, timezone
from typing import Any

import requests

from config import (
    get_headers, FORMS_API_V2, PROPERTIES_API, PIPELINES_API,
    SANDBOX_PORTAL_ID, IS_SANDBOX, require_production_confirmation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_raise(response: requests.Response, context: str) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        if response.status_code == 401:
            raise ValueError(
                f"HubSpot auth failed during '{context}' (401 Unauthorized).\n"
                "Verify your token has the required scopes for this operation."
            ) from exc
        raise


def _confirm_or_abort(message: str, assume_yes: bool) -> None:
    if assume_yes:
        return
    answer = input(f"{message} Type YES to continue: ").strip()
    if answer != "YES":
        raise SystemExit("Aborted by user.")


def _get_token_identity() -> dict[str, Any]:
    response = requests.get(
        "https://api.hubapi.com/integrations/v1/me",
        headers=get_headers(),
        timeout=30,
    )
    _safe_raise(response, "token_identity")
    return response.json()


# ---------------------------------------------------------------------------
# CSV schema loading (REQUIRED — rapid form property population)
# ---------------------------------------------------------------------------

def extract_property_names_from_csv(schema_csv: pathlib.Path) -> list[str]:
    """Extract canonical field names from a schema CSV.

    Reads the 'Canonical Field (Vault)' column. Deduplicates while
    preserving order. Tries multiple encodings for Windows compatibility.
    """
    names: list[str] = []
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with schema_csv.open("r", encoding=encoding, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    field = (row.get("Canonical Field (Vault)") or "").strip()
                    if field:
                        names.append(field)
            break
        except UnicodeDecodeError:
            names = []
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


# ---------------------------------------------------------------------------
# Property introspection
# ---------------------------------------------------------------------------

def get_contact_properties() -> dict[str, dict]:
    response = requests.get(
        f"{PROPERTIES_API}/0-1?archived=false",
        headers=get_headers(),
        timeout=30,
    )
    _safe_raise(response, "get_contact_properties")
    return {p["name"]: p for p in response.json().get("results", []) if p.get("name")}


def get_deal_properties() -> dict[str, dict]:
    response = requests.get(
        f"{PROPERTIES_API}/0-3?archived=false",
        headers=get_headers(),
        timeout=30,
    )
    _safe_raise(response, "get_deal_properties")
    return {p["name"]: p for p in response.json().get("results", []) if p.get("name")}


def discover_pipeline_and_stage() -> tuple[str, str]:
    response = requests.get(
        f"{PIPELINES_API}/deals",
        headers=get_headers(),
        timeout=30,
    )
    _safe_raise(response, "discover_pipeline_and_stage")
    results = response.json().get("results", [])
    if not results:
        raise ValueError("No deal pipelines found.")
    pipeline = results[0]
    stages = pipeline.get("stages") or []
    if not stages:
        raise ValueError(f"No stages in pipeline {pipeline['id']}.")
    return pipeline["id"], stages[0]["id"]


# ---------------------------------------------------------------------------
# Form creation
# ---------------------------------------------------------------------------

def create_form(portal_id: str) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    payload = {
        "name": f"IC ALPS Deal Intake {ts}",
        "submitText": "Submit",
        "notifyRecipients": "",
        "formFieldGroups": [
            {
                "fields": [
                    {"name": "firstname", "label": "First name", "type": "string", "fieldType": "text", "required": False},
                    {"name": "lastname", "label": "Last name", "type": "string", "fieldType": "text", "required": False},
                    {"name": "email", "label": "Email", "type": "string", "fieldType": "text", "required": True},
                ]
            }
        ],
    }
    response = requests.post(
        f"{FORMS_API_V2}?portalId={portal_id}",
        headers=get_headers(),
        json=payload,
        timeout=30,
    )
    _safe_raise(response, "create_form")
    return response.json()


# ---------------------------------------------------------------------------
# CSV-driven form field addition
# ---------------------------------------------------------------------------

def _to_form_field(prop: dict) -> dict:
    return {
        "name": prop["name"],
        "label": prop.get("label") or prop["name"],
        "type": prop.get("type", "string"),
        "fieldType": prop.get("fieldType", "text"),
        "required": False,
    }


def add_csv_properties_to_form(
    form_guid: str,
    schema_csv: pathlib.Path,
) -> tuple[dict, dict]:
    """Add fields from a CSV schema to an existing form.

    Matches CSV field names against HubSpot contact properties.
    Skips fields that don't exist or aren't form-compatible.
    """
    csv_names = extract_property_names_from_csv(schema_csv)
    available = get_contact_properties()

    matched: list[dict] = []
    skipped: list[str] = []
    for name in csv_names:
        prop = available.get(name)
        if not prop:
            skipped.append(f"{name} (not found)")
            continue
        if not prop.get("formField", False):
            skipped.append(f"{name} (not form-compatible)")
            continue
        matched.append(_to_form_field(prop))

    from forms import get_form
    existing = get_form(form_guid)
    groups = list(existing.get("formFieldGroups") or [])
    if groups:
        target = dict(groups[0])
        fields = list(target.get("fields") or [])
        existing_names = {f.get("name") for f in fields}
        for field in matched:
            if field["name"] not in existing_names:
                fields.append(field)
        target["fields"] = fields
        groups[0] = target
    else:
        groups = [{"fields": matched}]

    body = {
        "name": existing.get("name", "Updated form"),
        "redirect": existing.get("redirect"),
        "submitText": existing.get("submitText", "Submit"),
        "notifyRecipients": existing.get("notifyRecipients", ""),
        "formFieldGroups": groups,
    }
    response = requests.put(
        f"{FORMS_API_V2}/{form_guid}",
        headers=get_headers(),
        json=body,
        timeout=30,
    )
    _safe_raise(response, "update_form")
    updated = response.json()
    summary = {
        "requested_from_csv": len(csv_names),
        "matched": [f["name"] for f in matched],
        "skipped": skipped,
        "final_field_count": len((updated.get("formFieldGroups") or [{}])[0].get("fields", [])),
    }
    return updated, summary


# ---------------------------------------------------------------------------
# Deal form spec + capability preflight
# ---------------------------------------------------------------------------

def _is_icalps_field(name: str) -> bool:
    normalized = "".join(ch for ch in name.lower() if ch.isalnum())
    return normalized.startswith("icalps") or normalized.startswith("ccicalps")


def _is_writable(prop: dict) -> bool:
    if prop.get("calculated", False):
        return False
    mod = prop.get("modificationMetadata") or {}
    return not mod.get("readOnlyValue", False)


def build_deal_creation_form_spec(schema_csv: pathlib.Path) -> dict[str, Any]:
    csv_names = extract_property_names_from_csv(schema_csv)
    deal_props = get_deal_properties()
    candidates = [n for n in csv_names if _is_icalps_field(n)]

    matched: list[dict] = []
    skipped: list[str] = []
    for name in candidates:
        prop = deal_props.get(name)
        if not prop:
            skipped.append(f"{name} (not found)")
            continue
        matched.append({
            "name": prop["name"],
            "label": prop.get("label") or prop["name"],
            "type": prop.get("type"),
            "fieldType": prop.get("fieldType"),
            "required": False,
            "readOnly": not _is_writable(prop),
            "options": [
                {"label": o.get("label"), "value": o.get("value")}
                for o in (prop.get("options") or [])
                if not o.get("hidden")
            ],
        })

    return {
        "title": "Deal Creation Form Spec (ICALPS)",
        "objectType": "deal",
        "fields": matched,
        "summary": {
            "icalps_candidates": candidates,
            "matched": [f["name"] for f in matched],
            "skipped": skipped,
        },
    }


def evaluate_deal_form_capability(
    portal_id: str,
    schema_csv: pathlib.Path,
    threshold: int = 85,
) -> dict[str, Any]:
    """Preflight check: can we create a deal form for this portal?

    Scores 5 checks (25+20+20+15+20 = 100). Returns ready=True
    if score >= threshold (default 85%).
    """
    checks: list[dict] = []
    score = 0

    # 25 pts: token valid
    try:
        identity = _get_token_identity()
        checks.append({"check": "token_valid", "passed": True, "portalId": identity.get("portalId")})
        score += 25
    except Exception as exc:
        identity = {}
        checks.append({"check": "token_valid", "passed": False, "error": str(exc)})

    # 20 pts: portal match
    token_portal = identity.get("portalId")
    match = str(token_portal) == str(portal_id) and token_portal is not None
    checks.append({"check": "portal_match", "passed": match})
    if match:
        score += 20

    # 20 pts: deal schema access
    try:
        deal_props = get_deal_properties()
        checks.append({"check": "deal_schema_access", "passed": True, "count": len(deal_props)})
        score += 20
    except Exception as exc:
        deal_props = {}
        checks.append({"check": "deal_schema_access", "passed": False, "error": str(exc)})

    # 15 pts: pipeline + stage access
    try:
        pid, sid = discover_pipeline_and_stage()
        checks.append({"check": "pipeline_access", "passed": True, "pipeline": pid, "stage": sid})
        score += 15
    except Exception as exc:
        checks.append({"check": "pipeline_access", "passed": False, "error": str(exc)})

    # 20 pts: at least one writable icalps field
    csv_names = extract_property_names_from_csv(schema_csv)
    icalps = [n for n in csv_names if _is_icalps_field(n)]
    writable = [n for n in icalps if n in deal_props and _is_writable(deal_props[n])]
    checks.append({"check": "writable_icalps_fields", "passed": len(writable) > 0, "count": len(writable)})
    if writable:
        score += 20

    return {
        "threshold": threshold,
        "score": score,
        "ready": score >= threshold,
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="HubSpot form management")
    parser.add_argument("--mode", choices=[
        "create", "update-from-csv", "build-deal-creation-form-spec",
        "deal-creation-preflight", "deal-creation-form",
        "create-deal-native-from-icalps",
    ], default="create")
    parser.add_argument("--portal-id", type=str, default=SANDBOX_PORTAL_ID,
                        help=f"HubSpot portal ID. Defaults to sandbox ({SANDBOX_PORTAL_ID}). "
                             f"Production (9201667) requires confirmation.")
    parser.add_argument("--form-guid", type=str, default=None)
    parser.add_argument("--schema-csv", type=pathlib.Path,
                        default=pathlib.Path(__file__).resolve().parent / "schema" / "opportunity.csv",
                        help="CSV with 'Canonical Field (Vault)' column. "
                             "Available: schema/company.csv, schema/contact.csv, schema/opportunity.csv")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--capability-threshold", type=int, default=85)
    args = parser.parse_args()

    # Production gate — sandbox passes through; production requires explicit confirmation.
    require_production_confirmation(args.portal_id)

    env_label = "SANDBOX" if IS_SANDBOX else "PRODUCTION"
    print(f"  Environment: {env_label} (portal {args.portal_id})\n")

    if args.mode == "create":
        _confirm_or_abort(f"CREATE a new form in portal {args.portal_id}.", args.yes)
        result = create_form(args.portal_id)
        print(json.dumps({"guid": result.get("guid"), "name": result.get("name")}, indent=2))
        return 0

    if args.mode == "update-from-csv":
        if not args.form_guid:
            raise ValueError("--form-guid required for update-from-csv")
        _confirm_or_abort(f"UPDATE form {args.form_guid} in portal {args.portal_id}.", args.yes)
        _, summary = add_csv_properties_to_form(args.form_guid, args.schema_csv)
        print(json.dumps(summary, indent=2))
        return 0

    if args.mode == "build-deal-creation-form-spec":
        spec = build_deal_creation_form_spec(args.schema_csv)
        print(json.dumps(spec, indent=2, default=str))
        return 0

    if args.mode == "deal-creation-preflight":
        result = evaluate_deal_form_capability(args.portal_id, args.schema_csv, args.capability_threshold)
        print(json.dumps(result, indent=2, default=str))
        return 0

    print(f"Mode {args.mode} not yet implemented in migrated version.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
