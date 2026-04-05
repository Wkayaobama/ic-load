from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from context.config import SQL_RENDERED_DIR
from sql.render import render_engagement_upsert, render_entity_upsert


class GoldUpsertExecutor:
    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or SQL_RENDERED_DIR

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
