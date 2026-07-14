from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from adapters.accela.mongo_admin_import import run_import


ALEXANDER_SOURCE_URL = (
    "https://co-alexander-nc.smartgovcommunity.com/"
    "ApplicationPublic/ApplicationSearchAdvanced/Search"
)
ALEXANDER_STATE = "North Carolina"
ALEXANDER_COUNTY = "Alexander"
ALEXANDER_PROVIDER = "smartgovcommunity"
ALEXANDER_COLLECTION_NAME = "north_carolina_smartgov"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read Alexander permit documents from MongoDB and import them through the admin API."
    )
    parser.add_argument(
        "--collection-name",
        default=ALEXANDER_COLLECTION_NAME,
        help="MongoDB collection to read SmartGov permit documents from.",
    )
    parser.add_argument("--permit-id", help="Specific permits document _id to import.")
    parser.add_argument(
        "--source-url",
        default=None,
        help="Filter permit documents by source_url.",
    )
    parser.add_argument(
        "--state",
        default=ALEXANDER_STATE,
        help="Filter permit documents by state_name.",
    )
    parser.add_argument(
        "--county",
        default=ALEXANDER_COUNTY,
        help="Filter permit documents by county_name.",
    )
    parser.add_argument("--agency", help="Filter permit documents by agency_key.")
    parser.add_argument("--module", help="Filter permit documents by module_name.")
    parser.add_argument("--adapter-name", help="Filter permit documents by adapter_name.")
    parser.add_argument(
        "--provider",
        default=ALEXANDER_PROVIDER,
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
# python scraper_framework/adapters/generic/alexander_admin_import.py --dry-run

# cd /home/sourabh/CrawlPy/scraper_framework
# python scraper_framework/adapters/generic/alexander_admin_import.py --dry-run --limit 1

# cd /home/sourabh/CrawlPy/scraper_framework
# python scraper_framework/adapters/generic/alexander_admin_import.py --collection-name north_carolina_smartgov --county Alexander --dry-run --limit 1

# cd /home/sourabh/CrawlPy/scraper_framework
# python scraper_framework/adapters/generic/alexander_admin_import.py --collection-name north_carolina_smartgov --county Alexander --limit 20


