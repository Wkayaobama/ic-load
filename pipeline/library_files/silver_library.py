"""Phase 7a — Bronze → Silver normalisation for the IC'ALPS Library entity.

Reads ``sql/library/files_icalps.csv`` (BOM-prefixed UTF-8, Windows backslashes
in path columns, fixed-width-padded enum strings, literal "NULL" sentinel),
applies type casts + path normalisation + the at-least-one-FK filter, and
optionally UPSERTs into ``staging.stg_library_normalised``.

Two execution surfaces:
  - parse() — offline, read-only, yields normalised dicts. Used by tests.
  - normalise() — DB-touching: parse + owner resolution + bulk UPSERT.
                  Returns a SilverStats summary.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Optional


_SCHEMA_NAME_RX = re.compile(r"^[a-z_][a-z0-9_]*$")
_SQL_DIR = Path(__file__).parent / "sql"

_BRONZE_TO_SILVER: dict[str, str] = {
    "Libr_LibraryId":     "legacy_library_id",
    "Libr_CompanyId":     "legacy_company_id",
    "Libr_PersonId":      "legacy_contact_id",
    "Libr_OpportunityId": "legacy_deal_id",
    "Libr_CaseId":        "legacy_case_id",
    "Libr_FilePath":      "legacy_file_path",
    "Libr_FileName":      "legacy_file_name",
    "Libr_FileSize":      "libr_file_size",
    "Libr_Note":          "libr_note",
    "Libr_Type":          "libr_type",
    "Libr_Category":      "libr_category",
    "Libr_Status":        "libr_status",
    "Libr_CreatedBy":     "libr_created_by",
    "Libr_UpdatedBy":     "libr_updated_by",
    "Libr_CreatedDate":   "libr_created_at",
    "Libr_UpdatedDate":   "libr_updated_at",
}

_BIGINT_COLS = {
    "legacy_library_id", "legacy_company_id", "legacy_contact_id",
    "legacy_deal_id", "legacy_case_id", "libr_file_size",
}
_INT_COLS = {"libr_created_by", "libr_updated_by"}
_PATH_COL = "legacy_file_path"


def _clean_text(value: object) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.upper() == "NULL":
        return None
    return s


def _to_bigint(value: object) -> Optional[int]:
    s = _clean_text(value)
    if s is None:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def _normalise_path(value: object) -> Optional[str]:
    s = _clean_text(value)
    if s is None:
        return None
    return s.replace("\\", "/").strip("/").strip()


@dataclass
class SilverStats:
    total_rows: int = 0
    written_rows: int = 0
    filtered_inactive: int = 0
    filtered_deleted: int = 0
    filtered_no_fk: int = 0
    filtered_missing_pk: int = 0
    filtered_missing_path_or_name: int = 0


class LibrarySilverNormaliser:
    def __init__(
        self,
        bronze_csv: Path,
        *,
        dsn: Optional[str] = None,
        schema: str = "staging",
    ) -> None:
        if not _SCHEMA_NAME_RX.match(schema):
            raise ValueError(f"invalid schema {schema!r}")
        self.bronze_csv = bronze_csv
        self.dsn = dsn
        self.schema = schema
        self.stats = SilverStats()

    def _read_csv(self) -> Iterator[dict]:
        with self.bronze_csv.open("r", encoding="utf-8-sig", newline="") as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                yield row

    def _normalise_row(self, raw: Mapping[str, object]) -> Optional[dict]:
        # Bronze semantics: most rows have Libr_Active=NULL (only ~0.6% set explicit
        # 'Y'), so the flag is opt-OUT not opt-IN. Drop only on explicit 'N'.
        active = _clean_text(raw.get("Libr_Active"))
        if active is not None and active.upper() == "N":
            self.stats.filtered_inactive += 1
            return None
        # Same shape: drop only on explicit '1'. NULL/empty/0 all keep.
        deleted = _clean_text(raw.get("Libr_Deleted"))
        if deleted == "1":
            self.stats.filtered_deleted += 1
            return None

        out: dict = {}
        for bronze_col, silver_col in _BRONZE_TO_SILVER.items():
            v = raw.get(bronze_col)
            if silver_col == _PATH_COL:
                out[silver_col] = _normalise_path(v)
            elif silver_col in _BIGINT_COLS or silver_col in _INT_COLS:
                out[silver_col] = _to_bigint(v)
            else:
                out[silver_col] = _clean_text(v)

        if out["legacy_library_id"] is None:
            self.stats.filtered_missing_pk += 1
            return None
        if not out["legacy_file_path"] or not out["legacy_file_name"]:
            self.stats.filtered_missing_path_or_name += 1
            return None
        if (
            out["legacy_company_id"] is None
            and out["legacy_contact_id"] is None
            and out["legacy_deal_id"] is None
        ):
            self.stats.filtered_no_fk += 1
            return None
        return out

    def parse(self) -> Iterator[dict]:
        self.stats = SilverStats()
        for raw in self._read_csv():
            self.stats.total_rows += 1
            row = self._normalise_row(raw)
            if row is None:
                continue
            self.stats.written_rows += 1
            yield row

    def normalise(self) -> SilverStats:
        if not self.dsn:
            raise RuntimeError("DSN required for normalise(); use parse() for read-only.")
        rows = list(self.parse())
        if not rows:
            return self.stats
        owner_map = self._resolve_owners(
            {r["libr_created_by"] for r in rows if r["libr_created_by"] is not None}
        )
        for r in rows:
            owner = owner_map.get(r["libr_created_by"])
            r["icalps_owner_email"] = owner[0] if owner else None
            r["icalps_owner_fullname"] = owner[1] if owner else None
        self._bootstrap_table()
        self._bulk_upsert(rows)
        return self.stats

    def _bootstrap_table(self) -> None:
        ddl = (_SQL_DIR / "init_silver.sql").read_text(encoding="utf-8")
        # Use str.replace, not str.format. format() interprets any literal
        # {...} in the SQL (comments, JSON literals, array constructors) as a
        # named placeholder. self.schema has already been validated against
        # _SCHEMA_NAME_RX, so direct interpolation is safe.
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(ddl.replace("{schema}", self.schema))
            conn.commit()

    def install_fct_view(self) -> None:
        ddl = (_SQL_DIR / "init_fct_view.sql").read_text(encoding="utf-8")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(ddl.replace("{schema}", self.schema))
            conn.commit()

    def _resolve_owners(
        self, user_ids: Iterable[int]
    ) -> dict[int, tuple[Optional[str], Optional[str]]]:
        ids = [int(u) for u in user_ids if u is not None]
        if not ids:
            return {}
        out: dict[int, tuple[Optional[str], Optional[str]]] = {}
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    f"SELECT legacy_user_id, owner_email, owner_fullname "
                    f"FROM {self.schema}.stg_owner_resolution "
                    f"WHERE legacy_user_id = ANY(%s)",
                    (ids,),
                )
                for legacy_user_id, owner_email, owner_fullname in cur.fetchall():
                    out[int(legacy_user_id)] = (owner_email, owner_fullname)
        except Exception:
            return {}
        return out

    def _bulk_upsert(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        cols = list(_BRONZE_TO_SILVER.values()) + ["icalps_owner_email", "icalps_owner_fullname"]
        col_list = ", ".join(cols)
        placeholders = ", ".join(["%s"] * len(cols))
        update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "legacy_library_id")
        sql = (
            f"INSERT INTO {self.schema}.stg_library_normalised ({col_list}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT (legacy_library_id) DO UPDATE SET {update_set}"
        )
        with self._connect() as conn, conn.cursor() as cur:
            for r in rows:
                cur.execute(sql, [r.get(c) for c in cols])
            conn.commit()
        return len(rows)

    def _connect(self):
        import psycopg2
        return psycopg2.connect(self.dsn)
