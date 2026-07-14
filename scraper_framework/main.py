from __future__ import annotations

import argparse
import queue
import threading
from pathlib import Path
from typing import Any, Iterable

from bs4 import BeautifulSoup

from adapters.accela.constants import URLS as ACCELA_URLS
from adapters.accela.adapter import AccelaAdapter
from adapters.base.base_adapter import BaseAdapter
from adapters.detector import AdapterDetector, build_adapters
from adapters.iworq_platform.constants import URLS as IWORQ_PLATFORM_URLS
from adapters.smartgov.constants import SMARTGOV_URLS, STATE_NAMES
from adapters.smartgov.adapter import SmartGovAdapter
from db.mongo_client import MongoStore
from utils.logger import get_logger

logger = get_logger("crawler")


def save_raw_batches(
    store: MongoStore,
    *,
    raw_batches: list[list[dict[str, Any]]],
    source_metadata: dict[str, str | None],
    source_url: str,
    selected_adapter: BaseAdapter,
    is_smartgov: bool,
) -> int:
    saved_records = 0
    for raw_batch in raw_batches:
        if not raw_batch:
            continue

        store.save_raw_result_batch(
            county_name=source_metadata["county_name"],
            state_name=source_metadata["state_name"],
            agency_key=source_metadata["agency_key"],
            module_name=source_metadata["module_name"],
            source_url=source_url,
            adapter_name=selected_adapter.name,
            raw_items=raw_batch,
        )

        for raw in raw_batch:
            normalized = selected_adapter.normalize(raw)
            store.save_permit(
                county_name=source_metadata["county_name"],
                state_name=source_metadata["state_name"],
                agency_key=source_metadata["agency_key"],
                module_name=source_metadata["module_name"],
                source_url=source_url,
                adapter_name=selected_adapter.name,
                normalized_data=normalized,
                raw_data=raw,
                crawl_status="success",
            )
            if is_smartgov:
                store.save_resource_permit(
                    state_name=source_metadata["state_name"],
                    county_name=source_metadata["county_name"],
                    resource_name=selected_adapter.name,
                    source_url=source_url,
                    normalized_data=normalized,
                    raw_data=raw,
                    crawl_status="success",
                )
            saved_records += 1
    return saved_records


class BackgroundBatchWriter:
    def __init__(
        self,
        store: MongoStore,
        *,
        source_metadata: dict[str, str | None],
        source_url: str,
        selected_adapter: BaseAdapter,
        is_smartgov: bool,
    ) -> None:
        self.store = store
        self.source_metadata = source_metadata
        self.source_url = source_url
        self.selected_adapter = selected_adapter
        self.is_smartgov = is_smartgov
        self.saved_records = 0
        self._queue: queue.Queue[list[dict[str, Any]] | None] = queue.Queue()
        self._error: BaseException | None = None
        self._closed = False
        self._thread = threading.Thread(
            target=self._run,
            name=f"db-writer-{selected_adapter.name}",
            daemon=True,
        )
        self._thread.start()

    def enqueue(self, raw_batch: list[dict[str, Any]]) -> None:
        self.raise_if_failed()
        self._queue.put(list(raw_batch))
        logger.info(
            "Queued %s records for background DB save for %s",
            len(raw_batch),
            self.source_url,
        )

    def close(self, *, raise_errors: bool = True) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put(None)
            self._thread.join()
        if raise_errors:
            self.raise_if_failed()

    def raise_if_failed(self) -> None:
        if self._error is not None:
            raise RuntimeError("Background DB writer failed") from self._error

    def _run(self) -> None:
        while True:
            raw_batch = self._queue.get()
            try:
                if raw_batch is None:
                    return

                saved_count = save_raw_batches(
                    self.store,
                    raw_batches=[raw_batch],
                    source_metadata=self.source_metadata,
                    source_url=self.source_url,
                    selected_adapter=self.selected_adapter,
                    is_smartgov=self.is_smartgov,
                )
                self.saved_records += saved_count
                logger.info(
                    "Saved SmartGov background batch with %s records for %s",
                    saved_count,
                    self.source_url,
                )
            except BaseException as exc:  # noqa: BLE001
                self._error = exc
                logger.exception("Background DB writer failed for %s", self.source_url)
                return
            finally:
                self._queue.task_done()


