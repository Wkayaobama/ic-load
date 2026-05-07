"""Library row sources.

Reader abstraction returning per-file records that the runner combines with the
sandbox override map to produce LibraryFileRow targets.

Two concrete implementations:
  - CsvLibraryReader      — offline-testable source, used in unit tests
  - PostgresLibraryReader — read-only against prod postgres for live runs
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

# Each record is a row of the source mart that the migrator iterates.
# legacy_*_id values are strings (zero values stored as None for clarity).
@dataclass
class LibraryRecord:
    legacy_library_id: str
    legacy_file_name: str
    legacy_file_path: str  # relative to library_base_dir
    legacy_company_id: str | None = None
    legacy_contact_id: str | None = None
    legacy_deal_id: str | None = None


class CsvLibraryReader:
    """Reads LibraryRecord rows from a CSV with the columns above."""

    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path

    def fetch_rows(self) -> Iterator[LibraryRecord]:
        with self.csv_path.open("r", encoding="utf-8", newline="") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                yield LibraryRecord(
                    legacy_library_id=str(row["legacy_library_id"]),
                    legacy_file_name=str(row["legacy_file_name"]),
                    legacy_file_path=str(row["legacy_file_path"]),
                    legacy_company_id=row.get("legacy_company_id") or None,
                    legacy_contact_id=row.get("legacy_contact_id") or None,
                    legacy_deal_id=row.get("legacy_deal_id") or None,
                )


class PostgresLibraryReader:
    """Read-only reader against prod postgres.

    Not exercised by unit tests in this branch — gated behind PROD_POSTGRES_DSN
    and an explicit caller invocation. Built for the prod pilot phase.
    """

    DEFAULT_QUERY = """
        select
            legacy_library_id::text       as legacy_library_id,
            legacy_file_name              as legacy_file_name,
            legacy_file_path              as legacy_file_path,
            legacy_company_id::text       as legacy_company_id,
            legacy_contact_id::text       as legacy_contact_id,
            legacy_deal_id::text          as legacy_deal_id
        from staging.fct_library_files
    """

    def __init__(self, dsn: str, query: str | None = None) -> None:
        self.dsn = dsn
        self.query = query or self.DEFAULT_QUERY

    def fetch_rows(self) -> Iterable[LibraryRecord]:
        import psycopg2  # imported lazily so unit tests need not have it

        with psycopg2.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(self.query)
            cols = [c[0] for c in cur.description]
            for row in cur.fetchall():
                d = dict(zip(cols, row))
                yield LibraryRecord(
                    legacy_library_id=str(d["legacy_library_id"]),
                    legacy_file_name=str(d["legacy_file_name"]),
                    legacy_file_path=str(d["legacy_file_path"]),
                    legacy_company_id=d.get("legacy_company_id") or None,
                    legacy_contact_id=d.get("legacy_contact_id") or None,
                    legacy_deal_id=d.get("legacy_deal_id") or None,
                )
