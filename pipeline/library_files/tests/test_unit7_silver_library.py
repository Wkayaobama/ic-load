"""Phase 7a tests — LibrarySilverNormaliser parse/filter logic.

Six offline tests cover the type casts, BOM handling, path normalisation, and
filter rules against a synthetic bronze CSV. One "prove against real bronze"
test reads ``sql/library/files_icalps.csv`` (operator-supplied, gitignored)
and validates the row count + sample-row shape — proves the cleaning logic
works against the actual file structure before any postgres write.

The DB-touching ``normalise()`` path is covered later; this unit stops at
``parse()``.
"""
from __future__ import annotations

import csv
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from pipeline.library_files.silver_library import LibrarySilverNormaliser

REPO_ROOT = Path(__file__).parent.parent.parent.parent
REAL_BRONZE_CSV = REPO_ROOT / "sql" / "library" / "files_icalps.csv"

# Bronze schema (53 columns, abbreviated to the ones we touch + filter columns).
_BRONZE_HEADER = [
    "Libr_LibraryId", "Libr_CompanyId", "Company_Name", "Libr_PersonId",
    "Pers_FirstName", "Pers_LastName", "Libr_OpportunityId", "Oppo_Description",
    "Libr_CaseId", "Case_Description", "Libr_UserId", "Libr_ChannelId",
    "Libr_Type", "Libr_Category", "Libr_FilePath", "Libr_FileName",
    "Libr_Note", "Libr_Status", "Libr_Private", "Libr_CreatedBy",
    "Libr_CreatedDate", "Libr_UpdatedBy", "Libr_UpdatedDate", "Libr_TimeStamp",
    "Libr_Deleted", "Libr_LeadId", "libr_communicationId", "Libr_SolutionId",
    "Libr_Active", "Libr_language", "Libr_Global", "Libr_Mergetemplate",
    "Libr_CampaignId", "Libr_Entity", "Libr_FileSize",
]


@contextmanager
def _tmp():
    with tempfile.TemporaryDirectory(prefix="libfiles_unit7_") as d:
        yield Path(d)


def _row_dict(**overrides):
    """Build a synthetic bronze row with all 35 abbreviated columns. Default
    values represent a *valid keepable* row (Active=Y, Deleted=0, has FK)."""
    base = {col: "NULL" for col in _BRONZE_HEADER}
    base.update({
        "Libr_LibraryId": "1234",
        "Libr_CompanyId": "5678",
        "Libr_FilePath": "Customers\\Acme\\",
        "Libr_FileName": "invoice.pdf",
        "Libr_Type": "Proposal                 ",
        "Libr_Status": "Final                                   ",
        "Libr_Active": "Y                                       ",
        "Libr_Deleted": "0",
        "Libr_FileSize": "41984",
        "Libr_CreatedBy": "-1",
    })
    base.update(overrides)
    return base


def _write_bronze(path: Path, rows: list[dict], with_bom: bool = True) -> None:
    encoding = "utf-8-sig" if with_bom else "utf-8"
    with path.open("w", encoding=encoding, newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=_BRONZE_HEADER)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


# -- Offline tests on synthetic bronze --------------------------------------


def test_global_template_with_no_fks_filtered():
    """First 4 rows of the real bronze CSV are 'Global Templates' — all FKs
    NULL. They must be filtered out by silver."""
    with _tmp() as d:
        path = d / "bronze.csv"
        _write_bronze(path, [
            _row_dict(
                Libr_LibraryId="1",
                Libr_CompanyId="NULL", Libr_PersonId="NULL", Libr_OpportunityId="NULL",
                Libr_FilePath="Global Templates\\US\\",
                Libr_FileName="Panoply Fax.doc",
            ),
        ])
        norm = LibrarySilverNormaliser(path)
        rows = list(norm.parse())
        assert len(rows) == 0
        assert norm.stats.filtered_no_fk == 1


def test_inactive_row_filtered():
    with _tmp() as d:
        path = d / "bronze.csv"
        _write_bronze(path, [_row_dict(Libr_Active="N")])
        norm = LibrarySilverNormaliser(path)
        rows = list(norm.parse())
        assert rows == []
        assert norm.stats.filtered_inactive == 1


def test_deleted_row_filtered():
    with _tmp() as d:
        path = d / "bronze.csv"
        _write_bronze(path, [_row_dict(Libr_Deleted="1")])
        norm = LibrarySilverNormaliser(path)
        rows = list(norm.parse())
        assert rows == []
        assert norm.stats.filtered_deleted == 1


