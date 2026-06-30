import os
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from flask import current_app

EXCEL_EPOCH = datetime(1899, 12, 30)
XML_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
_PRESENT_VALUES = {"present", "p", "1", "yes"}
_ABSENT_VALUES = {"absent", "a", "0", "no"}
_CACHE: dict[tuple[str, float], dict[str, dict]] = {}


def _normalize_roll(value) -> str:
    return str(value or "").strip()


def _cell_value(cell, shared_strings: list[str]) -> str:
    value_node = cell.find("a:v", XML_NS)
    if value_node is None:
        return ""
    raw = value_node.text or ""
    if cell.attrib.get("t") == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return ""
    return raw


def _column_from_ref(cell_ref: str) -> str:
    letters = []
    for char in cell_ref:
        if char.isalpha():
            letters.append(char)
        else:
            break
    return "".join(letters)


def _worksheet_rows(path: str):
    with zipfile.ZipFile(path) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in shared_root.findall("a:si", XML_NS):
                shared_strings.append("".join(node.text or "" for node in item.iterfind(".//a:t", XML_NS)))

        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rel_root}
        first_sheet = workbook_root.find("a:sheets", XML_NS)[0]
        target = "xl/" + rel_map[first_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
        sheet_root = ET.fromstring(archive.read(target))
        for row in sheet_root.findall(".//a:sheetData/a:row", XML_NS):
            yield {
                _column_from_ref(cell.attrib.get("r", "")): _cell_value(cell, shared_strings)
                for cell in row.findall("a:c", XML_NS)
            }


def _parse_date_header(raw_value: str):
    raw = str(raw_value or "").strip()
    if not raw:
        return None
    try:
        serial = float(raw)
        return (EXCEL_EPOCH + timedelta(days=serial)).date()
    except ValueError:
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
    return None


def _status_bucket(raw_value: str) -> str | None:
    normalized = str(raw_value or "").strip().lower()
    if normalized in _PRESENT_VALUES:
        return "present"
    if normalized in _ABSENT_VALUES:
        return "absent"
    return None


def load_external_attendance_data(path: str | None = None) -> dict[str, dict]:
    if path is None:
        path = current_app.config.get("EXTERNAL_ATTENDANCE_XLSX", "")
    path = str(path or "").strip()
    if not path:
        return {}

    workbook_path = Path(path)
    if not workbook_path.exists() or workbook_path.suffix.lower() != ".xlsx":
        return {}

    cache_key = (str(workbook_path), workbook_path.stat().st_mtime)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    rows = list(_worksheet_rows(str(workbook_path)))
    if not rows:
        return {}

    header = rows[0]
    date_columns: list[tuple[str, object]] = []
    for column, raw_value in header.items():
        if column in {"A", "B", "C"}:
            continue
        parsed = _parse_date_header(raw_value)
        if parsed is not None:
            date_columns.append((column, parsed))

    results: dict[str, dict] = {}
    for row in rows[1:]:
        roll_number = _normalize_roll(row.get("B"))
        if not roll_number:
            continue

        monthly_summary = defaultdict(lambda: {"present": 0, "total": 0})
        daily_records = []
        for column, attendance_date in date_columns:
            status = _status_bucket(row.get(column, ""))
            if status is None:
                continue
            month_key = attendance_date.strftime("%Y-%m")
            monthly_summary[month_key]["total"] += 1
            if status == "present":
                monthly_summary[month_key]["present"] += 1
            daily_records.append(
                {
                    "date": attendance_date,
                    "status": status,
                }
            )

        monthly_rows = []
        total_present = 0
        total_lectures = 0
        for month_key, values in sorted(monthly_summary.items(), reverse=True):
            percentage = round((values["present"] / values["total"]) * 100, 2) if values["total"] else 0
            monthly_rows.append(
                {
                    "month": datetime.strptime(month_key, "%Y-%m").strftime("%b %Y"),
                    "month_key": month_key,
                    "present": values["present"],
                    "total": values["total"],
                    "percentage": percentage,
                }
            )
            total_present += values["present"]
            total_lectures += values["total"]

        results[roll_number] = {
            "roll_number": roll_number,
            "name": str(row.get("C") or "").strip(),
            "monthly_rows": monthly_rows,
            "total_present": total_present,
            "total_lectures": total_lectures,
            "overall_percentage": round((total_present / total_lectures) * 100, 2) if total_lectures else 0,
            "daily_records": sorted(daily_records, key=lambda item: item["date"], reverse=True),
        }

    _CACHE.clear()
    _CACHE[cache_key] = results
    return results


def get_external_attendance_for_roll(roll_number: str, path: str | None = None) -> dict | None:
    normalized_roll = _normalize_roll(roll_number)
    if not normalized_roll:
        return None
    return load_external_attendance_data(path).get(normalized_roll)



def summarize_external_attendance_for_rolls(roll_numbers, months: int = 6, path: str | None = None) -> dict:
    normalized_rolls = []
    seen = set()
    for value in roll_numbers:
        roll = _normalize_roll(value)
        if roll and roll not in seen:
            seen.add(roll)
            normalized_rolls.append(roll)

    matched_rows = []
    all_rows = load_external_attendance_data(path)
    for roll in normalized_rolls:
        row = all_rows.get(roll)
        if row:
            matched_rows.append(row)

    if not matched_rows:
        return {
            "matched_count": 0,
            "total_present": 0,
            "total_lectures": 0,
            "avg_percentage": 0,
            "labels": [],
            "values": [],
            "peak": 0,
            "monthly_rows": [],
        }

    month_map = defaultdict(lambda: {"present": 0, "total": 0})
    for row in matched_rows:
        for month_row in row.get("monthly_rows", []):
            key = month_row.get("month_key") or month_row.get("month")
            month_map[key]["present"] += month_row.get("present", 0)
            month_map[key]["total"] += month_row.get("total", 0)

    ordered_months = sorted(month_map.keys())
    if months and len(ordered_months) > months:
        ordered_months = ordered_months[-months:]

    monthly_rows = []
    labels = []
    values = []
    for key in ordered_months:
        month_date = datetime.strptime(key, "%Y-%m") if "-" in key else None
        label = month_date.strftime("%b %Y") if month_date else key
        present = month_map[key]["present"]
        total = month_map[key]["total"]
        percentage = round((present / total) * 100, 2) if total else 0
        monthly_rows.append(
            {
                "month": label,
                "month_key": key,
                "present": present,
                "total": total,
                "percentage": percentage,
            }
        )
        labels.append(label)
        values.append(present)

    total_present = sum(row.get("total_present", 0) for row in matched_rows)
    total_lectures = sum(row.get("total_lectures", 0) for row in matched_rows)
    avg_percentage = round(sum(row.get("overall_percentage", 0) for row in matched_rows) / len(matched_rows), 2) if matched_rows else 0

    return {
        "matched_count": len(matched_rows),
        "total_present": total_present,
        "total_lectures": total_lectures,
        "avg_percentage": avg_percentage,
        "labels": labels,
        "values": values,
        "peak": max(values) if values else 0,
        "monthly_rows": list(reversed(monthly_rows)),
    }


def summarize_external_attendance_for_students(students, months: int = 6, path: str | None = None) -> dict:
    return summarize_external_attendance_for_rolls([getattr(student, "roll_number", "") for student in students], months=months, path=path)
