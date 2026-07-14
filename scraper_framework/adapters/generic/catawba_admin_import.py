from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from adapters.accela.mongo_admin_import import run_import


CATAWBA_SOURCE_URL = (
    "https://co-catawba-nc.smartgovcommunity.com/"
    "ApplicationPublic/ApplicationSearchAdvanced/Search"
)
CATAWBA_STATE = "North Carolina"
CATAWBA_COUNTY = "Catawba"
CATAWBA_PROVIDER = "smartgovcommunity"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read Catawba permit documents from MongoDB and import them through the admin API."
    )
    parser.add_argument("--permit-id", help="Specific permits document _id to import.")
    parser.add_argument(
        "--source-url",
        default=CATAWBA_SOURCE_URL,
        help="Filter permit documents by source_url.",
    )
    parser.add_argument(
        "--state",
        default=CATAWBA_STATE,
        help="Filter permit documents by state_name.",
    )
    parser.add_argument(
        "--county",
        default=CATAWBA_COUNTY,
        help="Filter permit documents by county_name.",
    )
    parser.add_argument("--agency", help="Filter permit documents by agency_key.")
    parser.add_argument("--module", help="Filter permit documents by module_name.")
    parser.add_argument("--adapter-name", help="Filter permit documents by adapter_name.")
    parser.add_argument(
        "--provider",
        default=CATAWBA_PROVIDER,
        help="Override payload provider.",
    )
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


def main() -> int:
    args = parse_args()
    try:
        results = run_import(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    for result in results:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# cd /home/sourabh/CrawlPy/scraper_framework
# python scraper_framework/adapters/generic/catawba_admin_import.py --dry-run
# python scraper_framework/adapters/generic/catawba_admin_import.py
# python scraper_framework/adapters/generic/catawba_admin_import.py --permit-id 6a4f8eb78c2f5424c57b36c4 --dry-run
