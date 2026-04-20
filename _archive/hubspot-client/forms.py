"""HubSpot form CRUD operations.

Migrated from WorkflowStacksync/form_updates/forms.py.
Auth modernized: hapikey params → Bearer token headers.
"""
from __future__ import annotations

from typing import Any

import requests

from config import get_headers, FORMS_API_V2


def get_all_forms() -> list[dict[str, Any]]:
    """List all forms in the portal."""
    response = requests.get(FORMS_API_V2, headers=get_headers(), timeout=30)
    response.raise_for_status()
    return response.json()


def get_form(form_guid: str) -> dict[str, Any]:
    """Get a single form by GUID."""
    response = requests.get(
        f"{FORMS_API_V2}/{form_guid}",
        headers=get_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def filter_forms_by_name(keyword: str) -> list[dict[str, Any]]:
    """Find forms whose name contains keyword (case-insensitive)."""
    forms = get_all_forms()
    return [f for f in forms if keyword.upper() in f.get("name", "").upper()]


def parse_form_constants(form: dict[str, Any]) -> dict[str, Any]:
    """Extract the immutable fields needed for a form update body."""
    return {
        "form_id": form["guid"],
        "name": form["name"],
        "submitText": form.get("submitText", "Submit"),
        "redirect": form.get("redirect"),
        "notifyRecipients": form.get("notifyRecipients", ""),
    }


def build_update_body(
    template_form: dict[str, Any],
    constants: dict[str, Any],
) -> dict[str, Any]:
    """Build the PUT body: constants from target form + field groups from template."""
    return {
        "name": constants["name"],
        "redirect": constants["redirect"],
        "submitText": constants["submitText"],
        "notifyRecipients": constants["notifyRecipients"],
        "formFieldGroups": template_form["formFieldGroups"],
    }


def update_form(form_guid: str, body: dict[str, Any]) -> requests.Response:
    """Update a single form via PUT."""
    response = requests.put(
        f"{FORMS_API_V2}/{form_guid}",
        json=body,
        headers=get_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response


def bulk_update_forms(
    forms_to_update: list[dict[str, Any]],
    template_form: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply template fields to multiple forms. Returns list of results."""
    results = []
    for form in forms_to_update:
        constants = parse_form_constants(form)
        body = build_update_body(template_form, constants)
        response = update_form(constants["form_id"], body)
        results.append({
            "form_id": constants["form_id"],
            "name": constants["name"],
            "status": response.status_code,
        })
    return results
