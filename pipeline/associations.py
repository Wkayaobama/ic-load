from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from context.config import SQL_RENDERED_DIR, load_schema_context
from sql.render import render_association_bridge, select_body_association


class AssociationBridgeExecutor:
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

    # ─── preview (read-only; no hubspot writes) ─────────────────────────────
    def preview(
        self,
        entity: str,
        *,
        execute_sql_fetch: Callable[[str], tuple[list[str], list[tuple]]],
        csv_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Execute the Pass-A-UNION-Pass-B SELECT body read-only; write
        candidate-association rows to CSV. No INSERT into hubspot.associations_*.

        The SELECT body comes from select_body_association — the same helper
        that render_association_bridge wraps — so preview rows are exactly the
        associations a live run would insert (NOT EXISTS guard filters out
        associations already present).

        CSV destinations (in csv_dir, default artifacts/ops/):
            assoc_preview_<comm>_<target>.csv  for each supported pattern
        """
        from pipeline.hooks._primitives import write_csv

        if entity.lower() != "communication":
            return {"entity": entity, "mode": "preview", "statements": [], "reason": "not_applicable"}

        csv_dir = Path(csv_dir) if csv_dir else Path("artifacts/ops")
        csv_dir.mkdir(parents=True, exist_ok=True)
        schema = load_schema_context()

        results: list[dict[str, Any]] = []
        for mapping in schema["association_bridge"]["supported_patterns"]:
            comm_type = mapping["comm_type"]
            for target in mapping["targets"]:
                select_sql = select_body_association(comm_type, target, schema=schema)
                filename = f"assoc_preview_{comm_type.lower()}_{target}.csv"
                try:
                    columns, rows = execute_sql_fetch(select_sql)
                except Exception as exc:
                    results.append({
                        "file": filename,
                        "status": "error",
                        "detail": str(exc).split("\n")[0][:200],
                    })
                    continue
                path = csv_dir / filename
                written = write_csv(path, columns, rows)
                results.append({"file": path.name, "status": "ok", "rows": written, "columns": len(columns)})

        return {"entity": entity, "mode": "preview", "statements": results}
