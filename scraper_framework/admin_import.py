from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

import requests

try:
    from config.settings import (
        ADMIN_API_BASE_URL,
        ADMIN_API_IMPORT_PATH,
        ADMIN_API_TOKEN,
        REQUEST_TIMEOUT_SECONDS,
        USER_AGENT,
    )
    from utils.logger import get_logger
except ModuleNotFoundError:
    from scraper_framework.config.settings import (
        ADMIN_API_BASE_URL,
        ADMIN_API_IMPORT_PATH,
        ADMIN_API_TOKEN,
        REQUEST_TIMEOUT_SECONDS,
        USER_AGENT,
    )
    from scraper_framework.utils.logger import get_logger


logger = get_logger("admin_import")


def _utc_import_run_id(prefix: str = "python") -> str:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return f"{prefix}-{timestamp}"


def _strip_or_none(value: Any) -> Any:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return value


def _coalesce(*values: Any) -> Any:
    for value in values:
        cleaned = _strip_or_none(value)
        if cleaned is not None:
            return cleaned
    return None


@dataclass(slots=True)
class AdminPermitImportClient:
    base_url: str = ADMIN_API_BASE_URL
    token: str = ADMIN_API_TOKEN
    import_path: str = ADMIN_API_IMPORT_PATH
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS
    user_agent: str = USER_AGENT
    exclude_tmp: bool = True
    exclude_statuses: list[str] = field(default_factory=lambda: ["Withdrawn"])
    session: requests.Session = field(default_factory=requests.Session, repr=False)

    def __post_init__(self) -> None:
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
            }
        )
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    @property
    def endpoint(self) -> str:
        if not self.base_url:
            raise ValueError("Admin API base URL is required.")
        return urljoin(f"{self.base_url.rstrip('/')}/", self.import_path.lstrip("/"))

    def build_record(
        self,
        normalized_data: dict[str, Any],
        raw_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_data = raw_data or {}
        record = {
            "record_number": _coalesce(
                normalized_data.get("record_number"),
                normalized_data.get("permit_number"),
                normalized_data.get("case_number"),
                raw_data.get("record_number"),
                raw_data.get("CaseNumber"),
                raw_data.get("PermitNumber"),
                raw_data.get("RecordNumber"),
            ),
            "permit_type": _coalesce(
                normalized_data.get("permit_type"),
                raw_data.get("permit_type"),
                raw_data.get("record_type"),
                normalized_data.get("record_type"),
                raw_data.get("CaseType"),
                raw_data.get("PermitType"),
                raw_data.get("PermitTypeName"),
            ),
            "address": _coalesce(
                normalized_data.get("address"),
                raw_data.get("address"),
                raw_data.get("AddressDisplay"),
                raw_data.get("FullAddress"),
                raw_data.get("SiteAddress"),
                raw_data.get("LocationAddress"),
                raw_data.get("Address", {}).get("FullAddress")
                if isinstance(raw_data.get("Address"), dict)
                else None,
            ),
            "status": _coalesce(
                normalized_data.get("status"),
                raw_data.get("status"),
                raw_data.get("CaseStatus"),
                raw_data.get("Status"),
            ),
            "date": _coalesce(
                normalized_data.get("date"),
                normalized_data.get("issue_date"),
                normalized_data.get("issued_date"),
                raw_data.get("date"),
                raw_data.get("issue_date"),
                raw_data.get("issued_date"),
                raw_data.get("IssueDate"),
                raw_data.get("IssuedDate"),
                normalized_data.get("apply_date"),
                normalized_data.get("applied_date"),
                raw_data.get("apply_date"),
                raw_data.get("applied_date"),
                raw_data.get("ApplyDate"),
                raw_data.get("AppliedDate"),
            ),
            "expiration_date": _coalesce(
                normalized_data.get("expiration_date"),
                raw_data.get("expiration_date"),
                raw_data.get("ExpireDate"),
                raw_data.get("ExpirationDate"),
            ),
            "description": _coalesce(
                normalized_data.get("description"),
                raw_data.get("description"),
                raw_data.get("project_name"),
                raw_data.get("ProjectName"),
                raw_data.get("Description"),
            ),
            "raw": raw_data or dict(normalized_data),
        }
        return {key: value for key, value in record.items() if value is not None}

    def build_payload(
        self,
        *,
        state: str,
        county: str,
        records: list[dict[str, Any]],
        provider: str = "accela",
        fips: str | None = None,
        agency: str | None = None,
        module: str | None = None,
        source_url: str | None = None,
        import_run_id: str | None = None,
        exclude_tmp: bool | None = None,
        only_issued_active: bool | None = None,
        exclude_statuses: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "provider": provider,
            "state": state,
            "county": county,
            "fips": _strip_or_none(fips),
            "agency": _strip_or_none(agency),
            "module": _strip_or_none(module),
            "source_url": _strip_or_none(source_url),
            "import_run_id": import_run_id or _utc_import_run_id(),
            "exclude_tmp": self.exclude_tmp if exclude_tmp is None else exclude_tmp,
            "only_issued_active": only_issued_active,
            "exclude_statuses": self.exclude_statuses if exclude_statuses is None else exclude_statuses,
            "records": records,
        }
        return {key: value for key, value in payload.items() if value is not None}

    def build_payload_from_mongo_batch(
        self,
        batch_document: dict[str, Any],
        *,
        provider: str | None = None,
        fips: str | None = None,
        import_run_id: str | None = None,
        exclude_tmp: bool | None = None,
        only_issued_active: bool | None = None,
        exclude_statuses: list[str] | None = None,
    ) -> dict[str, Any]:
        raw_items = batch_document.get("raw_items") or []
        records = [self.build_record(item, raw_data=item) for item in raw_items]
        return self.build_payload(
            provider=provider or batch_document.get("adapter_name") or "accela",
            state=batch_document.get("state_name") or "",
            county=batch_document.get("county_name") or "",
            fips=fips,
            agency=batch_document.get("agency_key"),
            module=batch_document.get("module_name"),
            source_url=batch_document.get("source_url"),
            import_run_id=import_run_id,
            exclude_tmp=exclude_tmp,
            only_issued_active=only_issued_active,
            exclude_statuses=exclude_statuses,
            records=records,
        )

    def build_payload_from_permit_documents(
        self,
        permit_documents: list[dict[str, Any]],
        *,
        state: str | None = None,
        county: str | None = None,
        provider: str | None = None,
        fips: str | None = None,
        agency: str | None = None,
        module: str | None = None,
        source_url: str | None = None,
        import_run_id: str | None = None,
        exclude_tmp: bool | None = None,
        only_issued_active: bool | None = None,
        exclude_statuses: list[str] | None = None,
    ) -> dict[str, Any]:
        if not permit_documents:
            raise ValueError("At least one permit document is required to build the import payload.")

        first_document = permit_documents[0]
        records = [
            self.build_record(
                permit_document.get("normalized_data") or {},
                raw_data=permit_document.get("raw_data") or permit_document.get("raw"),
            )
            for permit_document in permit_documents
        ]
        return self.build_payload(
            provider=provider or first_document.get("adapter_name") or "accela",
            state=state or first_document.get("state_name") or "",
            county=county or first_document.get("county_name") or "",
            fips=fips,
            agency=agency or first_document.get("agency_key"),
            module=module or first_document.get("module_name"),
            source_url=source_url or first_document.get("source_url"),
            import_run_id=import_run_id,
            exclude_tmp=exclude_tmp,
            only_issued_active=only_issued_active,
            exclude_statuses=exclude_statuses,
            records=records,
        )

    def push_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "Authorization" not in self.session.headers:
            raise ValueError("Admin API token is required before pushing payloads.")

        response = self.session.post(
            self.endpoint,
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        logger.info(
            "Pushed %s permit records to %s",
            len(payload.get("records", [])),
            self.endpoint,
        )
        if not response.content:
            logger.info("Admin API response body: {}")
            return {}
        response_data = response.json()
        logger.info("Admin API response body: %s", response_data)
        return response_data
