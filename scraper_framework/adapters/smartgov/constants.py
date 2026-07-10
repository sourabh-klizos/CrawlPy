ADAPTER_NAME = "smartgov"
SIGNATURES = ["smartgovcommunity"]
STATE_NAMES = {
    "NC": "North Carolina",
}
SEARCH_WINDOW_YEARS = 2
MAX_CONCURRENT_PAGES = 4
WORKER_PAGE_NAVIGATION_RETRIES = 2
BROWSER_NAVIGATION_TIMEOUT_MS = 120000
BROWSER_POSTBACK_TIMEOUT_MS = 60000
BROWSER_RESULTS_TIMEOUT_MS = 60000


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


# County-specific permit type groups. Every SmartGov county should define the
# exact Type dropdown labels to search here.
COUNTY_PERMIT_TYPE_GROUPS: dict[str, dict[str, list[str]]] = {
    "alexander_county": {
        "Building (Commercial)": [
            "New Residential or Commercial",
        ],
        "Building (Residential)": [
            "New Residential or Commercial",
        ],
        "Manufactured & Mobile Homes": [
            "Manufactured Home Appearance Application",
            "Manufactured Home Permit",
        ],
    },
    "catawba_county": {
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
    },
}
