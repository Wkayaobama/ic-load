"""Postgres-backed ledger for the cleanup pipeline.

Mirrors ``pipeline.library_files.ledger.PostgresLedger`` shape: schema-name
allowlist, init from a SQL file, UPSERT on PK so re-runs converge.

Tables (DDL in sql/init_cleanup_ledger.sql):
    staging.fct_cleanup_manifest    — Phase B snapshot
    staging.fct_cleanup_archives    — Phase E archive outcomes
    staging.fct_cleanup_gdpr        — Phase E2 GDPR-delete outcomes
    staging.fct_cleanup_properties  — Phase F property-deletion outcomes
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Mapping

import psycopg2  # type: ignore[import-not-found]


_SCHEMA_NAME_RX = re.compile(r"^[a-z_][a-z0-9_]*$")
_SQL_DIR = Path(__file__).parent / "sql"


class CleanupLedger:
    def __init__(self, dsn: str, *, schema: str = "staging") -> None:
        if not _SCHEMA_NAME_RX.match(schema):
            raise ValueError(
                f"invalid schema name {schema!r}: must match {_SCHEMA_NAME_RX.pattern}"
            )
        self.dsn = dsn
        self.schema = schema

    def _connect(self):
        return psycopg2.connect(self.dsn)

    # -- DDL -----------------------------------------------------------------

    def bootstrap(self) -> None:
        ddl = (_SQL_DIR / "init_cleanup_ledger.sql").read_text(encoding="utf-8")
        # str.replace, not str.format — see library_files/silver_library.py
        # for rationale (any literal {...} in SQL breaks str.format).
        sql = ddl.replace("{schema}", self.schema)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()

    def bootstrap_views(self) -> None:
        """Materialise staging.fct_cleanup_{companies,contacts,deals}.

        Idempotent: each statement is CREATE OR REPLACE VIEW. Does not touch
        the manifest / archive / gdpr / property ledger tables — call
        ``bootstrap()`` first if those don't exist yet.

        The communication selection view lives in a separate SQL file and is
        loaded by ``bootstrap_communication_view()`` because its column names
        depend on the engagement-table schema (calls/notes/tasks shapes
        verified during the bronze-path-and-cleanup-views work).
        """
        ddl = (_SQL_DIR / "init_cleanup_views.sql").read_text(encoding="utf-8")
        sql = ddl.replace("{schema}", self.schema)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()

    def bootstrap_communication_view(self) -> None:
        """Materialise staging.fct_cleanup_communication.

        Selection-only: the cleanup runner does not currently support
        archiving engagements (calls/notes/tasks/meetings) —
        ``selection.SUPPORTED_OBJECTS`` excludes them. The view exists so
        operators can snapshot the communications cohort into the manifest
        for review; archiving is gated until the engagement dispatch is
        implemented in archiver.py / client.py.
        """
        ddl = (_SQL_DIR / "init_communication_cleanup_view.sql").read_text(encoding="utf-8")
        sql = ddl.replace("{schema}", self.schema)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()

    # -- Manifest (Phase B) --------------------------------------------------

    def upsert_manifest_rows(self, rows: Iterable[Mapping[str, object]]) -> int:
        sql = f"""
            INSERT INTO {self.schema}.fct_cleanup_manifest
                (object_type, hubspot_id, legacy_id, label)
            VALUES (%(object_type)s, %(hubspot_id)s, %(legacy_id)s, %(label)s)
            ON CONFLICT (object_type, hubspot_id) DO UPDATE SET
                legacy_id   = EXCLUDED.legacy_id,
                label       = EXCLUDED.label,
                snapshot_at = now()
        """
        n = 0
        with self._connect() as conn, conn.cursor() as cur:
            for row in rows:
                cur.execute(sql, dict(row))
                n += 1
            conn.commit()
        return n

    def manifest_ids(self, object_type: str) -> list[tuple[str, str | None, str | None]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT hubspot_id, legacy_id, label
                FROM {self.schema}.fct_cleanup_manifest
                WHERE object_type = %s
                ORDER BY hubspot_id
                """,
                (object_type,),
            )
            return [(r[0], r[1], r[2]) for r in cur.fetchall()]

    # -- Archive ledger (Phase E) -------------------------------------------

    def archive_skip_set(self, object_type: str) -> set[str]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT hubspot_id FROM {self.schema}.fct_cleanup_archives
                WHERE object_type = %s AND status = 'archived'
                """,
                (object_type,),
            )
            return {r[0] for r in cur.fetchall()}

    def record_archive(self, *, object_type: str, hubspot_id: str, status: str, error: str | None = None) -> None:
        sql = f"""
            INSERT INTO {self.schema}.fct_cleanup_archives
                (object_type, hubspot_id, status, error, attempts, last_attempt_at)
            VALUES (%s, %s, %s, %s, 1, now())
            ON CONFLICT (object_type, hubspot_id) DO UPDATE SET
                status          = EXCLUDED.status,
                error           = EXCLUDED.error,
                attempts        = {self.schema}.fct_cleanup_archives.attempts + 1,
                last_attempt_at = now()
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (object_type, hubspot_id, status, error))
            conn.commit()

    # -- Exemptions (load-bearing veto for archive) -------------------------

    def exemption_set(self, object_type: str) -> set[str]:
        """Return the set of hubspot_ids exempt from archive for this object_type.

        Read by archiver.archive() (and gdpr_delete_contacts()) to filter the
        pending list AFTER manifest read but BEFORE the HubSpot API call.
        Load-bearing — edits to fct_cleanup_exemptions at any time before
        archive() runs are honoured (including post-snapshot edits)."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT hubspot_id FROM {self.schema}.fct_cleanup_exemptions
                WHERE object_type = %s
                """,
                (object_type,),
            )
            return {r[0] for r in cur.fetchall()}

    # -- GDPR ledger (Phase E2) ---------------------------------------------

    def gdpr_skip_set(self, object_type: str = "contacts") -> set[str]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT hubspot_id FROM {self.schema}.fct_cleanup_gdpr
                WHERE object_type = %s AND status = 'purged'
                """,
                (object_type,),
            )
            return {r[0] for r in cur.fetchall()}

    def record_gdpr(self, *, object_type: str, hubspot_id: str, status: str, error: str | None = None) -> None:
        sql = f"""
            INSERT INTO {self.schema}.fct_cleanup_gdpr
                (object_type, hubspot_id, status, error, attempts, last_attempt_at)
            VALUES (%s, %s, %s, %s, 1, now())
            ON CONFLICT (object_type, hubspot_id) DO UPDATE SET
                status          = EXCLUDED.status,
                error           = EXCLUDED.error,
                attempts        = {self.schema}.fct_cleanup_gdpr.attempts + 1,
                last_attempt_at = now()
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (object_type, hubspot_id, status, error))
            conn.commit()

    # -- Property ledger (Phase F) ------------------------------------------

    def property_skip_set(self, object_type: str) -> set[str]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT property_name FROM {self.schema}.fct_cleanup_properties
                WHERE object_type = %s AND status IN ('deleted', 'already_absent')
                """,
                (object_type,),
            )
            return {r[0] for r in cur.fetchall()}

    def record_property(
        self,
        *,
        object_type: str,
        property_name: str,
        status: str,
        http_status: int | None = None,
        error: str | None = None,
    ) -> None:
        sql = f"""
            INSERT INTO {self.schema}.fct_cleanup_properties
                (object_type, property_name, status, http_status, error, attempts, last_attempt_at)
            VALUES (%s, %s, %s, %s, %s, 1, now())
            ON CONFLICT (object_type, property_name) DO UPDATE SET
                status          = EXCLUDED.status,
                http_status     = EXCLUDED.http_status,
                error           = EXCLUDED.error,
                attempts        = {self.schema}.fct_cleanup_properties.attempts + 1,
                last_attempt_at = now()
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (object_type, property_name, status, http_status, error))
            conn.commit()

    # -- Reporting -----------------------------------------------------------

    def status_summary(self) -> dict[str, list[tuple[str, str, int]]]:
        out: dict[str, list[tuple[str, str, int]]] = {}
        queries = {
            "manifest":   f"SELECT object_type, 'snapshotted'::text, COUNT(*) FROM {self.schema}.fct_cleanup_manifest    GROUP BY object_type ORDER BY object_type",
            "archives":   f"SELECT object_type, status,                COUNT(*) FROM {self.schema}.fct_cleanup_archives    GROUP BY object_type, status ORDER BY object_type, status",
            "gdpr":       f"SELECT object_type, status,                COUNT(*) FROM {self.schema}.fct_cleanup_gdpr        GROUP BY object_type, status ORDER BY object_type, status",
            "properties": f"SELECT object_type, status,                COUNT(*) FROM {self.schema}.fct_cleanup_properties  GROUP BY object_type, status ORDER BY object_type, status",
        }
        with self._connect() as conn, conn.cursor() as cur:
            for label, q in queries.items():
                cur.execute(q)
                out[label] = [(r[0], r[1], int(r[2])) for r in cur.fetchall()]
        return out
