from __future__ import annotations

import argparse

from .constants import DEFAULT_MODULE_NAME, DEFAULT_STATE_NAME
from .push_service import TylerEnerGovPushService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Push Tyler EnerGov county records to the admin permit import API.")
    parser.add_argument("--state-name", default=DEFAULT_STATE_NAME, help="State name stored in Mongo and sent to admin import.")
    parser.add_argument("--module-name", default=DEFAULT_MODULE_NAME, help="Module name sent to admin import.")
    parser.add_argument("--collection-name", default=None, help="Override the Mongo collection name to read from.")
    parser.add_argument("--agency-key", default=None, help="Override the admin import agency field.")
    parser.add_argument("--fips", default=None, help="Optional FIPS value for the admin import payload.")
    parser.add_argument("--limit", type=int, default=None, help="Limit how many stored records are loaded from Mongo.")
    parser.add_argument("--execute", action="store_true", help="Actually POST to the admin import API. Default is dry run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = TylerEnerGovPushService(
        state_name=args.state_name,
        module_name=args.module_name,
        collection_name=args.collection_name,
        agency_key=args.agency_key,
        limit=args.limit,
        fips=args.fips,
    )
    service.run(execute=args.execute)


if __name__ == "__main__":
    main()

# python3 -m scraper_framework.adapters.tyler_energov_import.push_cli  # dry run
# python3 -m scraper_framework.adapters.tyler_energov_import.push_cli --limit 5 # dry run
# python3 -m scraper_framework.adapters.tyler_energov_import.push_cli --execute
# python3 -m scraper_framework.adapters.tyler_energov_import.push_cli --limit 5 --execute
