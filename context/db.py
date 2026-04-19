from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any


def postgres_config() -> dict[str, Any]:
    return {
        "host": os.getenv("ICALPS_PGHOST") or os.getenv("PGHOST"),
        "port": int(os.getenv("ICALPS_PGPORT") or os.getenv("PGPORT") or "5432"),
        "database": os.getenv("ICALPS_PGDATABASE") or os.getenv("PGDATABASE") or "postgres",
        "user": os.getenv("ICALPS_PGUSER") or os.getenv("PGUSER"),
        "password": os.getenv("ICALPS_PGPASSWORD") or os.getenv("PGPASSWORD"),
    }


def is_postgres_configured(config: dict[str, Any] | None = None) -> bool:
    cfg = config or postgres_config()
    return bool(cfg.get("host") and cfg.get("user") and cfg.get("password"))


@contextmanager
def get_connection(config: dict[str, Any] | None = None):
    cfg = config or postgres_config()
    if not is_postgres_configured(cfg):
        raise RuntimeError("PostgreSQL connection is not configured. Set ICALPS_PG* or PG* environment variables.")

    try:
        import psycopg2
    except ImportError as exc:
        raise RuntimeError("psycopg2 is required for live PostgreSQL access.") from exc

    connect_timeout = int(os.getenv("ICALPS_PG_CONNECT_TIMEOUT", "10"))
    conn = None
    last_exc: Exception | None = None
    for delay in (0, 1, 2):
        if delay:
            time.sleep(delay)
        try:
            conn = psycopg2.connect(
                host=cfg["host"],
                port=cfg["port"],
                database=cfg["database"],
                user=cfg["user"],
                password=cfg["password"],
                connect_timeout=connect_timeout,
            )
            break
        except psycopg2.OperationalError as exc:
            last_exc = exc
    if conn is None:
        raise last_exc  # type: ignore[misc]
    try:
        yield conn
    finally:
        conn.close()
