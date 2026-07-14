from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from admin_import import AdminPermitImportClient
from adapters.accela.mongo_admin_import import (
    TRACKING_COLLECTION,
    build_api_payload,
    build_identity_filter,
    build_payload_hash,
)
from db.mongo_client import MongoStore


SPARTANBURG_STATE = "South Carolina"
SPARTANBURG_COUNTY = "Spartanburg County"
SPARTANBURG_PROVIDER = "tyler_energov"
SPARTANBURG_COLLECTION_NAME = "spartanburg_Construction_for_Commercial_Building"
SPARTANBURG_AGENCY = "SPARTANBURG"
SPARTANBURG_MODULE = "Permit"
SPARTANBURG_FIPS = "45083"
CHUNK_SIZE = 100


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read Spartanburg County permit documents from MongoDB "
            "and import them through the admin API."
        )
    )
    parser.add_argument(
        "--collection-name",
        default=SPARTANBURG_COLLECTION_NAME,
        help="MongoDB collection to read Spartanburg permit documents from.",
    )
    parser.add_argument("--permit-id", help="Specific document _id to import.")
    parser.add_argument(
        "--state",
        default=SPARTANBURG_STATE,
        help="State value to attach to the payload.",
    )
    parser.add_argument(
        "--county",
        default=SPARTANBURG_COUNTY,
        help="County value to attach to the payload.",
    )
    parser.add_argument(
        "--provider",
        default=SPARTANBURG_PROVIDER,
        help="Provider value to attach to the payload.",
    )
    parser.add_argument(
        "--agency",
        default=SPARTANBURG_AGENCY,
        help="Agency value to attach to the payload.",
    )
    parser.add_argument(
        "--module",
        default=SPARTANBURG_MODULE,
        help="Module value to attach to the payload.",
    )
    parser.add_argument(
        "--source-url",
        default=None,
        help="Optional source_url value to attach to the payload.",
    )
    parser.add_argument(
        "--fips",
        default=SPARTANBURG_FIPS,
        help="FIPS value to attach to the payload.",
    )
    parser.add_argument(
        "--only-issued-active",
        action="store_true",
        help="Attach only_issued_active=true in the payload.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="How many matching documents to process, newest first. Defaults to all matches.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and print payload details without posting to the admin API.",
    )
    parser.add_argument(
        "--print-payload",
        action="store_true",
        help="Print the full payload JSON for the processed batch.",
    )
    return parser.parse_args()


def build_query(args: argparse.Namespace) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if args.permit_id:
        try:
            query["_id"] = ObjectId(args.permit_id)
        except InvalidId as exc:
            raise ValueError(f"Invalid permit id: {args.permit_id}") from exc
    return query


def fetch_documents(store: MongoStore, collection_name: str, query: dict[str, Any], limit: int | None) -> list[dict[str, Any]]:
    if limit is not None and limit <= 0:
        raise ValueError("--limit must be greater than 0.")

    cursor = store._collection(collection_name).find(query).sort("_id", -1)
    if limit is not None:
        cursor = cursor.limit(limit)
    return list(cursor)


