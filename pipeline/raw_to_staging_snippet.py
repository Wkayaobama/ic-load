from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from context.db import get_connection
from pipeline.text_normalization import clean_text_utf8


@dataclass(frozen=True)
class DateFieldSpec:
    field_name: str
    output_format: str = "iso_datetime"


def read_raw_csv(csv_path: str | Path, *, encoding: str = "utf-8-sig") -> pd.DataFrame:
    """
    Read a raw Bronze/benchmark CSV with BOM-safe UTF-8 defaults.

    This is the shared salvage entry point before entity-specific mapping logic.
    """
    return pd.read_csv(
        csv_path,
        dtype=str,
        keep_default_na=False,
        na_values=[""],
        encoding=encoding,
    )


def serialize_date_value(value: Any, *, output_format: str = "iso_datetime") -> str | int | None:
    """
    Normalize common legacy date inputs into a stable staging representation.

    Supported output formats:
    - `iso_datetime`: `YYYY-MM-DD HH:MM:SS`
    - `iso_date`: `YYYY-MM-DD`
    - `epoch_millis`: integer milliseconds since epoch
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None

    text = str(value).strip()
    if not text:
        return None

    dt = pd.NaT
    try:
        numeric = float(text)
    except ValueError:
        numeric = None

    if numeric is not None:
        if numeric >= 1_000_000_000_000:
            dt = pd.to_datetime(int(numeric), unit="ms", errors="coerce")
        elif numeric >= 1_000_000_000:
            dt = pd.to_datetime(int(numeric), unit="s", errors="coerce")
        elif 20_000 <= numeric <= 60_000:
            dt = pd.to_datetime(numeric, unit="D", origin="1899-12-30", errors="coerce")

    if pd.isna(dt):
        dt = pd.to_datetime(text, errors="coerce")

    if pd.isna(dt):
        return None

    if output_format == "iso_date":
        return dt.strftime("%Y-%m-%d")
    if output_format == "epoch_millis":
        return int(dt.timestamp() * 1000)
    if output_format == "iso_datetime":
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    raise ValueError(f"Unsupported output_format: {output_format}")


def normalize_frame_for_staging(
    frame: pd.DataFrame,
    *,
    text_fields: list[str] | None = None,
    date_fields: list[DateFieldSpec] | None = None,
    rename_map: dict[str, str] | None = None,
    enum_maps: dict[str, dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    lowercase_columns: bool = True,
) -> pd.DataFrame:
    """
    Formalize the reusable raw-CSV -> normalized-staging steps:

    1. clean text fields with the universal UTF-8/mojibake rule
    2. serialize date fields deterministically
    3. map enumerations where needed
    4. rename into the target staging contract
    5. add optional metadata columns
    6. lowercase columns for PostgreSQL-friendly staging semantics
    """
    result = frame.copy()

    for field_name in text_fields or []:
        if field_name in result.columns:
            result[field_name] = result[field_name].apply(clean_text_utf8)

    for spec in date_fields or []:
        if spec.field_name in result.columns:
            result[spec.field_name] = result[spec.field_name].apply(
                lambda value: serialize_date_value(value, output_format=spec.output_format)
            )

    for field_name, mapping in (enum_maps or {}).items():
        if field_name in result.columns:
            result[field_name] = result[field_name].apply(lambda value: mapping.get(value, value))

    if rename_map:
        result = result.rename(columns=rename_map)

    for key, value in (metadata or {}).items():
        result[key] = value

    if lowercase_columns:
        result.columns = [column.lower() for column in result.columns]

    return result


def export_frame_to_staging(
    frame: pd.DataFrame,
    *,
    table_name: str,
    schema: str = "staging",
    replace: bool = True,
) -> int:
    """Write a normalized frame into PostgreSQL staging using COPY."""
    full_table_name = f"{schema}.{table_name}"

    type_map = {
        "int64": "BIGINT",
        "Int64": "BIGINT",
        "float64": "DOUBLE PRECISION",
        "bool": "BOOLEAN",
        "datetime64[ns]": "TIMESTAMP",
        "object": "TEXT",
    }

    with get_connection() as conn:
        with conn.cursor() as cursor:
            if replace:
                cursor.execute(f"DROP TABLE IF EXISTS {full_table_name} CASCADE")

            columns_sql = [f'"{col}" {type_map.get(str(frame[col].dtype), "TEXT")}' for col in frame.columns]
            cursor.execute(f"CREATE TABLE IF NOT EXISTS {full_table_name} ({', '.join(columns_sql)})")

            buffer = StringIO()
            frame.to_csv(buffer, index=False, header=False)
            buffer.seek(0)
            quoted_cols = ",".join(f'"{col}"' for col in frame.columns)
            cursor.copy_expert(f"COPY {full_table_name} ({quoted_cols}) FROM STDIN WITH CSV", buffer)
        conn.commit()

    return len(frame)


def _parse_date_field_specs(raw_specs: list[str]) -> list[DateFieldSpec]:
    specs: list[DateFieldSpec] = []
    for raw_spec in raw_specs:
        if ":" in raw_spec:
            field_name, output_format = raw_spec.split(":", 1)
        else:
            field_name, output_format = raw_spec, "iso_datetime"
        specs.append(DateFieldSpec(field_name=field_name, output_format=output_format))
    return specs


def _parse_key_value_pairs(raw_pairs: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_pair in raw_pairs:
        key, value = raw_pair.split("=", 1)
        parsed[key] = value
    return parsed


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reusable raw CSV -> normalized staging snippet.")
    parser.add_argument("csv_path")
    parser.add_argument("table_name")
    parser.add_argument("--text-field", action="append", default=[])
    parser.add_argument("--date-field", action="append", default=[])
    parser.add_argument("--rename", action="append", default=[])
    parser.add_argument("--metadata", action="append", default=[])
    parser.add_argument("--write-postgres", action="store_true")
    parser.add_argument("--schema", default="staging")
    parser.add_argument("--output-csv")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    frame = read_raw_csv(args.csv_path)
    normalized = normalize_frame_for_staging(
        frame,
        text_fields=args.text_field,
        date_fields=_parse_date_field_specs(args.date_field),
        rename_map=_parse_key_value_pairs(args.rename),
        metadata=_parse_key_value_pairs(args.metadata),
    )

    output_csv = args.output_csv
    if output_csv:
        Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
        normalized.to_csv(output_csv, index=False, encoding="utf-8")

    written_rows = None
    if args.write_postgres:
        written_rows = export_frame_to_staging(
            normalized,
            table_name=args.table_name,
            schema=args.schema,
        )

    print(
        json.dumps(
            {
                "csv_path": str(args.csv_path),
                "table_name": f"{args.schema}.{args.table_name}",
                "row_count": len(normalized),
                "columns": normalized.columns.tolist(),
                "wrote_postgres": args.write_postgres,
                "written_rows": written_rows,
                "output_csv": output_csv,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
