from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1] / "scraper_framework"))

from adapters.accela.mongo_admin_import import (
    apply_state_overrides,
    build_api_payload,
    build_query,
    fetch_permits,
    run_import,
)


def _args(**overrides: object) -> Namespace:
    defaults = {
        "collection_name": "permits",
        "permit_id": None,
        "source_url": None,
        "state": None,
        "county": None,
        "agency": None,
        "module": None,
        "adapter_name": None,
        "provider": None,
        "fips": None,
        "only_issued_active": False,
        "limit": None,
        "dry_run": False,
        "print_payload": False,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


def test_build_query_maps_known_filters() -> None:
    args = _args(
        source_url="https://example.com",
        state="FL",
        county="Polk County",
        agency="POLKCO",
        module="Building",
        adapter_name="accela",
    )

    query = build_query(args)

    assert query == {
        "source_url": "https://example.com",
        "state_name": "FL",
        "county_name": "Polk County",
        "agency_key": "POLKCO",
        "module_name": "Building",
        "adapter_name": "accela",
    }


def test_build_query_rejects_invalid_permit_id() -> None:
    with pytest.raises(ValueError, match="Invalid permit id"):
        build_query(_args(permit_id="not-an-object-id"))


def test_apply_state_overrides_sets_cooper_city_to_florida() -> None:
    permit_documents = [
        {
            "_id": "permit-cooper",
            "adapter_name": "accela",
            "agency_key": "COOPER_CITY",
            "county_name": "Cooper City",
            "module_name": "Building",
            "source_url": "https://aca-prod.accela.com/COOPER/Cap/CapHome.aspx?module=Building&TabName=Building",
            "state_name": None,
        }
    ]

    hydrated = apply_state_overrides(permit_documents)

    assert hydrated[0]["state_name"] == "FL"


def test_build_api_payload_strips_metadata_and_raw() -> None:
    payload = build_api_payload(
        {
            "provider": "accela",
            "state": "FL",
            "county": "Polk County",
            "fips": "12105",
            "source_url": "https://example.com",
            "exclude_tmp": True,
            "only_issued_active": True,
            "exclude_statuses": ["Withdrawn"],
            "records": [
                {
                    "record_number": "BLD-1",
                    "permit_type": "Residential",
                    "address": "123 Main St",
                    "status": "Issued",
                    "date": "07/10/2026",
                    "raw": {"some": "value"},
                }
            ],
        }
    )

    assert payload == {
        "state": "FL",
        "county": "Polk County",
        "provider": "accela",
        "fips": "12105",
        "source_url": "https://example.com",
        "exclude_tmp": True,
        "only_issued_active": True,
        "exclude_statuses": ["Withdrawn"],
        "records": [
            {
                "record_number": "BLD-1",
                "permit_type": "Residential",
                "address": "123 Main St",
                "status": "Issued",
                "date": "07/10/2026",
            }
        ],
    }


def test_run_import_returns_dry_run_summary_without_push() -> None:
    permit_document = {
        "_id": "permit-1",
        "adapter_name": "accela",
        "state_name": "FL",
        "county_name": "Polk County",
        "agency_key": "POLKCO",
        "module_name": "Building",
        "source_url": "https://example.com",
        "normalized_data": {
            "record_number": "BLD-1",
            "record_type": "Residential",
            "address": "123 Main St",
        },
        "raw_data": {"record_number": "BLD-1", "record_type": "Residential", "address": "123 Main St"},
    }

    fake_collection = Mock()
    fake_collection.find.return_value.sort.return_value = [permit_document]
    fake_store = SimpleNamespace(
        _collection=Mock(return_value=fake_collection),
        find_already_pushed=Mock(return_value=None),
    )

    results = run_import(_args(dry_run=True), store=fake_store)

    assert results[0]["mode"] == "dry-run"
    assert results[0]["summary"]["permit_ids"] == ["permit-1"]
    assert results[0]["summary"]["collection_name"] == "permits"
    assert results[0]["summary"]["adapter_name"] == "accela"
    assert results[0]["summary"]["state"] == "FL"
    assert results[0]["summary"]["county"] == "Polk County"
    assert results[0]["summary"]["agency"] == "POLKCO"
    assert results[0]["summary"]["module"] == "Building"
    assert results[0]["summary"]["source_url"] == "https://example.com"
    assert results[0]["summary"]["record_count"] == 1
    assert results[0]["summary"]["import_run_id"].startswith("python-")
    assert results[0]["summary"]["skipped_count"] == 0
    assert results[0]["summary"]["duplicate_found_count"] == 0
    assert results[0]["summary"]["new_pushed_count"] == 1
    assert results[0]["summary"]["tracking_collection"] == "already_pushed"
    assert results[0]["skipped"] == []


def test_run_import_uses_cooper_city_state_override(monkeypatch: pytest.MonkeyPatch) -> None:
    permit_document = {
        "_id": "permit-cooper",
        "adapter_name": "accela",
        "state_name": None,
        "county_name": "Cooper City",
        "agency_key": "COOPER_CITY",
        "module_name": "Building",
        "source_url": "https://aca-prod.accela.com/COOPER/Cap/CapHome.aspx?module=Building&TabName=Building",
        "normalized_data": {
            "record_number": "26TMP-003261",
            "record_type": "Building Permit Application",
        },
        "raw_data": {
            "record_number": "26TMP-003261",
            "record_type": "Building Permit Application",
            "date": "07/09/2026",
        },
    }
    fake_collection = Mock()
    fake_collection.find.return_value.sort.return_value = [permit_document]
    fake_store = SimpleNamespace(
        _collection=Mock(return_value=fake_collection),
        find_already_pushed=Mock(return_value=None),
        save_already_pushed=Mock(),
    )

    push_payload = Mock(return_value={"job_id": "job-cooper"})
    fake_client = SimpleNamespace(
        build_payload_from_permit_documents=Mock(
            return_value={
                "provider": "accela",
                "state": "FL",
                "county": "Cooper City",
                "fips": None,
                "agency": "COOPER_CITY",
                "module": "Building",
                "source_url": "https://aca-prod.accela.com/COOPER/Cap/CapHome.aspx?module=Building&TabName=Building",
                "exclude_tmp": True,
                "only_issued_active": False,
                "exclude_statuses": ["Withdrawn"],
                "import_run_id": "python-2026-07-10T12:00:00Z",
                "records": [{"record_number": "26TMP-003261", "permit_type": "Building Permit Application"}],
            }
        ),
        build_record=Mock(
            return_value={
                "record_number": "26TMP-003261",
                "permit_type": "Building Permit Application",
                "date": "07/09/2026",
            }
        ),
        push_payload=push_payload,
    )
    monkeypatch.setattr("adapters.accela.mongo_admin_import.AdminPermitImportClient", lambda: fake_client)

    results = run_import(_args(agency="COOPER_CITY"), store=fake_store)

    assert results[0]["summary"]["state"] == "FL"
    payload_call = fake_client.build_payload_from_permit_documents.call_args_list[-1]
    assert payload_call.args[0][0]["state_name"] == "FL"
    saved_tracking = fake_store.save_already_pushed.call_args.kwargs
    assert saved_tracking["identity_filter"]["state"] == "FL"
    assert saved_tracking["payload_metadata"]["state"] == "FL"


def test_run_import_pushes_payload_when_not_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    permit_document = {
        "_id": "permit-2",
        "adapter_name": "accela",
        "state_name": "FL",
        "county_name": "Polk County",
        "agency_key": "POLKCO",
        "module_name": "Building",
        "source_url": "https://example.com",
        "normalized_data": {
            "record_number": "BLD-2",
            "record_type": "Residential",
            "address": "456 Main St",
        },
        "raw_data": {"record_number": "BLD-2", "record_type": "Residential", "address": "456 Main St"},
    }
    fake_collection = Mock()
    fake_collection.find.return_value.sort.return_value = [permit_document]
    fake_store = SimpleNamespace(
        _collection=Mock(return_value=fake_collection),
        find_already_pushed=Mock(return_value=None),
        save_already_pushed=Mock(),
    )

    push_payload = Mock(return_value={"job_id": "job-123"})
    fake_client = SimpleNamespace(
        build_payload_from_permit_documents=Mock(
            return_value={
                "provider": "accela",
                "state": "FL",
                "county": "Polk County",
                "fips": None,
                "agency": "POLKCO",
                "module": "Building",
                "source_url": "https://example.com",
                "exclude_tmp": True,
                "only_issued_active": False,
                "exclude_statuses": ["Withdrawn"],
                "import_run_id": "python-2026-07-10T12:00:00Z",
                "records": [{"record_number": "BLD-2", "permit_type": "Residential", "address": "456 Main St"}],
            }
        ),
        build_record=Mock(
            return_value={
                "record_number": "BLD-2",
                "permit_type": "Residential",
                "address": "456 Main St",
            }
        ),
        push_payload=push_payload,
    )
    monkeypatch.setattr("adapters.accela.mongo_admin_import.AdminPermitImportClient", lambda: fake_client)

    results = run_import(_args(), store=fake_store)

    push_payload.assert_called_once()
    assert push_payload.call_args.args[0] == {
        "state": "FL",
        "county": "Polk County",
        "provider": "accela",
        "source_url": "https://example.com",
        "exclude_tmp": True,
        "only_issued_active": False,
        "exclude_statuses": ["Withdrawn"],
        "records": [{"record_number": "BLD-2", "permit_type": "Residential", "address": "456 Main St"}],
    }
    assert results == [
        {
            "mode": "push",
            "summary": {
                "permit_ids": ["permit-2"],
                "collection_name": "permits",
                "adapter_name": "accela",
                "state": "FL",
                "county": "Polk County",
                "agency": "POLKCO",
                "module": "Building",
                "source_url": "https://example.com",
                "record_count": 1,
                "import_run_id": "python-2026-07-10T12:00:00Z",
                "skipped_count": 0,
                "duplicate_found_count": 0,
                "new_pushed_count": 1,
                "tracking_collection": "already_pushed",
            },
            "response": {"job_id": "job-123"},
            "skipped": [],
        }
    ]
    fake_store.save_already_pushed.assert_called_once()


def test_run_import_skips_permits_already_pushed(monkeypatch: pytest.MonkeyPatch) -> None:
    permit_document = {
        "_id": "permit-3",
        "adapter_name": "accela",
        "state_name": "FL",
        "county_name": "Polk County",
        "agency_key": "POLKCO",
        "module_name": "Building",
        "source_url": "https://example.com",
        "normalized_data": {
            "record_number": "BLD-3",
            "record_type": "Residential",
            "address": "789 Main St",
        },
        "raw_data": {"record_number": "BLD-3", "record_type": "Residential", "address": "789 Main St"},
    }
    fake_collection = Mock()
    fake_collection.find.return_value.sort.return_value = [permit_document]
    fake_store = SimpleNamespace(
        _collection=Mock(return_value=fake_collection),
        find_already_pushed=Mock(return_value={"payload_hash": "existing-hash"}),
    )

    fake_client = SimpleNamespace(
        build_payload_from_permit_documents=Mock(
            return_value={
                "provider": "accela",
                "state": "FL",
                "county": "Polk County",
                "agency": "POLKCO",
                "module": "Building",
                "source_url": "https://example.com",
                "exclude_tmp": True,
                "only_issued_active": False,
                "exclude_statuses": ["Withdrawn"],
                "import_run_id": "python-2026-07-10T12:00:00Z",
                "records": [{"record_number": "BLD-3"}],
            }
        ),
        build_record=Mock(
            return_value={
                "record_number": "BLD-3",
                "permit_type": "Residential",
                "address": "789 Main St",
            }
        ),
    )
    monkeypatch.setattr("adapters.accela.mongo_admin_import.AdminPermitImportClient", lambda: fake_client)

    results = run_import(_args(), store=fake_store)

    assert results == [
        {
            "mode": "skip",
            "summary": {
                "permit_ids": ["permit-3"],
                "collection_name": "permits",
                "skipped_count": 1,
                "duplicate_found_count": 1,
                "new_pushed_count": 0,
                "tracking_collection": "already_pushed",
            },
            "skipped": [
                {
                    "permit_id": "permit-3",
                    "payload_hash": results[0]["skipped"][0]["payload_hash"],
                    "reason": "already-pushed",
                    "matched_by": "identity_filter",
                }
            ],
        }
    ]
    assert results[0]["skipped"][0]["payload_hash"]


def test_run_import_reads_from_requested_collection_and_resolves_source_url(monkeypatch: pytest.MonkeyPatch) -> None:
    permit_document = {
        "_id": "permit-4",
        "adapter_name": "smartgovcommunity",
        "county_name": "Alexander",
        "normalized_data": {
            "record_number": "BPR-26-0060",
            "record_type": "New Residential or Commercial",
            "address": "2724 LITTLE RIVER CHURCH RD",
            "status": "Additional Information Requested",
            "issue_date": "7/9/2026",
            "description": "New Residential or Commercial",
        },
        "raw_data": {
            "record_number": "BPR-26-0060",
            "record_type": "New Residential or Commercial",
            "address": "2724 LITTLE RIVER CHURCH RD",
        },
        "raw_columns": {
            "source_url": "https://co-alexander-nc.smartgovcommunity.com/ApplicationPublic/ApplicationSearchAdvanced/Search",
        },
    }
    fake_collection = Mock()
    fake_collection.find.return_value.sort.return_value = [permit_document]
    fake_store = SimpleNamespace(
        _collection=Mock(return_value=fake_collection),
        find_already_pushed=Mock(return_value=None),
    )

    fake_client = SimpleNamespace(
        build_payload_from_permit_documents=Mock(
            return_value={
                "provider": "smartgovcommunity",
                "state": "North Carolina",
                "county": "Alexander",
                "agency": None,
                "module": None,
                "source_url": "https://co-alexander-nc.smartgovcommunity.com/ApplicationPublic/ApplicationSearchAdvanced/Search",
                "exclude_tmp": True,
                "only_issued_active": False,
                "exclude_statuses": ["Withdrawn"],
                "import_run_id": "python-2026-07-10T12:00:00Z",
                "records": [{"record_number": "BPR-26-0060"}],
            }
        ),
        build_record=Mock(
            return_value={
                "record_number": "BPR-26-0060",
                "permit_type": "New Residential or Commercial",
                "address": "2724 LITTLE RIVER CHURCH RD",
                "date": "7/9/2026",
            }
        ),
    )
    monkeypatch.setattr("adapters.accela.mongo_admin_import.AdminPermitImportClient", lambda: fake_client)

    results = run_import(
        _args(
            collection_name="north_carolina_smartgov",
            state="North Carolina",
            county="Alexander",
            dry_run=True,
        ),
        store=fake_store,
    )

    fake_store._collection.assert_called_with("north_carolina_smartgov")
    payload_call = fake_client.build_payload_from_permit_documents.call_args
    assert payload_call.args[0][0]["source_url"] == (
        "https://co-alexander-nc.smartgovcommunity.com/ApplicationPublic/ApplicationSearchAdvanced/Search"
    )
    assert results[0]["summary"]["collection_name"] == "north_carolina_smartgov"


def test_fetch_permits_uses_object_id_sort_for_non_permits_collection() -> None:
    fake_cursor = Mock()
    fake_cursor.sort.return_value = []
    fake_collection = Mock()
    fake_collection.find.return_value = fake_cursor
    fake_store = SimpleNamespace(
        collection_name="north_carolina_smartgov",
        _collection=Mock(return_value=fake_collection),
    )

    assert fetch_permits(fake_store, {"county_name": "Alexander"}, None) == []
    fake_cursor.sort.assert_called_once_with("_id", -1)
