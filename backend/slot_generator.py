from models import (ShiftSlot, Office, CustomRestriction,
    get_days_in_month, get_nth_tuesdays, get_weekend_blocks,
    get_call_balance_group)
from typing import List, Optional

SHIFT_TIMES = {
    "office_am": ("08:00", "12:00"),
    "office_pm": ("13:00", "17:00"),
    "office_late": ("13:30", "18:30"),
    "call_day": ("07:00", "19:00"),
    "call_night": ("19:00", "07:00"),
    "surgical_am": ("07:00", "12:00"),
    "surgical_hosp_pm": ("13:00", "17:00"),
}

def _resolve_day_off_set(day_off_dates) -> set:
    if isinstance(day_off_dates, dict):
        entries = [e for v in day_off_dates.values() if isinstance(v, list) for e in v]
    else:
        entries = list(day_off_dates)
    dates = set()
    for e in entries:
        if isinstance(e, str):
            dates.add(e)
        elif isinstance(e, dict) and 'date' in e:
            if e.get('period', 'all_day') == 'all_day':
                dates.add(e['date'])
    return dates


def generate_slots(
    year: int,
    month: int,
    offices: List[Office],
    day_off_dates,
    custom_restrictions: List[CustomRestriction]
) -> List[ShiftSlot]:
    """
    Generate all assignable ShiftSlot objects for the given month.
    month is 0-indexed
    Returns a flat list. No doctor or availability logic here.
    day_off_dates can be List[str] or Dict[str, List[str]] (per-doctor).
    For slot generation, we use the global union of all day-off dates.
    """
    day_off_set = _resolve_day_off_set(day_off_dates)
    days = get_days_in_month(year, month)
    restricted_tuesdays = set(get_nth_tuesdays(year, month))
    weekend_blocks = get_weekend_blocks(year, month)
    hospital = next((o for o in offices if o.is_hospital), None)
    non_hospital = [o for o in offices if not o.is_hospital]
    slots = []
    for day in days:
        date = day['date']
        is_day_off = date in day_off_set
        is_weekend = day['is_weekend']
        is_tuesday = day['is_tuesday']
        is_restricted_tue = date in restricted_tuesdays
        is_mon_or_thu = day['is_monday'] or day['is_thursday']
        is_surgical_day = day['day_of_week'] in [1, 2, 3]

        if hospital and not is_weekend:
            cap = _get_capacity(hospital, date, "call_day", custom_restrictions, 1)
            slots.append(ShiftSlot(
                slot_id=f"{date}_{hospital.id}_call_day",
                date=date, office_id=hospital.id, shift_type="call_day",
                start_time="07:00", end_time="19:00", max_doctors=cap,
                call_balance_group=get_call_balance_group(date, "call_day")
            ))
            cap = _get_capacity(hospital, date, "call_night", custom_restrictions, 1)
            bg = get_call_balance_group(date, "call_night")
            slots.append(ShiftSlot(
                slot_id=f"{date}_{hospital.id}_call_night",
                date=date, office_id=hospital.id, shift_type="call_night",
                start_time="19:00", end_time="07:00", max_doctors=cap,
                call_balance_group=bg
            ))

        if hospital and day['day_of_week'] == 5:
            block = next((b for b in weekend_blocks if b.saturday == date), None)
            if block:
                slots.append(ShiftSlot(
                    slot_id=f"{date}_{hospital.id}_call_weekend",
                    date=date, office_id=hospital.id, shift_type="call_weekend",
                    start_time="00:00", end_time="23:59", max_doctors=1,
                    is_weekend=True,
                    call_balance_group="weekend_block"
                ))
                slots.append(ShiftSlot(
                    slot_id=f"{block.sunday}_{hospital.id}_call_weekend_sun",
                    date=block.sunday, office_id=hospital.id,
                    shift_type="call_weekend_sun",
                    start_time="00:00", end_time="23:59",
                    max_doctors=1, is_weekend=True,
                    call_balance_group="weekend_block"
                ))

        if is_day_off or is_weekend:
            continue

        for office in non_hospital:
            for stype in ["office_am", "office_pm"]:
                cap = _get_capacity(office, date, stype, custom_restrictions, office.max_per_shift)
                slots.append(ShiftSlot(
                    slot_id=f"{date}_{office.id}_{stype}",
                    date=date, office_id=office.id, shift_type=stype,
                    start_time=SHIFT_TIMES[stype][0], end_time=SHIFT_TIMES[stype][1],
                    max_doctors=cap
                ))
            if is_mon_or_thu:
                cap = _get_capacity(office, date, "office_late", custom_restrictions, office.max_per_shift)
                slots.append(ShiftSlot(
                    slot_id=f"{date}_{office.id}_office_late",
                    date=date, office_id=office.id, shift_type="office_late",
                    start_time="13:30", end_time="18:30", max_doctors=cap
                ))

        if hospital:
            for stype in ["office_am", "office_pm"]:
                cap = _get_capacity(hospital, date, stype, custom_restrictions, hospital.max_per_shift)
                is_restricted = is_tuesday and is_restricted_tue
                if is_restricted:
                    cap = min(cap, hospital.restricted_tuesday_max)
                slots.append(ShiftSlot(
                    slot_id=f"{date}_{hospital.id}_{stype}",
                    date=date, office_id=hospital.id, shift_type=stype,
                    start_time=SHIFT_TIMES[stype][0], end_time=SHIFT_TIMES[stype][1],
                    max_doctors=cap,
                    is_restricted_tuesday=is_restricted
                ))
            if is_mon_or_thu:
                cap = _get_capacity(hospital, date, "office_late", custom_restrictions, hospital.max_per_shift)
                slots.append(ShiftSlot(
                    slot_id=f"{date}_{hospital.id}_office_late",
                    date=date, office_id=hospital.id, shift_type="office_late",
                    start_time="13:30", end_time="18:30", max_doctors=cap
                ))

        if hospital and is_surgical_day:
            slots.append(ShiftSlot(
                slot_id=f"{date}_{hospital.id}_surgical_am",
                date=date, office_id=hospital.id, shift_type="surgical_am",
                start_time="07:00", end_time="12:00", max_doctors=1
            ))
            slots.append(ShiftSlot(
                slot_id=f"{date}_{hospital.id}_surgical_hosp_pm",
                date=date, office_id=hospital.id, shift_type="surgical_hosp_pm",
                start_time="13:00", end_time="17:00", max_doctors=1
            ))

    return slots

def _get_capacity(
    office: Office,
    date: str,
    shift_type: str,
    custom_restrictions: List[CustomRestriction],
    default: int
) -> int:
    """
    Returns the effective doctor capacity for one combination.
    Custom restrictions take highest priority over the office default.
    If no custom restriction matches, return default.
    """
    for cr in custom_restrictions:
        if cr.date == date and cr.office_id == office.id and cr.shift_type == shift_type:
            return cr.max_override
    return default

def get_slot_by_id(slots: List[ShiftSlot], slot_id: str) -> Optional[ShiftSlot]:
    """
    O(n) lookup. For repeated lookups in hot paths, build a dict externally:
    slot_map = {s.slot_id: s for s in slots}
    """
    return next((s for s in slots if s.slot_id == slot_id), None)
