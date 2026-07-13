from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from admin_import import AdminPermitImportClient
from db.mongo_client import MongoStore


TRACKING_COLLECTION = "already_pushed"
ACCELA_AGENCY_STATE_OVERRIDES = {
    "COOPER_CITY": "FL",
}
API_RECORD_FIELDS = (
    "record_number",
    "permit_type",
    "address",
    "status",
    "date",
    "expiration_date",
    "description",
)
API_TOP_LEVEL_FIELDS = (
    "state",
    "county",
    "provider",
    "source_url",
    "fips",
    "exclude_tmp",
    "only_issued_active",
    "exclude_statuses",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read permit documents from MongoDB and import them through the admin API."
    )
    parser.add_argument("--permit-id", help="Specific permits document _id to import.")
    parser.add_argument("--source-url", help="Filter permit documents by source_url.")
    parser.add_argument("--state", help="Filter permit documents by state_name.")
    parser.add_argument("--county", help="Filter permit documents by county_name.")
    parser.add_argument("--agency", help="Filter permit documents by agency_key.")
    parser.add_argument("--module", help="Filter permit documents by module_name.")
    parser.add_argument("--adapter-name", help="Filter permit documents by adapter_name.")
    parser.add_argument("--provider", help="Override payload provider.")
    parser.add_argument("--fips", help="Attach a FIPS code to the payload.")
    parser.add_argument(
        "--only-issued-active",
        action="store_true",
        help="Keep only records whose normalized status is Active or Complete.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="How many matching permit documents to process, newest first. Defaults to all matches.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print payload details without posting to the admin API.",
    )
    parser.add_argument(
        "--print-payload",
        action="store_true",
        help="Print the full payload JSON for each processed batch.",
    )
    return parser.parse_args()


def build_query(args: argparse.Namespace) -> dict[str, Any]:
    query: dict[str, Any] = {}
    field_map = {
        "source_url": "source_url",
        "state": "state_name",
        "county": "county_name",
        "agency": "agency_key",
        "module": "module_name",
        "adapter_name": "adapter_name",
    }
    for arg_name, mongo_field in field_map.items():
        value = getattr(args, arg_name)
        if value:
            query[mongo_field] = value

    if args.permit_id:
        try:
            query["_id"] = ObjectId(args.permit_id)
        except InvalidId as exc:
            raise ValueError(f"Invalid permit id: {args.permit_id}") from exc

    return query


def fetch_permits(store: MongoStore, query: dict[str, Any], limit: int | None) -> list[dict[str, Any]]:
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be greater than 0.")

    cursor = store._collection("permits").find(query).sort("crawl_timestamp", -1)
    if limit is not None:
        cursor = cursor.limit(limit)
    return list(cursor)


def resolve_state_name(permit_document: dict[str, Any], cli_state: str | None = None) -> str | None:
    if cli_state:
        return cli_state

    state_name = permit_document.get("state_name")
    if state_name:
        return state_name

    if permit_document.get("adapter_name") == "accela":
        return ACCELA_AGENCY_STATE_OVERRIDES.get(permit_document.get("agency_key"))

    return None


def apply_state_overrides(permit_documents: list[dict[str, Any]], cli_state: str | None = None) -> list[dict[str, Any]]:
    hydrated_documents: list[dict[str, Any]] = []
    for permit_document in permit_documents:
        effective_state = resolve_state_name(permit_document, cli_state=cli_state)
        if effective_state == permit_document.get("state_name"):
            hydrated_documents.append(permit_document)
            continue

        hydrated_documents.append(
            {
                **permit_document,
                "state_name": effective_state,
            }
        )
    return hydrated_documents


def build_identity_filter(
    permit_document: dict[str, Any],
    payload_record: dict[str, Any],
    payload_metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "provider": payload_metadata.get("provider"),
        "state": payload_metadata.get("state"),
        "county": payload_metadata.get("county"),
        "agency": payload_metadata.get("agency"),
        "module": payload_metadata.get("module"),
        "source_url": payload_metadata.get("source_url"),
        "record_number": payload_record.get("record_number"),
        "permit_type": payload_record.get("permit_type"),
        "address": payload_record.get("address"),
        "date": payload_record.get("date"),
    }


