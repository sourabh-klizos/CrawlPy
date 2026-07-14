from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...db.mongo_client import MongoStore
from ...utils.logger import get_logger

from .client import TylerEnerGovSearchClient
from .constants import DEFAULT_MODULE_NAME, DEFAULT_STATE_NAME, PERMIT_TYPE_IDS
from .helpers import build_county_collection_name, slugify
from .repository import TylerEnerGovImportRepository

logger = get_logger("tyler_energov_import")


@dataclass(slots=True)
class TylerEnerGovCountyImporter:
    base_url: str
    county_name: str
    permit_type_ids: list[str] | None
    payload_path: Path
    state_name: str = DEFAULT_STATE_NAME
    page_size: int = 100
    collection_name: str | None = None
    agency_key: str | None = None
    module_name: str = DEFAULT_MODULE_NAME
    request_timeout_seconds: int = 60
    save_shared_collections: bool = True
    client: TylerEnerGovSearchClient = field(init=False, repr=False)
    store: MongoStore = field(init=False, repr=False)
    repository: TylerEnerGovImportRepository = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.permit_type_ids = self.permit_type_ids or list(PERMIT_TYPE_IDS)
        if not self.permit_type_ids:
            raise ValueError("PERMIT_TYPE_IDS is empty. Add at least one permit type in constants.py.")

        self.collection_name = self.collection_name or build_county_collection_name(
            county_name=self.county_name,
            state_name=self.state_name,
        )
        self.agency_key = self.agency_key or slugify(self.county_name).upper()

        self.client = TylerEnerGovSearchClient(
            base_url=self.base_url,
            payload_path=self.payload_path,
            request_timeout_seconds=self.request_timeout_seconds,
        )
        self.store = MongoStore()
        self.repository = TylerEnerGovImportRepository(
            store=self.store,
            state_name=self.state_name,
            county_name=self.county_name,
            agency_key=self.agency_key,
            module_name=self.module_name,
            source_url=self.client.source_url,
            collection_name=self.collection_name,
            save_shared_collections=self.save_shared_collections,
        )

    def extract_records(self, response_json: dict[str, Any]) -> list[dict[str, Any]]:
        result_payload = response_json.get("Result")
        records = []
        if isinstance(result_payload, dict):
            records = result_payload.get("EntityResults") or []

        if not records:
            records = (
                response_json.get("SearchResults")
                or response_json.get("Results")
                or response_json.get("Items")
                or []
            )
        return [record for record in records if isinstance(record, dict)]

    def import_data(self) -> dict[str, int | str]:
        total_records = 0
        inserted_county_records = 0
        page_count = 0

        logger.info(
            "Starting Tyler EnerGov import for county=%s collection=%s permit_types=%s payload=%s",
            self.county_name,
            self.collection_name,
            ",".join(self.permit_type_ids),
            self.payload_path,
        )

        for permit_type_id in self.permit_type_ids:
            page = 1
            permit_type_records = 0

            while True:
                result = self.client.search_permit_type(
                    permit_type_id=permit_type_id,
                    page=page,
                    page_size=self.page_size,
                )
                records = self.extract_records(result)
                if not records:
                    if page == 1:
                        logger.info("No records found for permit_type=%s", permit_type_id)
                    else:
                        logger.info("Finished permit_type=%s after %s pages", permit_type_id, page_count)
                    break

                logger.info(
                    "Fetched %s records for permit_type=%s page=%s",
                    len(records),
                    permit_type_id,
                    page,
                )
                inserted_county_records += self.repository.save_page(
                    permit_type_id=permit_type_id,
                    page=page,
                    records=records,
                )
                total_records += len(records)
                permit_type_records += len(records)
                page_count += 1

                if len(records) < self.page_size:
                    logger.info(
                        "Completed permit_type=%s with %s records across %s pages",
                        permit_type_id,
                        permit_type_records,
                        page,
                    )
                    break
                page += 1

        summary = {
            "collection_name": self.collection_name,
            "total_records": total_records,
            "inserted_county_records": inserted_county_records,
            "pages_fetched": page_count,
        }
        logger.info(
            "Import complete collection=%s total_records=%s inserted=%s pages=%s",
            summary["collection_name"],
            summary["total_records"],
            summary["inserted_county_records"],
            summary["pages_fetched"],
        )
        return summary
