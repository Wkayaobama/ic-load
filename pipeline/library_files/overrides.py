"""Sandbox override map.

Production postgres carries prod HubSpot record ids, but the sandbox portal has
its own (different) id namespace. The override map lets the migrator translate
legacy IC'ALPS ids → sandbox HubSpot ids for the duration of testing, without
ever pointing prod ids at sandbox calls (which would 404).

Map shape (json on disk):
{
  "<legacy_company_id>": {"company": "<sandbox_company_id>"},
  "<legacy_contact_id>": {"contact": "<sandbox_contact_id>"},
  "<legacy_deal_id>":    {"deal":    "<sandbox_deal_id>"}
}

The map is keyed by *legacy* id (stable across prod and sandbox) rather than the
prod HubSpot id (meaningless in sandbox).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SandboxOverrideMap:
    """legacy_id -> {object_type: sandbox_id}"""

    entries: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: Path) -> "SandboxOverrideMap":
        with path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        # normalise — legacy ids stored as strings
        return cls({str(k): {kk: str(vv) for kk, vv in v.items()} for k, v in data.items()})

    def to_json(self, path: Path) -> None:
        with path.open("w", encoding="utf-8") as fp:
            json.dump(self.entries, fp, indent=2, sort_keys=True)

    def set(self, legacy_id: str, object_type: str, sandbox_id: str) -> None:
        self.entries.setdefault(str(legacy_id), {})[object_type] = str(sandbox_id)

    def resolve(
        self,
        *,
        legacy_company_id: str | None = None,
        legacy_contact_id: str | None = None,
        legacy_deal_id: str | None = None,
    ) -> list[tuple[str, str]]:
        """Return the (object_type, sandbox_id) tuples present in the map for
        any of the supplied legacy ids. Missing ids are dropped silently — the
        uploader's caller is responsible for asserting at-least-one target."""
        out: list[tuple[str, str]] = []
        for legacy_id, kind in (
            (legacy_company_id, "company"),
            (legacy_contact_id, "contact"),
            (legacy_deal_id, "deal"),
        ):
            if legacy_id is None:
                continue
            sandbox_id = self.entries.get(str(legacy_id), {}).get(kind)
            if sandbox_id is not None:
                out.append((kind, sandbox_id))
        return out