def test_valid_row_with_company_fk_passes_and_path_normalised():
    with _tmp() as d:
        path = d / "bronze.csv"
        _write_bronze(path, [_row_dict(
            Libr_LibraryId="100",
            Libr_CompanyId="5678",
            Libr_FilePath="Customers\\Acme Corp\\Q1 2024\\",
            Libr_FileName="invoice.pdf",
        )])
        norm = LibrarySilverNormaliser(path)
        rows = list(norm.parse())
        assert len(rows) == 1
        r = rows[0]
        assert r["legacy_library_id"] == 100
        assert r["legacy_company_id"] == 5678
        assert r["legacy_contact_id"] is None
        assert r["legacy_deal_id"] is None
        # Backslash → forward slash, no leading or trailing slash
        assert r["legacy_file_path"] == "Customers/Acme Corp/Q1 2024"
        assert r["legacy_file_name"] == "invoice.pdf"


def test_fixed_width_padding_trimmed():
    with _tmp() as d:
        path = d / "bronze.csv"
        _write_bronze(path, [_row_dict(
            Libr_Type="Proposal                 ",
            Libr_Status="Final                                   ",
        )])
        norm = LibrarySilverNormaliser(path)
        rows = list(norm.parse())
        assert rows[0]["libr_type"] == "Proposal"
        assert rows[0]["libr_status"] == "Final"


def test_bom_prefixed_csv_reads_first_column_correctly():
    """The real bronze CSV is utf-8-sig (BOM-prefixed). Without strip-BOM,
    the first column key would be '﻿Libr_LibraryId' and break the rename
    map. utf-8-sig in _read_csv handles this."""
    with _tmp() as d:
        path = d / "bronze.csv"
        _write_bronze(path, [_row_dict(Libr_LibraryId="42")], with_bom=True)
        norm = LibrarySilverNormaliser(path)
        rows = list(norm.parse())
        assert len(rows) == 1
        assert rows[0]["legacy_library_id"] == 42


def test_mixed_set_4_total_2_pass():
    """Sanity: 4 rows in (1 valid, 1 inactive, 1 deleted, 1 no-fk) → 1 row out."""
    with _tmp() as d:
        path = d / "bronze.csv"
        _write_bronze(path, [
            _row_dict(Libr_LibraryId="1", Libr_CompanyId="100"),                   # keep
            _row_dict(Libr_LibraryId="2", Libr_Active="N"),                        # filter
            _row_dict(Libr_LibraryId="3", Libr_Deleted="1"),                       # filter
            _row_dict(Libr_LibraryId="4",                                          # filter — no FK
                      Libr_CompanyId="NULL", Libr_PersonId="NULL", Libr_OpportunityId="NULL"),
        ])
        norm = LibrarySilverNormaliser(path)
        rows = list(norm.parse())
        assert len(rows) == 1
        assert rows[0]["legacy_library_id"] == 1
        assert norm.stats.total_rows == 4
        assert norm.stats.written_rows == 1


# -- Prove against real bronze CSV ------------------------------------------


def test_real_bronze_csv_parses_and_filter_sanity():
    """Pre-prod sanity check: read the actual sql/library/files_icalps.csv and
    verify our cleaning logic produces structurally-correct rows. Skips when
    the CSV isn't present (it's gitignored — operator-supplied)."""
    if not REAL_BRONZE_CSV.is_file():
        pytest.skip(f"{REAL_BRONZE_CSV} not present — operator-supplied bronze CSV")

    norm = LibrarySilverNormaliser(REAL_BRONZE_CSV)
    rows = list(norm.parse())
    s = norm.stats

    # Headline counts (operator-visible)
    print(
        f"\n  total_rows={s.total_rows}  written={s.written_rows}\n"
        f"  filtered_inactive={s.filtered_inactive}  "
        f"filtered_deleted={s.filtered_deleted}  "
        f"filtered_no_fk={s.filtered_no_fk}\n"
        f"  filtered_missing_pk={s.filtered_missing_pk}  "
        f"filtered_missing_path_or_name={s.filtered_missing_path_or_name}"
    )

    # Real CSV had 5,989 data rows when added. Allow +/- a few in case of
    # operator re-extraction.
    assert s.total_rows >= 5_500, f"unexpectedly few rows: {s.total_rows}"
    assert s.written_rows > 0, "no rows passed silver filter — bronze schema may have changed"

    # Filter ratio: most production rows have at least one FK; 'Global
    # Templates' should be a small minority.
    assert s.written_rows / s.total_rows > 0.5, (
        f"too many rows filtered: kept {s.written_rows}/{s.total_rows}"
    )

    # Sample shape sanity on first 20 rows
    sample = rows[:20]
    assert all(isinstance(r["legacy_library_id"], int) for r in sample)
    assert all(r["legacy_file_path"] for r in sample)
    assert all(r["legacy_file_name"] for r in sample)
    # No remaining backslashes in path
    assert all("\\" not in r["legacy_file_path"] for r in sample), (
        "path normalisation missed something"
    )
    # Each row has at least one FK
    assert all(
        any(r[k] is not None for k in ("legacy_company_id", "legacy_contact_id", "legacy_deal_id"))
        for r in sample
    ), "row passed filter without any FK — filter logic broken"
