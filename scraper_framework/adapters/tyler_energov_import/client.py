from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from ..tyler_energov.client import TylerEnerGovAdapterClient
from ..tyler_energov.constants import ADAPTER_NAME


class TylerEnerGovSearchClient:
    def __init__(self, base_url: str, payload_path: Path, request_timeout_seconds: int = 60) -> None:
        self.base_url = base_url.rstrip("/")
        self.search_url = f"{self.base_url}/apps/selfservice/api/energov/search/search"
        self.source_url = f"{self.base_url}/apps/SelfService"
        self.request_timeout_seconds = request_timeout_seconds
        self.payload_template = self._load_payload_template(payload_path)

        adapter_client = TylerEnerGovAdapterClient(
            adapter_name=ADAPTER_NAME,
            request_timeout_seconds=request_timeout_seconds,
        )
        self.session = adapter_client.requests
        self.session.headers.update(self._build_headers())

    def _load_payload_template(self, payload_path: Path) -> dict[str, Any]:
        if not payload_path.exists():
            raise FileNotFoundError(f"Payload file not found: {payload_path}")

        with payload_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if not isinstance(payload, dict):
            raise ValueError("Payload file must contain a JSON object at the top level.")

        return payload

    def _build_headers(self) -> dict[str, str]:
        return {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json;charset=UTF-8",
            "tenantid": "1",
            "tenantname": "EnerGovProd",
            "tyler-tenant-culture": "en-US",
            "tyler-tenanturl": "home",
            "origin": self.base_url,
            "referer": self.source_url,
        }

    def search_permit_type(self, permit_type_id: str, page: int, page_size: int) -> dict[str, Any]:
        payload = copy.deepcopy(self.payload_template)

        payload.setdefault("PermitCriteria", {})
        payload["PermitCriteria"]["PermitTypeId"] = permit_type_id
        payload["PermitCriteria"]["PageNumber"] = page
        payload["PermitCriteria"]["PageSize"] = page_size
        payload["PageNumber"] = page
        payload["PageSize"] = page_size

        response = self.session.post(
            self.search_url,
            json=payload,
            timeout=self.request_timeout_seconds,
        )
        response.raise_for_status()
        return response.json()
