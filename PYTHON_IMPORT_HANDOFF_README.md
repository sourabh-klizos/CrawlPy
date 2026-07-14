# Python Admin API Payload Handoff

This document is only about the admin import API contract.

It does **not** cover:

- export folders
- CSV review flow
- local run artifacts
- scrape orchestration

Your new Python project flow is assumed to be:

1. scrape data in Python
2. store raw data in MongoDB
3. read raw data from MongoDB
4. build admin API payload
5. push payload to the admin API

## Main Endpoint

```http
POST /api/admin/permits/import
Content-Type: application/json
```

Base URL:

- production/staging host of the coverage app

Example:

```text
https://<host>/api/admin/permits/import
```

## Auth

Use a static admin API token.

Supported auth in the contract:

```http
Authorization: Bearer <ADMIN_API_TOKEN>
```

The current repo client uses Bearer auth, so your Python project should do the
same.

## Top-Level Payload Shape

This is the shape your Python service should send:

```json
{
  "provider": "accela",
  "state": "FL",
  "county": "Polk County",
  "fips": "12105",
  "agency": "POLKCO",
  "module": "Building",
  "source_url": "https://aca-prod.accela.com/POLKCO/Cap/CapHome.aspx?module=Building",
  "import_run_id": "python-2026-07-10T12-00-00Z",
  "exclude_tmp": true,
  "exclude_statuses": ["Withdrawn"],
  "records": [
    {
      "record_number": "BLD-26-0525706",
      "permit_type": "Residential New Construction and Additions",
      "address": "1318 W Arch St, Tampa, FL 33607",
      "status": "In Process",
      "date": "06/08/2026",
      "expiration_date": "12/05/2026",
      "description": "optional",
      "raw": {}
    }
  ]
}
```

## Which Top-Level Fields Matter

### Required in practice

- `state`
- `county`
- `records`

### Strongly recommended

- `provider`
- `fips`
- `source_url`

### Extra provenance fields this repo also sends

- `agency`
- `module`
- `import_run_id`

These extra fields should be preserved if you have them, because they help with
traceability, but the core contract is centered on location plus `records`.

## Record Shape

Each item inside `records` should look like this:

```json
{
  "record_number": "BLD-26-0525706",
  "permit_type": "Residential New Construction and Additions",
  "address": "1318 W Arch St, Tampa, FL 33607",
  "status": "In Process",
  "date": "06/08/2026",
  "expiration_date": "12/05/2026",
  "description": "optional",
  "raw": {}
}
```

## What Each Record Field Means

- `record_number`
  - unique permit/application identifier from the source system
- `permit_type`
  - permit/record/work type label
- `address`
  - address string for the permit
- `status`
  - source status label
- `date`
  - source date field used for the record
- `expiration_date`
  - expiration date if the source has it
- `description`
  - description/notes/work description
- `raw`
  - original raw source object from MongoDB

## Important Rule For `raw`

Keep `raw` as the original source payload from MongoDB.

That means:

- do not flatten it into only a few fields
- do not replace it with normalized values
- do not drop source-only keys if they may be useful later

`raw` is the provenance/debug payload.

## Import Filters

This repo’s current Accela policy is:

```json
{
  "exclude_tmp": true,
  "exclude_statuses": ["Withdrawn"]
}
```

Meaning:

- exclude records whose `record_number` contains `TMP`
- exclude records whose normalized/source status is `Withdrawn`

If your Python job already filters those rows before building the payload, that
is fine.

If you want the API/import path to reflect the same policy explicitly, include
these fields in the top-level payload.

## What The API Does With The Payload

Important behavior from the contract:

- rows missing `address` or `permit_type` are skipped and reported in `errors`
- re-posting the same natural permit key updates existing data instead of
  creating duplicates
- geocoding is deferred after import
- a `report` object comes back describing what was received/imported/excluded

## Response Shape

Typical response:

