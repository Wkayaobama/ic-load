"""Filesystem walker — mimics the production folder-iteration boundary.

For Unit 3, walks a directory and produces one LibraryFileRow per non-image file,
all routed to a single sandbox target record. Postgres-driven target resolution
arrives in Unit 4.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, Iterator

from .uploader import LibraryFileRow


# Same defaults as the original spec (§6, image extensions deferred).
IMAGE_EXTS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".svg"}
)


def walk_files(
    root: Path, *, exclude_exts: Iterable[str] = IMAGE_EXTS
) -> Iterator[Path]:
    excl = {e.lower() for e in exclude_exts}
    for p in sorted(root.rglob("*")):  # sorted for deterministic test order
        if p.is_file() and p.suffix.lower() not in excl:
            yield p


def _synthetic_legacy_id(root: Path, file_path: Path) -> str:
    """Stable id for pre-postgres units, derived from the path under root."""
    rel = file_path.resolve().relative_to(root.resolve()).as_posix()
    h = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]
    return f"fs:{h}"


def build_rows(
    root: Path,
    *,
    target_associations: list[tuple[str, str]],
    note_body_template: str = "Legacy migrated file: {name}",
    exclude_exts: Iterable[str] = IMAGE_EXTS,
) -> list[LibraryFileRow]:
    """Walk ``root`` and produce a LibraryFileRow per non-image file, all
    pointing at the same target record set."""
    rows: list[LibraryFileRow] = []
    for fp in walk_files(root, exclude_exts=exclude_exts):
        rows.append(
            LibraryFileRow(
                legacy_id=_synthetic_legacy_id(root, fp),
                file_path=fp,
                note_body=note_body_template.format(name=fp.name),
                target_associations=list(target_associations),
            )
        )
    return rows
