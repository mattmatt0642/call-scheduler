import csv
import io
from typing import List, Dict


def export_balance_csv(doctors, offices, totals: Dict[str, dict]) -> str:
    """
    Export running balance counts as a CSV string (for download and Excel editing).
    Use csv.QUOTE_ALL so office names with spaces or commas don't break parsing.

    Columns:
        doctor_name, doctor_id,
        weekday_day, weekday_night, friday_night, weekend_blocks,
        total_sessions, am_sessions, pm_sessions, late_sessions,
        {OfficeName}_visits  (one column per non-hospital office)
    """
    # Build fieldnames
    fieldnames = [
        "doctor_name", "doctor_id",
        "weekday_day", "weekday_night", "friday_night", "weekend_blocks",
        "total_sessions", "am_sessions", "pm_sessions", "late_sessions"
    ]
    # non-hospital offices for visit columns
    non_hosp_offices = [o for o in offices if not o.is_hospital]
    office_cols = [f"{o.id}_visits" for o in non_hosp_offices]
    fieldnames.extend(office_cols)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
    writer.writeheader()

    for doc in doctors:
        t = totals.get(doc.id, {})
        row = {
            "doctor_name": doc.name,
            "doctor_id": doc.id,
            "weekday_day": t.get("weekday_day", 0),
            "weekday_night": t.get("weekday_night", 0),
            "friday_night": t.get("friday_night", 0),
            "weekend_blocks": t.get("weekend_blocks", 0),
            "total_sessions": t.get("total_sessions", 0),
            "am_sessions": t.get("am_sessions", 0),
            "pm_sessions": t.get("pm_sessions", 0),
            "late_sessions": t.get("late_sessions", 0),
        }
        office_visits = t.get("office_visits", {})
        for o in non_hosp_offices:
            row[f"{o.id}_visits"] = office_visits.get(o.id, 0)
        writer.writerow(row)

    return output.getvalue()


def import_balance_csv(csv_content: str) -> Dict[str, dict]:
    """
    Parse a previously exported balance CSV back into a historical_balance dict.
    Returns {doctor_id: {weekday_day, weekday_night, ..., office_visits: {name: count}}}.

    Handle missing or empty values gracefully — treat them as 0.
    """
    result = {}
    reader = csv.DictReader(io.StringIO(csv_content))
    for row in reader:
        doc_id = row.get("doctor_id", "")
        if not doc_id:
            continue
        parsed = {}
        int_fields = [
            "weekday_day", "weekday_night", "friday_night",
            "weekend_blocks", "total_sessions", "am_sessions",
            "pm_sessions", "late_sessions"
        ]
        for f in int_fields:
            val = row.get(f, "")
            try:
                parsed[f] = int(val) if val.strip() else 0
            except (ValueError, AttributeError):
                parsed[f] = 0

        # Office visits: any column ending with _visits
        office_visits = {}
        for key, val in row.items():
            if key and key.endswith("_visits"):
                office_id = key[:-7]  # strip "_visits"
                try:
                    office_visits[office_id] = int(val) if val.strip() else 0
                except (ValueError, AttributeError):
                    office_visits[office_id] = 0
        parsed["office_visits"] = office_visits

        result[doc_id] = parsed

    return result


def export_schedule_csv(doctors, offices, assignments, slots) -> str:
    """
    Export the monthly schedule as a human-readable CSV (for Excel handoff).
    One row per calendar day. "-" for unfilled slots.

    Columns:
        Date, Day,
        Call Day (7am-7pm), Call Night (7pm-7am),
        Weekend Call, Surgical AM,
        {OfficeName} AM, {OfficeName} PM, {OfficeName} Late
            (one set per non-hospital office),
        {HospitalName} AM, {HospitalName} PM

    Use csv.QUOTE_ALL throughout.
    """
    # Build mappings
    slot_map = {s.slot_id: s for s in slots}
    # For each slot, find assigned doctor name
    slot_docs = {}
    for a in assignments:
        slot_docs[a.slot_id] = next((d.name for d in doctors if d.id == a.doctor_id), a.doctor_id)

    # Identify hospital office
    hospital = next((o for o in offices if o.is_hospital), None)
    non_hosp = [o for o in offices if not o.is_hospital]

    # Group slots by date and type
    from collections import defaultdict
    date_slots = defaultdict(dict)
    for s in slots:
        date_slots[s.date][s.shift_type] = s

    all_dates = sorted(date_slots.keys())

    # Build columns
    fieldnames = ["Date", "Day"]
    # Call columns always appear
    fieldnames.extend([
        "Call Day (7am-7pm)", "Call Night (7pm-7am)",
        "Weekend Call", "Surgical AM"
    ])
    # Non-hospital office columns
    for o in non_hosp:
        fieldnames.extend([f"{o.name} AM", f"{o.name} PM", f"{o.name} Late"])
    # Hospital office columns
    if hospital:
        fieldnames.extend([f"{hospital.name} AM", f"{hospital.name} PM"])

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
    writer.writeheader()

    for date_str in all_dates:
        from datetime import datetime
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_name = dt.strftime("%A")
        row = {
            "Date": date_str,
            "Day": day_name,
            "Call Day (7am-7pm)": _get_doc_s(date_slots[date_str], "call_day", slot_docs, slot_map),
            "Call Night (7pm-7am)": _get_doc_s(date_slots[date_str], "call_night", slot_docs, slot_map),
            "Weekend Call": _get_doc_s(date_slots[date_str], "call_weekend", slot_docs, slot_map),
            "Surgical AM": _get_doc_s(date_slots[date_str], "surgical_am", slot_docs, slot_map),
        }
        for o in non_hosp:
            am_slot = _find_slot_by_type(date_slots[date_str], "office_am", o.id)
            pm_slot = _find_slot_by_type(date_slots[date_str], "office_pm", o.id)
            late_slot = _find_slot_by_type(date_slots[date_str], "office_late", o.id)
            row[f"{o.name} AM"] = slot_docs.get(am_slot.slot_id, "-") if am_slot else "-"
            row[f"{o.name} PM"] = slot_docs.get(pm_slot.slot_id, "-") if pm_slot else "-"
            row[f"{o.name} Late"] = slot_docs.get(late_slot.slot_id, "-") if late_slot else "-"
        if hospital:
            am_slot = _find_slot_by_type(date_slots[date_str], "office_am", hospital.id)
            pm_slot = _find_slot_by_type(date_slots[date_str], "office_pm", hospital.id)
            row[f"{hospital.name} AM"] = slot_docs.get(am_slot.slot_id, "-") if am_slot else "-"
            row[f"{hospital.name} PM"] = slot_docs.get(pm_slot.slot_id, "-") if pm_slot else "-"
        writer.writerow(row)

    return output.getvalue()


def _get_doc_s(date_slots, shift_type, slot_docs, slot_map):
    """Helper to find a doctor for a given shift_type on a date."""
    for stype, slot in date_slots.items():
        if stype == shift_type or (shift_type == "call_weekend" and stype == "call_weekend_sun"):
            return slot_docs.get(slot.slot_id, "-")
    return "-"


def _find_slot_by_type(date_slots, shift_type, office_id):
    """Find a slot by shift_type and office_id for a date."""
    for stype, slot in date_slots.items():
        if stype == shift_type and slot.office_id == office_id:
            return slot
    return None
