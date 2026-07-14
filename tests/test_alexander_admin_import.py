from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "scraper_framework"))

from adapters.generic.alexander_admin_import import (
    ALEXANDER_COLLECTION_NAME,
    ALEXANDER_COUNTY,
    ALEXANDER_PROVIDER,
    ALEXANDER_SOURCE_URL,
    ALEXANDER_STATE,
)


def test_alexander_import_defaults_match_source() -> None:
    assert ALEXANDER_SOURCE_URL == (
        "https://co-alexander-nc.smartgovcommunity.com/"
        "ApplicationPublic/ApplicationSearchAdvanced/Search"
    )
    assert ALEXANDER_STATE == "North Carolina"
    assert ALEXANDER_COUNTY == "Alexander"
    assert ALEXANDER_PROVIDER == "smartgovcommunity"
    assert ALEXANDER_COLLECTION_NAME == "north_carolina_smartgov"
