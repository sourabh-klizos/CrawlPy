## Generic Admin Import Rules

This file documents the reusable rule set for Mongo-to-admin import scripts in this repo.

### Applies To

- Any script that reads permit-like records from MongoDB
- Any script that builds admin import payloads
- Any script that pushes records to the admin API

Examples:

- `scraper_framework/adapters/generic/spartanburg_admin_import.py`
- future collection-based import scripts that follow the same flow

### Core Rules

1. Do not rely on a collection name only from runbook text. Make the target collection obvious in every command.
2. Always pass `--collection-name` explicitly in commands and docs, even if the script currently has an internal default.
3. Admin API payloads must be sent in chunks of 100 records.
4. Duplicate filtering must happen before any API push by checking the `already_pushed` collection.
5. Every successfully pushed record must be saved into the `already_pushed` collection so future runs can skip duplicates.
6. Use `--dry-run` first when validating a new collection, a new document shape, or a new payload mapping.
7. Keep the admin payload structure consistent with the shared admin import contract already used in this repo.
8. When a new collection has different field names, normalize those fields before building the shared payload.

### Recommended Flow

1. Read source rows from MongoDB.
2. Normalize collection-specific field names into the shared payload shape.
3. Check each record against `already_pushed`.
4. Remove duplicates before chunking.
5. Split the remaining records into chunks of 100.
6. Build one admin payload per chunk.
7. Use `--dry-run` to inspect the payload before any live push.
8. Push each chunk separately.
9. Save every successfully pushed record into `already_pushed`.

### Command Template

```bash
# Move into the repo area used by the script
cd /home/sourabh/CrawlPy/scraper_framework

# Dry run against a target collection
python <script_path>.py --collection-name <collection_name> --dry-run --limit 250

# Dry run and print the payload JSON
python <script_path>.py --collection-name <collection_name> --dry-run --print-payload --limit 5

# Push live in chunks of 100
python <script_path>.py --collection-name <collection_name> --limit 250

# Push one specific document by _id
python <script_path>.py --collection-name <collection_name> --dry-run --permit-id <mongo_object_id>
```

### Example

```bash
cd /home/sourabh/CrawlPy/scraper_framework
python scraper_framework/adapters/generic/spartanburg_admin_import.py --collection-name spartanburg_Construction_for_Commercial_Building --dry-run --limit 250
python scraper_framework/adapters/generic/spartanburg_admin_import.py --collection-name spartanburg_single_family --dry-run --limit 250
```

### Expected Behavior

- If 250 new records are ready to push, the script should make 3 API calls: 100, 100, 50.
- If some records already exist in `already_pushed`, they should be skipped before chunking.
- Only records that are actually pushed successfully should be written back into `already_pushed`.

### When Adding A New Collection

- Reuse the same chunk size rule of 100 unless the shared rule is intentionally changed.
- Reuse the same duplicate tracking collection: `already_pushed`.
- Add or update tests for the new collection shape.
- Keep the commands in docs explicit about which collection is being used.
- If the rule changes, update both the script and the tests that cover that flow.