def build_payload_hash(payload_record: dict[str, Any], payload_metadata: dict[str, Any]) -> str:
    serialized = json.dumps(
        {
            "metadata": payload_metadata,
            "record": payload_record,
        },
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_api_payload(full_payload: dict[str, Any]) -> dict[str, Any]:
    records = [
        {
            key: value
            for key, value in record.items()
            if key in API_RECORD_FIELDS and value is not None
        }
        for record in full_payload.get("records", [])
    ]
    payload = {
        key: full_payload.get(key)
        for key in API_TOP_LEVEL_FIELDS
        if full_payload.get(key) is not None
    }
    payload["records"] = records
    return payload


def build_payload_metadata(
    client: AdminPermitImportClient,
    permit_document: dict[str, Any],
    *,
    provider: str | None,
    fips: str | None,
    only_issued_active: bool,
) -> dict[str, Any]:
    payload = client.build_payload_from_permit_documents(
        [permit_document],
        provider=provider,
        fips=fips,
        only_issued_active=only_issued_active,
    )
    return {
        "provider": payload.get("provider"),
        "state": payload.get("state"),
        "county": payload.get("county"),
        "fips": payload.get("fips"),
        "agency": payload.get("agency"),
        "module": payload.get("module"),
        "source_url": payload.get("source_url"),
        "exclude_tmp": payload.get("exclude_tmp"),
        "only_issued_active": payload.get("only_issued_active"),
        "exclude_statuses": payload.get("exclude_statuses"),
    }


def split_permits_for_push(
    permit_documents: list[dict[str, Any]],
    client: AdminPermitImportClient,
    store: MongoStore,
    *,
    provider: str | None,
    fips: str | None,
    only_issued_active: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    permits_to_push: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for permit_document in permit_documents:
        payload_metadata = build_payload_metadata(
            client,
            permit_document,
            provider=provider,
            fips=fips,
            only_issued_active=only_issued_active,
        )
        payload_record = client.build_record(
            permit_document.get("normalized_data") or {},
            raw_data=permit_document.get("raw_data"),
        )
        identity_filter = build_identity_filter(permit_document, payload_record, payload_metadata)
        payload_hash = build_payload_hash(payload_record, payload_metadata)
        existing = store.find_already_pushed(payload_hash, identity_filter)

        if existing:
            skipped.append(
                {
                    "permit_id": str(permit_document.get("_id")),
                    "payload_hash": payload_hash,
                    "reason": "already-pushed",
                    "matched_by": "payload_hash" if existing.get("payload_hash") == payload_hash else "identity_filter",
                }
            )
            continue

        permits_to_push.append(permit_document)

    return permits_to_push, skipped


def summarize_payload(permit_documents: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    first_document = permit_documents[0]
    return {
        "permit_ids": [str(document.get("_id")) for document in permit_documents],
        "adapter_name": first_document.get("adapter_name"),
        "state": payload.get("state"),
        "county": payload.get("county"),
        "agency": payload.get("agency"),
        "module": payload.get("module"),
        "source_url": payload.get("source_url"),
        "record_count": len(payload.get("records", [])),
        "import_run_id": payload.get("import_run_id"),
    }


def persist_push_tracking(
    store: MongoStore,
    client: AdminPermitImportClient,
    permit_documents: list[dict[str, Any]],
    payload: dict[str, Any],
    response: dict[str, Any],
) -> None:
    payload_metadata = {
        "provider": payload.get("provider"),
        "state": payload.get("state"),
        "county": payload.get("county"),
        "fips": payload.get("fips"),
        "agency": payload.get("agency"),
        "module": payload.get("module"),
        "source_url": payload.get("source_url"),
        "exclude_tmp": payload.get("exclude_tmp"),
        "exclude_statuses": payload.get("exclude_statuses"),
        "import_run_id": payload.get("import_run_id"),
        "tracking_collection": TRACKING_COLLECTION,
    }

    for permit_document, payload_record in zip(permit_documents, payload.get("records", []), strict=False):
        identity_filter = build_identity_filter(permit_document, payload_record, payload_metadata)
        payload_hash = build_payload_hash(payload_record, payload_metadata)
        store.save_already_pushed(
            permit_id=permit_document.get("_id"),
            payload_hash=payload_hash,
            identity_filter=identity_filter,
            payload_record=payload_record,
            payload_metadata=payload_metadata,
            api_response=response,
        )


def run_import(args: argparse.Namespace, store: MongoStore | None = None) -> list[dict[str, Any]]:
    store = store or MongoStore()
    client = AdminPermitImportClient()
    query = build_query(args)
    permit_documents = apply_state_overrides(fetch_permits(store, query, args.limit), cli_state=args.state)

    if not permit_documents:
        raise ValueError(f"No permits documents matched query: {query}")

    permits_to_push, skipped = split_permits_for_push(
        permit_documents,
        client,
        store,
        provider=args.provider,
        fips=args.fips,
        only_issued_active=args.only_issued_active,
    )
    if not permits_to_push:
        return [
            {
                "mode": "skip",
                "summary": {
                    "permit_ids": [str(document.get("_id")) for document in permit_documents],
                    "skipped_count": len(skipped),
                    "tracking_collection": TRACKING_COLLECTION,
                },
                "skipped": skipped,
            }
        ]

    full_payload = client.build_payload_from_permit_documents(
        permits_to_push,
        provider=args.provider,
        fips=args.fips,
        only_issued_active=args.only_issued_active,
    )
    payload = build_api_payload(full_payload)
    summary = summarize_payload(permits_to_push, full_payload)
    summary["skipped_count"] = len(skipped)
    summary["tracking_collection"] = TRACKING_COLLECTION

    if args.print_payload or args.dry_run:
        print(json.dumps(payload, indent=2, default=str))

    if args.dry_run:
        return [
            {
                "mode": "dry-run",
                "summary": summary,
                "skipped": skipped,
            }
        ]

    response = client.push_payload(payload)
    persist_push_tracking(store, client, permits_to_push, full_payload, response)
    return [
        {
            "mode": "push",
            "summary": summary,
            "response": response,
            "skipped": skipped,
        }
    ]


def main() -> int:
    args = parse_args()
    try:
        results = run_import(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    for result in results:
        print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# cd /home/sourabh/CrawlPy/scraper_framework
# python scraper_framework/adapters/accela/mongo_admin_import.py --agency COOPER_CITY --module Building --dry-run
# python scraper_framework/adapters/accela/mongo_admin_import.py --agency COOPER_CITY --module Building

# python scraper_framework/adapters/accela/mongo_admin_import.py --permit-id 6a4fb949f5eebd00afb24b99 --dry-run # for specific permit id


# cd /home/sourabh/CrawlPy/scraper_framework
# python scraper_framework/adapters/accela/mongo_admin_import.py --agency COOPER_CITY --module Building --dry-run