from __future__ import annotations

import re
from typing import Any

from .constants import DEFAULT_COLLECTION_SUFFIX


def slugify(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.strip().lower())).strip("_")


def build_county_collection_name(
    county_name: str,
    state_name: str | None = None,
    suffix: str = DEFAULT_COLLECTION_SUFFIX,
) -> str:
    parts = [county_name]
    if state_name:
        parts.append(state_name)
    parts.append(suffix)
    return "_".join(filter(None, (slugify(part) for part in parts)))


def pick_first_value(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def build_normalized_record(record: dict[str, Any], permit_type_id: str) -> dict[str, Any]:
    return {
        "permit_type_id": permit_type_id,
        "permit_number": pick_first_value(
            record,
            (
                "PermitNumber",
                "PermitNo",
                "RecordNumber",
                "RecordNo",
                "CaseNumber",
                "Number",
                "Id",
            ),
        ),
        "permit_type": pick_first_value(
            record,
            ("PermitType", "PermitTypeName", "Type", "RecordType", "CaseType"),
        ),
        "status": pick_first_value(record, ("Status", "PermitStatus", "RecordStatus", "CaseStatus")),
        "description": pick_first_value(
            record,
            ("Description", "ProjectDescription", "WorkDescription", "ProjectName"),
        ),
        "address": pick_first_value(
            record,
            ("AddressDisplay", "FullAddress", "SiteAddress", "LocationAddress"),
        )
        or (
            record.get("Address", {}).get("FullAddress")
            if isinstance(record.get("Address"), dict)
            else None
        ),
        "parcel_number": pick_first_value(record, ("ParcelNumber", "ParcelNo", "ParcelId", "MainParcel")),
        "applied_date": pick_first_value(record, ("AppliedDate", "ApplicationDate", "SubmitDate", "ApplyDate")),
        "issued_date": pick_first_value(record, ("IssuedDate", "IssueDate")),
    }
