from __future__ import annotations

import argparse
from pathlib import Path

from .constants import DEFAULT_BASE_URL, DEFAULT_COUNTY_NAME, DEFAULT_MODULE_NAME, DEFAULT_STATE_NAME
from .service import TylerEnerGovCountyImporter
from ...utils.logger import get_logger

PAYLOAD_PATH = Path(__file__).resolve().with_name("payload.json")
logger = get_logger("tyler_energov_import_cli")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import Tyler EnerGov JSON search results into MongoDB.")
    parser.add_argument("--state-name", default=DEFAULT_STATE_NAME, help="State name stored in Mongo.")
    parser.add_argument("--page-size", type=int, default=100, help="Search page size.")
    parser.add_argument("--collection-name", default=None, help="Override the Mongo collection name for county-specific records.")
    parser.add_argument("--agency-key", default=None, help="Optional agency key metadata override.")
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME, help="Module name stored in Mongo.")
    parser.add_argument("--request-timeout-seconds", type=int, default=60, help="HTTP request timeout in seconds.")
    parser.add_argument(
        "--skip-shared-collections",
        action="store_true",
        help="Only write to the county-specific collection and skip permits/raw_permit_batches.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    importer = TylerEnerGovCountyImporter(
        base_url=DEFAULT_BASE_URL,
        county_name=DEFAULT_COUNTY_NAME,
        permit_type_ids=None,
        payload_path=PAYLOAD_PATH,
        state_name=args.state_name,
        page_size=args.page_size,
        collection_name=args.collection_name,
        agency_key=args.agency_key,
        module_name=args.module_name,
        request_timeout_seconds=args.request_timeout_seconds,
        save_shared_collections=not args.skip_shared_collections,
    )
    summary = importer.import_data()
    logger.info(
        "Run finished collection=%s total_records=%s inserted=%s pages=%s",
        summary["collection_name"],
        summary["total_records"],
        summary["inserted_county_records"],
        summary["pages_fetched"],
    )


if __name__ == "__main__":
    main()

# python3 -m scraper_framework.adapters.tyler_energov_import.cli
