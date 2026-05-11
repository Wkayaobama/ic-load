from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any
from urllib.parse import parse_qs, urlparse


def _parse_jdbc_url(jdbc_url: str) -> dict[str, Any]:
    """Parse a JDBC PostgreSQL URL into psycopg2 connect kwargs.

    Accepts:
      jdbc:postgresql://host:port/database?user=U&password=P
      postgresql://host:port/database?user=U&password=P   (without jdbc: prefix)
    """
    url = jdbc_url.removeprefix("jdbc:")
    parsed = urlparse(url)
    params = parse_qs(parsed.query)

    # user/password may be in URL authority OR in query params (JDBC convention)
    user = (
        parsed.username
        or (params.get("user") or params.get("username") or [None])[0]
    )
    password = (
        parsed.password
        or (params.get("password") or [None])[0]
    )
    return {
        "host": parsed.hostname,
        "port": int(parsed.port or 5432),
        "database": (parsed.path or "").lstrip("/") or "postgres",
        "user": user,
        "password": password,
    }


def postgres_config() -> dict[str, Any]:
    # Resolution order:
    #   1. ICALPS_JDBC_URL / DATABASE_URL / PROD_POSTGRES_DSN — single
    #      JDBC connection string. PROD_POSTGRES_DSN is the canonical name
    #      in .env.icalps and is also consumed by pipeline.library_files /
    #      pipeline.cleanup; recognising it here keeps every runner reading
    #      the same secret from the same file.
    #   2. ICALPS_PG* individual vars
    #   3. PG* standard vars
    jdbc = (
        os.getenv("ICALPS_JDBC_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("PROD_POSTGRES_DSN")
    )
    if jdbc:
        return _parse_jdbc_url(jdbc)

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
