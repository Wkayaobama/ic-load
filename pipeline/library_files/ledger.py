"""Postgres-backed idempotency ledger.

Lets the two-phase uploader survive crashes and re-run safely. Each row in
``staging.fct_files_uploaded`` records a Phase-1 outcome; each row in
``staging.fct_file_notes_posted`` records a Phase-2 outcome. PK is
``legacy_library_id``; UPSERT on conflict so re-runs converge.

These are *our* staging tables — not StackSync-mirrored. Writing to them does
not propagate to HubSpot.

The uploader takes any object satisfying ``LedgerLike`` (a Protocol), so unit
tests can inject an in-memory fake without psycopg2.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Mapping, Protocol


_SCHEMA_NAME_RX = re.compile(r"^[a-z_][a-z0-9_]*$")
_SQL_DIR = Path(__file__).parent / "sql"


class LedgerLike(Protocol):
    """Structural type — uploader only depends on this surface."""

    def upload_skip_set(self) -> set[str]: ...
    def attach_skip_set(self) -> set[str]: ...
    def load_existing(self, legacy_ids: Iterable[str]) -> dict[str, dict]: ...
    def record_upload(self, entry: Mapping[str, object]) -> None: ...
    def record_attach(self, entry: Mapping[str, object]) -> None: ...


class PostgresLedger:
    """psycopg2-backed concrete LedgerLike."""

    def __init__(self, dsn: str, *, schema: str = "staging") -> None:
        if not _SCHEMA_NAME_RX.match(schema):
            raise ValueError(
                f"invalid schema name {schema!r}: must match {_SCHEMA_NAME_RX.pattern}"
            )
        self.dsn = dsn
        self.schema = schema

    # -- DDL -----------------------------------------------------------------

    def bootstrap(self) -> None:
        ddl = (_SQL_DIR / "init_ledger.sql").read_text(encoding="utf-8")
        sql = ddl.format(schema=self.schema)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()

    # -- Read paths ----------------------------------------------------------

    def upload_skip_set(self) -> set[str]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT legacy_library_id FROM {self.schema}.fct_files_uploaded "
                f"WHERE status = 'uploaded'"
            )
            return {row[0] for row in cur.fetchall()}

    def attach_skip_set(self) -> set[str]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT legacy_library_id FROM {self.schema}.fct_file_notes_posted "
                f"WHERE status = 'attached'"
            )
            return {row[0] for row in cur.fetchall()}

    def load_existing(self, legacy_ids: Iterable[str]) -> dict[str, dict]:
        ids = list(legacy_ids)
        if not ids:
            return {}
        out: dict[str, dict] = {lid: {"legacy_id": lid} for lid in ids}
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT legacy_library_id, hs_file_id, status "
                f"FROM {self.schema}.fct_files_uploaded "
                f"WHERE legacy_library_id = ANY(%s)",
                (ids,),
            )
            for legacy_id, hs_file_id, status in cur.fetchall():
                out[legacy_id]["hs_file_id"] = hs_file_id
                out[legacy_id]["upload_status"] = status
            cur.execute(
                f"SELECT legacy_library_id, hs_note_id, status "
                f"FROM {self.schema}.fct_file_notes_posted "
                f"WHERE legacy_library_id = ANY(%s)",
                (ids,),
            )
            for legacy_id, hs_note_id, status in cur.fetchall():
                out[legacy_id]["hs_note_id"] = hs_note_id
                out[legacy_id]["attach_status"] = status
        return out

    # -- Write paths ---------------------------------------------------------

    def record_upload(self, entry: Mapping[str, object]) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self.schema}.fct_files_uploaded
                    (legacy_library_id, hs_file_id, status, error, attempts,
                     first_seen_at, last_attempt_at)
                VALUES (%s, %s, %s, %s, 1, now(), now())
                ON CONFLICT (legacy_library_id) DO UPDATE SET
                    hs_file_id      = EXCLUDED.hs_file_id,
                    status          = EXCLUDED.status,
                    error           = EXCLUDED.error,
                    attempts        = {self.schema}.fct_files_uploaded.attempts + 1,
                    last_attempt_at = now();
                """,
                (
                    entry["legacy_id"],
                    entry.get("hs_file_id"),
                    entry["status"],
                    entry.get("error"),
                ),
            )
            conn.commit()

    def record_attach(self, entry: Mapping[str, object]) -> None:
        idempotency_key = (
            entry.get("idempotency_key")
            or f"icalps_libfile_{entry['legacy_id']}"
        )
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self.schema}.fct_file_notes_posted
                    (legacy_library_id, hs_note_id, idempotency_key, status,
                     error, attempts, first_seen_at, last_attempt_at)
                VALUES (%s, %s, %s, %s, %s, 1, now(), now())
                ON CONFLICT (legacy_library_id) DO UPDATE SET
                    hs_note_id      = EXCLUDED.hs_note_id,
                    idempotency_key = EXCLUDED.idempotency_key,
                    status          = EXCLUDED.status,
                    error           = EXCLUDED.error,
                    attempts        = {self.schema}.fct_file_notes_posted.attempts + 1,
                    last_attempt_at = now();
                """,
                (
                    entry["legacy_id"],
                    entry.get("hs_note_id"),
                    idempotency_key,
                    entry["status"],
                    entry.get("error"),
                ),
            )
            conn.commit()

    # -- Connection ---------------------------------------------------------

    def _connect(self):
        import psycopg2  # local import keeps unit tests independent of psycopg2

        return psycopg2.connect(self.dsn)