def load_urls_from_file(file_path: str | Path) -> list[str]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"URL file not found: {path}")

    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        urls.append(value)
    return urls


def load_accela_urls(agencies: Iterable[str] | None = None, modules: Iterable[str] | None = None) -> list[str]:
    agency_filter = {value.strip().upper() for value in (agencies or []) if value.strip()}
    module_filter = {value.strip().lower() for value in (modules or []) if value.strip()}
    selected_urls: list[str] = []

    for agency_key, agency_config in ACCELA_URLS.items():
        if agency_filter and agency_key.upper() not in agency_filter:
            continue

        target_scrape_urls = agency_config.get("target_scrape_urls", {})
        ordered_modules = agency_config.get("modules", list(target_scrape_urls.keys()))
        for module_name in ordered_modules:
            if module_filter and module_name.lower() not in module_filter:
                continue

            url = target_scrape_urls.get(module_name)
            if url:
                selected_urls.append(url)

    return selected_urls


def load_iworq_platform_urls(agencies: Iterable[str] | None = None) -> list[str]:
    agency_filter = {value.strip().upper() for value in (agencies or []) if value.strip()}
    selected_urls: list[str] = []

    for agency_key, agency_config in IWORQ_PLATFORM_URLS.items():
        if agency_filter and agency_key.upper() not in agency_filter:
            continue

        url = agency_config.get("url")
        if url:
            selected_urls.append(url)

    return selected_urls


def get_source_metadata(source_url: str) -> dict[str, str | None]:
    for agency_key, agency_config in ACCELA_URLS.items():
        target_scrape_urls = agency_config.get("target_scrape_urls", {})
        for module_name, configured_url in target_scrape_urls.items():
            if configured_url == source_url:
                return {
                    "agency_key": agency_key,
                    "county_name": agency_config.get("agency_name"),
                    "state_name": agency_config.get("state_name") or agency_config.get("state"),
                    "module_name": module_name,
                }

    for agency_key, agency_config in IWORQ_PLATFORM_URLS.items():
        if agency_config.get("url") == source_url:
            return {
                "agency_key": agency_key,
                "county_name": agency_config.get("county_name") or agency_config.get("agency_name"),
                "state_name": agency_config.get("state_name") or agency_config.get("state"),
                "module_name": None,
            }

    return {
        "agency_key": None,
        "county_name": None,
        "state_name": None,
        "module_name": None,
    }


def load_smartgov_urls(counties: Iterable[str] | None = None) -> list[str]:
    """Return SmartGov search URLs, optionally filtered by county key."""
    county_filter = {value.strip().lower() for value in (counties or []) if value.strip()}
    selected_urls: list[str] = []
    for county_key, county_config in SMARTGOV_URLS.items():
        if county_filter and county_key.lower() not in county_filter:
            continue
        url = county_config.get("search_url")
        if url:
            selected_urls.append(url)
    return selected_urls


def get_smartgov_source_metadata(source_url: str) -> dict[str, str | None]:
    """Return county metadata for a SmartGov search URL."""
    for county_key, county_config in SMARTGOV_URLS.items():
        if county_config.get("search_url") == source_url:
            county_name = county_config.get("county_name")
            if county_name and county_name.endswith(" County"):
                county_name = county_name.removesuffix(" County")
            state_code = county_config.get("state")
            return {
                "agency_key": county_key,
                "county_name": county_name,
                "state_name": STATE_NAMES.get(state_code, state_code),
                "module_name": "smartgov",
            }
    return {
        "agency_key": None,
        "county_name": None,
        "state_name": None,
        "module_name": None,
    }


def limit_urls(urls: list[str], limit: int | None = None) -> list[str]:
    if limit is None or limit <= 0:
        return urls
    return urls[:limit]


