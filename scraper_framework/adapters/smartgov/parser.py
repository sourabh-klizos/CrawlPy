from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


TABLE_SELECTORS = [
    "#ctl00_PlaceHolderMain_dgvPermitList_gdvPermitList",
    "#ctl00_PlaceHolderMain_DataGrid",
    ".ACA_GridView",
    "table.table",
    "table",
]
SMARTGOV_RECORD_NUMBER_RE = re.compile(r"^(?:[A-Z]+-)?\d{2,4}(?:-\d{2,})+")
SMARTGOV_DETAIL_ACTION_RE = re.compile(
    r"(https?://[^\s'\"<>]+/PermittingPublic/PermitLandingPagePublic/Index/[^\s'\"<>]+"
    r"|/?PermittingPublic/PermitLandingPagePublic/Index/[^\s'\"<>]+"
    r"|Detail/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


def parse_rows(soup: BeautifulSoup, source_url: str) -> list[dict[str, Any]]:
    print("Parsing search results table...")

    table_elements = []
    for selector in TABLE_SELECTORS:
        table_elements = soup.select(selector)
        if table_elements:
            print(f"Found result table with selector: {selector}")
            break

    if not table_elements:
        print("No data table found on the page. Trying SmartGov result list parser...")
        records = parse_result_list(soup, source_url)
        print(f"Successfully scraped {len(records)} records from result list.")
        return records

    records: list[dict[str, Any]] = []
    for table_element in table_elements:
        headers = [
            header.get_text(" ", strip=True)
            for header in table_element.select("tr th")
        ]
        header_map = {header.lower(): index for index, header in enumerate(headers)}
        rows = table_element.select("tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even")
        if not rows:
            rows = [row for row in table_element.select("tr") if row.find_all("td")]

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue

            try:
                raw_columns = _raw_columns_from_cells(cells, headers, source_url)
                date = _first_cell_text(
                    cells,
                    header_map,
                    ("issued on", "issue date", "date"),
                )

                record_num = None
                record_link = None
                record_index = _find_first_index(
                    header_map,
                    ("application number", "record number", "permit number"),
                )
                if record_index is not None and record_index < len(cells):
                    link_tag = cells[record_index].find("a")
                    if link_tag:
                        raw_link = link_tag.get("href", "").strip()
                        record_link = _smartgov_detail_link(link_tag, source_url) or _normalized_link(
                            raw_link,
                            source_url,
                        )

                        span_tag = link_tag.find("span")
                        record_num = span_tag.text.strip() if span_tag else link_tag.get_text(" ", strip=True)
                    else:
                        span_tag = cells[record_index].find("span")
                        record_num = (
                            span_tag.text.strip()
                            if span_tag
                            else cells[record_index].get_text(" ", strip=True)
                        )

                record_type = _first_cell_text(cells, header_map, ("type", "record type"))
                project_name = _cell_text(cells, header_map, "project name")
                description = _first_cell_text(
                    cells,
                    header_map,
                    ("description", "scope of work", "project name"),
                )
                address = _cell_text(cells, header_map, "address")
                status = _cell_text(cells, header_map, "status")
                expiration_date = _cell_text(cells, header_map, "expiration date")
                action = _cell_text(cells, header_map, "action")
                if record_link is None:
                    record_link = _first_link_url(cells, source_url)

                records.append(
                    {
                        "date": date,
                        "issue_date": date,
                        "record_number": record_num,
                        "detail_link": record_link,
                        "record_type": record_type,
                        "project_name": project_name,
                        "description": description,
                        "address": address,
                        "action": action,
                        "status": status or "N/A",
                        "expiration_date": expiration_date,
                        "raw_columns": raw_columns,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                print(f"Error parsing row elements: {exc}. Skipping row fields.")
                continue

    if not records:
        print("No records found in table parser. Trying SmartGov result list parser...")
        records = parse_result_list(soup, source_url)

    print(f"Successfully scraped {len(records)} records from page.")
    return records


def parse_result_list(soup: BeautifulSoup, source_url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_record_numbers: set[str] = set()

    for link_tag in soup.find_all("a", href=True):
        record_number = link_tag.get_text(" ", strip=True)
        if not SMARTGOV_RECORD_NUMBER_RE.match(record_number):
            continue
        if record_number in seen_record_numbers:
            continue

        seen_record_numbers.add(record_number)
        detail_link = _smartgov_detail_link(link_tag, source_url) or _normalized_link(
            link_tag["href"],
            source_url,
        )
        container = _result_container(link_tag)
        container_text = _clean_text(container.get_text("\n", strip=True)) if container else ""
        lines = [
            line.strip()
            for line in container_text.splitlines()
            if line.strip() and line.strip() != record_number
        ]

        record_type = lines[0] if lines else None
        status, issue_date = _parse_status_date(lines)
        address = _first_matching_line(lines, (r"\d+\s+.+",))
        city_state = _first_matching_line(lines, (r".+,\s*[A-Z]{2}(?:\s+\d{5})?$",))
        people = [
            line
            for line in lines
            if line not in {record_type, status, issue_date, address, city_state}
            and not re.search(r"\d{1,2}/\d{1,2}/\d{4}", line)
        ]

        raw_columns = {
            "application_number": record_number,
            "detail_action": detail_link,
            "type": record_type,
            "status": status,
            "issued_on": issue_date,
            "address": address,
            "city_state": city_state,
        }
        if people:
            raw_columns["applicant"] = people[0]
        if len(people) > 1:
            raw_columns["contractor"] = people[1]

        records.append(
            {
                "date": issue_date,
                "issue_date": issue_date,
                "record_number": record_number,
                "detail_link": detail_link,
                "record_type": record_type,
                "description": record_type,
                "address": address,
                "status": status or "N/A",
                "applicant": people[0] if people else None,
                "contractor": people[1] if len(people) > 1 else None,
                "raw_columns": raw_columns,
            }
        )

    return records


def parse_detail_fields(soup: BeautifulSoup) -> dict[str, Any]:
    fields: dict[str, Any] = {}

    title = soup.find(["h1", "h2", "h3"])
    if title:
        fields["detail_title"] = title.get_text(" ", strip=True)
    fields.update(_parse_header_summary(soup))

    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue
        key = _normalize_key(cells[0].get_text(" ", strip=True))
        value = cells[1].get_text(" ", strip=True)
        if key and value:
            fields[key] = value

    labels = soup.select("label, .control-label, .field-label, .display-label, dt")
    for label in labels:
        label_text = label.get_text(" ", strip=True)
        key = _normalize_key(label_text)
        if not key:
            continue

        value = None
        label_for = label.get("for")
        if label_for:
            control = soup.find(id=label_for)
            if control is not None:
                value = _element_value(control)

        if not value:
            value = _nearby_value(label)

        if value:
            fields[key] = value

    for label_value in soup.select("input, textarea, select"):
        key = _input_key(label_value, soup)
        value = _element_value(label_value)
        if key and value:
            fields[key] = value

    fields.update(_parse_project_information(soup))
    fields.update(_parse_fee_summary(soup))
    fields.update(_parse_detail_sections(soup))

    return fields


def merge_detail_fields(record: dict[str, Any], detail_fields: dict[str, Any]) -> dict[str, Any]:
    raw_columns = dict(record.get("raw_columns") or {})
    raw_columns.update(detail_fields)

    merged = {
        **record,
        "raw_columns": raw_columns,
        "record_number": record.get("record_number") or raw_columns.get("record_number"),
        "status": _first_present(
            raw_columns,
            ("status", "process_status", "record_status"),
        )
        or record.get("status"),
        "address": record.get("address") or _first_present(
            raw_columns,
            ("address", "location", "site_address", "project_location"),
        ),
        "record_type": record.get("record_type") or raw_columns.get("detail_title"),
        "description": record.get("description") or _first_present(
            raw_columns,
            ("scope_of_work", "project_description", "description", "detail_title"),
        ),
        "issue_date": record.get("issue_date") or _first_present(
            raw_columns,
            ("issued", "issued_on", "issue_date"),
        ),
        "applicant": record.get("applicant") or raw_columns.get("applicant"),
        "contractor": record.get("contractor") or _first_present(
            raw_columns,
            (
                "contractor",
                "contractor_company_name",
                "general_contractor_name",
                "electrical_contractor_name",
            ),
        ),
        "owner": record.get("owner") or _first_present(
            raw_columns,
            ("owner", "property_owner_name", "property owner"),
        ),
        "parcel": record.get("parcel") or _first_present(
            raw_columns,
            ("parcel", "parcel_number", "parcel number"),
        ),
        "valuation": record.get("valuation") or _first_present(
            raw_columns,
            ("valuation", "estimated_cost_of_project", "estimated cost of project"),
        ),
        "scope_of_work": record.get("scope_of_work") or _first_present(
            raw_columns,
            ("scope_of_work", "description"),
        ),
        "number_of_units": record.get("number_of_units") or raw_columns.get("number_of_units"),
    }
    return merged


def _find_index(header_map: dict[str, int], header_name: str) -> int | None:
    return header_map.get(header_name.lower())


def _find_first_index(header_map: dict[str, int], header_names: tuple[str, ...]) -> int | None:
    for header_name in header_names:
        index = _find_index(header_map, header_name)
        if index is not None:
            return index
    return None


def _cell_text(cells: list[Any], header_map: dict[str, int], header_name: str) -> str | None:
    index = _find_index(header_map, header_name)
    if index is None or index >= len(cells):
        return None

    span_tag = cells[index].find("span")
    if span_tag:
        return span_tag.get_text(" ", strip=True)
    return cells[index].get_text(" ", strip=True) or None


def _first_cell_text(
    cells: list[Any],
    header_map: dict[str, int],
    header_names: tuple[str, ...],
) -> str | None:
    for header_name in header_names:
        value = _cell_text(cells, header_map, header_name)
        if value:
            return value
    return None


def _raw_columns_from_cells(cells: list[Any], headers: list[str], source_url: str) -> dict[str, Any]:
    raw_columns: dict[str, Any] = {}
    for index, header in enumerate(headers):
        if index >= len(cells):
            continue

        key = _normalize_key(header)
        if not key:
            continue

        raw_columns[key] = cells[index].get_text(" ", strip=True) or None
        link_tag = cells[index].find("a")
        if link_tag and link_tag.get("href"):
            raw_columns[f"{key}_action"] = _normalized_link(link_tag["href"], source_url)
    return raw_columns


def _first_link_url(cells: list[Any], source_url: str) -> str | None:
    for cell in cells:
        link_tag = cell.find("a")
        if link_tag and link_tag.get("href"):
            return _smartgov_detail_link(link_tag, source_url) or _normalized_link(
                link_tag["href"],
                source_url,
            )
    return None


def _smartgov_detail_link(link_tag: Any, source_url: str) -> str | None:
    attribute_blob = " ".join(
        str(value)
        for value in (
            link_tag.get("href"),
            link_tag.get("onclick"),
            link_tag.get("data-url"),
            link_tag.get("data-href"),
        )
        if value
    )
    match = SMARTGOV_DETAIL_ACTION_RE.search(attribute_blob)
    if not match:
        return None

    raw_link = match.group(1).strip()
    if raw_link.startswith("http"):
        return raw_link
    if raw_link.startswith("Detail/"):
        detail_id = raw_link.removeprefix("Detail/")
        return urljoin(
            source_url,
            f"/PermittingPublic/PermitLandingPagePublic/Index/{detail_id}?_conv=1",
        )
    return urljoin(source_url, f"/{raw_link.lstrip('/')}")


def _normalized_link(raw_link: str | None, source_url: str) -> str | None:
    if not raw_link:
        return None
    raw_link = raw_link.strip()
    if not raw_link or raw_link.lower().startswith("javascript:"):
        return None
    return urljoin(source_url, raw_link)


def _normalize_key(value: str) -> str:
    key = value.strip().lower().rstrip(":")
    key = re.sub(r"[^a-z0-9]+", "_", key)
    return key.strip("_")


def _element_value(element: Any) -> str | None:
    if element.name == "select":
        selected = element.find("option", selected=True)
        if selected is not None:
            return selected.get_text(" ", strip=True) or selected.get("value")
        value = element.get("value")
        if value:
            return str(value).strip()
    if element.name in {"input", "textarea"}:
        value = element.get("value")
        if value:
            return str(value).strip()
    return element.get_text(" ", strip=True) or None


def _nearby_value(label: Any) -> str | None:
    sibling = label.find_next_sibling()
    if sibling is not None:
        value = _element_value(sibling)
        if value and value != label.get_text(" ", strip=True):
            return value

    parent = label.parent
    if parent is not None:
        label_text = label.get_text(" ", strip=True)
        parent_text = parent.get_text(" ", strip=True)
        value = parent_text.replace(label_text, "", 1).strip(" :-")
        if value:
            return value

    return None


def _first_present(values: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = values.get(key)
        if value:
            return value
    return None


def _result_container(link_tag: Any) -> Any:
    current = link_tag
    for _ in range(6):
        current = current.parent
        if current is None:
            return link_tag.parent
        text = current.get_text(" ", strip=True)
        if "Basic Search" in text or "Edit Search" in text:
            return link_tag.parent
        if len(current.find_all("a", href=True)) > 1 and len(text) > 300:
            return link_tag.parent
        if len(text) > 80:
            return current
    return link_tag.parent


def _parse_status_date(lines: list[str]) -> tuple[str | None, str | None]:
    for line in lines:
        match = re.search(r"([A-Za-z ]+),\s*(\d{1,2}/\d{1,2}/\d{4})", line)
        if match:
            return match.group(1).strip(), match.group(2)
    return None, None


def _first_matching_line(lines: list[str], patterns: tuple[str, ...]) -> str | None:
    for line in lines:
        if any(re.fullmatch(pattern, line) for pattern in patterns):
            return line
    return None


def _clean_text(value: str) -> str:
    return re.sub(r"\n{2,}", "\n", value).strip()


def _input_key(element: Any, soup: BeautifulSoup) -> str | None:
    element_id = element.get("id")
    if element_id:
        label = soup.find("label", attrs={"for": element_id})
        if label is not None:
            key = _normalize_key(label.get_text(" ", strip=True))
            if key:
                return key

    aria_label = element.get("aria-label")
    if aria_label:
        return _normalize_key(aria_label)

    name = element.get("name")
    if name:
        parts = re.split(r"[._\-\[\]]+", name)
        key = _normalize_key(parts[-1] if parts else name)
        if key:
            return key

    parent = element.parent
    if parent is not None:
        label = parent.find("label")
        if label is not None:
            key = _normalize_key(label.get_text(" ", strip=True))
            if key:
                return key
        previous_text = parent.get_text(" ", strip=True).replace(_element_value(element) or "", "").strip()
        key = _normalize_key(previous_text)
        if key and len(key) <= 80:
            return key

    return None


def _parse_project_information(soup: BeautifulSoup) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    project_header = soup.find(string=re.compile(r"Project Information", re.I))
    if project_header is None:
        return fields

    section = project_header.find_parent()
    for _ in range(4):
        if section is None:
            return fields
        text = section.get_text("\n", strip=True)
        if "Location" in text and ("Created" in text or "Submitted" in text):
            break
        section = section.parent

    text_lines = [
        line.strip()
        for line in section.get_text("\n", strip=True).splitlines()
        if line.strip()
    ]
    for index, line in enumerate(text_lines):
        key = _normalize_key(line)
        if key in {"location", "parcel", "created", "submitted", "approved", "issued", "closed", "application_expires"}:
            next_value = text_lines[index + 1] if index + 1 < len(text_lines) else None
            if next_value and _normalize_key(next_value) not in {
                "location",
                "parcel",
                "created",
                "submitted",
                "approved",
                "issued",
                "closed",
                "application_expires",
            }:
                fields[key] = next_value
    return fields


def _parse_header_summary(soup: BeautifulSoup) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    lines = [
        line.strip()
        for line in soup.get_text("\n", strip=True).splitlines()
        if line.strip()
    ]
    for index, line in enumerate(lines):
        key = _normalize_key(line)
        if key in {"reference_number", "record_number"} and index + 1 < len(lines):
            fields[key] = lines[index + 1]

    statuses = (
        "Additional Information Requested",
        "Payment Pending",
        "Requested",
        "Issued",
        "Closed",
        "Approved",
        "Denied",
        "Expired",
    )
    for line in lines:
        if line in statuses:
            fields["record_status"] = line
            break

    if "record_status" not in fields and fields.get("record_number"):
        record_index = lines.index(fields["record_number"]) if fields["record_number"] in lines else -1
        if record_index >= 0 and record_index + 1 < len(lines):
            candidate = lines[record_index + 1]
            if not candidate.startswith("$") and candidate.lower() != "current fees":
                fields["record_status"] = candidate

    return fields


def _parse_fee_summary(soup: BeautifulSoup) -> dict[str, Any]:
    text = soup.get_text(" ", strip=True)
    match = re.search(r"Current Fees\s*\$?\s*([0-9,]+(?:\.\d{2})?)", text, re.I)
    if not match:
        return {}
    return {"current_fees": match.group(1)}


def _parse_detail_sections(soup: BeautifulSoup) -> dict[str, Any]:
    section_names = (
        "Project Information",
        "Contacts",
        "Details",
        "Parcels",
        "Inspections",
        "Fees",
    )
    sections: dict[str, Any] = {}
    for section_name in section_names:
        header = soup.find(string=re.compile(rf"^\s*{re.escape(section_name)}\s*$", re.I))
        if header is None:
            continue

        container = _section_container(header)
        if container is None:
            continue

        lines = [
            line.strip()
            for line in container.get_text("\n", strip=True).splitlines()
            if line.strip()
        ]
        cleaned_lines = [
            line
            for line in lines
            if line.lower() not in {section_name.lower(), "done"}
            and not line.startswith("▲")
            and not line.startswith("▼")
        ]
        if not cleaned_lines:
            continue

        section_key = _normalize_key(section_name)
        sections[section_key] = {
            "lines": cleaned_lines,
            "fields": _paired_lines_to_fields(cleaned_lines),
        }

    return {"detail_sections": sections} if sections else {}


def _section_container(header: Any) -> Any:
    current = header.find_parent()
    for _ in range(6):
        if current is None:
            return None
        text = current.get_text(" ", strip=True)
        if len(text) > 30 and ("Done" in text or len(text) > 80):
            return current
        current = current.parent
    return header.find_parent()


def _paired_lines_to_fields(lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for index, line in enumerate(lines[:-1]):
        key = _normalize_key(line)
        if not key or len(key) > 60:
            continue
        next_line = lines[index + 1]
        next_key = _normalize_key(next_line)
        if not next_line or next_key in fields:
            continue
        if re.search(r"\d|[$@]", next_line) or len(next_line.split()) <= 8:
            fields.setdefault(key, next_line)
    return fields
