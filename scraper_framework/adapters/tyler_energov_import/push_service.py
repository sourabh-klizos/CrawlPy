from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from ...admin_import import AdminPermitImportClient
from ...db.mongo_client import MongoStore
from ...utils.logger import get_logger
from .constants import DEFAULT_BASE_URL, DEFAULT_COUNTY_NAME, DEFAULT_MODULE_NAME, DEFAULT_STATE_NAME
from .helpers import build_county_collection_name, slugify

logger = get_logger("tyler_energov_push")


@dataclass(slots=True)
class TylerEnerGovPushService:
    county_name: str = DEFAULT_COUNTY_NAME
    state_name: str = DEFAULT_STATE_NAME
    module_name: str = DEFAULT_MODULE_NAME
    base_url: str = DEFAULT_BASE_URL
    collection_name: str | None = None
    agency_key: str | None = None
    limit: int | None = None
    fips: str | None = None
    store: MongoStore = field(default_factory=MongoStore, repr=False)
    admin_client: AdminPermitImportClient = field(default_factory=AdminPermitImportClient, repr=False)
    source_url: str = field(init=False)

    def __post_init__(self) -> None:
        self.collection_name = self.collection_name or build_county_collection_name(
            county_name=self.county_name,
            state_name=self.state_name,
        )
        self.agency_key = self.agency_key or slugify(self.county_name).upper()
        self.source_url = f"{self.base_url.rstrip('/')}/apps/SelfService"

    def load_documents(self) -> list[dict[str, Any]]:
        return self.store.find_documents(
            self.collection_name,
            sort=[("imported_at", 1)],
            limit=self.limit,
        )

    def build_payload(self) -> dict[str, Any]:
        documents = self.load_documents()
        return self.admin_client.build_payload_from_permit_documents(
            provider="tyler_energov",
            state=self.state_name,
            county=self.county_name,
            agency=self.agency_key,
            module=self.module_name,
            source_url=self.source_url,
            permit_documents=documents,
            fips=self.fips,
        )

    def run(self, execute: bool = False) -> dict[str, Any]:
        payload = self.build_payload()
        record_count = len(payload["records"])
        logger.info(
            "Prepared admin import payload for county=%s collection=%s records=%s mode=%s",
            self.county_name,
            self.collection_name,
            record_count,
            "EXECUTE" if execute else "DRY RUN",
        )
        if payload["records"]:
            sample = payload["records"][0]
            logger.info(
                "Sample record record_number=%s status=%s address=%s",
                sample.get("record_number"),
                sample.get("status"),
                sample.get("address"),
            )
            logger.info(
                "First record payload preview:\n%s",
                json.dumps(sample, indent=2, default=str),
            )

        payload_preview = {
            key: value
            for key, value in payload.items()
            if key != "records"
        }
        payload_preview["records_count"] = record_count
        logger.info(
            "Top-level payload preview:\n%s",
            json.dumps(payload_preview, indent=2, default=str),
        )

        if not execute:
            return {"mode": "dry_run", "payload": payload}

        response = self.admin_client.push_payload(payload)
        logger.info("Push complete for county=%s records=%s", self.county_name, record_count)
        return {"mode": "execute", "payload": payload, "response": response}
