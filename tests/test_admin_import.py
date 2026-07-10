from pathlib import Path
import sys
from unittest.mock import Mock

import pytest
import requests

sys.path.append(str(Path(__file__).resolve().parents[1] / "scraper_framework"))

from admin_import import AdminPermitImportClient


def test_build_payload_from_mongo_batch_preserves_raw_items() -> None:
    client = AdminPermitImportClient(base_url="https://coverage.example.com", token="secret")

    batch_document = {
        "adapter_name": "accela",
        "state_name": "FL",
        "county_name": "Polk County",
        "agency_key": "POLKCO",
        "module_name": "Building",
        "source_url": "https://aca-prod.accela.com/POLKCO/Cap/CapHome.aspx?module=Building",
        "raw_items": [
            {
                "record_number": "BLD-26-0525706",
                "record_type": "Residential New Construction and Additions",
                "address": "1318 W Arch St, Tampa, FL 33607",
                "status": "In Process",
                "date": "06/08/2026",
                "expiration_date": "12/05/2026",
                "description": "optional",
            }
        ],
    }

    payload = client.build_payload_from_mongo_batch(
        batch_document,
        fips="12105",
        import_run_id="python-2026-07-10T12-00-00Z",
    )

    assert payload["provider"] == "accela"
    assert payload["state"] == "FL"
    assert payload["county"] == "Polk County"
    assert payload["fips"] == "12105"
    assert payload["agency"] == "POLKCO"
    assert payload["module"] == "Building"
    assert payload["exclude_tmp"] is True
    assert payload["exclude_statuses"] == ["Withdrawn"]
    assert payload["records"][0]["permit_type"] == "Residential New Construction and Additions"
    assert payload["records"][0]["raw"] == batch_document["raw_items"][0]


def test_build_payload_from_permit_documents_uses_accela_raw_fallbacks() -> None:
    client = AdminPermitImportClient(base_url="https://coverage.example.com", token="secret")

    permit_documents = [
        {
            "adapter_name": "accela",
            "state_name": "FL",
            "county_name": "Cooper City",
            "agency_key": "COOPER_CITY",
            "module_name": "Building",
            "source_url": "https://aca-prod.accela.com/COOPER/Cap/CapHome.aspx?module=Building&TabName=Building",
            "normalized_data": {
                "record_number": "26TMP-003261",
                "status": "N/A",
                "address": None,
                "record_type": "Building Permit Application",
                "description": "",
                "issue_date": "07/09/2026",
            },
            "raw_data": {
                "date": "07/09/2026",
                "record_number": "26TMP-003261",
                "record_type": "Building Permit Application",
                "project_name": "",
                "description": "",
                "address": None,
                "status": "N/A",
                "expiration_date": "",
            },
        }
    ]

    payload = client.build_payload_from_permit_documents(
        permit_documents,
        import_run_id="python-2026-07-10T12-00-00Z",
    )

    assert payload["provider"] == "accela"
    assert payload["state"] == "FL"
    assert payload["county"] == "Cooper City"
    assert payload["agency"] == "COOPER_CITY"
    assert payload["module"] == "Building"
    assert payload["records"][0] == {
        "record_number": "26TMP-003261",
        "permit_type": "Building Permit Application",
        "status": "N/A",
        "date": "07/09/2026",
        "raw": permit_documents[0]["raw_data"],
    }


def test_build_record_prefers_raw_record_type_over_bad_normalized_record_type() -> None:
    client = AdminPermitImportClient(base_url="https://coverage.example.com", token="secret")

    record = client.build_record(
        {
            "record_number": "BPR-26-0061",
            "record_type": "Alexander",
            "description": "New residential construction-SFD",
            "issue_date": "7/8/2026",
        },
        raw_data={
            "record_number": "BPR-26-0061",
            "record_type": "New Residential or Commercial",
            "issue_date": "7/8/2026",
            "description": "New residential construction-SFD",
            "address": "1531 BOSTON RD",
            "status": "Additional Information Requested",
        },
    )

    assert record["permit_type"] == "New Residential or Commercial"
    assert record["date"] == "7/8/2026"
    assert record["status"] == "Additional Information Requested"
    assert record["address"] == "1531 BOSTON RD"

def test_push_payload_posts_to_admin_import_endpoint() -> None:
    session = requests.Session()
    session.post = Mock()
    session.post.return_value = Mock(
        raise_for_status=Mock(),
        content=b'{"job_id":"abc-123"}',
        json=Mock(return_value={"job_id": "abc-123"}),
    )
    client = AdminPermitImportClient(
        base_url="https://coverage.example.com",
        token="secret",
        session=session,
        timeout_seconds=45,
    )

    response = client.push_payload(
        {
            "state": "FL",
            "county": "Polk County",
            "records": [{"record_number": "BLD-26-0525706"}],
        }
    )

    session.post.assert_called_once_with(
        "https://coverage.example.com/api/admin/permits/import",
        json={
            "state": "FL",
            "county": "Polk County",
            "records": [{"record_number": "BLD-26-0525706"}],
        },
        timeout=45,
    )
    assert session.headers["Authorization"] == "Bearer secret"
    assert response == {"job_id": "abc-123"}


def test_push_payload_logs_response_body(monkeypatch: pytest.MonkeyPatch) -> None:
    session = requests.Session()
    session.post = Mock()
    session.post.return_value = Mock(
        raise_for_status=Mock(),
        content=b'{"job_id":"abc-123","received":1}',
        json=Mock(return_value={"job_id": "abc-123", "received": 1}),
    )
    log_info = Mock()
    monkeypatch.setattr("admin_import.logger.info", log_info)

    client = AdminPermitImportClient(
        base_url="https://coverage.example.com",
        token="secret",
        session=session,
        timeout_seconds=45,
    )

    client.push_payload(
        {
            "state": "FL",
            "county": "Polk County",
            "records": [{"record_number": "BLD-26-0525706"}],
        }
    )

    assert any(
        call.args[0] == "Admin API response body: %s"
        and call.args[1] == {"job_id": "abc-123", "received": 1}
        for call in log_info.call_args_list
    )


def test_push_payload_requires_token() -> None:
    client = AdminPermitImportClient(base_url="https://coverage.example.com", token="")

    with pytest.raises(ValueError, match="token is required"):
        client.push_payload({"state": "FL", "county": "Polk County", "records": []})
