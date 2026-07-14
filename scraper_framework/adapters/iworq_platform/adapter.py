import asyncio
from typing import Any

from bs4 import BeautifulSoup

from adapters.base.base_adapter import BaseAdapter

from .client import IworqPlatformAdapterClient
from .constants import ADAPTER_NAME
from .detector import is_match
from .extractor import extract_records
from .parser import parse_page
from .workflow import IworqPlatformWorkflow


class IworqPlatformAdapter(BaseAdapter):
    name = ADAPTER_NAME
    client_class = IworqPlatformAdapterClient

    def __init__(self, headed: bool = False) -> None:
        super().__init__()
        self.headed = headed
        self.workflow = IworqPlatformWorkflow(
            request_timeout_ms=self.client.request_timeout_seconds * 1000
        )

    def fetch_html(self, url: str) -> str:
        return asyncio.run(self._fetch_html_async(url))

    async def _fetch_html_async(self, url: str) -> str:
        async with self.client.build_async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=not self.headed)
            context = await self.client.build_async_browser_context(browser)
            page = await context.new_page()
            try:
                return await self.workflow.run(page, url)
            finally:
                await context.close()
                await browser.close()

    def can_handle(self, url: str, html: str, soup: BeautifulSoup) -> bool:
        return is_match(url, html, soup)

    def extract(self, url: str, html: str, soup: BeautifulSoup) -> list[dict[str, Any]]:
        page_data = parse_page(soup)
        return extract_records(page_data)
