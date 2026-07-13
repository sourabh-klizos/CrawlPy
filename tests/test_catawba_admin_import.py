from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "scraper_framework"))

from adapters.generic.catawba_admin_import import (
    CATAWBA_COUNTY,
    CATAWBA_PROVIDER,
    CATAWBA_SOURCE_URL,
    CATAWBA_STATE,
)


def test_catawba_import_defaults_match_source() -> None:
    assert CATAWBA_SOURCE_URL == (
        "https://co-catawba-nc.smartgovcommunity.com/"
        "ApplicationPublic/ApplicationSearchAdvanced/Search"
    )
    assert CATAWBA_STATE == "North Carolina"
    assert CATAWBA_COUNTY == "Catawba"
    assert CATAWBA_PROVIDER == "smartgovcommunity"
