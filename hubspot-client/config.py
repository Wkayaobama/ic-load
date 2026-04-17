"""HubSpot client configuration.

Reads credentials from environment variables. This package talks to
HubSpot directly (Bearer token auth) for one-time configuration
operations (form creation, property creation). It does NOT participate
in the data flow — that goes through managed Postgres + StackSync.
"""
from __future__ import annotations

import os


HUBSPOT_ACCESS_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN") or os.getenv("HUBSPOT_SANDBOX_TOKEN")
HUBSPOT_PORTAL_ID = os.getenv("HUBSPOT_PORTAL_ID")

FORMS_API_V2 = "https://api.hubapi.com/forms/v2/forms"
FORMS_API_V3 = "https://api.hubapi.com/marketing/v3/forms"
PROPERTIES_API = "https://api.hubapi.com/crm/v3/properties"
PIPELINES_API = "https://api.hubapi.com/crm/v3/pipelines"


def get_headers() -> dict[str, str]:
    if not HUBSPOT_ACCESS_TOKEN:
        raise ValueError(
            "Missing HubSpot token. Set HUBSPOT_ACCESS_TOKEN or "
            "HUBSPOT_SANDBOX_TOKEN environment variable."
        )
    return {
        "Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def require_portal_id() -> str:
    if not HUBSPOT_PORTAL_ID:
        raise ValueError("Missing HUBSPOT_PORTAL_ID environment variable.")
    return HUBSPOT_PORTAL_ID
