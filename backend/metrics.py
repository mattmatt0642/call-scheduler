from typing import List, Dict
from models import (DoctorProfile, Office, ShiftSlot, Assignment,
                    ScheduleCounts, get_call_balance_group, is_friday)


def gini(values: List[float]) -> float:
    """
    Gini coefficient. 0.0 = perfect equality. 1.0 = maximum inequality.
    Returns 0.0 for empty or all-zero lists.
    """
    if not values or sum(values) == 0:
        return 0.0
    n = len(values)
    s = sorted(values)
    total = sum(s)
    numerator = sum((2 * (i + 1) - n - 1) * v for i, v in enumerate(s))
    return numerator / (n * total)


def compute_counts(
    doctors: List[DoctorProfile],
    offices: List[Office],
    assignments: List[Assignment],
    slots: List[ShiftSlot],
    historical_balance: Dict[str, Dict]
) -> Dict[str, ScheduleCounts]:
    """
    Compute per-doctor counts for this month and cumulative totals.
    Returns dict of doctor_id -> ScheduleCounts.
    Weekend blocks counted once per Saturday slot (not again for Sunday).
    preferred_day_call_rate: fraction of weekday calls on preferred days.
        Excludes friday_night calls (preferences don't apply there).
        None if the doctor has no preferred_call_days set.
    """
    from datetime import date as dt_class

    slot_map = {s.slot_id: s for s in slots}

    this_month: Dict[str, Dict] = {}
    for doc in doctors:
        this_month[doc.id] = {
            'weekday_day_calls':   0,
            'weekday_night_calls': 0,
            'friday_night_calls':  0,
            'weekend_blocks':      0,
            'total_sessions':      0,
            'am_sessions':         0,
            'pm_sessions':         0,
            'late_sessions':       0,
            'office_visits':       {o.id: 0 for o in offices},
            'preferred_calls':     0,
            'weekday_call_total':  0,
        }

    weekend_seen = set()

    for a in assignments:
        slot = slot_map.get(a.slot_id)
        if not slot or a.doctor_id not in this_month:
            continue
        c = this_month[a.doctor_id]
        bg = get_call_balance_group(slot.date, slot.shift_type)
        doc = next((d for d in doctors if d.id == a.doctor_id), None)

        if slot.shift_type == "call_day":
            c['weekday_day_calls'] += 1
            c['weekday_call_total'] += 1
            if doc and doc.preferred_call_days:
                dow = dt_class.fromisoformat(slot.date).weekday()
                if dow in doc.preferred_call_days:
                    c['preferred_calls'] += 1

        elif slot.shift_type == "call_night":
            if bg == "friday_night":
                c['friday_night_calls'] += 1
            else:
                c['weekday_night_calls'] += 1
                c['weekday_call_total'] += 1
                if doc and doc.preferred_call_days:
                    dow = dt_class.fromisoformat(slot.date).weekday()
                    if dow in doc.preferred_call_days:
                        c['preferred_calls'] += 1

        elif slot.shift_type == "call_weekend":
            key = (a.doctor_id, slot.date)
            if key not in weekend_seen:
                weekend_seen.add(key)
                c['weekend_blocks'] += 1

        elif slot.shift_type in ("office_am", "surgical_am", "surgical_hosp_pm"):
            c['am_sessions'] += 1
            c['total_sessions'] += 1
            c['office_visits'][slot.office_id] = \
                c['office_visits'].get(slot.office_id, 0) + 1

        elif slot.shift_type == "office_pm":
            c['pm_sessions'] += 1
            c['total_sessions'] += 1
            c['office_visits'][slot.office_id] = \
                c['office_visits'].get(slot.office_id, 0) + 1

        elif slot.shift_type == "office_late":
            c['late_sessions'] += 1
            c['total_sessions'] += 1
            c['office_visits'][slot.office_id] = \
                c['office_visits'].get(slot.office_id, 0) + 1

    # Build ScheduleCounts with cumulative totals
    result = {}
    session_counts = [this_month[d.id]['total_sessions'] for d in doctors]
    sess_gini = gini(session_counts)

    eligible = [d for d in doctors if d.hospital_call_eligible]
    call_counts_per_type = {
        g: [this_month[d.id].get(
            {'weekday_day': 'weekday_day_calls',
             'weekday_night': 'weekday_night_calls',
             'friday_night': 'friday_night_calls',
             'weekend_block': 'weekend_blocks'}[g], 0)
            for d in eligible]
        for g in ('weekday_day', 'weekday_night', 'friday_night', 'weekend_block')
    }
    call_gini_val = gini([
        sum(call_counts_per_type[g][i] for g in call_counts_per_type)
        for i in range(len(eligible))
    ]) if eligible else 0.0

    for doc in doctors:
        h = historical_balance.get(doc.id, {})
        c = this_month[doc.id]
        wc = c['weekday_call_total']
        pref_rate = (c['preferred_calls'] / wc
                     if wc > 0 and doc.preferred_call_days else None)
        result[doc.id] = ScheduleCounts(
            doctor_id=doc.id,
            doctor_name=doc.name,
            weekday_day_calls=c['weekday_day_calls'],
            weekday_night_calls=c['weekday_night_calls'],
            friday_night_calls=c['friday_night_calls'],
            weekend_blocks=c['weekend_blocks'],
            total_calls=(c['weekday_day_calls'] + c['weekday_night_calls'] +
                         c['friday_night_calls'] + c['weekend_blocks']),
            total_sessions=c['total_sessions'],
            am_sessions=c['am_sessions'],
            pm_sessions=c['pm_sessions'],
            late_sessions=c['late_sessions'],
            office_visit_counts=c['office_visits'],
            cumulative_weekday_day=h.get('weekday_day', 0) + c['weekday_day_calls'],
            cumulative_weekday_night=h.get('weekday_night', 0) + c['weekday_night_calls'],
            cumulative_friday_night=h.get('friday_night', 0) + c['friday_night_calls'],
            cumulative_weekend_blocks=h.get('weekend_blocks', 0) + c['weekend_blocks'],
            cumulative_sessions=h.get('total_sessions', 0) + c['total_sessions'],
            preferred_day_call_rate=pref_rate,
            call_gini=call_gini_val,
            session_gini=sess_gini,
        )

    return result