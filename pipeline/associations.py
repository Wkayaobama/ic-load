from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from context.config import SQL_RENDERED_DIR, load_schema_context
from sql.render import render_association_bridge


class AssociationBridgeExecutor:
    def __init__(self, output_dir: Path | None = None):
        self.output_dir = output_dir or SQL_RENDERED_DIR

    def execute(
        self,
        entity: str,
        *,
        dry_run: bool = False,
        execute_sql: Callable[[str], int] | None = None,
    ) -> dict[str, Any]:
        if entity.lower() != "communication":
            return {"entity": entity, "mode": "not_applicable", "statements": []}

        schema = load_schema_context()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []

        for mapping in schema["association_bridge"]["supported_patterns"]:
            comm_type = mapping["comm_type"]
            for target in mapping["targets"]:
                sql_text = render_association_bridge(comm_type, target, schema=schema)
                path = self.output_dir / f"association_{comm_type.lower()}_{target}.sql"
                path.write_text(sql_text, encoding="utf-8")
                rowcount = 0
                if not dry_run and execute_sql is not None:
                    rowcount = execute_sql(sql_text)
                results.append({"file": path.name, "rowcount": rowcount})

        return {"entity": entity, "mode": "dry_run" if dry_run else "executed", "statements": results}
