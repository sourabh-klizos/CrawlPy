from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.cursor import Cursor

try:
    from config.settings import (
        MONGODB_DB,
        MONGODB_HOST,
        MONGODB_PARAMS,
        MONGODB_PASSWORD,
        MONGODB_SRV,
        MONGODB_USERNAME,
    )
except ModuleNotFoundError:
    from scraper_framework.config.settings import (
        MONGODB_DB,
        MONGODB_HOST,
        MONGODB_PARAMS,
        MONGODB_PASSWORD,
        MONGODB_SRV,
        MONGODB_USERNAME,
    )


class MongoStore:
    def __init__(self) -> None:
        self.client = MongoClient(self._build_uri())
        self.db = self.client[MONGODB_DB]
        self._indexed_collections: set[str] = set()

    def _build_uri(self) -> str:
        scheme = "mongodb+srv" if MONGODB_SRV else "mongodb"
        if MONGODB_USERNAME and MONGODB_PASSWORD:
            username = quote_plus(MONGODB_USERNAME)
            password = quote_plus(MONGODB_PASSWORD)
            auth = f"{username}:{password}@"
        else:
            auth = ""

        uri = f"{scheme}://{auth}{MONGODB_HOST}"
        if MONGODB_PARAMS:
            uri = f"{uri}/?{MONGODB_PARAMS}"
        return uri

    def _collection(self, name: str) -> Collection:
        return self.db[name]

    def find_documents(
        self,
        collection_name: str,
        query: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        cursor: Cursor = self._collection(collection_name).find(query or {})
        if sort:
            cursor = cursor.sort(sort)
        if limit is not None and limit > 0:
            cursor = cursor.limit(limit)
        return list(cursor)

    def insert_many_documents(self, collection_name: str, documents: list[dict[str, Any]]) -> int:
        if not documents:
            return 0

        result = self._collection(collection_name).insert_many(documents)
        return len(result.inserted_ids)

    def create_run(
        self,
        source_url: str,
        adapter_name: str,
        state_name: str | None = None,
        county_name: str | None = None,
        agency_key: str | None = None,
        module_name: str | None = None,
    ) -> Any:
        payload = {
            "source_url": source_url,
            "adapter_name": adapter_name,
            "state_name": state_name,
            "county_name": county_name,
            "agency_key": agency_key,
            "module_name": module_name,
            "status": "running",
            "started_at": datetime.now(timezone.utc),
            "finished_at": None,
            "error": None,
        }
        result = self._collection("crawl_runs").insert_one(payload)
        return result.inserted_id

    def complete_run(self, run_id: Any, status: str, error: str | None = None) -> None:
        self._collection("crawl_runs").update_one(
            {"_id": run_id},
            {
                "$set": {
                    "status": status,
                    "finished_at": datetime.now(timezone.utc),
                    "error": error,
                }
            },
        )

    def log(self, run_id: Any, level: str, message: str, context: dict[str, Any] | None = None) -> None:
        self._collection("crawl_logs").insert_one(
            {
                "run_id": run_id,
                "level": level,
                "message": message,
                "context": context or {},
                "timestamp": datetime.now(timezone.utc),
            }
        )

    def save_source(
        self,
        source_url: str,
        adapter_name: str,
        state_name: str | None = None,
        county_name: str | None = None,
        agency_key: str | None = None,
        module_name: str | None = None,
    ) -> None:
        self._collection("sources").update_one(
            {"source_url": source_url},
            {
                "$set": {
                    "source_url": source_url,
                    "adapter_name": adapter_name,
                    "state_name": state_name,
                    "county_name": county_name,
                    "agency_key": agency_key,
                    "module_name": module_name,
                    "updated_at": datetime.now(timezone.utc),
                },
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )

    def save_permit(
        self,
        state_name: str | None,
        county_name: str | None,
        agency_key: str | None,
        module_name: str | None,
        source_url: str,
        adapter_name: str,
        normalized_data: dict[str, Any],
        raw_data: dict[str, Any],
        crawl_status: str,
    ) -> None:
        collection = self._collection("permits")
        self._ensure_hash_index(collection)
        now = datetime.now(timezone.utc)
        record_hash = self._record_hash(source_url, adapter_name, normalized_data, raw_data)
        collection.update_one(
            {"record_hash": record_hash},
            {
                "$set": {
                    "county_name": county_name,
                    "state_name": state_name,
                    "agency_key": agency_key,
                    "module_name": module_name,
                    "source_url": source_url,
                    "adapter_name": adapter_name,
                    "normalized_data": normalized_data,
                    "raw_data": raw_data,
                    "crawl_status": crawl_status,
                    "record_hash": record_hash,
                    "content_hash": self._content_hash(normalized_data, raw_data),
                    "updated_at": now,
                },
                "$setOnInsert": {"crawl_timestamp": now},
            },
            upsert=True,
        )

    def save_resource_permit(
        self,
        state_name: str | None,
        county_name: str | None,
        resource_name: str,
        source_url: str,
        normalized_data: dict[str, Any],
        raw_data: dict[str, Any],
        crawl_status: str,
    ) -> None:
        collection_name = self._resource_collection_name(state_name, resource_name)
        collection = self._collection(collection_name)
        self._ensure_hash_index(collection)
        now = datetime.now(timezone.utc)
        record_hash = self._record_hash(source_url, resource_name, normalized_data, raw_data)
        collection.update_one(
            {"record_hash": record_hash},
            {
                "$set": {
                    "source_url": source_url,
                    "state_name": state_name,
                    "county_name": county_name,
                    "normalized_data": normalized_data,
                    "raw_data": raw_data,
                    "crawl_status": crawl_status,
                    "record_hash": record_hash,
                    "content_hash": self._content_hash(normalized_data, raw_data),
                    "updated_at": now,
                },
                "$setOnInsert": {"crawl_timestamp": now},
            },
            upsert=True,
        )

    def save_raw_result_batch(
        self,
        state_name: str | None,
        county_name: str | None,
        agency_key: str | None,
        module_name: str | None,
        source_url: str,
        adapter_name: str,
        raw_items: list[dict[str, Any]],
    ) -> None:
        collection = self._collection("raw_permit_batches")
        self._ensure_hash_index(collection)
        now = datetime.now(timezone.utc)
        batch_hash = self._hash_payload(
            {
                "state_name": state_name,
                "county_name": county_name,
                "agency_key": agency_key,
                "module_name": module_name,
                "source_url": source_url,
                "adapter_name": adapter_name,
                "raw_items": raw_items,
            }
        )
        collection.update_one(
            {"record_hash": batch_hash},
            {
                "$set": {
                    "county_name": county_name,
                    "state_name": state_name,
                    "agency_key": agency_key,
                    "module_name": module_name,
                    "source_url": source_url,
                    "adapter_name": adapter_name,
                    "record_count": len(raw_items),
                    "raw_items": raw_items,
                    "record_hash": batch_hash,
                    "content_hash": batch_hash,
                    "updated_at": now,
                },
                "$setOnInsert": {"crawl_timestamp": now},
            },
            upsert=True,
        )

    def _resource_collection_name(self, state_name: str | None, resource_name: str) -> str:
        state_part = self._slug(state_name or "unknown_state")
        resource_part = self._slug(resource_name)
        return f"{state_part}_{resource_part}"

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
        return slug or "unknown"

    def _ensure_hash_index(self, collection: Collection) -> None:
        if collection.name in self._indexed_collections:
            return
        collection.create_index(
            "record_hash",
            unique=True,
            partialFilterExpression={"record_hash": {"$exists": True}},
        )
        self._indexed_collections.add(collection.name)

    def _record_hash(
        self,
        source_url: str,
        adapter_name: str,
        normalized_data: dict[str, Any],
        raw_data: dict[str, Any],
    ) -> str:
        record_number = normalized_data.get("record_number") or raw_data.get("record_number")
        application_type = raw_data.get("application_type")
        detail_link = raw_data.get("detail_link")
        identity = {
            "source_url": source_url,
            "adapter_name": adapter_name,
            "record_number": record_number,
            "application_type": application_type,
            "detail_link": detail_link,
        }
        if not record_number and not detail_link:
            identity["normalized_data"] = normalized_data
            identity["raw_data"] = raw_data
        return self._hash_payload(identity)

    def _content_hash(self, normalized_data: dict[str, Any], raw_data: dict[str, Any]) -> str:
        return self._hash_payload(
            {
                "normalized_data": normalized_data,
                "raw_data": raw_data,
            }
        )

    def _hash_payload(self, payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


    def find_already_pushed(
        self,
        payload_hash: str,
        identity_filter: dict[str, Any],
    ) -> dict[str, Any] | None:
        identity_query = {f"identity_filter.{key}": value for key, value in identity_filter.items()}
        return self._collection("already_pushed").find_one(
            {
                "$or": [
                    {"payload_hash": payload_hash},
                    identity_query,
                ]
            }
        )

    def save_already_pushed(
        self,
        *,
        permit_id: Any,
        payload_hash: str,
        identity_filter: dict[str, Any],
        payload_record: dict[str, Any],
        payload_metadata: dict[str, Any],
        api_response: dict[str, Any],
    ) -> None:
        self._collection("already_pushed").update_one(
            {"permit_id": permit_id},
            {
                "$set": {
                    "permit_id": permit_id,
                    "payload_hash": payload_hash,
                    "identity_filter": identity_filter,
                    "payload_record": payload_record,
                    "payload_metadata": payload_metadata,
                    "api_response": api_response,
                    "updated_at": datetime.now(timezone.utc),
                },
                "$setOnInsert": {
                    "created_at": datetime.now(timezone.utc),
                },
            },
            upsert=True,
        )
