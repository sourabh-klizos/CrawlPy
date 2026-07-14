from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scraper_framework.adapters.tyler_energov_import.helpers import (
    build_county_collection_name,
    build_normalized_record,
    slugify,
)


def test_slugify_collapses_non_alphanumeric_sequences() -> None:
    assert slugify("Person County, NC") == "person_county_nc"


def test_build_county_collection_name_uses_county_and_state() -> None:
    assert (
        build_county_collection_name("Person County", "North Carolina")
        == "person_county_north_carolina_tyler_energov_raw"
    )


def test_build_normalized_record_picks_common_tyler_fields() -> None:
    record = {
        "PermitNumber": "PRM-123",
        "PermitTypeName": "Residential Building",
        "Status": "Issued",
        "Description": "New single family home",
        "FullAddress": "123 Main St",
        "ParcelNumber": "999-99-999",
        "ApplicationDate": "2026-07-01",
        "IssuedDate": "2026-07-10",
    }

    normalized = build_normalized_record(record, "permit-type-1")

    assert normalized == {
        "permit_type_id": "permit-type-1",
        "permit_number": "PRM-123",
        "permit_type": "Residential Building",
        "status": "Issued",
        "description": "New single family home",
        "address": "123 Main St",
        "parcel_number": "999-99-999",
        "applied_date": "2026-07-01",
        "issued_date": "2026-07-10",
    }


def test_build_normalized_record_handles_result_entity_results_shape() -> None:
    record = {
        "CaseNumber": "BLDC-000108-2025",
        "CaseType": "Building New Construction (Commercial)",
        "CaseStatus": "Issued",
        "ProjectName": "",
        "AddressDisplay": "909 Stans Way Rougemont NC 27572",
        "MainParcel": "A76 15",
        "ApplyDate": "2025-12-10T13:04:41",
        "IssueDate": "2026-01-20T12:39:12",
    }

    normalized = build_normalized_record(record, "permit-type-2")

    assert normalized == {
        "permit_type_id": "permit-type-2",
        "permit_number": "BLDC-000108-2025",
        "permit_type": "Building New Construction (Commercial)",
        "status": "Issued",
        "description": None,
        "address": "909 Stans Way Rougemont NC 27572",
        "parcel_number": "A76 15",
        "applied_date": "2025-12-10T13:04:41",
        "issued_date": "2026-01-20T12:39:12",
    }
