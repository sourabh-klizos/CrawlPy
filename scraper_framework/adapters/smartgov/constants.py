ADAPTER_NAME = "smartgov"
SIGNATURES = ["smartgovcommunity"]
SEARCH_WINDOW_YEARS = 2
MAX_CONCURRENT_PAGES = 4
WORKER_PAGE_NAVIGATION_RETRIES = 2
BROWSER_NAVIGATION_TIMEOUT_MS = 60000
BROWSER_POSTBACK_TIMEOUT_MS = 30000
BROWSER_RESULTS_TIMEOUT_MS = 30000


# ---------------------------------------------------------------------------
# SmartGov county search URLs (North Carolina)
# ---------------------------------------------------------------------------
SMARTGOV_URLS: dict[str, dict[str, str]] = {
    "alexander_county": {
        "county_name": "Alexander County",
        "state": "NC",
        "search_url": "https://co-alexander-nc.smartgovcommunity.com/ApplicationPublic/ApplicationSearchAdvanced/Search",
    },
    "catawba_county": {
        "county_name": "Catawba County",
        "state": "NC",
        "search_url": "https://co-catawba-nc.smartgovcommunity.com/ApplicationPublic/ApplicationSearchAdvanced/Search",
    },
    "columbus_county": {
        "county_name": "Columbus County",
        "state": "NC",
        "search_url": "https://co-columbus-nc.smartgovcommunity.com/ApplicationPublic/ApplicationSearchAdvanced/Search",
    },
    "moore_county": {
        "county_name": "Moore County",
        "state": "NC",
        "search_url": "https://co-moore-nc.smartgovcommunity.com/ApplicationPublic/ApplicationSearchAdvanced/Search",
    },
    "pasquotank_county": {
        "county_name": "Pasquotank County",
        "state": "NC",
        "search_url": "https://co-pasquotank-nc.smartgovcommunity.com/ApplicationPublic/ApplicationSearchAdvanced/Search",
    },
}


# ---------------------------------------------------------------------------
# Permit type groups to select in the Type dropdown on the search form.
# Keys are the category labels (informational / for logging).
# Values are the exact option labels to select one-by-one in the dropdown.
# ---------------------------------------------------------------------------
PERMIT_TYPE_GROUPS: dict[str, list[str]] = {
    "Building (Commercial)": [
        "Commercial New Construction Permit",
    ],
    "Building (Residential)": [
        "Residential Duplex or Townhouse Permit",
        "Residential New Single Family Permit",
    ],
    "Manufactured & Mobile Homes": [
        "Manufactured Home Permit",
    ],
}
