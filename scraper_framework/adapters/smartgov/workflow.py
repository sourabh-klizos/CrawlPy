from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil.relativedelta import relativedelta
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .constants import (
    BROWSER_NAVIGATION_TIMEOUT_MS,
    BROWSER_POSTBACK_TIMEOUT_MS,
    BROWSER_RESULTS_TIMEOUT_MS,
    COUNTY_PERMIT_TYPE_GROUPS,
    MAX_CONCURRENT_PAGES,
    SEARCH_WINDOW_YEARS,
    SMARTGOV_URLS,
    WORKER_PAGE_NAVIGATION_RETRIES,
)
from .parser import (
    SMARTGOV_RECORD_NUMBER_RE,
    merge_detail_fields,
    parse_detail_fields,
    parse_rows,
)


class SmartGovPlaywrightWorkflow:
    # Example test runs:
    # python3 scraper_framework/main.py --headed --limit 1
    # python3 scraper_framework/main.py --headed --limit 1 --agency PASCO_COUNTY
    # python3 scraper_framework/main.py --headed --limit 1 --agency PASCO_COUNTY --module Building

    permit_type_selector = "#ctl00_PlaceHolderMain_generalSearchForm_ddlGSPermitType"
    start_date_selector = "#ctl00_PlaceHolderMain_generalSearchForm_txtGSStartDate"
    end_date_selector = "#ctl00_PlaceHolderMain_generalSearchForm_txtGSEndDate"
    search_button_selector = "#ctl00_PlaceHolderMain_btnNewSearch"
    results_page_element_indicator = ".ACA_GridView, #ctl00_PlaceHolderMain_DataGrid, table.table, table"
    smartgov_record_link_pattern = SMARTGOV_RECORD_NUMBER_RE
    pagination_link_selector = (
        ".aca_pagination td.aca_pagination_td a, "
        "nav[aria-label*='Pagination'] a, "
        "nav[aria-label*='pagination'] a, "
        ".pagination a, "
        "ul.pagination a, "
        "a.page-link"
    )
    pagination_cell_selector = ".aca_pagination td.aca_pagination_td, .pagination li, ul.pagination li"
    pagination_more_texts = ("...", "…")
    pagination_next_texts = ("Next", "›", ">", "»")

    def __init__(self, request_timeout_ms: int) -> None:
        self.request_timeout_ms = request_timeout_ms
        self.result_pages_html: list[str] = []
        self.result_record_batches: list[list[dict[str, Any]]] = []
        self.result_batch_callback: Callable[[list[dict[str, Any]]], None] | None = None
        self.page_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PAGES)
        self.detail_page_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PAGES)

    async def run(self, page: Any, url: str) -> str:
        self.result_pages_html = []
        self.result_record_batches = []
        await self.before_navigation(page, url)
        await self.goto_search_page(page, url)
        await self.after_navigation(page, url)
        await self.apply_site_logic(page, url)
        await self.before_html_capture(page, url)
        if self.result_pages_html:
            return "\n".join(self.result_pages_html)
        return await page.content()

    async def before_navigation(self, page: Any, url: str) -> None:
        """Hook before opening the target URL."""

    async def after_navigation(self, page: Any, url: str) -> None:
        """Hook immediately after the initial page load finishes."""

    async def apply_site_logic(self, page: Any, url: str) -> None:
        permit_type_groups = self.get_permit_type_groups(url)
        permit_types = self.get_target_permit_types(permit_type_groups)
        print(f"Permit types to scrape ({len(permit_types)} total): {permit_types}")

        type_to_category = self.get_type_to_category(permit_type_groups)

        for option_text in permit_types:
            category = type_to_category.get(option_text, "Unknown")
            print(f"[{category}] Selecting permit type in new tab: {option_text}")
            tab_page = await self.open_residential_option_tab(page, url, option_text)
            try:
                await self.after_residential_selection(tab_page, url, option_text, category)
            finally:
                await tab_page.close()

    def get_permit_type_groups(self, url: str) -> dict[str, list[str]]:
        county_key = self.get_county_key(url)
        if not county_key:
            raise ValueError(f"SmartGov URL is not configured in SMARTGOV_URLS: {url}")
        if county_key not in COUNTY_PERMIT_TYPE_GROUPS:
            raise ValueError(
                f"No SmartGov permit type groups configured for county key: {county_key}"
            )
        return COUNTY_PERMIT_TYPE_GROUPS[county_key]

    def get_county_key(self, url: str) -> str | None:
        for county_key, county_config in SMARTGOV_URLS.items():
            if county_config.get("search_url") == url:
                return county_key
        return None

    def get_target_permit_types(self, permit_type_groups: dict[str, list[str]]) -> list[str]:
        """Return a flat ordered list of all permit type labels from configured groups.

        The list preserves the category order and the within-category order defined
        in constants.py.  Each label will be selected one-by-one in the Type dropdown.
        """
        permit_types: list[str] = []
        seen: set[str] = set()
        for types in permit_type_groups.values():
            for permit_type in types:
                if permit_type in seen:
                    continue
                permit_types.append(permit_type)
                seen.add(permit_type)
        return permit_types

    def get_type_to_category(self, permit_type_groups: dict[str, list[str]]) -> dict[str, str]:
        type_to_categories: dict[str, list[str]] = {}
        for category, permit_types in permit_type_groups.items():
            for permit_type in permit_types:
                type_to_categories.setdefault(permit_type, []).append(category)
        return {
            permit_type: "; ".join(categories)
            for permit_type, categories in type_to_categories.items()
        }

    async def validate_permit_type_on_page(
        self,
        page: Any,
        permit_type_groups: dict[str, list[str]] | None = None,
    ) -> list[str]:
        """Return the subset of target permit types that actually exist in the dropdown.

        Useful for debugging when a county's dropdown does not have all expected options.
        """
        await page.wait_for_load_state("networkidle")
        dropdown = page.locator(self.permit_type_selector)
        all_options = await dropdown.locator("option").all_inner_texts()
        available = {opt.strip() for opt in all_options if opt.strip()}
        if permit_type_groups is None:
            raise ValueError("permit_type_groups is required for SmartGov validation")
        target = self.get_target_permit_types(permit_type_groups)
        missing = [t for t in target if t not in available]
        if missing:
            print(f"WARNING: The following permit types were NOT found in dropdown: {missing}")
            print(f"Available dropdown options: {sorted(available)}")
        return [t for t in target if t in available]

    async def open_residential_option_tab(self, page: Any, url: str, option_text: str) -> Any:
        tab_page = await page.context.new_page()
        await self.goto_search_page(tab_page, url)

        dropdown = await self.find_type_dropdown(tab_page)
        await dropdown.select_option(label=option_text)
        await self.wait_for_postback_settle(tab_page)
        await self.apply_date_range(tab_page)
        return tab_page

    async def after_residential_selection(
        self,
        page: Any,
        url: str,
        option_text: str,
        category: str,
    ) -> None:
        await self.click_search(page)
        await self.collect_paginated_results(page, url, option_text, category)
        # Write the next step for each selected option here.
        # Example steps:
        # - verify the selected value stayed selected after postback
        # - wait for the result grid
        # - scrape rows or detail links
        # - paginate
        # - save/export data

    async def before_html_capture(self, page: Any, url: str) -> None:
        """Hook for final waits or UI cleanup before we capture page HTML."""

    async def apply_date_range(self, page: Any) -> None:
        await page.wait_for_load_state("networkidle")

        today = datetime.now()
        start_date = today - relativedelta(years=SEARCH_WINDOW_YEARS)

        current_date_str = today.strftime("%m/%d/%Y")
        start_date_str = start_date.strftime("%m/%d/%Y")
        print(f"Setting date range from: {start_date_str} to: {current_date_str}")

        start_date_input = page.locator(self.start_date_selector)
        if await start_date_input.count() == 0:
            print("Date range inputs not found on SmartGov form; continuing without date filter.")
            return
        await start_date_input.fill("")
        await start_date_input.type(start_date_str)

        end_date_input = page.locator(self.end_date_selector)
        if await end_date_input.count() == 0:
            await start_date_input.press("Tab")
            return
        await end_date_input.fill("")
        await end_date_input.type(current_date_str)
        await end_date_input.press("Tab")

    async def click_search(self, page: Any) -> None:
        print("Attempting to click search and wait for results...")

        try:
            async with page.expect_navigation(
                wait_until="domcontentloaded",
                timeout=BROWSER_POSTBACK_TIMEOUT_MS,
            ):
                await self.click_search_button(page)
        except PlaywrightTimeoutError:
            print("Primary navigation timed out. Attempting fallback strategy...")

            await self.click_search_button(page, force=True)
            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=BROWSER_POSTBACK_TIMEOUT_MS,
            )

            try:
                await self.wait_for_results_page(page)
            except PlaywrightTimeoutError:
                print("Fallback failed: Results element did not appear. Page might be stuck.")
                raise
        else:
            await self.wait_for_results_page(page)

        await self.print_search_result_snapshot(page)

    async def print_search_result_snapshot(self, page: Any) -> None:
        title = await page.title()
        current_url = page.url
        body_text = (await page.locator("body").inner_text()).strip()
        body_preview = body_text[:1000]

        print(f"Search result URL: {current_url}")
        print(f"Search result title: {title}")
        print(f"Search result preview:\n{body_preview}")

    async def collect_paginated_results(
        self,
        page: Any,
        url: str,
        option_text: str,
        category: str,
    ) -> None:
        await self.wait_for_results_page(page)
        current_page_num = 1
        processed_pages: set[int] = set()

        while True:
            print(f"[{category}] Capturing {option_text} results page {current_page_num}...")
            await self.capture_result_page(page, url, option_text, category, current_page_num)
            processed_pages.add(current_page_num)

            next_page_num = await self.click_next_unprocessed_results_page(
                page,
                processed_pages,
                current_page_num,
            )
            if next_page_num is None:
                break
            current_page_num = next_page_num

        print(
            f"[{category}] Finished {option_text}: processed result pages "
            f"{sorted(processed_pages)}"
        )

    async def click_next_unprocessed_results_page(
        self,
        page: Any,
        processed_pages: set[int],
        current_page_num: int,
    ) -> int | None:
        visible_pages = await self.get_visible_page_numbers(page, processed_pages)
        if visible_pages:
            next_page_num = visible_pages[0]
            if await self.click_page_number_if_visible(page, next_page_num):
                return next_page_num

        if await self.click_next_pagination_control(page):
            await self.wait_for_results_page(page)
            return current_page_num + 1

        for more_text in self.pagination_more_texts:
            if await self.click_special_pagination_control(page, more_text):
                new_visible_pages = await self.get_visible_page_numbers(page, processed_pages)
                if new_visible_pages:
                    next_page_num = new_visible_pages[0]
                    if await self.click_page_number_if_visible(page, next_page_num):
                        return next_page_num

        return None

    async def get_visible_page_numbers(self, page: Any, processed_pages: set[int]) -> list[int]:
        visible_pages: list[int] = []

        for selector in (self.pagination_link_selector, "a"):
            page_links = page.locator(selector)
            for index in range(await page_links.count()):
                link = page_links.nth(index)
                if not await link.is_visible():
                    continue
                link_text = (await link.inner_text()).strip()
                if link_text.isdigit():
                    page_num = int(link_text)
                    if page_num not in processed_pages:
                        visible_pages.append(page_num)
            if visible_pages:
                break

        return sorted(set(visible_pages))

    async def advance_pagination_window(self, page: Any, processed_pages: set[int]) -> bool:
        current_max_processed = max(processed_pages)
        if await self.click_page_number_if_visible(page, current_max_processed):
            new_visible_pages = await self.get_visible_page_numbers(page, processed_pages)
            if new_visible_pages:
                return True

        for more_text in self.pagination_more_texts:
            if await self.click_special_pagination_control(page, more_text):
                new_visible_pages = await self.get_visible_page_numbers(page, processed_pages)
                if new_visible_pages:
                    return True

        pagination_cells = page.locator(self.pagination_cell_selector)
        for index in range(await pagination_cells.count()):
            cell = pagination_cells.nth(index)
            cell_text = (await cell.inner_text()).strip()
            if not any(next_text in cell_text for next_text in self.pagination_next_texts):
                continue

            next_link = cell.locator("a")
            if await next_link.count() == 0 or not await next_link.first.is_visible():
                continue

            await self.click_and_wait_for_results(page, next_link.first)
            new_visible_pages = await self.get_visible_page_numbers(page, processed_pages)
            if new_visible_pages:
                return True

        if await self.click_next_pagination_control(page):
            new_visible_pages = await self.get_visible_page_numbers(page, processed_pages)
            if new_visible_pages:
                return True

        return False

    async def click_page_number_if_visible(self, page: Any, target_page_num: int) -> bool:
        for selector in (self.pagination_link_selector, "a"):
            page_links = page.locator(selector)
            for index in range(await page_links.count()):
                link = page_links.nth(index)
                link_text = (await link.inner_text()).strip()
                if link_text == str(target_page_num) and await link.is_visible():
                    await self.click_and_wait_for_results(page, link)
                    return True
        return False

    async def fetch_target_results_page(
        self,
        context: Any,
        url: str,
        option_text: str,
        category: str,
        target_page_num: int,
    ) -> tuple[str, list[dict[str, Any]]] | None:
        async with self.page_semaphore:
            last_error: Exception | None = None
            for attempt in range(1, WORKER_PAGE_NAVIGATION_RETRIES + 1):
                worker_page = await context.new_page()
                try:
                    print(f"Opening worker for Page {target_page_num} (attempt {attempt})...")
                    await self.goto_search_page(worker_page, url)

                    dropdown = await self.find_type_dropdown(worker_page)
                    await dropdown.select_option(label=option_text)
                    await self.wait_for_postback_settle(worker_page)
                    await self.apply_date_range(worker_page)
                    await self.click_search(worker_page)

                    if target_page_num > 1 and not await self.go_to_results_page(worker_page, target_page_num):
                        print(f"Could not reach Page {target_page_num}.")
                        return None

                    return await self.capture_result_page(
                        worker_page,
                        url,
                        option_text,
                        category,
                        target_page_num,
                    )
                except PlaywrightTimeoutError as exc:
                    last_error = exc
                    print(
                        f"Worker timeout on Page {target_page_num} attempt {attempt}. Retrying..."
                    )
                finally:
                    await worker_page.close()

            if last_error is not None:
                raise last_error
            return None

    async def go_to_results_page(self, page: Any, current_page_num: int) -> bool:
        while True:
            for selector in (self.pagination_link_selector, "a"):
                page_links = page.locator(selector)
                for index in range(await page_links.count()):
                    link = page_links.nth(index)
                    link_text = (await link.inner_text()).strip()
                    if link_text == str(current_page_num) and await link.is_visible():
                        await self.click_and_wait_for_results(page, link)
                        return True

            if not await self.advance_results_window_once(page):
                return False

    async def advance_results_window_once(self, page: Any) -> bool:
        for more_text in self.pagination_more_texts:
            if await self.click_special_pagination_control(page, more_text):
                return True

        pagination_cells = page.locator(self.pagination_cell_selector)
        for index in range(await pagination_cells.count()):
            cell = pagination_cells.nth(index)
            cell_text = (await cell.inner_text()).strip()
            if not any(next_text in cell_text for next_text in self.pagination_next_texts):
                continue

            next_link = cell.locator("a")
            if await next_link.count() == 0 or not await next_link.first.is_visible():
                continue

            await self.click_and_wait_for_results(page, next_link.first)
            return True

        if await self.click_next_pagination_control(page):
            return True

        return False

    async def click_special_pagination_control(self, page: Any, control_text: str) -> bool:
        for selector in (self.pagination_link_selector, "a"):
            page_links = page.locator(selector)
            for index in range(await page_links.count()):
                link = page_links.nth(index)
                link_text = (await link.inner_text()).strip()
                if link_text == control_text and await link.is_visible():
                    await self.click_and_wait_for_results(page, link)
                    return True
        return False

    async def click_next_pagination_control(self, page: Any) -> bool:
        for selector in (self.pagination_link_selector, "a"):
            page_links = page.locator(selector)
            for index in range(await page_links.count()):
                link = page_links.nth(index)
                if not await link.is_visible():
                    continue
                link_text = (await link.inner_text()).strip()
                aria_label = (await link.get_attribute("aria-label") or "").strip()
                title = (await link.get_attribute("title") or "").strip()
                candidates = {link_text, aria_label, title}
                if any(
                    next_text == candidate or next_text in candidate
                    for candidate in candidates
                    for next_text in self.pagination_next_texts
                ):
                    await self.click_and_wait_for_results(page, link)
                    return True
        return False

    async def click_and_wait_for_results(self, page: Any, locator: Any) -> None:
        try:
            async with page.expect_navigation(
                wait_until="domcontentloaded",
                timeout=BROWSER_POSTBACK_TIMEOUT_MS,
            ):
                await locator.click()
        except PlaywrightTimeoutError:
            try:
                await page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=BROWSER_POSTBACK_TIMEOUT_MS,
                )
            except PlaywrightTimeoutError:
                pass

        await self.wait_for_results_page(page)

    async def goto_search_page(self, page: Any, url: str) -> None:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=BROWSER_NAVIGATION_TIMEOUT_MS,
        )
        await self.find_type_dropdown(page, timeout=BROWSER_NAVIGATION_TIMEOUT_MS)

    async def wait_for_postback_settle(self, page: Any, selector: str | None = None) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            pass
        if selector:
            await page.wait_for_selector(selector, timeout=BROWSER_POSTBACK_TIMEOUT_MS)
        else:
            await self.find_type_dropdown(page, timeout=BROWSER_POSTBACK_TIMEOUT_MS)

    async def wait_for_results_page(self, page: Any) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            pass

        record_link = page.get_by_role("link", name=self.smartgov_record_link_pattern).first
        try:
            await record_link.wait_for(state="visible", timeout=BROWSER_RESULTS_TIMEOUT_MS)
            return
        except PlaywrightTimeoutError:
            pass

        try:
            await page.wait_for_function(
                """() => /\\b\\d+\\s+results\\b/i.test(document.body.innerText)""",
                timeout=3000,
            )
            return
        except PlaywrightTimeoutError:
            pass

        await page.wait_for_selector(
            self.results_page_element_indicator,
            timeout=3000,
        )

    async def capture_result_page(
        self,
        page: Any,
        url: str,
        option_text: str,
        category: str,
        page_num: int = 1,
    ) -> tuple[str, list[dict[str, Any]]]:
        html = await page.content()
        self.result_pages_html.append(html)
        records = parse_rows(BeautifulSoup(html, "html.parser"), url)
        if not records:
            raise RuntimeError(
                f"No SmartGov records parsed for {option_text} page {page_num}; stopping this permit type."
            )
        records = [
            {
                **record,
                "application_group": category,
                "application_type": option_text,
            }
            for record in records
        ]
        records = await self.enrich_records_with_details(page, records, url, option_text, page_num)
        if records:
            self.result_record_batches.append(records)
            if self.result_batch_callback is not None:
                self.result_batch_callback(records)
        return html, records

    async def enrich_records_with_details(
        self,
        page: Any,
        records: list[dict[str, Any]],
        url: str,
        option_text: str,
        page_num: int,
    ) -> list[dict[str, Any]]:
        if not records:
            return []

        enriched_records: list[dict[str, Any]] = []
        for record in records:
            try:
                detail_result = await self.fetch_detail_fields(
                    page,
                    record,
                    url,
                    option_text,
                    page_num,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"Failed to fetch detail for {record.get('record_number')}: {exc}")
                raise
            enriched_records.append(merge_detail_fields(record, detail_result or {}))
        return enriched_records

    async def fetch_detail_fields(
        self,
        page: Any,
        record: dict[str, Any],
        url: str,
        option_text: str,
        page_num: int,
    ) -> dict[str, Any]:
        detail_link = record.get("detail_link")

        async with self.detail_page_semaphore:
            if detail_link:
                detail_page = await page.context.new_page()
                try:
                    print(
                        f"Opening direct detail page for {record.get('record_number')}: "
                        f"{detail_link}"
                    )
                    await detail_page.goto(
                        detail_link,
                        wait_until="domcontentloaded",
                        timeout=BROWSER_NAVIGATION_TIMEOUT_MS,
                    )
                    return await self.parse_open_detail_page(detail_page)
                except Exception as exc:  # noqa: BLE001
                    await self.print_detail_failure_debug(
                        detail_page,
                        record,
                        option_text,
                        page_num,
                        f"direct detail URL failed: {exc}",
                    )
                    raise
                finally:
                    await detail_page.close()

            print(
                f"No direct detail URL parsed for {record.get('record_number')}; "
                "falling back to search-page detail lookup."
            )
            return await self.fetch_detail_fields_by_click(
                page,
                record,
                url,
                option_text,
                page_num,
            )

    async def fetch_detail_fields_by_click(
        self,
        page: Any,
        record: dict[str, Any],
        url: str,
        option_text: str,
        page_num: int,
    ) -> dict[str, Any]:
        record_number = record.get("record_number")
        if not record_number:
            return {}

        detail_page = await page.context.new_page()
        debug_printed = False
        try:
            await self.goto_search_page(detail_page, url)
            dropdown = await self.find_type_dropdown(detail_page)
            await dropdown.select_option(label=option_text)
            await self.wait_for_postback_settle(detail_page)
            await self.apply_date_range(detail_page)
            await self.click_search(detail_page)
            if page_num > 1 and not await self.go_to_results_page(detail_page, page_num):
                raise RuntimeError(f"Could not return detail worker to results page {page_num}")

            link = detail_page.get_by_role("link", name=str(record_number), exact=True).first
            if await link.count() == 0:
                link = detail_page.locator("a").filter(has_text=str(record_number)).first
            if await link.count() == 0 or not await link.is_visible():
                await self.print_detail_failure_debug(
                    detail_page,
                    record,
                    option_text,
                    page_num,
                    f"record link not found for {record_number}",
                )
                debug_printed = True
                raise RuntimeError(f"Could not find detail link for {record_number}")

            detail_url = await self.extract_detail_url_from_link(link, url)
            if detail_url:
                await detail_page.goto(
                    detail_url,
                    wait_until="domcontentloaded",
                    timeout=BROWSER_NAVIGATION_TIMEOUT_MS,
                )
                return await self.parse_open_detail_page(detail_page)

            await link.scroll_into_view_if_needed(timeout=BROWSER_RESULTS_TIMEOUT_MS)
            return await self.click_record_link_and_parse_detail(
                detail_page,
                link,
                record_number,
            )
        except Exception as exc:  # noqa: BLE001
            if not debug_printed:
                await self.print_detail_failure_debug(
                    detail_page,
                    record,
                    option_text,
                    page_num,
                    f"fallback detail lookup failed: {exc}",
                )
            raise
        finally:
            await detail_page.close()

    async def print_detail_failure_debug(
        self,
        page: Any,
        record: dict[str, Any],
        option_text: str,
        page_num: int,
        reason: str,
    ) -> None:
        record_number = record.get("record_number")
        print("SmartGov detail failure debug:")
        print(f"  reason: {reason}")
        print(f"  record_number: {record_number}")
        print(f"  permit_type: {option_text}")
        print(f"  expected_results_page: {page_num}")
        print(f"  parsed_detail_link: {record.get('detail_link')}")

        try:
            print(f"  current_url: {page.url}")
        except Exception as exc:  # noqa: BLE001
            print(f"  current_url: <unavailable: {exc}>")

        try:
            print(f"  page_title: {await page.title()}")
        except Exception as exc:  # noqa: BLE001
            print(f"  page_title: <unavailable: {exc}>")

        try:
            body_text = await page.locator("body").inner_text(timeout=3000)
            body_preview = " ".join(body_text.split())[:1200]
            target_present = bool(record_number and record_number in body_text)
            print(f"  target_record_present_in_body: {target_present}")
            print(f"  body_preview: {body_preview}")
        except Exception as exc:  # noqa: BLE001
            print(f"  body_preview: <unavailable: {exc}>")

        try:
            visible_record_links = await self.visible_record_link_debug(page, limit=25)
            print(f"  visible_record_links: {visible_record_links}")
        except Exception as exc:  # noqa: BLE001
            print(f"  visible_record_links: <unavailable: {exc}>")

    async def visible_record_link_debug(self, page: Any, limit: int) -> list[str]:
        links = page.locator("a")
        visible_links: list[str] = []
        for index in range(await links.count()):
            link = links.nth(index)
            try:
                if not await link.is_visible():
                    continue
                text = " ".join((await link.inner_text()).split())
            except Exception:  # noqa: BLE001
                continue
            if not text or not self.smartgov_record_link_pattern.match(text):
                continue
            visible_links.append(text)
            if len(visible_links) >= limit:
                break
        return visible_links

    async def extract_detail_url_from_link(self, link: Any, source_url: str) -> str | None:
        attribute_blob = await link.evaluate(
            """element => Array.from(element.attributes)
                .map(attribute => `${attribute.name}=${attribute.value}`)
                .join(" ")"""
        )
        match = re.search(
            r"(https?://[^\s'\"<>]+/PermittingPublic/PermitLandingPagePublic/Index/[^\s'\"<>]+"
            r"|/?PermittingPublic/PermitLandingPagePublic/Index/[^\s'\"<>]+)",
            attribute_blob,
        )
        if match:
            raw_url = match.group(1)
            if raw_url.startswith("http"):
                return raw_url
            return urljoin(source_url, f"/{raw_url.lstrip('/')}")

        detail_match = re.search(
            r"Detail/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
            attribute_blob,
        )
        if detail_match:
            detail_id = detail_match.group(1)
            return urljoin(
                source_url,
                f"/PermittingPublic/PermitLandingPagePublic/Index/{detail_id}?_conv=1",
            )

        return None

    async def click_record_link_and_parse_detail(
        self,
        page: Any,
        link: Any,
        record_number: str,
    ) -> dict[str, Any]:
        popup_task = asyncio.create_task(
            page.context.wait_for_event("page", timeout=BROWSER_RESULTS_TIMEOUT_MS)
        )
        detail_task = asyncio.create_task(self.wait_for_detail_page(page, record_number))
        try:
            await link.click()
            done, pending = await asyncio.wait(
                {popup_task, detail_task},
                timeout=BROWSER_RESULTS_TIMEOUT_MS,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if popup_task in done and popup_task.exception() is None:
                popup_page = popup_task.result()
                for pending_task in pending:
                    pending_task.cancel()
                try:
                    await popup_page.wait_for_load_state(
                        "domcontentloaded",
                        timeout=BROWSER_NAVIGATION_TIMEOUT_MS,
                    )
                    return await self.parse_open_detail_page(popup_page)
                finally:
                    await popup_page.close()

            if detail_task in done and detail_task.exception() is None:
                for pending_task in pending:
                    pending_task.cancel()
                return await self.parse_open_detail_page(page)

            for done_task in done:
                if not done_task.cancelled() and done_task.exception() is not None:
                    done_task.exception()
            for pending_task in pending:
                pending_task.cancel()

            await link.evaluate("element => element.click()")
            await self.wait_for_detail_page(page, record_number)
            return await self.parse_open_detail_page(page)
        except Exception:
            for task in (popup_task, detail_task):
                if not task.done():
                    task.cancel()
            raise

    async def parse_open_detail_page(self, page: Any) -> dict[str, Any]:
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            pass
        await self.expand_detail_sections(page)
        return parse_detail_fields(BeautifulSoup(await page.content(), "html.parser"))

    async def wait_for_detail_page(self, page: Any, record_number: str) -> None:
        try:
            await page.wait_for_url(
                "**/PermittingPublic/PermitLandingPagePublic/**",
                timeout=BROWSER_NAVIGATION_TIMEOUT_MS,
            )
            return
        except PlaywrightTimeoutError:
            pass

        await page.wait_for_function(
            """() => {
                const text = document.body ? document.body.innerText : "";
                return text.includes("Project Information")
                    || text.includes("Current Fees")
                    || text.includes("Reference Number");
            }""",
            timeout=BROWSER_RESULTS_TIMEOUT_MS,
        )

    async def expand_detail_sections(self, page: Any) -> None:
        section_names = (
            "Contacts",
            "Details",
            "Parcels",
            "Inspections",
            "Fees",
        )
        for section_name in section_names:
            locators = [
                page.get_by_text(section_name, exact=True),
                page.locator(f"text={section_name}"),
            ]
            for locator in locators:
                count = await locator.count()
                for index in range(count):
                    section_toggle = locator.nth(index)
                    if not await section_toggle.is_visible():
                        continue
                    try:
                        should_click = await section_toggle.evaluate(
                            """element => {
                                const clickable = element.closest("button,a,[role='button']") || element;
                                const expanded = clickable.getAttribute("aria-expanded");
                                if (expanded === "false") return true;
                                if (expanded === "true") return false;
                                const parent = element.parentElement;
                                return parent ? parent.innerText.trim().length < 120 : true;
                            }"""
                        )
                        if not should_click:
                            continue
                        await section_toggle.click(timeout=1500)
                        await page.wait_for_timeout(250)
                    except Exception:  # noqa: BLE001
                        continue
                    break

        try:
            await page.wait_for_load_state("networkidle", timeout=3000)
        except PlaywrightTimeoutError:
            pass

    async def find_type_dropdown(self, page: Any, timeout: int = BROWSER_POSTBACK_TIMEOUT_MS) -> Any:
        await page.wait_for_selector("select", timeout=timeout)
        selectors = [
            self.permit_type_selector,
            "select[name*='Type']",
            "select[id*='Type']",
            "xpath=//label[contains(normalize-space(.), 'Type')]/following::select[1]",
            "xpath=//*[contains(normalize-space(.), 'Type')]/following::select[1]",
        ]
        for selector in selectors:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                continue
            if await locator.is_visible():
                return locator

        first_select = page.locator("select").first
        if await first_select.count() > 0 and await first_select.is_visible():
            return first_select
        raise PlaywrightTimeoutError("Could not find SmartGov Type dropdown")

    async def click_search_button(self, page: Any, force: bool = False) -> None:
        locators = [
            page.locator(self.search_button_selector),
            page.get_by_role("button", name="Search"),
            page.locator("input[type='submit'][value='Search']"),
            page.locator("button:has-text('Search')"),
        ]
        for locator in locators:
            if await locator.count() == 0:
                continue
            button = locator.first
            if not await button.is_visible():
                continue
            await button.click(force=force)
            return
        raise PlaywrightTimeoutError("Could not find SmartGov Search button")
