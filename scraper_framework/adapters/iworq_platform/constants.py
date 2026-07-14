ADAPTER_NAME = "iworq_platform"
SIGNATURES = ["iworq", "permit search", "permit center", "permit portal"]
BROWSER_NAVIGATION_TIMEOUT_MS = 60000
BROWSER_POSTBACK_TIMEOUT_MS = 30000
SEARCH_FIELD_SELECTOR = "select#searchField"
START_DATE_SELECTOR = "input#startDate"
END_DATE_SELECTOR = "input#endDate"
SEARCH_BUTTON_SELECTOR = "button[type='submit']"
SEARCH_FIELD_VALUE = "permit_dt_range"
DATE_LOOKBACK_DAYS = 365 * 2
HUMAN_STEP_DELAY_MS = 350
HUMAN_TYPING_DELAY_MS = 120
VERIFICATION_RETRY_DELAY_MS = 2000
IDENTITY_VERIFICATION_TEXT = "your identity could not be verified"

URLS = {
    "GREENE_COUNTY": {
        "agency_name": "Greene County",
        "county_name": "Greene County",
        "state_name": "North Carolina",
        "state": "NC",
        "url": "https://portal.iworq.net/GREENECOUNTY/permits/600",
    },
    "STOKES_COUNTY": {
        "agency_name": "Stokes County",
        "county_name": "Stokes County",
        "state_name": "North Carolina",
        "state": "NC",
        "url": "https://portal.iworq.net/STOKESCOUNTY/permits/600",
    },
    "WATAUGA_COUNTY": {
        "agency_name": "Watauga County",
        "county_name": "Watauga County",
        "state_name": "North Carolina",
        "state": "NC",
        "url": "https://portal.iworq.net/WATAUGACOUNTY/permits/600",
    },
    "WILKES_COUNTY": {
        "agency_name": "Wilkes County",
        "county_name": "Wilkes County",
        "state_name": "North Carolina",
        "state": "NC",
        "url": "https://portal.iworq.net/WILKESCOUNTY/permits/600",
    },
    "YANCEY_COUNTY": {
        "agency_name": "Yancey County",
        "county_name": "Yancey County",
        "state_name": "North Carolina",
        "state": "NC",
        "url": "https://portal.iworq.net/YANCEYCOUNTY/permits/601",
    },
    "ASHE_COUNTY": {
    "agency_name": "Ashe County",
    "county_name": "Ashe County",
    "state_name": "North Carolina",
    "state": "NC",
    "url": "https://portal.iworq.net/ASHECOUNTY/permits/600",
    },
}
