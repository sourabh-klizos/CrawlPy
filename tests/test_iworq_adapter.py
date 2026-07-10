import asyncio
from datetime import datetime
import importlib
from pathlib import Path
import sys
from unittest.mock import patch

from bs4 import BeautifulSoup

sys.path.append(str(Path(__file__).resolve().parents[1] / "scraper_framework"))

from adapters.detector import build_adapters
from adapters.iworq_platform.adapter import IworqPlatformAdapter
from adapters.iworq_platform.detector import is_match
from adapters.iworq_platform.extractor import extract_records
from adapters.iworq_platform.constants import URLS
from adapters.iworq_platform.parser import parse_page
from adapters.iworq_platform.workflow import (
    IworqPlatformWorkflow,
    build_date_range_strings,
    to_date_input_value,
)
from main import get_bootstrap_adapter, get_source_metadata, load_iworq_platform_urls, parse_args


class _NavigationContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeLocator:
    def __init__(self, selector: str, calls: list[tuple[str, str, str | None]]) -> None:
        self.selector = selector
        self.calls = calls

    async def click(self) -> None:
        self.calls.append(("locator_click", self.selector, None))

    async def fill(self, value: str) -> None:
        self.calls.append(("locator_fill", self.selector, value))

    async def press(self, key: str) -> None:
        self.calls.append(("locator_press", self.selector, key))

    async def type(self, value: str, delay: int) -> None:
        self.calls.append(("locator_type", self.selector, f"{value}|{delay}"))

    async def evaluate(self, expression: str) -> bool:
        marker = "showPicker" if "showPicker" in expression else "setDateValue"
        self.calls.append(("locator_evaluate", self.selector, marker))
        return True


class _FakePage:
    def __init__(self, content_sequence: list[str] | None = None) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self._locators: dict[str, _FakeLocator] = {}
        self._content_sequence = content_sequence or [""]
        self._content_index = 0

    def locator(self, selector: str):
        locator = self._locators.get(selector)
        if locator is None:
            locator = _FakeLocator(selector, self.calls)
            self._locators[selector] = locator
        return locator

    async def select_option(self, selector: str, value: str) -> None:
        self.calls.append(("select_option", selector, value))

    def expect_navigation(self, **kwargs):
        self.calls.append(("expect_navigation", kwargs["wait_until"], str(kwargs["timeout"])))
        return _NavigationContext()

    async def click(self, selector: str, force: bool = False) -> None:
        self.calls.append(("click", selector, "force" if force else None))

    async def wait_for_load_state(self, state: str, timeout: int | None = None) -> None:
        self.calls.append(("wait_for_load_state", state, str(timeout) if timeout else None))

    async def wait_for_timeout(self, timeout: int) -> None:
        self.calls.append(("wait_for_timeout", str(timeout), None))

    async def content(self) -> str:
        index = min(self._content_index, len(self._content_sequence) - 1)
        value = self._content_sequence[index]
        self._content_index += 1
        return value


def test_iworq_adapter_detects_signature() -> None:
    html = """
    <html><head><title>Permit Search</title><meta name="description" content="Building permits" /></head>
    <body><div>iWorQ Portal</div></body></html>
    """
    soup = BeautifulSoup(html, "html.parser")

    assert is_match("https://example.com/iworq/permits", html, soup)

    adapters = build_adapters()
    assert any(adapter.name == "iworq_platform" for adapter in adapters)


def test_iworq_parser_extracts_content() -> None:
    html = """
    <html><head><title>Permit Center</title></head><body><main>Building permit application available</main></body></html>
    """
    soup = BeautifulSoup(html, "html.parser")

    page_data = parse_page(soup)
    records = extract_records(page_data)

    assert records[0]["record_type"] == "unknown"
    assert "Permit Center" in records[0]["description"]


def test_iworq_constants_load_one_url_per_county() -> None:
    urls = load_iworq_platform_urls()

    assert len(urls) == len(URLS)
    assert "https://portal.iworq.net/ASHECOUNTY/permits/600" in urls


