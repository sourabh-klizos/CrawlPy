from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scraper_framework.admin_import import AdminPermitImportClient


def test_build_payload_from_permit_documents_preserves_raw_and_contract_fields() -> None:
    client = AdminPermitImportClient(base_url="https://example.com", token="token")

    payload = client.build_payload_from_permit_documents(
        provider="tyler_energov",
        state="North Carolina",
        county="Person County",
        agency="PERSON_COUNTY",
        module="Permits",
        source_url="https://example.com/apps/SelfService",
        permit_documents=[
            {
                "normalized_data": {
                    "permit_number": "BLDC-000108-2025",
                    "permit_type": "Building New Construction (Commercial)",
                    "status": "Issued",
                    "address": "909 Stans Way Rougemont NC 27572",
                    "issued_date": "2026-01-20T12:39:12",
                    "applied_date": "2025-12-10T13:04:41",
                    "parcel_number": "A76 15",
                },
                "raw_data": {"CaseNumber": "BLDC-000108-2025", "CaseStatus": "Issued"},
            }
        ],
        fips="37145",
        import_run_id="run-123",
    )

    assert payload["provider"] == "tyler_energov"
    assert payload["state"] == "North Carolina"
    assert payload["county"] == "Person County"
    assert payload["fips"] == "37145"
    assert payload["agency"] == "PERSON_COUNTY"
    assert payload["module"] == "Permits"
    assert payload["source_url"] == "https://example.com/apps/SelfService"
    assert payload["import_run_id"] == "run-123"
    assert payload["exclude_tmp"] is True
    assert payload["exclude_statuses"] == ["Withdrawn"]
    assert payload["records"] == [
        {
            "record_number": "BLDC-000108-2025",
            "permit_type": "Building New Construction (Commercial)",
            "status": "Issued",
            "address": "909 Stans Way Rougemont NC 27572",
            "description": None,
            "issue_date": "2026-01-20T12:39:12",
            "apply_date": "2025-12-10T13:04:41",
            "expiration_date": None,
            "parcel_number": "A76 15",
            "raw": {"CaseNumber": "BLDC-000108-2025", "CaseStatus": "Issued"},
        }
    ]


def test_push_payload_requires_token() -> None:
    client = AdminPermitImportClient(base_url="https://example.com", token="")

    try:
        client.push_payload({"records": []})
    except ValueError as exc:
        assert "ADMIN_API_TOKEN" in str(exc)
    else:
        raise AssertionError("Expected missing token to raise ValueError")