def _pick_first(raw_document: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw_document.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def build_normalized_data(raw_document: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_number": _pick_first(raw_document, "CaseNumber", "Case Number", "PermitNumber", "Permit Number"),
        "permit_type": _pick_first(raw_document, "CaseType", "Type", "PermitType", "Permit Type"),
        "status": _pick_first(raw_document, "CaseStatus", "Status", "PermitStatus", "Permit Status"),
        "date": _pick_first(
            raw_document,
            "IssueDate",
            "Issue Date",
            "ApplyDate",
            "Applied Date",
            "AppliedDate",
        ),
        "expiration_date": _pick_first(
            raw_document,
            "ExpireDate",
            "Expire Date",
            "ExpirationDate",
            "Expiration Date",
        ),
        "description": _pick_first(raw_document, "Description", "ProjectName", "Project Name"),
        "address": _pick_first(raw_document, "AddressDisplay", "FullAddress", "Address"),
        "module": _pick_first(raw_document, "Module Name", "ModuleName"),
    }


def build_permit_document(raw_document: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    normalized_data = build_normalized_data(raw_document)
    return {
        "_id": raw_document.get("_id"),
        "adapter_name": args.provider,
        "state_name": args.state,
        "county_name": args.county,
        "agency_key": args.agency,
        "module_name": normalized_data.get("module") or args.module,
        "source_url": args.source_url,
        "normalized_data": {key: value for key, value in normalized_data.items() if key != "module" and value is not None},
        "raw_data": raw_document,
    }


def chunk_documents(documents: list[dict[str, Any]], size: int = CHUNK_SIZE) -> list[list[dict[str, Any]]]:
    return [documents[index : index + size] for index in range(0, len(documents), size)]


def split_documents_for_push(
    permit_documents: list[dict[str, Any]],
    client: AdminPermitImportClient,
    store: MongoStore,
    *,
    provider: str,
    fips: str | None,
    only_issued_active: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    documents_to_push: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for permit_document in permit_documents:
        full_payload = client.build_payload_from_permit_documents(
            [permit_document],
            state=permit_document.get("state_name"),
            county=permit_document.get("county_name"),
            provider=provider,
            fips=fips,
            agency=permit_document.get("agency_key"),
            module=permit_document.get("module_name"),
            source_url=permit_document.get("source_url"),
            only_issued_active=only_issued_active,
        )
        payload_record = full_payload.get("records", [{}])[0]
        payload_metadata = {
            "provider": full_payload.get("provider"),
            "state": full_payload.get("state"),
            "county": full_payload.get("county"),
            "agency": full_payload.get("agency"),
            "module": full_payload.get("module"),
            "source_url": full_payload.get("source_url"),
        }
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
        documents_to_push.append(permit_document)

    return documents_to_push, skipped


def summarize_payload(
    collection_name: str,
    payload: dict[str, Any],
    permit_documents: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    *,
    chunk_number: int | None = None,
    total_chunks: int | None = None,
) -> dict[str, Any]:
    return {
        "permit_ids": [str(document.get("_id")) for document in permit_documents],
        "collection_name": collection_name,
        "adapter_name": payload.get("provider"),
        "state": payload.get("state"),
        "county": payload.get("county"),
        "agency": payload.get("agency"),
        "module": payload.get("module"),
        "source_url": payload.get("source_url"),
        "record_count": len(payload.get("records", [])),
        "import_run_id": payload.get("import_run_id"),
        "skipped_count": len(skipped),
        "duplicate_found_count": len(skipped),
        "new_pushed_count": len(permit_documents),
        "tracking_collection": TRACKING_COLLECTION,
        "chunk_number": chunk_number,
        "total_chunks": total_chunks,
    }


def persist_push_tracking(
    store: MongoStore,
    permit_documents: list[dict[str, Any]],
    full_payload: dict[str, Any],
    response: dict[str, Any],
) -> None:
    payload_metadata = {
        "provider": full_payload.get("provider"),
        "state": full_payload.get("state"),
        "county": full_payload.get("county"),
        "fips": full_payload.get("fips"),
        "agency": full_payload.get("agency"),
        "module": full_payload.get("module"),
        "source_url": full_payload.get("source_url"),
        "exclude_tmp": full_payload.get("exclude_tmp"),
        "exclude_statuses": full_payload.get("exclude_statuses"),
        "import_run_id": full_payload.get("import_run_id"),
        "tracking_collection": TRACKING_COLLECTION,
    }

    for permit_document, payload_record in zip(permit_documents, full_payload.get("records", []), strict=False):
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
    query = build_query(args)
    raw_documents = fetch_documents(store, args.collection_name, query, args.limit)
    if not raw_documents:
        raise ValueError(
            f"No documents matched query in collection '{args.collection_name}': {query}"
        )

    permit_documents = [build_permit_document(document, args) for document in raw_documents]
    client = AdminPermitImportClient()
    documents_to_push, skipped = split_documents_for_push(
        permit_documents,
        client,
        store,
        provider=args.provider,
        fips=args.fips,
        only_issued_active=args.only_issued_active,
    )

    if not documents_to_push:
        return [
            {
                "mode": "skip",
                "summary": {
                    "permit_ids": [str(document.get("_id")) for document in permit_documents],
                    "collection_name": args.collection_name,
                    "skipped_count": len(skipped),
                    "duplicate_found_count": len(skipped),
                    "new_pushed_count": 0,
                    "tracking_collection": TRACKING_COLLECTION,
                },
                "skipped": skipped,
            }
        ]

    results: list[dict[str, Any]] = []
    document_chunks = chunk_documents(documents_to_push)
    total_chunks = len(document_chunks)

    for chunk_index, document_chunk in enumerate(document_chunks, start=1):
        full_payload = client.build_payload_from_permit_documents(
            document_chunk,
            state=args.state,
            county=args.county,
            provider=args.provider,
            fips=args.fips,
            agency=args.agency,
            module=args.module,
            source_url=args.source_url,
            only_issued_active=args.only_issued_active,
        )
        payload = build_api_payload(full_payload)
        summary = summarize_payload(
            args.collection_name,
            full_payload,
            document_chunk,
            skipped,
            chunk_number=chunk_index,
            total_chunks=total_chunks,
        )

        if args.print_payload or args.dry_run:
            print(json.dumps(payload, indent=2, default=str))

        if args.dry_run:
            results.append(
                {
                    "mode": "dry-run",
                    "summary": summary,
                    "skipped": skipped,
                }
            )
            continue

        response = client.push_payload(payload)
        persist_push_tracking(store, document_chunk, full_payload, response)
        results.append(
            {
                "mode": "push",
                "summary": summary,
                "response": response,
                "skipped": skipped,
            }
        )

    return results


def main() -> int:
    args = parse_args()
    try:
        results = run_import(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    for result in results:
        summary = result.get("summary", {})
        duplicate_count = summary.get("duplicate_found_count", summary.get("skipped_count", 0))
        new_count = summary.get("new_pushed_count", summary.get("record_count", 0))
        print(
            "collection={collection} county={county} duplicate found {duplicates} number new pushed {new_count} data mode={mode}".format(
                collection=summary.get("collection_name", args.collection_name),
                county=summary.get("county", args.county),
                duplicates=duplicate_count,
                new_count=new_count,
                mode=result.get("mode"),
            )
        )
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# cd /home/sourabh/CrawlPy/scraper_framework
# python scraper_framework/adapters/generic/spartanburg_admin_import.py --collection-name spartanburg_Construction_for_Commercial_Building --dry-run --limit 20
# python scraper_framework/adapters/generic/spartanburg_admin_import.py --collection-name spartanburg_Construction_for_Commercial_Building --dry-run --permit-id 67ed290761cc1c388a8adf9b
# python scraper_framework/adapters/generic/spartanburg_admin_import.py --collection-name spartanburg_Construction_for_Commercial_Building --print-payload --dry-run --limit 5
# python scraper_framework/adapters/generic/spartanburg_admin_import.py --collection-name spartanburg_Construction_for_Commercial_Building --limit 20
# python scraper_framework/adapters/generic/spartanburg_admin_import.py --collection-name spartanburg_single_family --dry-run --limit 20
# python scraper_framework/adapters/generic/spartanburg_admin_import.py --collection-name spartanburg_Construction_for_Commercial_Building --dry-run --limit 20
