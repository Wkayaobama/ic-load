from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable, Optional

import requests

from .config import Settings


class HubSpotClient:
    """Thin REST client. No retries — orchestration layer adds those."""

    def __init__(
        self,
        token: str,
        base_url: str = "https://api.hubapi.com",
        session: Optional[requests.Session] = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._session = session or requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {token}"})

    @classmethod
    def from_settings(cls, settings: Settings) -> "HubSpotClient":
        return cls(token=settings.hubspot_token, base_url=settings.api_base_url)

    # -- CRM: companies (used only to seed/cleanup sandbox test records) -----

    def create_company(self, *, name: str, **extra_properties: str) -> dict:
        url = f"{self.base_url}/crm/v3/objects/companies"
        payload = {"properties": {"name": name, **extra_properties}}
        resp = self._session.post(url, json=payload, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

    def delete_company(self, company_id: str) -> None:
        url = f"{self.base_url}/crm/v3/objects/companies/{company_id}"
        resp = self._session.delete(url, timeout=self.timeout_s)
        resp.raise_for_status()

    # -- CRM: notes ----------------------------------------------------------

    def create_note(
        self,
        *,
        hs_note_body: str,
        hs_attachment_ids: Iterable[str],
        hs_timestamp_ms: Optional[int] = None,
        extra_properties: Optional[dict] = None,
    ) -> dict:
        """Create a note with attachments. hs_timestamp is required by HubSpot;
        we default to now() in milliseconds if the caller does not supply one.
        hs_attachment_ids is serialised as a semicolon-delimited string per v3 spec."""
        ts = hs_timestamp_ms if hs_timestamp_ms is not None else int(time.time() * 1000)
        attachment_str = ";".join(str(i) for i in hs_attachment_ids)
        properties = {
            "hs_note_body": hs_note_body,
            "hs_attachment_ids": attachment_str,
            "hs_timestamp": str(ts),
        }
        if extra_properties:
            properties.update(extra_properties)
        url = f"{self.base_url}/crm/v3/objects/notes"
        resp = self._session.post(url, json={"properties": properties}, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

    def get_note(
        self,
        note_id: str,
        *,
        associations: Optional[Iterable[str]] = None,
        properties: Optional[Iterable[str]] = None,
    ) -> dict:
        url = f"{self.base_url}/crm/v3/objects/notes/{note_id}"
        params: dict = {}
        if associations:
            params["associations"] = ",".join(associations)
        if properties:
            params["properties"] = ",".join(properties)
        resp = self._session.get(url, params=params, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json()

    def delete_note(self, note_id: str) -> None:
        url = f"{self.base_url}/crm/v3/objects/notes/{note_id}"
        resp = self._session.delete(url, timeout=self.timeout_s)
        resp.raise_for_status()

    # -- Files API -----------------------------------------------------------

    def upload_file(
        self,
        path: Path,
        *,
        folder_path: str = "/legacy_migrations",
        access: str = "PRIVATE",
        overwrite: bool = False,
    ) -> dict:
        url = f"{self.base_url}/files/v3/files"
        options = {"access": access, "overwrite": overwrite}
        with path.open("rb") as fp:
            files = {"file": (path.name, fp)}
            data = {
                "options": json.dumps(options),
                "folderPath": folder_path,
            }
            resp = self._session.post(
                url, files=files, data=data, timeout=self.timeout_s
            )
        resp.raise_for_status()
        return resp.json()

    def delete_file(self, file_id: str) -> None:
        url = f"{self.base_url}/files/v3/files/{file_id}"
        resp = self._session.delete(url, timeout=self.timeout_s)
        resp.raise_for_status()

    # -- v4 default associations ---------------------------------------------

    def associate_default(
        self,
        from_object_type: str,
        from_object_id: str,
        to_object_type: str,
        to_object_id: str,
    ) -> dict:
        """PUT /crm/v4/objects/{from_type}/{from_id}/associations/default/{to_type}/{to_id}.
        Path uses singular object types: 'note', 'company', 'contact', 'deal'."""
        url = (
            f"{self.base_url}/crm/v4/objects/{from_object_type}/{from_object_id}"
            f"/associations/default/{to_object_type}/{to_object_id}"
        )
        resp = self._session.put(url, timeout=self.timeout_s)
        resp.raise_for_status()
        return resp.json() if resp.content else {}
