from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Optional

from context.db import get_connection

try:
    import duckdb
    import pandas as pd
except ImportError:  # pragma: no cover - exercised only when live deps are absent
    duckdb = None
    pd = None

try:
    import psycopg2
except ImportError:  # pragma: no cover
    psycopg2 = None


class DuckDBBronzeLoader:
    """Load approved Bronze extracts into staging with the legacy watermark logic intact."""

    _ENTITY_PK = {
        "company": "Comp_CompanyId",
        "contact": "Pers_PersonId",
        "opportunity": "Oppo_OpportunityId",
        "communication": "Comm_CommunicationId",
    }

    def __init__(self, duckdb_path: Optional[str] = None):
        if duckdb is None or pd is None:
            raise RuntimeError("duckdb and pandas are required for Bronze loading.")
        self.duckdb_path = duckdb_path or ":memory:"
        self.conn = duckdb.connect(self.duckdb_path)

    def load_csv_to_duckdb(self, csv_path: str, table_name: str) -> int:
        """Load one approved CSV into an in-memory DuckDB table."""
        csv_path_obj = Path(csv_path)
        source_path = str(csv_path_obj) if csv_path_obj.exists() else csv_path

        self.conn.execute(
            f"""
            CREATE OR REPLACE TABLE {table_name} AS
            SELECT * FROM read_csv_auto(
                '{source_path}',
                header=true,
                auto_detect=true,
                normalize_names=false,
                sample_size=-1
            )
            """
        )
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])

    def add_bronze_metadata(self, table_name: str, source_file: str) -> None:
        """Attach source and load timestamps without mutating the source payload."""
        self.conn.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN IF NOT EXISTS _bronze_loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            """
        )
        self.conn.execute(
            f"""
            ALTER TABLE {table_name}
            ADD COLUMN IF NOT EXISTS _bronze_source_file VARCHAR DEFAULT '{source_file.replace("'", "''")}'
            """
        )

    def _tag_load_status(self, duckdb_table: str, pk_col: str, schema: str = "staging") -> dict[str, int]:
        """Preserve the proven NEW/MODIFIED/UNCHANGED watermark behavior from the legacy loader."""
        now = pd.Timestamp.utcnow().isoformat()
        hash_table = f"{schema}.stg_{duckdb_table.replace('bronze_', '')}_hashes"

        all_cols = [d[0] for d in self.conn.execute(f"SELECT * FROM {duckdb_table} LIMIT 0").description]
        concat_expr = " || '|' || ".join([f"COALESCE(CAST({col} AS VARCHAR), '')" for col in all_cols])
        self.conn.execute(
            f"""
            CREATE OR REPLACE TABLE {duckdb_table}_hashed AS
            SELECT
                {pk_col},
                md5({concat_expr}) AS _row_hash
            FROM {duckdb_table}
            """
        )

        prior_exists = False
        try:
            with get_connection() as pg_conn:
                with pg_conn.cursor() as _cur:
                    _cur.execute(f"SELECT * FROM {hash_table}")
                    prior_df = pd.DataFrame(_cur.fetchall(), columns=[d[0] for d in _cur.description])
            if not prior_df.empty:
                self.conn.register("prior_hashes", prior_df)
                prior_exists = True
        except Exception as exc:
            if psycopg2 is None or not isinstance(exc, psycopg2.errors.UndefinedTable):
                raise

        if prior_exists:
            self.conn.execute(
                f"""
                CREATE OR REPLACE TABLE {duckdb_table}_status AS
                SELECT
                    n.{pk_col},
                    n._row_hash,
                    CASE
                        WHEN p.{pk_col} IS NULL THEN 'NEW'
                        WHEN p._row_hash != n._row_hash THEN 'MODIFIED'
                        ELSE 'UNCHANGED'
                    END AS _load_status,
                    COALESCE(p._first_seen_at, '{now}') AS _first_seen_at,
                    CASE
                        WHEN p.{pk_col} IS NULL OR p._row_hash != n._row_hash THEN '{now}'
                        ELSE p._last_modified_at
                    END AS _last_modified_at
                FROM {duckdb_table}_hashed n
                LEFT JOIN prior_hashes p USING ({pk_col})
                """
            )
        else:
            self.conn.execute(
                f"""
                CREATE OR REPLACE TABLE {duckdb_table}_status AS
                SELECT
                    {pk_col},
                    _row_hash,
                    'NEW' AS _load_status,
                    '{now}' AS _first_seen_at,
                    '{now}' AS _last_modified_at
                FROM {duckdb_table}_hashed
                """
            )

        new_hashes_df = self.conn.execute(
            f"SELECT {pk_col}, _row_hash, _first_seen_at, _last_modified_at FROM {duckdb_table}_status"
        ).df()

        with get_connection() as pg_conn:
            cur = pg_conn.cursor()
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {hash_table} (
                    {pk_col} TEXT PRIMARY KEY,
                    _row_hash TEXT,
                    _first_seen_at TEXT,
                    _last_modified_at TEXT
                )
                """
            )
            for _, row in new_hashes_df.iterrows():
                cur.execute(
                    f"""
                    INSERT INTO {hash_table} ({pk_col}, _row_hash, _first_seen_at, _last_modified_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT ({pk_col}) DO UPDATE SET
                        _row_hash = EXCLUDED._row_hash,
                        _last_modified_at = EXCLUDED._last_modified_at
                    """,
                    (str(row[pk_col]), row["_row_hash"], row["_first_seen_at"], row["_last_modified_at"]),
                )
            pg_conn.commit()

        self.conn.execute(
            f"""
            CREATE OR REPLACE TABLE {duckdb_table} AS
            SELECT t.*, s._load_status, s._first_seen_at, s._last_modified_at
            FROM {duckdb_table} t
            JOIN {duckdb_table}_status s USING ({pk_col})
            """
        )

        counts_df = self.conn.execute(
            f"""
            SELECT _load_status, COUNT(*) AS n
            FROM {duckdb_table}
            GROUP BY _load_status
            """
        ).df()
        return dict(zip(counts_df["_load_status"], counts_df["n"].astype(int)))

    def export_to_postgres(self, duckdb_table: str, postgres_table: str, schema: str = "staging", mode: str = "replace") -> int:
        """Ship the staged DuckDB relation into PostgreSQL using COPY for predictable bulk load behavior."""
        df = self.conn.execute(f"SELECT * FROM {duckdb_table}").df()
        full_table = f"{schema}.{postgres_table}"

        with get_connection() as pg_conn:
            with pg_conn.cursor() as cursor:
                if mode == "replace":
                    cursor.execute(f"DROP TABLE IF EXISTS {full_table} CASCADE")

                type_map = {
                    "int64": "BIGINT",
                    "int32": "INTEGER",
                    "float64": "DOUBLE PRECISION",
                    "bool": "BOOLEAN",
                    "datetime64[ns]": "TIMESTAMP",
                    "object": "TEXT",
                }
                cols = [f'"{col}" {type_map.get(str(df[col].dtype), "TEXT")}' for col in df.columns]
                cursor.execute(f"CREATE TABLE IF NOT EXISTS {full_table} ({', '.join(cols)})")

                csv_buffer = StringIO()
                df.to_csv(csv_buffer, index=False, header=False)
                csv_buffer.seek(0)
                cursor.copy_expert(f"COPY {full_table} FROM STDIN WITH CSV", csv_buffer)
            pg_conn.commit()
        return len(df)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