def get_bootstrap_adapter(url: str, adapters: Iterable[BaseAdapter]) -> BaseAdapter:
    empty_soup = BeautifulSoup("", "html.parser")
    adapters_by_name = {adapter.name: adapter for adapter in adapters}

    for adapter in adapters:
        if adapter.name == "accela":
            continue
        if adapter.can_handle(url, "", empty_soup):
            return adapter

    return adapters_by_name.get("accela") or next(iter(adapters))


def crawl(
    urls: Iterable[str],
    headed: bool = False,
    smartgov_scrape_details: bool = True,
    smartgov_detail_concurrency: int | None = None,
    smartgov_permit_types: list[str] | None = None,
) -> None:
    adapters: list[BaseAdapter] = build_adapters()
    accela_adapter = next((adapter for adapter in adapters if isinstance(adapter, AccelaAdapter)), None)
    smartgov_adapter = next((adapter for adapter in adapters if isinstance(adapter, SmartGovAdapter)), None)
    if smartgov_adapter is not None:
        smartgov_adapter.configure(
            scrape_details=smartgov_scrape_details,
            detail_concurrency=smartgov_detail_concurrency,
            permit_types=smartgov_permit_types,
        )
    for adapter in adapters:
        if hasattr(adapter, "headed"):
            adapter.headed = headed
    detector = AdapterDetector(adapters)
    store = MongoStore()

    for source_url in urls:
        source_url = source_url.strip()
        if not source_url:
            continue

        run_id = None
        is_smartgov = "smartgovcommunity" in source_url.lower()
        source_metadata = (
            get_smartgov_source_metadata(source_url) if is_smartgov else get_source_metadata(source_url)
        )
        logger.info("Crawling %s", source_url)
        background_writer: BackgroundBatchWriter | None = None

        try:
            if is_smartgov and smartgov_adapter:
                bootstrap_adapter: BaseAdapter = smartgov_adapter
            elif "accela" in source_url.lower() and accela_adapter:
                bootstrap_adapter = accela_adapter
            else:
                bootstrap_adapter = get_bootstrap_adapter(source_url, adapters)

            selected_adapter = bootstrap_adapter
            run_id = store.create_run(
                source_url,
                selected_adapter.name,
                county_name=source_metadata["county_name"],
                state_name=source_metadata["state_name"],
                agency_key=source_metadata["agency_key"],
                module_name=source_metadata["module_name"],
            )
            store.save_source(
                source_url,
                selected_adapter.name,
                county_name=source_metadata["county_name"],
                state_name=source_metadata["state_name"],
                agency_key=source_metadata["agency_key"],
                module_name=source_metadata["module_name"],
            )
            store.log(
                run_id,
                "INFO",
                "Adapter selected",
                {
                    "adapter": selected_adapter.name,
                    "county_name": source_metadata["county_name"],
                    "state_name": source_metadata["state_name"],
                    "agency_key": source_metadata["agency_key"],
                    "module_name": source_metadata["module_name"],
                },
            )

            callback_saved_records = 0
            smartgov_callback_enabled = is_smartgov and isinstance(selected_adapter, SmartGovAdapter)
            if smartgov_callback_enabled:
                background_writer = BackgroundBatchWriter(
                    store,
                    source_metadata=source_metadata,
                    source_url=source_url,
                    selected_adapter=selected_adapter,
                    is_smartgov=True,
                )

                def save_smartgov_batch(raw_batch: list[dict[str, Any]]) -> None:
                    if background_writer is None:
                        raise RuntimeError("Background DB writer was not initialized")
                    background_writer.enqueue(raw_batch)

                smartgov_adapter.set_raw_batch_callback(save_smartgov_batch)

            try:
                html = bootstrap_adapter.fetch_html(source_url)
            finally:
                if smartgov_callback_enabled:
                    smartgov_adapter.set_raw_batch_callback(None)

            soup = bootstrap_adapter.parse(html)

            detected_adapter = detector.detect(source_url, html, soup)
            if detected_adapter.name != selected_adapter.name:
                selected_adapter = detected_adapter

            raw_items = selected_adapter.extract(source_url, html, soup)
            raw_batches = (
                selected_adapter.get_raw_batches()
                if hasattr(selected_adapter, "get_raw_batches")
                else [raw_items]
            )
            total_raw_records = sum(len(batch) for batch in raw_batches)
            logger.info(
                "Saving %s records across %s batches for %s",
                total_raw_records,
                len(raw_batches),
                source_url,
            )
            if not raw_items:
                store.log(run_id, "INFO", "No permits found", {})

            if smartgov_callback_enabled:
                if background_writer is not None:
                    background_writer.close()
                    callback_saved_records = background_writer.saved_records
                logger.info(
                    "SmartGov records were saved by background writer: %s records for %s",
                    callback_saved_records,
                    source_url,
                )
            else:
                save_raw_batches(
                    store,
                    raw_batches=raw_batches,
                    source_metadata=source_metadata,
                    source_url=source_url,
                    selected_adapter=selected_adapter,
                    is_smartgov=is_smartgov,
                )

            if run_id is not None:
                store.complete_run(run_id, status="success")
            logger.info("Completed %s", source_url)

        except Exception as exc:  # noqa: BLE001
            if background_writer is not None:
                try:
                    background_writer.close(raise_errors=False)
                    logger.info(
                        "Background writer flushed %s records before failure for %s",
                        background_writer.saved_records,
                        source_url,
                    )
                except Exception as writer_exc:  # noqa: BLE001
                    logger.exception("Failed to close background writer: %s", writer_exc)
            logger.exception("Failed %s", source_url)
            if run_id is not None:
                store.log(run_id, "ERROR", str(exc), {"url": source_url})
                store.complete_run(run_id, status="failed", error=str(exc))
            continue


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Universal Permit Crawler")
    default_urls_file = Path(__file__).resolve().parent / "urls.txt"
    parser.add_argument(
        "--source",
        choices=("accela_constants", "smartgov_constants", "iworq_platform_constants", "file"),
        default="iworq_platform_constants",
        help="Where to load URLs from. Defaults to the iWorQ Platform URLS constant.",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="Single URL to crawl (can be repeated)",
    )
    parser.add_argument(
        "--urls",
        default=str(default_urls_file),
        help="Path to a file containing one URL per line",
    )
    parser.add_argument(
        "--agency",
        action="append",
        default=[],
        help="Agency key from adapters/accela/constants.py, e.g. SAN_DIEGO or SACRAMENTO.",
    )
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        help="Module name filter, e.g. Building, Planning, Enforcement.",
    )
    parser.add_argument(
        "--county",
        action="append",
        default=[],
        help="SmartGov county key from adapters/smartgov/constants.py, e.g. alexander_county.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Open pages in a visible Playwright browser window.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of resolved URLs, useful for testing with 1 site.",
    )
    parser.add_argument(
        "--smartgov-skip-details",
        action="store_true",
        help="SmartGov only: save result-list rows without opening each detail page.",
    )
    parser.add_argument(
        "--smartgov-detail-concurrency",
        type=int,
        default=None,
        help="SmartGov only: number of detail pages to fetch concurrently.",
    )
    parser.add_argument(
        "--smartgov-permit-type",
        action="append",
        default=[],
        help="SmartGov only: exact Type dropdown label to scrape. Can be repeated.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.url:
        target_urls = args.url
    elif args.source == "smartgov_constants":
        target_urls = load_smartgov_urls(args.county)
    elif args.source == "accela_constants":
        target_urls = load_accela_urls(args.agency, args.module)
    elif args.source == "iworq_platform_constants":
        target_urls = load_iworq_platform_urls(args.agency)
    else:
        target_urls = load_urls_from_file(args.urls)

    target_urls = limit_urls(target_urls, args.limit)

    if not target_urls:
        raise ValueError("No URLs were resolved. Check your constants, agency filters, or module filters.")

    crawl(
        target_urls,
        headed=args.headed,
        smartgov_scrape_details=not args.smartgov_skip_details,
        smartgov_detail_concurrency=args.smartgov_detail_concurrency,
        smartgov_permit_types=args.smartgov_permit_type,
    )


if __name__ == "__main__":
    main()
