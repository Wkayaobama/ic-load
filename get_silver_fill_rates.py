#!/usr/bin/env python3

import os
from pathlib import Path

import pandas as pd
import psycopg2


REQUIRED_ENV_VARS = [
    "ICALPS_PGDATABASE",
    "ICALPS_PGHOST",
    "ICALPS_PGPASSWORD",
    "ICALPS_PGPORT",
    "ICALPS_PGUSER",
]


SQL = """
SELECT
    table_name                                                  AS "Property type",
    col_name,
    COUNT(*)                                                    AS total_rows,
    COUNT(NULLIF(col_value, ''))                                AS filled_rows,
    ROUND(100.0 * COUNT(NULLIF(col_value, '')) / COUNT(*), 1)  AS fill_pct
FROM (
    SELECT 'Company'       AS table_name, kv.key AS col_name, kv.value AS col_value
    FROM staging.stg_company_normalised t, jsonb_each_text(to_jsonb(t)) AS kv
    UNION ALL
    SELECT 'Contact',        kv.key, kv.value
    FROM staging.stg_contact_normalised t, jsonb_each_text(to_jsonb(t)) AS kv
    UNION ALL
    SELECT 'Deal',           kv.key, kv.value
    FROM staging.stg_opportunity_normalised t, jsonb_each_text(to_jsonb(t)) AS kv
    UNION ALL
    SELECT 'Communication',  kv.key, kv.value
    FROM staging.stg_communication_normalised t, jsonb_each_text(to_jsonb(t)) AS kv
) unpivoted
GROUP BY table_name, col_name
ORDER BY table_name, fill_pct DESC;
"""


def get_required_env_var(name: str) -> str:
    value = os.environ.get(name)

    if value is None or value.strip() == "":
        raise RuntimeError(f"Missing required environment variable: {name}")

    return value


def main() -> None:
    for env_var in REQUIRED_ENV_VARS:
        get_required_env_var(env_var)

    artifacts_dir = Path.cwd() / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    output_file = artifacts_dir / "property_fill_report.csv"

    connection = psycopg2.connect(
        dbname=get_required_env_var("ICALPS_PGDATABASE"),
        host=get_required_env_var("ICALPS_PGHOST"),
        password=get_required_env_var("ICALPS_PGPASSWORD"),
        port=get_required_env_var("ICALPS_PGPORT"),
        user=get_required_env_var("ICALPS_PGUSER"),
    )

    try:
        df = pd.read_sql_query(SQL, connection)
        df.to_csv(output_file, index=False)
    finally:
        connection.close()

    print(f"Wrote report to: {output_file}")


if __name__ == "__main__":
    main()