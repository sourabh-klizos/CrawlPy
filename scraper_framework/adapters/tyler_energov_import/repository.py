from __future__ import annotations

from datetime import datetime, timezone

from ...db.mongo_client import MongoStore
from ..tyler_energov.constants import ADAPTER_NAME

from .helpers import build_normalized_record


class TylerEnerGovImportRepository:
    def __init__(
        self,
        store: MongoStore,
        state_name: str,
        county_name: str,
        agency_key: str,
        module_name: str,
        source_url: str,
        collection_name: str,
        save_shared_collections: bool = True,
    ) -> None:
        self.store = store
        self.state_name = state_name
        self.county_name = county_name
        self.agency_key = agency_key
        self.module_name = module_name
        self.source_url = source_url
        self.collection_name = collection_name
        self.save_shared_collections = save_shared_collections

    def build_county_documents(
        self,
        permit_type_id: str,
        page: int,
        records: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        timestamp = datetime.now(timezone.utc)
        documents: list[dict[str, object]] = []

        for record in records:
            documents.append(
                {
                    "state_name": self.state_name,
                    "county_name": self.county_name,
                    "agency_key": self.agency_key,
                    "module_name": self.module_name,
                    "source_url": self.source_url,
                    "adapter_name": ADAPTER_NAME,
                    "permit_type_id": permit_type_id,
                    "page_number": page,
                    "imported_at": timestamp,
                    "normalized_data": build_normalized_record(record, permit_type_id),
                    "raw_data": record,
                }
            )
        return documents

    def save_page(self, permit_type_id: str, page: int, records: list[dict[str, object]]) -> int:
        county_documents = self.build_county_documents(permit_type_id, page, records)
        inserted_count = self.store.insert_many_documents(self.collection_name, county_documents)

        if self.save_shared_collections:
            self.store.save_raw_result_batch(
                state_name=self.state_name,
                county_name=self.county_name,
                agency_key=self.agency_key,
                module_name=self.module_name,
                source_url=self.source_url,
                adapter_name=ADAPTER_NAME,
                raw_items=records,
            )
            for record in records:
                self.store.save_permit(
                    state_name=self.state_name,
                    county_name=self.county_name,
                    agency_key=self.agency_key,
                    module_name=self.module_name,
                    source_url=self.source_url,
                    adapter_name=ADAPTER_NAME,
                    normalized_data=build_normalized_record(record, permit_type_id),
                    raw_data=record,
                    crawl_status="success",
                )

        return inserted_count
