from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

from pymongo import MongoClient
from pymongo.collection import Collection

from config.settings import (
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

    def create_run(
        self,
        source_url: str,
        adapter_name: str,
        county_name: str | None = None,
        state_name: str | None = None,
        agency_key: str | None = None,
        module_name: str | None = None,
    ) -> Any:
        payload = {
            "source_url": source_url,
            "adapter_name": adapter_name,
            "county_name": county_name,
            "state_name": state_name,
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
        county_name: str | None = None,
        state_name: str | None = None,
        agency_key: str | None = None,
        module_name: str | None = None,
    ) -> None:
        self._collection("sources").update_one(
            {"source_url": source_url},
            {
                "$set": {
                    "source_url": source_url,
                    "adapter_name": adapter_name,
                    "county_name": county_name,
                    "state_name": state_name,
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
        county_name: str | None,
        state_name: str | None,
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
        county_name: str | None,
        state_name: str | None,
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
        collection.create_index(
            "record_hash",
            unique=True,
            partialFilterExpression={"record_hash": {"$exists": True}},
        )

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
