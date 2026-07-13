from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "scraper_framework"))

from adapters.generic.columbus_admin_import import (
    COLUMBUS_COUNTY,
    COLUMBUS_PROVIDER,
    COLUMBUS_SOURCE_URL,
    COLUMBUS_STATE,
)


def test_columbus_import_defaults_match_source() -> None:
    assert COLUMBUS_SOURCE_URL == (
        "https://co-columbus-nc.smartgovcommunity.com/"
        "ApplicationPublic/ApplicationSearchAdvanced/Search"
    )
    assert COLUMBUS_STATE == "North Carolina"
    assert COLUMBUS_COUNTY == "Columbus"
    assert COLUMBUS_PROVIDER == "smartgovcommunity"
