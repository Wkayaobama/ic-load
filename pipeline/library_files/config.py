from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    hubspot_token: str
    hubspot_portal_id: str | None
    library_base_dir: Path | None
    prod_postgres_dsn: str | None
    api_base_url: str = "https://api.hubapi.com"

    @classmethod
    def from_env(cls, *, token_var: str = "HUBSPOT_SANDBOX_TOKEN") -> "Settings":
        load_dotenv()
        token = os.environ.get(token_var)
        if not token:
            raise RuntimeError(
                f"{token_var} is not set. Copy .env.example to .env and fill it in."
            )
        base_dir = os.environ.get("LIBRARY_BASE_DIR")
        return cls(
            hubspot_token=token,
            hubspot_portal_id=os.environ.get("HUBSPOT_SANDBOX_PORTAL_ID"),
            library_base_dir=Path(base_dir) if base_dir else None,
            prod_postgres_dsn=os.environ.get("PROD_POSTGRES_DSN"),
        )
