from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


@dataclass(frozen=True)
class Settings:
    hubspot_token: str
    hubspot_portal_id: str | None
    library_base_dir: Path | None
    prod_postgres_dsn: str | None
    api_base_url: str = "https://api.hubapi.com"

    @classmethod
    def from_env(cls, *, token_var: str = "HUBSPOT_SANDBOX_TOKEN") -> "Settings":
        # Two-stage env load so multiple worktrees can share one canonical
        # `.env.icalps` at the parent (Codebase/) level while still allowing a
        # worktree-local `.env` to override individual values for ad-hoc work.
        # Process env beats file values; worktree `.env` beats parent
        # `.env.icalps`. find_dotenv walks up from cwd, so this works from any
        # subdirectory inside any worktree.
        load_dotenv(find_dotenv(filename=".env.icalps", usecwd=True))
        load_dotenv(find_dotenv(usecwd=True), override=True)
        token = os.environ.get(token_var)
        if not token:
            raise RuntimeError(
                f"{token_var} is not set. Populate either .env.icalps at the "
                f"Codebase root or .env in this worktree."
            )
        base_dir = os.environ.get("LIBRARY_BASE_DIR")
        return cls(
            hubspot_token=token,
            hubspot_portal_id=os.environ.get("HUBSPOT_SANDBOX_PORTAL_ID"),
            library_base_dir=Path(base_dir) if base_dir else None,
            prod_postgres_dsn=os.environ.get("PROD_POSTGRES_DSN"),
        )