def test_iworq_source_metadata_includes_state_and_county() -> None:
    metadata = get_source_metadata("https://portal.iworq.net/YANCEYCOUNTY/permits/601")

    assert metadata["agency_key"] == "YANCEY_COUNTY"
    assert metadata["state_name"] == "North Carolina"
    assert metadata["county_name"] == "Yancey County"
    assert metadata["module_name"] is None


def test_iworq_url_bootstraps_with_iworq_adapter() -> None:
    adapter = get_bootstrap_adapter("https://portal.iworq.net/WILKESCOUNTY/permits/600", build_adapters())

    assert isinstance(adapter, IworqPlatformAdapter)


def test_iworq_date_range_uses_html_input_format() -> None:
    start_date, end_date = build_date_range_strings(datetime(2026, 7, 10))

    assert start_date == "10-07-2024"
    assert end_date == "10-07-2026"


def test_iworq_converts_display_date_to_native_date_input_value() -> None:
    assert to_date_input_value("10-07-2024") == "2024-07-10"


def test_iworq_workflow_applies_search_filters() -> None:
    async def _run() -> list[tuple[str, str, str | None]]:
        workflow = IworqPlatformWorkflow(request_timeout_ms=30000)
        page = _FakePage()
        original = build_date_range_strings
        try:
            from adapters.iworq_platform import workflow as workflow_module

            workflow_module.build_date_range_strings = lambda now=None: ("10-07-2024", "10-07-2026")
            await workflow.apply_search_filters(page)
        finally:
            workflow_module.build_date_range_strings = original
        return page.calls

    calls = asyncio.run(_run())

    assert ("click", "select#searchField", None) in calls
    assert ("select_option", "select#searchField", "permit_dt_range") in calls
    assert ("locator_click", "input#startDate", None) in calls
    assert ("locator_evaluate", "input#startDate", "showPicker") in calls
    assert ("locator_evaluate", "input#startDate", "setDateValue") in calls
    assert ("locator_fill", "input#startDate", "") in calls
    assert ("locator_press", "input#startDate", "Enter") in calls
    assert ("locator_press", "input#startDate", "Tab") in calls
    assert ("locator_click", "input#endDate", None) in calls
    assert ("locator_evaluate", "input#endDate", "showPicker") in calls
    assert ("locator_evaluate", "input#endDate", "setDateValue") in calls
    assert ("locator_fill", "input#endDate", "") in calls
    assert ("locator_press", "input#endDate", "Enter") in calls
    assert ("locator_press", "input#endDate", "Tab") in calls
    assert ("click", "button[type='submit']", None) in calls


def test_iworq_retries_once_after_identity_verification_error() -> None:
    async def _run() -> list[tuple[str, str, str | None]]:
        workflow = IworqPlatformWorkflow(request_timeout_ms=30000)
        page = _FakePage(
            content_sequence=[
                "<div>Your identity could not be verified. Please perform the search again.</div>",
                "<div>search results</div>",
            ]
        )
        original = build_date_range_strings
        try:
            from adapters.iworq_platform import workflow as workflow_module

            workflow_module.build_date_range_strings = lambda now=None: ("10-07-2024", "10-07-2026")
            await workflow.apply_search_filters(page)
        finally:
            workflow_module.build_date_range_strings = original
        return page.calls

    calls = asyncio.run(_run())

    assert calls.count(("click", "button[type='submit']", None)) == 2
    assert ("wait_for_timeout", "2000", None) in calls


def test_iworq_is_the_default_source() -> None:
    with patch.object(sys, "argv", ["main.py", "--limit", "1"]):
        args = parse_args()

    assert args.source == "iworq_platform_constants"


def test_build_adapters_skips_missing_optional_adapter_dependency() -> None:
    real_import_module = importlib.import_module

    def _fake_import_module(name: str, package: str | None = None):
        if name == "adapters.accela.adapter":
            raise ModuleNotFoundError("No module named 'dateutil'")
        return real_import_module(name, package)

    with patch("adapters.detector.import_module", side_effect=_fake_import_module):
        adapters = build_adapters()

    assert any(adapter.name == "iworq_platform" for adapter in adapters)
