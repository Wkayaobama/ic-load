"""Build the cleanup manifest from operator-defined selection criteria.

Two modes:
  - Inline predicate: --where "icalps_company_id IS NOT NULL AND ..."
  - Materialised view: --source-view staging.fct_cleanup_companies

The runner translates the operator's choice into a SELECT against
``hubspot.{object_type}`` (or against the chosen view) and pipes the rows into
``CleanupLedger.upsert_manifest_rows``.

StackSync mirrors `hubspot.*.icalps_*_id` as VARCHAR/TEXT, even though the
project CLAUDE.md historically described them as BIGINT. Use ``IS NOT NULL``
and ``<> ''`` as the empty-check (varchar can hold the empty string in a way
bigint cannot). Casts in JOINs should go bigint → text, never text → bigint
— the latter fails on any non-numeric value HubSpot might allow.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

import psycopg2  # type: ignore[import-not-found]


# HubSpot's plural object names match the table names under hubspot.* and the
# REST endpoints. Everything in cleanup uses plural consistently.
#
# Engagement types (calls / meetings / notes / tasks) carry no icalps_*_id
# mirror column in the StackSync gold layer — the legacy bridge lives in
# staging.fct_communication_* tables, not on hubspot.{type}. Their _OBJECT_META
# entry therefore uses legacy_id_col=None and plan_from_where emits
# `NULL::text AS legacy_id` for these. `hubspot.emails` is not synced by
# StackSync at all; archiving emails would require a direct REST path and is
# intentionally out of scope here.
SUPPORTED_OBJECTS = (
    "companies", "contacts", "deals",
    "calls", "meetings", "notes", "tasks",
)


# Per-object metadata: legacy-id column on the hubspot.* table (None for
# engagements which have no mirror column), label expression for
# human-readable manifest entries.
_OBJECT_META = {
    "companies": {
        "legacy_id_col": "icalps_company_id",
        "label_expr":    "name",
    },
    "contacts": {
        "legacy_id_col": "icalps_contact_id",
        # CONCAT_WS produces 'Firstname Lastname (email)' or partial
        "label_expr":    "CONCAT_WS(' ', firstname, lastname, CASE WHEN email IS NOT NULL THEN '(' || email || ')' END)",
    },
    "deals": {
        "legacy_id_col": "icalps_deal_id",
        "label_expr":    "dealname",
    },
    "calls":    {"legacy_id_col": None, "label_expr": "call_title"},
    "meetings": {"legacy_id_col": None, "label_expr": "meeting_name"},
    "notes":    {"legacy_id_col": None, "label_expr": "note_body"},
    "tasks":    {"legacy_id_col": None, "label_expr": "task_title"},
}


# Allow only ASCII identifiers as fully-qualified view names: 'schema.view' or
# 'view'. Refuse anything with parens, semicolons, quotes, etc.
_VIEW_NAME_RX = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$")


@dataclass(frozen=True)
class SelectionPlan:
    object_type: str
    sql: str        # the SELECT statement to execute
    description: str  # for the operator-visible banner


def plan_from_where(object_type: str, where: str | None) -> SelectionPlan:
    if object_type not in SUPPORTED_OBJECTS:
        raise ValueError(f"unsupported object_type {object_type!r}")
    meta = _OBJECT_META[object_type]
    legacy_col = meta["legacy_id_col"]
    label_expr = meta["label_expr"]
    # icalps_*_id is varchar in StackSync's mirror — guard against both NULL
    # and empty string. The legacy bigint assumption was wrong (see
    # init_fct_view.sql cast comment for the discovery and the fix).
    # Engagement types have no legacy column on the mirror; emit NULL and
    # require an explicit --where (default predicate would be meaningless).
    if legacy_col is None:
        legacy_select     = "NULL::text AS legacy_id"
        default_predicate = "id IS NOT NULL"
    else:
        legacy_select     = f"{legacy_col} AS legacy_id"
        default_predicate = f"{legacy_col} IS NOT NULL AND {legacy_col} <> ''"
    predicate = where.strip() if where else default_predicate
    sql = (
        f"SELECT id::text AS hubspot_id, "
        f"{legacy_select}, "
        f"{label_expr} AS label "
        f"FROM hubspot.{object_type} "
        f"WHERE {predicate}"
    )
    return SelectionPlan(
        object_type=object_type,
        sql=sql,
        description=f"hubspot.{object_type} WHERE {predicate}",
    )


def plan_from_view(object_type: str, view_name: str) -> SelectionPlan:
    if object_type not in SUPPORTED_OBJECTS:
        raise ValueError(f"unsupported object_type {object_type!r}")
    if not _VIEW_NAME_RX.match(view_name):
        raise ValueError(
            f"invalid view name {view_name!r}: must match {_VIEW_NAME_RX.pattern}. "
            f"Identifiers cannot be parameterised; we whitelist instead."
        )
    sql = (
        f"SELECT hubspot_id::text, "
        f"COALESCE(legacy_id::text, NULL) AS legacy_id, "
        f"label "
        f"FROM {view_name}"
    )
    return SelectionPlan(
        object_type=object_type,
        sql=sql,
        description=f"view {view_name}",
    )


def execute_plan(dsn: str, plan: SelectionPlan) -> Iterable[dict]:
    """Stream rows from the prod-postgres SELECT into manifest-row dicts."""
    with psycopg2.connect(dsn) as conn, conn.cursor(name="cleanup_select") as cur:
        cur.itersize = 500
        cur.execute(plan.sql)
        for hubspot_id, legacy_id, label in cur:
            yield {
                "object_type": plan.object_type,
                "hubspot_id":  hubspot_id,
                "legacy_id":   legacy_id,
                "label":       label,
            }
