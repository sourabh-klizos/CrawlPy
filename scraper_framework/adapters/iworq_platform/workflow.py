from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .constants import (
    BROWSER_NAVIGATION_TIMEOUT_MS,
    BROWSER_POSTBACK_TIMEOUT_MS,
    DATE_LOOKBACK_DAYS,
    END_DATE_SELECTOR,
    HUMAN_STEP_DELAY_MS,
    HUMAN_TYPING_DELAY_MS,
    IDENTITY_VERIFICATION_TEXT,
    SEARCH_BUTTON_SELECTOR,
    SEARCH_FIELD_SELECTOR,
    SEARCH_FIELD_VALUE,
    START_DATE_SELECTOR,
    VERIFICATION_RETRY_DELAY_MS,
)


def build_date_range_strings(now: datetime | None = None) -> tuple[str, str]:
    current = now or datetime.now()
    two_years_ago = current - timedelta(days=DATE_LOOKBACK_DAYS)
    return two_years_ago.strftime("%d-%m-%Y"), current.strftime("%d-%m-%Y")


def to_date_input_value(display_value: str) -> str:
    return datetime.strptime(display_value, "%d-%m-%Y").strftime("%Y-%m-%d")


class IworqPlatformWorkflow:
    
    # python3 scraper_framework/main.py --limit 1
    # python3 scraper_framework/main.py --limit 1 --headed
    def __init__(self, request_timeout_ms: int) -> None:
        self.request_timeout_ms = request_timeout_ms

    async def run(self, page: Any, url: str) -> str:
        await self.goto_search_page(page, url)
        await self.apply_search_filters(page)
        return await page.content()

    async def goto_search_page(self, page: Any, url: str) -> None:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=BROWSER_NAVIGATION_TIMEOUT_MS,
        )
        await page.wait_for_selector(
            SEARCH_FIELD_SELECTOR,
            timeout=BROWSER_NAVIGATION_TIMEOUT_MS,
        )

    async def apply_search_filters(self, page: Any) -> None:
        start_date_str, end_date_str = build_date_range_strings()
        await self.populate_search_filters(page, start_date_str, end_date_str)
        await self.submit_search(page)

        if await self.has_identity_verification_error(page):
            await page.wait_for_timeout(VERIFICATION_RETRY_DELAY_MS)
            await self.populate_search_filters(page, start_date_str, end_date_str)
            await self.submit_search(page)

    async def populate_search_filters(self, page: Any, start_date_str: str, end_date_str: str) -> None:

        await page.click(SEARCH_FIELD_SELECTOR)
        await page.wait_for_timeout(HUMAN_STEP_DELAY_MS)
        await page.select_option(SEARCH_FIELD_SELECTOR, value=SEARCH_FIELD_VALUE)
        await page.wait_for_timeout(HUMAN_STEP_DELAY_MS)

        await self.type_like_human(page, START_DATE_SELECTOR, start_date_str)
        await page.wait_for_timeout(HUMAN_STEP_DELAY_MS)
        await self.type_like_human(page, END_DATE_SELECTOR, end_date_str)
        await page.wait_for_timeout(HUMAN_STEP_DELAY_MS)

    async def submit_search(self, page: Any) -> None:
        try:
            async with page.expect_navigation(
                wait_until="domcontentloaded",
                timeout=BROWSER_POSTBACK_TIMEOUT_MS,
            ):
                await page.click(SEARCH_BUTTON_SELECTOR)
        except PlaywrightTimeoutError:
            await page.click(SEARCH_BUTTON_SELECTOR, force=True)
            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=BROWSER_POSTBACK_TIMEOUT_MS,
            )

        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except PlaywrightTimeoutError:
            pass

    async def has_identity_verification_error(self, page: Any) -> bool:
        page_content = (await page.content()).lower()
        return IDENTITY_VERIFICATION_TEXT in page_content

    async def type_like_human(self, page: Any, selector: str, value: str) -> None:
        field = page.locator(selector)
        await field.click()
        await page.wait_for_timeout(HUMAN_STEP_DELAY_MS)
        await self.open_date_picker(field)
        await page.wait_for_timeout(HUMAN_STEP_DELAY_MS)
        await field.fill("")
        await page.wait_for_timeout(HUMAN_STEP_DELAY_MS)
        await field.press("Control+a")
        await field.press("Backspace")
        await page.wait_for_timeout(HUMAN_STEP_DELAY_MS)
        await self.select_date_value(field, value)
        await page.wait_for_timeout(HUMAN_STEP_DELAY_MS)
        await field.press("Enter")
        await page.wait_for_timeout(HUMAN_STEP_DELAY_MS)
        await field.press("Tab")

    async def open_date_picker(self, field: Any) -> None:
        try:
            await field.evaluate(
                """(element) => {
                    if (typeof element.showPicker === "function") {
                        element.showPicker();
                        return true;
                    }
                    return false;
                }"""
            )
        except Exception:  # noqa: BLE001
            return

    async def select_date_value(self, field: Any, value: str) -> None:
        iso_value = to_date_input_value(value)
        try:
            updated = await field.evaluate(
                f"""(element) => {{
                    const isNativeDate = element instanceof HTMLInputElement && element.type === "date";
                    if (!isNativeDate) {{
                        return false;
                    }}
                    element.value = "{iso_value}";
                    element.dispatchEvent(new Event("input", {{ bubbles: true }}));
                    element.dispatchEvent(new Event("change", {{ bubbles: true }}));
                    return true;
                }}"""
            )
            if updated:
                return
        except Exception:  # noqa: BLE001
            pass

        await field.type(value, delay=HUMAN_TYPING_DELAY_MS)