```json
{
  "job_id": "a6fa5c7c-1826-4a0f-bb41-eeed964f7b66",
  "provider": "accela",
  "state": "FL",
  "county": "Polk County",
  "fips": "12105",
  "received": 100,
  "valid": 98,
  "invalid": 2,
  "inserted": 98,
  "geocode": "pending",
  "report": {
    "input_records": 100,
    "tmp_records": 16,
    "status_breakdown": {
      "Active": 69,
      "Withdrawn": 15,
      "(blank)": 16
    },
    "excluded_tmp": 0,
    "excluded_status": 0,
    "imported_after_filters": 100,
    "filters": {
      "exclude_tmp": false,
      "only_issued_active": false
    }
  },
  "errors": [
    {
      "row": 12,
      "errors": ["address"]
    }
  ]
}
```

If everything is filtered out, the contract says:

- `job_id` can be `null`
- `inserted` can be `0`
- only the report may come back

## MongoDB To API Mapping

Since your Python project keeps raw data in MongoDB first, the handoff boundary
should be:

### Mongo document

- raw scraper output
- source metadata you need for payload assembly
- enough fields to derive:
  - `provider`
  - `state`
  - `county`
  - `fips`
  - `agency`
  - `module`
  - `source_url`
  - normalized permit fields

### API payload

- one top-level batch object
- `records` built from Mongo rows/documents
- `raw` inside each record set to the original Mongo source payload

## Recommended Minimal Python Builder

Your Python builder should conceptually do this:

1. fetch raw permit docs from MongoDB
2. normalize each one into admin-record shape
3. batch them
4. POST batches to `/api/admin/permits/import`

## Suggested Python Request Example

```python
import requests

payload = {
    "provider": provider,
    "state": state,
    "county": county,
    "fips": fips,
    "agency": agency,
    "module": module_name,
    "source_url": source_url,
    "import_run_id": run_id,
    "exclude_tmp": True,
    "exclude_statuses": ["Withdrawn"],
    "records": records,
}

response = requests.post(
    f"{base_url}/api/admin/permits/import",
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    },
    json=payload,
    timeout=120,
)
response.raise_for_status()
result = response.json()
print(result)
```

## Suggested Record Builder Example

```python
def build_record(raw_doc):
    return {
        "record_number": raw_doc.get("record_number", ""),
        "permit_type": raw_doc.get("permit_type", ""),
        "address": raw_doc.get("address", ""),
        "status": raw_doc.get("status", ""),
        "date": raw_doc.get("date", ""),
        "expiration_date": raw_doc.get("expiration_date", ""),
        "description": raw_doc.get("description", ""),
        "raw": raw_doc,
    }
```

If your Mongo documents are not already normalized, then build these values from
their source keys before sending.

## Accela Field Mapping To Preserve

If your Mongo raw docs still look like Accela export rows, the existing repo
uses this mapping:

- `record_number`
  - `Record Number`
  - fallback: `Permit Number`
  - fallback: `Permit #`
  - fallback: `Application Number`
- `permit_type`
  - configured type if available
  - fallback: `Record Type`
  - fallback: `Permit Type`
  - fallback: `Type`
- `address`
  - `Address`
  - fallback: `Project Address`
  - fallback: `Site Address`
  - fallback: `Location`
- `status`
  - `Status`
  - fallback: `Permit Status`
  - fallback: `Record Status`
- `date`
  - `Date`
  - fallback: `Applied Date`
  - fallback: `Application Date`
  - fallback: `Issued Date`
- `expiration_date`
  - `Expiration Date`
  - fallback: `Expires`
- `description`
  - `Description`
  - fallback: `Project Description`
  - fallback: `Work Description`
  - fallback: `Short Notes`

## Things To Preserve In The Python Migration

- endpoint path: `/api/admin/permits/import`
- Bearer token auth
- top-level payload field names
- per-record payload field names
- `raw` source object
- Accela TMP/Withdrawn filtering policy
- batch imports for large datasets

## Things You Can Ignore For This Project

You said to ignore export-folder logic, so these are not needed for your new
implementation:

- `data/latest-run.json`
- local export directory structure
- CSV review helper flow
- Node push orchestration around exported files

## Repo Files That Define This Contract

- `docs/admin-api-requirements.md`
- `scripts/lib/admin-client.cjs`
- `scripts/push-latest-to-admin.cjs`
- `scripts/lib/normalize.cjs`

Those are the files that matter most for the API side.
