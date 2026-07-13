from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

import requests

try:
    from config.settings import ADMIN_API_BASE_URL, ADMIN_API_IMPORT_PATH, ADMIN_API_TOKEN
except ModuleNotFoundError:
    from scraper_framework.config.settings import (
        ADMIN_API_BASE_URL,
        ADMIN_API_IMPORT_PATH,
        ADMIN_API_TOKEN,
    )


def _pick_first_value(payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


@dataclass(slots=True)
class AdminPermitImportClient:
    base_url: str = ADMIN_API_BASE_URL
    import_path: str = ADMIN_API_IMPORT_PATH
    token: str = ADMIN_API_TOKEN
    exclude_tmp: bool = True
    exclude_statuses: list[str] = field(default_factory=lambda: ["Withdrawn"])
    session: requests.Session = field(default_factory=requests.Session, repr=False)

    @property
    def endpoint(self) -> str:
        if not self.base_url:
            raise ValueError("ADMIN_API_BASE_URL is not configured.")
        return urljoin(self.base_url.rstrip("/") + "/", self.import_path.lstrip("/"))

    def build_record(self, normalized_data: dict[str, Any], raw_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "record_number": _pick_first_value(
                normalized_data,
                ("record_number", "permit_number", "case_number"),
            )
            or _pick_first_value(raw_data, ("CaseNumber", "PermitNumber", "RecordNumber")),
            "permit_type": _pick_first_value(normalized_data, ("permit_type", "record_type"))
            or _pick_first_value(raw_data, ("CaseType", "PermitType", "PermitTypeName")),
            "status": _pick_first_value(normalized_data, ("status",))
            or _pick_first_value(raw_data, ("CaseStatus", "Status")),
            "address": _pick_first_value(normalized_data, ("address",))
            or _pick_first_value(raw_data, ("AddressDisplay",))
            or (
                raw_data.get("Address", {}).get("FullAddress")
                if isinstance(raw_data.get("Address"), dict)
                else None
            ),
            "description": _pick_first_value(normalized_data, ("description",))
            or _pick_first_value(raw_data, ("Description", "ProjectName")),
            "issue_date": _pick_first_value(normalized_data, ("issue_date", "issued_date", "date"))
            or _pick_first_value(raw_data, ("IssueDate", "IssuedDate")),
            "apply_date": _pick_first_value(normalized_data, ("apply_date", "applied_date"))
            or _pick_first_value(raw_data, ("ApplyDate", "AppliedDate")),
            "expiration_date": _pick_first_value(normalized_data, ("expiration_date",))
            or _pick_first_value(raw_data, ("ExpireDate", "ExpirationDate")),
            "parcel_number": _pick_first_value(normalized_data, ("parcel_number",))
            or _pick_first_value(raw_data, ("MainParcel", "ParcelNumber")),
            "raw": raw_data,
        }

    def build_payload_from_permit_documents(
        self,
        provider: str,
        state: str | None,
        county: str | None,
        agency: str | None,
        module: str | None,
        source_url: str | None,
        permit_documents: list[dict[str, Any]],
        *,
        fips: str | None = None,
        import_run_id: str | None = None,
        exclude_tmp: bool | None = None,
        exclude_statuses: list[str] | None = None,
    ) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        for document in permit_documents:
            normalized_data = document.get("normalized_data") or {}
            raw_data = document.get("raw_data") or document.get("raw") or {}
            if not isinstance(normalized_data, dict) or not isinstance(raw_data, dict):
                continue
            records.append(self.build_record(normalized_data, raw_data))

        return {
            "provider": provider,
            "state": state,
            "county": county,
            "fips": fips,
            "agency": agency,
            "module": module,
            "source_url": source_url,
            "import_run_id": import_run_id or str(uuid4()),
            "exclude_tmp": self.exclude_tmp if exclude_tmp is None else exclude_tmp,
            "exclude_statuses": self.exclude_statuses if exclude_statuses is None else exclude_statuses,
            "records": records,
        }

    def push_payload(self, payload: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
        if not self.token:
            raise ValueError("ADMIN_API_TOKEN is not configured.")

        response = self.session.post(
            self.endpoint,
            json=payload,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
