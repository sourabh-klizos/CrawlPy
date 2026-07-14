from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1] / "scraper_framework"))

from adapters.generic import spartanburg_admin_import as spartanburg_module
from adapters.generic.spartanburg_admin_import import build_permit_document, build_query, run_import


def _args(**overrides: object) -> Namespace:
    defaults = {
        "collection_name": "spartanburg_Construction_for_Commercial_Building",
        "permit_id": None,
        "state": "South Carolina",
        "county": "Spartanburg County",
        "provider": "tyler_energov",
        "agency": "SPARTANBURG",
        "module": "Permit",
        "source_url": None,
        "fips": "45083",
        "only_issued_active": False,
        "limit": None,
        "dry_run": False,
        "print_payload": False,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


def test_build_query_rejects_invalid_permit_id() -> None:
    with pytest.raises(ValueError, match="Invalid permit id"):
        build_query(_args(permit_id="not-an-object-id"))


def test_build_permit_document_wraps_raw_document_with_payload_metadata() -> None:
    raw_document = {
        "_id": "permit-1",
        "Case Number": "COMERCONST-1023-1125",
        "Type": "New Construction for Commercial Building",
        "Module Name": "Permit",
        "Address": "6001 EAGLE ROOST WAY BOILING SPRINGS SC 29316",
    }

    permit_document = build_permit_document(raw_document, _args())

    assert permit_document["adapter_name"] == "tyler_energov"
    assert permit_document["state_name"] == "South Carolina"
    assert permit_document["county_name"] == "Spartanburg County"
    assert permit_document["agency_key"] == "SPARTANBURG"
    assert permit_document["module_name"] == "Permit"
    assert permit_document["normalized_data"]["record_number"] == "COMERCONST-1023-1125"
    assert permit_document["normalized_data"]["permit_type"] == "New Construction for Commercial Building"
    assert permit_document["normalized_data"]["address"] == "6001 EAGLE ROOST WAY BOILING SPRINGS SC 29316"
    assert permit_document["raw_data"] == raw_document


def test_run_import_returns_dry_run_summary_without_push() -> None:
    raw_document = {
        "_id": "permit-1",
        "Case Number": "COMERCONST-1023-1125",
        "Type": "New Construction for Commercial Building",
        "Status": "Submitted - Online",
        "Applied Date": "10/09/2023",
        "Module Name": "Permit",
        "Address": "6001 EAGLE ROOST WAY BOILING SPRINGS SC 29316",
    }

    fake_collection = Mock()
    fake_collection.find.return_value.sort.return_value = [raw_document]
    fake_store = SimpleNamespace(
        _collection=Mock(return_value=fake_collection),
        find_already_pushed=Mock(return_value=None),
    )

    results = run_import(_args(dry_run=True), store=fake_store)

    assert results[0]["mode"] == "dry-run"
    assert results[0]["summary"]["permit_ids"] == ["permit-1"]
    assert results[0]["summary"]["collection_name"] == "spartanburg_Construction_for_Commercial_Building"
    assert results[0]["summary"]["adapter_name"] == "tyler_energov"
    assert results[0]["summary"]["state"] == "South Carolina"
    assert results[0]["summary"]["county"] == "Spartanburg County"
    assert results[0]["summary"]["agency"] == "SPARTANBURG"
    assert results[0]["summary"]["module"] == "Permit"
    assert results[0]["summary"]["record_count"] == 1
    assert results[0]["summary"]["import_run_id"].startswith("python-")
    assert results[0]["summary"]["chunk_number"] == 1
    assert results[0]["summary"]["total_chunks"] == 1
    assert results[0]["summary"]["skipped_count"] == 0
    assert results[0]["summary"]["duplicate_found_count"] == 0
    assert results[0]["summary"]["new_pushed_count"] == 1
    assert results[0]["summary"]["tracking_collection"] == "already_pushed"
    assert results[0]["skipped"] == []


def test_run_import_still_supports_single_family_shape() -> None:
    raw_document = {
        "_id": "permit-2",
        "CaseNumber": "BLDRESDNTL-0125-13793",
        "CaseType": "New Single Family House",
        "CaseStatus": "Issued",
        "IssueDate": "2025-01-21T00:00:00",
        "ExpireDate": "2025-07-20T00:00:00",
        "Address": {"FullAddress": "1337 STRAWBERRY JAM RD LYMAN SC 29365"},
        "Description": "",
        "ModuleName": 2,
    }

    fake_collection = Mock()
    fake_collection.find.return_value.sort.return_value = [raw_document]
    fake_store = SimpleNamespace(
        _collection=Mock(return_value=fake_collection),
        find_already_pushed=Mock(return_value=None),
    )

    results = run_import(
        _args(collection_name="spartanburg_single_family", dry_run=True, module="Building"),
        store=fake_store,
    )

    assert results[0]["mode"] == "dry-run"
    assert results[0]["summary"]["collection_name"] == "spartanburg_single_family"
    assert results[0]["summary"]["record_count"] == 1


def test_run_import_pushes_in_chunks_of_100_and_tracks_each_record(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_documents = [
        {
            "_id": f"permit-{index}",
            "Case Number": f"COMERCONST-{index:04d}",
            "Type": "New Construction for Commercial Building",
            "Status": "Submitted - Online",
            "Applied Date": "10/09/2023",
            "Module Name": "Permit",
            "Address": f"{index} EAGLE ROOST WAY BOILING SPRINGS SC 29316",
        }
        for index in range(205)
    ]

    fake_collection = Mock()
    fake_collection.find.return_value.sort.return_value = raw_documents
    fake_store = SimpleNamespace(
        _collection=Mock(return_value=fake_collection),
        find_already_pushed=Mock(return_value=None),
        save_already_pushed=Mock(),
    )

    class _FakeAdminClient:
        def __init__(self) -> None:
            self.pushed_payloads: list[dict[str, object]] = []

        def build_payload_from_permit_documents(self, permit_documents, **kwargs):
            records = []
            for permit_document in permit_documents:
                normalized = permit_document["normalized_data"]
                records.append(
                    {
                        "record_number": normalized["record_number"],
                        "permit_type": normalized["permit_type"],
                        "address": normalized["address"],
                        "status": normalized["status"],
                        "date": normalized["date"],
                        "raw": permit_document["raw_data"],
                    }
                )
            return {
                "provider": kwargs["provider"],
                "state": kwargs["state"],
                "county": kwargs["county"],
                "fips": kwargs["fips"],
                "agency": kwargs["agency"],
                "module": kwargs["module"],
                "source_url": kwargs["source_url"],
                "exclude_tmp": True,
                "exclude_statuses": ["Withdrawn"],
                "import_run_id": "python-2026-07-14T00:00:00Z",
                "records": records,
            }

        def push_payload(self, payload):
            self.pushed_payloads.append(payload)
            return {"ok": True, "received": len(payload["records"])}

    fake_client = _FakeAdminClient()
    monkeypatch.setattr(spartanburg_module, "AdminPermitImportClient", lambda: fake_client)

    results = run_import(_args(), store=fake_store)

    assert len(results) == 3
    assert [result["summary"]["record_count"] for result in results] == [100, 100, 5]
    assert [result["summary"]["chunk_number"] for result in results] == [1, 2, 3]
    assert all(result["summary"]["total_chunks"] == 3 for result in results)
    assert [len(payload["records"]) for payload in fake_client.pushed_payloads] == [100, 100, 5]
    assert fake_store.save_already_pushed.call_count == 205
