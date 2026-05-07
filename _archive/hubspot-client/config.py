"""HubSpot client configuration.

Reads credentials from environment variables. This package talks to
HubSpot directly (Bearer token auth) for one-time configuration
operations (form creation, property creation). It does NOT participate
in the data flow — that goes through managed Postgres + StackSync.

Environment model
-----------------
Two portals, two token env vars, one rule:

  SANDBOX FIRST. Always probe sandbox before touching production.

  Sandbox: portal 49610528  →  HUBSPOT_SANDBOX_TOKEN
  Production: portal 9201667  →  HUBSPOT_ACCESS_TOKEN

Token resolution order:
  1. HUBSPOT_SANDBOX_TOKEN (if set → sandbox mode, safe)
  2. HUBSPOT_ACCESS_TOKEN  (if set → production mode, gated)

The CLI defaults to --portal-id 49610528 (sandbox). Production requires
explicit --portal-id 9201667 and a confirmation prompt.

For the live association sync (StackSync workflows), the swap is done in
the HubSpot UI: change the workflow's webhook trigger from sandbox private
app to production private app credentials. No code change needed.
"""
from __future__ import annotations

import os


# Portal IDs — hardcoded, not configurable. These are fixed per HubSpot account.
SANDBOX_PORTAL_ID = "49610528"
PRODUCTION_PORTAL_ID = "9201667"

# Token resolution: sandbox takes precedence when both are set.
# This ensures accidental runs hit sandbox, not production.
_SANDBOX_TOKEN = os.getenv("HUBSPOT_SANDBOX_TOKEN")
_PRODUCTION_TOKEN = os.getenv("HUBSPOT_ACCESS_TOKEN")

HUBSPOT_ACCESS_TOKEN = _SANDBOX_TOKEN or _PRODUCTION_TOKEN
HUBSPOT_PORTAL_ID = os.getenv("HUBSPOT_PORTAL_ID") or SANDBOX_PORTAL_ID

# True when we resolved to sandbox token (safe mode).
IS_SANDBOX = bool(_SANDBOX_TOKEN)

FORMS_API_V2 = "https://api.hubapi.com/forms/v2/forms"
FORMS_API_V3 = "https://api.hubapi.com/marketing/v3/forms"
PROPERTIES_API = "https://api.hubapi.com/crm/v3/properties"
PIPELINES_API = "https://api.hubapi.com/crm/v3/pipelines"


def get_headers() -> dict[str, str]:
    if not HUBSPOT_ACCESS_TOKEN:
        raise ValueError(
            "Missing HubSpot token. Set HUBSPOT_SANDBOX_TOKEN (recommended) "
            "or HUBSPOT_ACCESS_TOKEN environment variable."
        )
    return {
        "Authorization": f"Bearer {HUBSPOT_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def require_portal_id() -> str:
    if not HUBSPOT_PORTAL_ID:
        raise ValueError("Missing HUBSPOT_PORTAL_ID environment variable.")
    return HUBSPOT_PORTAL_ID


def require_production_confirmation(portal_id: str) -> None:
    """Gate production operations behind an explicit confirmation.

    Called by CLI entry points before any mutating call to production.
    Sandbox operations pass through without prompt.
    """
    if portal_id == PRODUCTION_PORTAL_ID and not IS_SANDBOX:
        print(f"\n  WARNING: You are targeting PRODUCTION portal {PRODUCTION_PORTAL_ID}.")
        print(f"  Token source: HUBSPOT_ACCESS_TOKEN (not sandbox).\n")
        answer = input("  Type PRODUCTION to confirm, or Ctrl+C to abort: ").strip()
        if answer != "PRODUCTION":
            raise SystemExit("Aborted — production confirmation not provided.")
