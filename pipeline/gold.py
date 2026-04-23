from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from context.config import SQL_RENDERED_DIR
from sql.render import (
    render_engagement_upsert,
    render_entity_upsert,
    select_body_engagement,
    select_body_entity,
)


class GoldUpsertExecutor:
    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or SQL_RENDERED_DIR

    # ─── execute ────────────────────────────────────────────────────────────
    def execute(
        self,
        entity: str,
        *,
        dry_run: bool = False,
        execute_sql: Callable[[str], int] | None = None,
    ) -> dict[str, Any]:
        normalized = entity.lower()
        statements: list[tuple[str, str]] = []

        if normalized == "company":
            statements.append(("upsert_company.sql", render_entity_upsert("Company")))
        elif normalized == "contact":
            statements.append(("upsert_person.sql", render_entity_upsert("Person")))
        elif normalized == "opportunity":
            statements.append(("upsert_opportunity.sql", render_entity_upsert("Opportunity")))
        elif normalized == "communication":
            for comm_type in ("Calls", "Tasks", "Notes", "Meetings"):
                statements.append((f"engagement_{comm_type.lower()}.sql", render_engagement_upsert(comm_type)))
        elif normalized == "case":
            # Case/Ticket Gold upsert — GATED: live_push_ready=FALSE
            # Do not execute until:
            #   1. stg_case_v2 assessment probe shows match rate >= 95%
            #   2. case_stage_mapper implemented with confirmed HubSpot stage IDs
            #   3. stacksync_record_id_* column name for tickets confirmed from portal
            #   4. Existing HubSpot tickets deleted and user has given explicit green light
            # The SQL is read from sql/case/06_gold_upsert.sql and rendered to disk;
            # execution only proceeds when --approve-gold is passed to the runner.
            sql_path = Path(__file__).resolve().parent.parent / "sql" / "case" / "06_gold_upsert.sql"
            if sql_path.exists():
                statements.append(("upsert_case.sql", sql_path.read_text(encoding="utf-8")))
            else:
                return {
                    "entity": entity,
                    "statements": [],
                    "mode": "not_applicable",
                    "reason": "06_gold_upsert.sql not present — confirm stage IDs and run assessment probe first",
                }
        else:
            return {"entity": entity, "statements": [], "mode": "not_applicable"}

        results: list[dict[str, Any]] = []
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for filename, sql_text in statements:
            rendered_path = self.output_dir / filename
            rendered_path.write_text(sql_text, encoding="utf-8")
            rowcount = 0
            if not dry_run and execute_sql is not None:
                rowcount = execute_sql(sql_text)
            results.append({"file": rendered_path.name, "rowcount": rowcount})

        return {"entity": entity, "statements": results, "mode": "dry_run" if dry_run else "executed"}

    # ─── preview (read-only; no hubspot writes) ─────────────────────────────
    def preview(
        self,
        entity: str,
        *,
        execute_sql_fetch: Callable[[str], tuple[list[str], list[tuple]]],
        csv_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Execute the SELECT body read-only; write candidate rows to CSV.

        Uses the same select_body_* helpers that render_*_upsert composes, so
        the preview shows exactly what a live run would INSERT — modulo
        ON CONFLICT behavior. No hubspot.* mutation occurs.

        CSV destinations (in csv_dir, default artifacts/ops/):
            company         → gold_preview_company.csv
            contact         → gold_preview_contact.csv
            opportunity     → gold_preview_opportunity.csv
            communication   → gold_preview_engagement_{calls,notes,tasks,meetings}.csv
            case            → not_applicable (gated)
        """
        from pipeline.hooks._primitives import write_csv

        csv_dir = Path(csv_dir) if csv_dir else Path("artifacts/ops")
        csv_dir.mkdir(parents=True, exist_ok=True)
        normalized = entity.lower()
        previews: list[tuple[str, str]] = []  # (csv_filename, select_sql)

        if normalized == "company":
            previews.append(("gold_preview_company.csv", select_body_entity("Company")))
        elif normalized == "contact":
            previews.append(("gold_preview_contact.csv", select_body_entity("Person")))
        elif normalized == "opportunity":
            previews.append(("gold_preview_opportunity.csv", select_body_entity("Opportunity")))
        elif normalized == "communication":
            for comm_type in ("Calls", "Tasks", "Notes", "Meetings"):
                previews.append(
                    (f"gold_preview_engagement_{comm_type.lower()}.csv", select_body_engagement(comm_type))
                )
        elif normalized == "case":
            return {
                "entity": entity,
                "mode": "preview",
                "statements": [],
                "reason": "case gold is gated; no preview path until stage mapper lands",
            }
        else:
            return {"entity": entity, "mode": "preview", "statements": [], "reason": "not_applicable"}

        results: list[dict[str, Any]] = []
        for filename, select_sql in previews:
            try:
                columns, rows = execute_sql_fetch(select_sql)
            except Exception as exc:
                results.append({"file": filename, "status": "error", "detail": str(exc).split("\n")[0][:200]})
                continue
            path = csv_dir / filename
            written = write_csv(path, columns, rows)
            results.append({"file": path.name, "status": "ok", "rows": written, "columns": len(columns)})

        return {"entity": entity, "mode": "preview", "statements": results}
