from models import (
    DoctorProfile, Office, ShiftSlot, Assignment, ScheduleInput, ScheduleResult,
    abs_times_overlap, get_days_in_month, get_weekend_blocks,
    get_call_balance_group, is_friday, WeekendCallBlock, CustomRestriction,
    RecurringSlot, OneTimeOverride
)
from slot_generator import generate_slots, get_slot_by_id
from datetime import date as dt_class, timedelta
from collections import defaultdict
from typing import List, Dict, Optional, Tuple


def _get_day_off_set(day_off_dates, doctor_id=None):
    """Resolve day_off_dates to a set of date strings (all_day entries only).
    Supports both flat string arrays and entry objects with period info.
    """
    if day_off_dates is None:
        return set()
    if isinstance(day_off_dates, dict):
        if doctor_id is not None:
            entries = day_off_dates.get(doctor_id, [])
        else:
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


def _get_day_off_entries(day_off_dates, doctor_id):
    """Resolve day_off_dates to a list of entry dicts for a specific doctor.
    Flat strings are wrapped as {date: str, period: 'all_day'}.
    """
    if day_off_dates is None:
        return []
    if isinstance(day_off_dates, dict):
        raw = day_off_dates.get(doctor_id, [])
    else:
        raw = list(day_off_dates)
    entries = []
    for e in raw:
        if isinstance(e, str):
            entries.append({'date': e, 'period': 'all_day'})
        elif isinstance(e, dict) and 'date' in e:
            entries.append(e)
    return entries


SHIFT_PERIODS = {
    "office_am": "morning",
    "office_pm": "afternoon",
    "office_late": "afternoon",
    "call_day": "all_day",
    "call_night": "all_day",
    "surgical_am": "morning",
    "surgical_hosp_pm": "afternoon",
}

SHIFT_TIMES = {
    "office_am": ("08:00", "12:00"),
    "office_pm": ("13:00", "17:00"),
    "office_late": ("13:30", "18:30"),
    "call_day": ("07:00", "19:00"),
    "call_night": ("19:00", "07:00"),
    "surgical_am": ("07:00", "12:00"),
    "surgical_hosp_pm": ("13:00", "17:00"),
}


def _times_overlap(s1, e1, s2, e2):
    def to_min(t):
        h, m = t.split(":")
        return int(h) * 60 + int(m)
    a1, b1 = to_min(s1), to_min(e1)
    a2, b2 = to_min(s2), to_min(e2)
    if b1 <= a1:
        b1 += 24 * 60
    if b2 <= a2:
        b2 += 24 * 60
    return a1 < b2 and a2 < b1


def _is_blocked_by_timeoff(entry, slot_type):
    period = entry.get("period", "all_day")
    if period == "all_day":
        return True
    slot_period = SHIFT_PERIODS.get(slot_type, "all_day")
    if slot_period == "all_day":
        return True
    if period == "morning" and slot_period == "morning":
        return True
    if period == "afternoon" and slot_period == "afternoon":
        return True
    if period == "custom":
        st = entry.get("startTime")
        et = entry.get("endTime")
        shift_times = SHIFT_TIMES.get(slot_type)
        if st and et and shift_times:
            return _times_overlap(shift_times[0], shift_times[1], st, et)
        return True
    return False


def _init_load(doctors, offices):
    """
    Initialize per-doctor load tracking dict.
    Keys: doctor_id -> dict with counts and post_call_since.
    """
    load = {}
    for d in doctors:
        load[d.id] = {
            'weekday_day_calls': 0,
            'weekday_night_calls': 0,
            'friday_night_calls': 0,
            'weekend_blocks': 0,
            'total_sessions': 0,
            'post_call_since': None,
        }
    return load


def _update_load(load, doctor_id, slot, hospital_id):
    """
    Update load tracking after assigning doctor_id to slot.
    - call_day: weekday_day_calls += 1, post_call_since = slot.date
    - call_night: weekday_night_calls or friday_night_calls += 1, post_call_since = slot.date
    - call_weekend: weekend_blocks += 1, post_call_since = slot.date
    - call_weekend_sun: (counted as part of weekend block, no separate increment)
    - office_am/office_pm/office_late/surgical_am/surgical_hosp_pm: total_sessions += 1
    - If slot is at hospital and post_call_since is set, clear post_call_since
    """
    entry = load[doctor_id]
    shift = slot.shift_type
    if shift == 'call_day':
        entry['weekday_day_calls'] += 1
        entry['post_call_since'] = slot.date
    elif shift == 'call_night':
        if slot.call_balance_group == 'friday_night':
            entry['friday_night_calls'] += 1
        else:
            entry['weekday_night_calls'] += 1
        entry['post_call_since'] = slot.date
    elif shift == 'call_weekend':
        entry['weekend_blocks'] += 1
        entry['post_call_since'] = slot.date
    elif shift == 'call_weekend_sun':
        entry['post_call_since'] = slot.date
    elif shift in ('office_am', 'office_pm', 'office_late',
                    'surgical_am', 'surgical_hosp_pm'):
        entry['total_sessions'] += 1
        if slot.office_id == hospital_id and entry['post_call_since'] is not None:
            entry['post_call_since'] = None


def call_debt_with_preference(doc, load, slot, historical_balance):
    """
    Compute a 'debt' score for assigning doc to a call slot.
    Uses preference-weighted scoring for weekday day/night calls.
    Lower is better (more deserving of the assignment).
    """
    entry = load[doc.id]
    bg = slot.call_balance_group
    hist = historical_balance.get(doc.id, {})

    if bg == 'weekday_day':
        current = entry['weekday_day_calls']
        cumulative = hist.get('weekday_day', 0) + current
        remaining = max(0, doc.max_weekday_day_calls - current)
    elif bg == 'weekday_night':
        current = entry['weekday_night_calls']
        cumulative = hist.get('weekday_night', 0) + current
        remaining = max(0, doc.max_weekday_night_calls - current)
    elif bg == 'friday_night':
        current = entry['friday_night_calls']
        cumulative = hist.get('friday_night', 0) + current
        remaining = max(0, doc.max_friday_night_calls - current)
    elif bg == 'weekend_block':
        current = entry['weekend_blocks']
        cumulative = hist.get('weekend_blocks', 0) + current
        remaining = max(0, doc.max_weekend_blocks - current)
    else:
        return 9999

    if remaining <= 0:
        return 9999

    balance_score = cumulative
    if doc.preferred_call_days and bg in ('weekday_day', 'weekday_night'):
        dow = dt_class.fromisoformat(slot.date).weekday()
        if dow in doc.preferred_call_days:
            balance_score -= 0.1
        else:
            balance_score += 0.05

    return balance_score


def call_debt_balance_only(doc, load, slot, historical_balance):
    """
    Compute a 'debt' score for assigning doc to a call slot.
    Uses balance-only scoring (no preference influence).
    Used for friday_night and weekend_block calls.
    """
    entry = load[doc.id]
    bg = slot.call_balance_group
    hist = historical_balance.get(doc.id, {})

    if bg == 'weekday_day':
        current = entry['weekday_day_calls']
        cumulative = hist.get('weekday_day', 0) + current
        remaining = max(0, doc.max_weekday_day_calls - current)
    elif bg == 'weekday_night':
        current = entry['weekday_night_calls']
        cumulative = hist.get('weekday_night', 0) + current
        remaining = max(0, doc.max_weekday_night_calls - current)
    elif bg == 'friday_night':
        current = entry['friday_night_calls']
        cumulative = hist.get('friday_night', 0) + current
        remaining = max(0, doc.max_friday_night_calls - current)
    elif bg == 'weekend_block':
        current = entry['weekend_blocks']
        cumulative = hist.get('weekend_blocks', 0) + current
        remaining = max(0, doc.max_weekend_blocks - current)
    else:
        return 9999

    if remaining <= 0:
        return 9999

    return cumulative


def _is_available(doc_id, slot, assignments, slot_map, load,
                  doc_map, hospital_id, doc_day_off_entries):
    """
    Check if doctor doc_id can be assigned to slot.
    Returns False if:
    - Slot date/period conflicts with doctor's time-off entries
    - Doctor has an overlapping assignment
    - Doctor's allowed_offices doesn't include slot.office_id
    - Post-call restriction (H8): doctor has post_call_since set and
      this slot is not at the hospital
    """
    doc = doc_map.get(doc_id)
    if not doc:
        return False

    for entry in doc_day_off_entries:
        entry_date = entry.get('date') if isinstance(entry, dict) else entry
        if entry_date == slot.date:
            if isinstance(entry, str):
                return False
            if _is_blocked_by_timeoff(entry, slot.shift_type):
                return False

    dow = dt_class.fromisoformat(slot.date).weekday()
    if dow in doc.standing_days_off:
        return False

    if doc.allowed_offices is not None and slot.office_id not in doc.allowed_offices:
        return False

    if slot.shift_type not in ('call_day', 'call_night',
                                'call_weekend', 'call_weekend_sun'):
        if slot.office_id != hospital_id:
            doc_assigns = sorted(
                [(slot_map[a.slot_id], a) for a in assignments if a.doctor_id == doc_id
                 and slot_map[a.slot_id].date <= slot.date],
                key=lambda x: (x[0].date, x[0].start_time)
            )
            all_items = [(s, False) for s, _ in doc_assigns] + [(slot, True)]
            all_items.sort(key=lambda x: (x[0].date, x[0].start_time))
            post_call_restricted = False
            for s, is_current in all_items:
                if post_call_restricted:
                    if is_current:
                        return False
                    if s.shift_type in ('office_am', 'office_pm', 'office_late',
                                        'surgical_am', 'surgical_hosp_pm'):
                        if s.office_id == hospital_id:
                            post_call_restricted = False
                if s.shift_type in ('call_day', 'call_night',
                                    'call_weekend', 'call_weekend_sun'):
                    post_call_restricted = True
            if post_call_restricted:
                return False

    for a in assignments:
        if a.doctor_id != doc_id:
            continue
        other = slot_map.get(a.slot_id)
        if other and abs_times_overlap(slot, other):
            return False

    return True


def expand_recurring_slots(doctors, slots, year, month):
    """
    Expand each doctor's fixed_recurring list into Assignment objects
    for matching slots in the current month.
    A RecurringSlot matches a ShiftSlot if:
    - day_of_week matches
    - office_id matches
    - shift_type matches
    """
    assignments = []
    slot_by_dow = defaultdict(list)
    for s in slots:
        dow = dt_class.fromisoformat(s.date).weekday()
        slot_by_dow[(dow, s.office_id, s.shift_type)].append(s)

    for doc in doctors:
        for rec in doc.fixed_recurring:
            key = (rec.day_of_week, rec.office_id, rec.shift_type)
            for s in slot_by_dow.get(key, []):
                assignments.append(Assignment(
                    doctor_id=doc.id, slot_id=s.slot_id, is_locked=True
                ))
    return assignments


def expand_one_time_overrides(doctors, year, month, slot_id_set):
    """
    Expand each doctor's one_time_overrides into Assignment objects.
    Only include overrides whose slot_id exists in slot_id_set.
    """
    assignments = []
    for doc in doctors:
        for ovr in doc.one_time_overrides:
            slot_id = f"{ovr.date}_{ovr.office_id}_{ovr.shift_type}"
            if slot_id in slot_id_set:
                assignments.append(Assignment(
                    doctor_id=doc.id, slot_id=slot_id, is_locked=True
                ))
    return assignments


def _can_assign_ilp(doc, slot, inp, day_off_dates):
    """
    Quick feasibility check for ILP variable creation.
    Returns True if doc could potentially be assigned to slot
    (not checking overlap — that's handled by ILP constraints).
    """
    if not doc.hospital_call_eligible:
        if slot.shift_type in ('call_day', 'call_night',
                                'call_weekend', 'call_weekend_sun'):
            return False
    if not doc.surgical_assist_eligible:
        if slot.shift_type in ('surgical_am', 'surgical_hosp_pm'):
            return False

    doc_day_off_entries = _get_day_off_entries(day_off_dates, doc.id)
    for entry in doc_day_off_entries:
        entry_date = entry.get('date') if isinstance(entry, dict) else entry
        if entry_date == slot.date:
            if isinstance(entry, str):
                return False
            if _is_blocked_by_timeoff(entry, slot.shift_type):
                return False

    dow = dt_class.fromisoformat(slot.date).weekday()
    if dow in doc.standing_days_off:
        return False

    if doc.allowed_offices is not None and slot.office_id not in doc.allowed_offices:
        return False

    return True


def schedule_greedy(inp: ScheduleInput) -> ScheduleResult:
    """
    Pure greedy scheduler. Assigns call shifts first (balance-driven),
    then fills office sessions. Used as fallback when ILP is unavailable.
    """
    from constraint_checker import validate_schedule, ConstraintViolation
    from metrics import compute_counts, gini

    slots = generate_slots(inp.year, inp.month, inp.offices,
                           inp.day_off_dates, inp.custom_restrictions)
    slot_map = {s.slot_id: s for s in slots}
    hospital_id = None
    for o in inp.offices:
        if o.is_hospital:
            hospital_id = o.id
            break

    slot_id_set = set(slot_map.keys())
    recurring = expand_recurring_slots(inp.doctors, slots, inp.year, inp.month)
    overrides = expand_one_time_overrides(inp.doctors, inp.year, inp.month, slot_id_set)
    all_locked = {(a.doctor_id, a.slot_id)
                  for a in inp.locked_assignments + recurring + overrides}

    assignments = list(inp.locked_assignments + recurring + overrides)
    load = _init_load(inp.doctors, inp.offices)
    doc_map = {d.id: d for d in inp.doctors}
    global_day_off_set = _get_day_off_set(inp.day_off_dates)

    for a in assignments:
        slot = slot_map.get(a.slot_id)
        if slot:
            _update_load(load, a.doctor_id, slot, hospital_id)

    weekend_blocks_list = get_weekend_blocks(inp.year, inp.month)
    paired_sun_ids = set()
    if hospital_id:
        for block in weekend_blocks_list:
            sat_id = f"{block.saturday}_{hospital_id}_call_weekend"
            sun_id = f"{block.sunday}_{hospital_id}_call_weekend_sun"
            if sat_id in slot_map and sun_id in slot_map:
                paired_sun_ids.add(sun_id)

    def _find_eligible(slot, p_sun_id=None):
        existing = [a for a in assignments if a.slot_id == slot.slot_id]
        if len(existing) >= slot.max_doctors:
            return []
        result = []
        for doc in inp.doctors:
            if not doc.hospital_call_eligible:
                continue
            doc_day_off_entries = _get_day_off_entries(inp.day_off_dates, doc.id)
            if not _is_available(doc.id, slot, assignments, slot_map, load,
                                 doc_map, hospital_id, doc_day_off_entries):
                continue
            if slot.shift_type in ('call_day', 'call_night'):
                partner_type = 'call_night' if slot.shift_type == 'call_day' else 'call_day'
                partner_id = f"{slot.date}_{slot.office_id}_{partner_type}"
                if any(a.doctor_id == doc.id and a.slot_id == partner_id for a in assignments):
                    continue
            if p_sun_id:
                sun_slot = slot_map[p_sun_id]
                if not _is_available(doc.id, sun_slot, assignments, slot_map,
                                     load, doc_map, hospital_id, doc_day_off_entries):
                    continue
            if slot.call_balance_group in ('friday_night', 'weekend_block'):
                debt = call_debt_balance_only(doc, load, slot, inp.historical_balance)
            else:
                debt = call_debt_with_preference(doc, load, slot, inp.historical_balance)
            result.append((debt, doc))
        result.sort(key=lambda x: x[0])
        return result

    def _do_assign(slot, doc, p_sun_id=None):
        assignments.append(Assignment(doctor_id=doc.id, slot_id=slot.slot_id))
        _update_load(load, doc.id, slot, hospital_id)
        if p_sun_id and not any(a.slot_id == p_sun_id for a in assignments):
            sun_slot = slot_map[p_sun_id]
            assignments.append(Assignment(doctor_id=doc.id, slot_id=p_sun_id))
            _update_load(load, doc.id, sun_slot, hospital_id)

    # Phase 1: Assign weekend blocks first (they are the most constrained
    # because call_night on Friday overlaps call_weekend on Saturday).
    # Assigning them first prevents friday-night calls from blocking them.
    weekend_call_slots = [s for s in slots
                          if s.shift_type == 'call_weekend']
    weekend_call_slots.sort(key=lambda s: s.date)
    for slot in weekend_call_slots:
        p_sun_id = None
        if hospital_id:
            block = next((b for b in weekend_blocks_list
                          if b.saturday == slot.date), None)
            if block:
                p_sun_id = f"{block.sunday}_{hospital_id}_call_weekend_sun"
                if p_sun_id not in slot_map:
                    p_sun_id = None
        for debt, doc in _find_eligible(slot, p_sun_id):
            if len([a for a in assignments if a.slot_id == slot.slot_id]) >= slot.max_doctors:
                break
            _do_assign(slot, doc, p_sun_id)
            break

    # Phase 2: Assign weekday day/night calls (excluding friday nights)
    weekday_call_slots = [s for s in slots
                          if s.shift_type in ('call_day', 'call_night')
                          and s.call_balance_group != 'friday_night']
    weekday_call_slots.sort(key=lambda s: (s.date, s.start_time))
    for slot in weekday_call_slots:
        for debt, doc in _find_eligible(slot):
            if len([a for a in assignments if a.slot_id == slot.slot_id]) >= slot.max_doctors:
                break
            _do_assign(slot, doc)
            break

    # Phase 3: Assign friday night calls last (they may overlap with
    # already-assigned weekend blocks, so only assign if no conflict)
    friday_night_slots = [s for s in slots
                          if s.shift_type == 'call_night'
                          and s.call_balance_group == 'friday_night']
    friday_night_slots.sort(key=lambda s: s.date)
    for slot in friday_night_slots:
        for debt, doc in _find_eligible(slot):
            if len([a for a in assignments if a.slot_id == slot.slot_id]) >= slot.max_doctors:
                break
            _do_assign(slot, doc)
            break

    # Phase 4: Retry any unfilled call slots (soften max-call limits)
    # If a call slot is still unfilled, try ALL call-eligible doctors
    # regardless of debt score (debt=9999 means over limit, but still
    # assign if no one else can fill it — coverage > balance)
    assigned_call_ids = {a.slot_id for a in assignments}
    unfilled_call_slots = [s for s in slots
                           if s.shift_type in ('call_day', 'call_night',
                                               'call_weekend', 'call_weekend_sun')
                           and s.slot_id not in assigned_call_ids]
    for slot in unfilled_call_slots:
        p_sun_id = None
        if slot.shift_type == 'call_weekend' and hospital_id:
            block = next((b for b in weekend_blocks_list
                          if b.saturday == slot.date), None)
            if block:
                p_sun_id = f"{block.sunday}_{hospital_id}_call_weekend_sun"
                if p_sun_id not in slot_map:
                    p_sun_id = None
        for doc in inp.doctors:
            if not doc.hospital_call_eligible:
                continue
            doc_day_off_entries = _get_day_off_entries(inp.day_off_dates, doc.id)
            if not _is_available(doc.id, slot, assignments, slot_map, load,
                                 doc_map, hospital_id, doc_day_off_entries):
                continue
            if slot.shift_type in ('call_day', 'call_night'):
                partner_type = 'call_night' if slot.shift_type == 'call_day' else 'call_day'
                partner_id = f"{slot.date}_{slot.office_id}_{partner_type}"
                if any(a.doctor_id == doc.id and a.slot_id == partner_id
                       for a in assignments):
                    continue
            if p_sun_id:
                sun_slot = slot_map[p_sun_id]
                if not _is_available(doc.id, sun_slot, assignments, slot_map,
                                     load, doc_map, hospital_id,
                                     doc_day_off_entries):
                    continue
            _do_assign(slot, doc, p_sun_id)
            break

    surgical_slots = [s for s in slots
                      if s.shift_type in ('surgical_am', 'surgical_hosp_pm')]
    for slot in surgical_slots:
        existing = [a for a in assignments if a.slot_id == slot.slot_id]
        if len(existing) >= slot.max_doctors:
            continue
        for doc in inp.doctors:
            if not doc.surgical_assist_eligible:
                continue
            doc_day_off_entries = _get_day_off_entries(inp.day_off_dates, doc.id)
            if not _is_available(doc.id, slot, assignments, slot_map, load,
                                 doc_map, hospital_id, doc_day_off_entries):
                continue
            assignments.append(Assignment(doctor_id=doc.id, slot_id=slot.slot_id))
            _update_load(load, doc.id, slot, hospital_id)
            if slot.shift_type == 'surgical_am':
                pm_id = slot.slot_id.replace('surgical_am', 'surgical_hosp_pm')
                pm_slot = slot_map.get(pm_id)
                if pm_slot and not any(a.slot_id == pm_id for a in assignments):
                    if _is_available(doc.id, pm_slot, assignments, slot_map,
                                     load, doc_map, hospital_id,
                                     doc_day_off_entries):
                        assignments.append(Assignment(doctor_id=doc.id, slot_id=pm_id))
                        _update_load(load, doc.id, pm_slot, hospital_id)
            break

    office_shift_types = ['office_am', 'office_pm', 'office_late']
    days = get_days_in_month(inp.year, inp.month)
    sessions_by_doc_week = defaultdict(lambda: defaultdict(int))

    for day in days:
        if day['is_weekend'] or day['date'] in global_day_off_set:
            continue
        date = day['date']
        week_num = day['week_num']
        day_office_slots = [s for s in slots
                            if s.date == date
                            and s.shift_type in office_shift_types
                            and not any(a.slot_id == s.slot_id
                                        for a in assignments)]
        hosp_slots = [s for s in day_office_slots
                      if s.office_id == hospital_id]
        non_hosp_slots = [s for s in day_office_slots
                          if s.office_id != hospital_id]

        for slot_obj in hosp_slots:
            if any(a.slot_id == slot_obj.slot_id for a in assignments):
                continue
            avail_docs = [d for d in inp.doctors
                          if _is_available(d.id, slot_obj, assignments,
                                           slot_map, load, doc_map,
                                           hospital_id,
                                           _get_day_off_entries(
                                               inp.day_off_dates, d.id))]
            avail_docs.sort(key=lambda d: sessions_by_doc_week[d.id].get(week_num, 0))
            for doc in avail_docs:
                week_count = sessions_by_doc_week[doc.id].get(week_num, 0)
                if week_count >= doc.required_sessions_per_week:
                    continue
                assignments.append(Assignment(doctor_id=doc.id,
                                              slot_id=slot_obj.slot_id))
                _update_load(load, doc.id, slot_obj, hospital_id)
                sessions_by_doc_week[doc.id][week_num] += 1
                break

        for slot_obj in non_hosp_slots:
            if any(a.slot_id == slot_obj.slot_id for a in assignments):
                continue
            avail_docs = [d for d in inp.doctors
                          if _is_available(d.id, slot_obj, assignments,
                                           slot_map, load, doc_map,
                                           hospital_id,
                                           _get_day_off_entries(
                                               inp.day_off_dates, d.id))]
            avail_docs.sort(key=lambda d: sessions_by_doc_week[d.id].get(week_num, 0))
            for doc in avail_docs:
                week_count = sessions_by_doc_week[doc.id].get(week_num, 0)
                if week_count >= doc.required_sessions_per_week:
                    continue
                assignments.append(Assignment(doctor_id=doc.id,
                                              slot_id=slot_obj.slot_id))
                _update_load(load, doc.id, slot_obj, hospital_id)
                sessions_by_doc_week[doc.id][week_num] += 1
                break

    violations = validate_schedule(inp, slots, assignments)

    el = [d for d in inp.doctors if d.hospital_call_eligible]
    call_counts = [
        sum(1 for a in assignments
            if a.doctor_id == d.id
            and slot_map[a.slot_id].call_balance_group in
            ("weekday_day", "weekday_night", "friday_night", "weekend_block"))
        for d in el
    ]
    session_counts = [
        sum(1 for a in assignments
            if a.doctor_id == d.id
            and slot_map[a.slot_id].shift_type in
            ("office_am", "office_pm", "office_late", "surgical_am",
             "surgical_hosp_pm"))
        for d in inp.doctors
    ]
    counts = compute_counts(inp.doctors, inp.offices, assignments, slots,
                            inp.historical_balance)

    return ScheduleResult(
        month_key=f"{inp.year}-{str(inp.month + 1).zfill(2)}",
        assignments=assignments,
        slots=slots,
        solver_status="greedy",
        gini_calls=gini(call_counts) if call_counts else 0.0,
        gini_sessions=gini(session_counts) if session_counts else 0.0,
        unmet_constraints=[{
            'id': v.constraint_id,
            'name': v.constraint_name,
            'severity': v.severity,
            'description': v.description,
            'suggestion': v.suggestion,
            'affected_doctors': v.affected_doctors,
            'affected_dates': v.affected_dates,
        } for v in violations],
        partial=len(violations) > 0,
        counts=counts
    )


def schedule_ilp(inp: ScheduleInput) -> ScheduleResult:
    """
    Hybrid ILP + greedy scheduler. Uses PuLP/CBC to optimally assign call
    shifts and surgical pairs (where balance optimization matters most),
    then uses the greedy logic to fill office sessions.

    Phase 1 (ILP): Assign call_day, call_night, call_weekend, call_weekend_sun,
                    surgical_am, surgical_hosp_pm with balance optimization.
    Phase 2 (Greedy): Fill office sessions using ILP results as locked assignments,
                      respecting H8, H9, H10, weekly quotas.
    """
    try:
        import pulp
    except ImportError:
        result = schedule_greedy(inp)
        result.solver_status = "greedy_fallback (pulp not installed)"
        return result

    try:
        from constraint_checker import validate_schedule, ConstraintViolation
        from metrics import compute_counts, gini
        from datetime import timedelta
        from collections import defaultdict

        slots = generate_slots(inp.year, inp.month, inp.offices,
                               inp.day_off_dates, inp.custom_restrictions)
        slot_map = {s.slot_id: s for s in slots}
        hospital_id = None
        for o in inp.offices:
            if o.is_hospital:
                hospital_id = o.id
                break

        # Expand pre-fills
        slot_id_set = set(slot_map.keys())
        recurring = expand_recurring_slots(inp.doctors, slots, inp.year, inp.month)
        overrides = expand_one_time_overrides(inp.doctors, inp.year, inp.month, slot_id_set)
        all_locked = {(a.doctor_id, a.slot_id)
                      for a in inp.locked_assignments + recurring + overrides}

        # Only consider call and surgical slots for ILP
        ilp_shift_types = {"call_day", "call_night", "call_weekend",
                           "call_weekend_sun", "surgical_am", "surgical_hosp_pm"}
        ilp_slots = [s for s in slots if s.shift_type in ilp_shift_types]
        ilp_slot_set = {s.slot_id for s in ilp_slots}
        slots_by_date = {}
        for slot in slots:
            slots_by_date.setdefault(slot.date, []).append(slot)

        prob = pulp.LpProblem("call_schedule", pulp.LpMinimize)

        day_off_dates = inp.day_off_dates

        # Pre-filter feasible (doc, slot) pairs for ILP slots only
        feasible_pairs = []
        for doc in inp.doctors:
            for slot in ilp_slots:
                if _can_assign_ilp(doc, slot, inp, day_off_dates):
                    feasible_pairs.append((doc.id, slot.slot_id))

        # Decision variables (only for call + surgical slots)
        x = {}
        for doc_id, slot_id in feasible_pairs:
            x[(doc_id, slot_id)] = pulp.LpVariable(
                f"x_{doc_id}_{slot_id}", cat='Binary'
            )

        # Build per-slot doc lists
        slot_x_docs = {s.slot_id: [] for s in ilp_slots}
        for (did, sid) in x:
            slot_x_docs[sid].append(did)

        # Lock pre-filled assignments for ILP slots
        for doc_id, slot_id in all_locked:
            if (doc_id, slot_id) in x:
                prob += (x[(doc_id, slot_id)] == 1,
                         f"locked_{doc_id}_{slot_id}")

        # H1: Capacity for ILP slots
        for slot in ilp_slots:
            docs_for_slot = slot_x_docs[slot.slot_id]
            if docs_for_slot:
                prob += (
                    pulp.lpSum(x[(did, slot.slot_id)] for did in docs_for_slot if (did, slot.slot_id) in x)
                    <= slot.max_doctors,
                    f"cap_{slot.slot_id}"
                )

        # H3: Exactly 1 on call slots
        for slot in ilp_slots:
            if slot.shift_type in ("call_day", "call_night", "call_weekend",
                                   "call_weekend_sun"):
                docs_for_slot = slot_x_docs[slot.slot_id]
                if not docs_for_slot:
                    raise Exception(
                        f"No feasible doctor for call slot {slot.slot_id} on {slot.date}. "
                        f"Possible causes: (1) no doctors have hospitalCallEligible=true, "
                        f"(2) all eligible doctors are blocked by blackout/standing-days-off on this date, "
                        f"or (3) the hospital office is excluded from all doctors' allowedOffices."
                    )
            prob += (
                pulp.lpSum(x[(did, slot.slot_id)] for did in docs_for_slot if (did, slot.slot_id) in x)
                == 1,
                f"call_cov_{slot.slot_id}"
            )

        # H3b: Exactly 1 on surgical slots
        _surg_cov_seen = set()
        for slot in ilp_slots:
            if slot.shift_type in ("surgical_am", "surgical_hosp_pm"):
                _name = f"surg_coverage_{slot.slot_id}"
                if _name in _surg_cov_seen:
                    continue
                _surg_cov_seen.add(_name)
                docs_for_slot = slot_x_docs[slot.slot_id]
                if not docs_for_slot:
                    raise Exception(
                        f"No feasible doctor for surgical slot {slot.slot_id} "
                        f"on {slot.date}. Possible causes: (1) no doctors "
                        f"have surgicalAssistEligible=true, (2) all eligible "
                        f"doctors are blocked by blackout/standing-days-off "
                        f"on this date, or (3) the hospital office is "
                        f"excluded from all doctors' allowedOffices."
                    )
                prob += (
                    pulp.lpSum(x[(did, slot.slot_id)] for did in docs_for_slot if (did, slot.slot_id) in x)
                    == 1,
                    f"surg_coverage_{slot.slot_id}"
                )

        # H6: No overlap among ILP slots (same-day + cross-day overnight)
            doc_x_ilp_slots = {d.id: [] for d in inp.doctors}
            for (did, sid) in x:
                doc_x_ilp_slots[did].append(slot_map[sid])

            all_dates = sorted(slots_by_date.keys())
            for doc in inp.doctors:
                did = doc.id
                for j in range(len(all_dates) - 1):
                    date_str = all_dates[j]
                    next_date = all_dates[j + 1]
                    if (dt_class.fromisoformat(next_date) -
                        dt_class.fromisoformat(date_str)).days != 1:
                        continue
                    today = [s for s in slots_by_date.get(date_str, [])
                             if s.slot_id in ilp_slot_set and (did, s.slot_id) in x]
                    next_day_slots = [s for s in slots_by_date.get(next_date, [])
                                      if s.slot_id in ilp_slot_set and (did, s.slot_id) in x]
        # Same-day overlaps and double-call prevention
        # Exception: surgical_am/surgical_hosp_pm are sub-activities
        # of call_day (the call doctor covers surgical), so they do
        # NOT overlap with call_day on the same date.
        _surgical_types = ("surgical_am", "surgical_hosp_pm")
        for idx, s1 in enumerate(today):
            for s2 in today[idx + 1:]:
                same_date_surgical_call = (
                    s1.date == s2.date
                    and ((s1.shift_type == "call_day" and s2.shift_type in _surgical_types)
                         or (s2.shift_type == "call_day" and s1.shift_type in _surgical_types))
                )
                if same_date_surgical_call:
                    continue
                if abs_times_overlap(s1, s2):
                    prob += (
                        x[(did, s1.slot_id)] + x[(did, s2.slot_id)] <= 1,
                        f"noov_{did}_{s1.slot_id}_{s2.slot_id}"
                    )
                    s1_call = s1.shift_type in ("call_day", "call_night", "call_weekend", "call_weekend_sun")
                    s2_call = s2.shift_type in ("call_day", "call_night", "call_weekend", "call_weekend_sun")
                    if s1_call and s2_call:
                        prob += (
                            x[(did, s1.slot_id)] + x[(did, s2.slot_id)] <= 1,
                            f"nodbl_{did}_{s1.slot_id}_{s2.slot_id}"
                        )
                    # Cross-day (overnight spillover)
                    overnight = [s for s in today
                                 if s.end_time <= s.start_time
                                 or s.shift_type in ("call_night", "call_weekend")]
                    if not overnight:
                        continue
                    for s1 in overnight:
                        for s2 in next_day_slots:
                            if abs_times_overlap(s1, s2):
                                prob += (
                                    x[(did, s1.slot_id)] + x[(did, s2.slot_id)] <= 1,
                                    f"noov_x_{did}_{s1.slot_id}_{s2.slot_id}"
                                )

            # H7: Surgical pairing
            for day_item in get_days_in_month(inp.year, inp.month):
                if day_item['day_of_week'] in (1, 2, 3) and hospital_id:
                    surg_am_id = f"{day_item['date']}_{hospital_id}_surgical_am"
                    surg_pm_id = f"{day_item['date']}_{hospital_id}_surgical_hosp_pm"
                    for doc in inp.doctors:
                        if (doc.id, surg_am_id) in x and (doc.id, surg_pm_id) in x:
                            prob += (
                                x[(doc.id, surg_am_id)] == x[(doc.id, surg_pm_id)],
                                f"surg_pair_{doc.id}_{day_item['date']}"
                            )

            # H5e: Weekend block pairing (Sat+Sun same doctor)
            for block in get_weekend_blocks(inp.year, inp.month):
                if not hospital_id:
                    continue
                sat_id = f"{block.saturday}_{hospital_id}_call_weekend"
                sun_id = f"{block.sunday}_{hospital_id}_call_weekend_sun"
                for doc in inp.doctors:
                    if (doc.id, sat_id) in x and (doc.id, sun_id) in x:
                        prob += (
                            x[(doc.id, sat_id)] == x[(doc.id, sun_id)],
                            f"wknd_pair_{doc.id}_{block.saturday}"
                        )

            # H5a/b/c/d: Balance constraints (separate max_dev per group)
            eligible = [d for d in inp.doctors if d.hospital_call_eligible]
            max_dev_terms = []

            for group in ("weekday_day", "weekday_night", "friday_night", "weekend_block"):
                group_dev = pulp.LpVariable(f"max_dev_{group}", lowBound=0)
                max_dev_terms.append(group_dev)

                if group == "weekday_day":
                    group_slots = [s for s in ilp_slots
                                   if s.call_balance_group == "weekday_day"]
                elif group == "weekday_night":
                    group_slots = [s for s in ilp_slots
                                   if s.call_balance_group == "weekday_night"]
                elif group == "friday_night":
                    group_slots = [s for s in ilp_slots
                                   if s.call_balance_group == "friday_night"]
                else:
                    group_slots = [s for s in ilp_slots
                                   if s.shift_type == "call_weekend"]

                if not group_slots or not eligible:
                    continue

                total_per_doc = {
                    d.id: pulp.lpSum(
                        x.get((d.id, s.slot_id), 0) for s in group_slots
                    ) for d in eligible
                }
                avg_expr = pulp.lpSum(total_per_doc.values()) / len(eligible)

                for d in eligible:
                    prob += (total_per_doc[d.id] - avg_expr <= group_dev,
                             f"bal_upper_{group}_{d.id}")
                    prob += (avg_expr - total_per_doc[d.id] <= group_dev,
                             f"bal_lower_{group}_{d.id}")

            # Preference term (weekday calls only)
            # Keep preference coefficients small relative to max_dev weight
            # so CBC's feasibility pump heuristic doesn't sacrifice feasibility
            # for preference score. Negative coefficients in the objective can
            # cause CBC to produce solutions that violate hard constraints.
            pref_cost_terms = []
            for (did, sid) in x:
                slot = slot_map[sid]
                if slot.call_balance_group not in ("weekday_day", "weekday_night"):
                    continue
                doc = next((d for d in inp.doctors if d.id == did), None)
                if not doc or not doc.preferred_call_days:
                    continue
                dow = dt_class.fromisoformat(slot.date).weekday()
                if dow in doc.preferred_call_days:
                    pref_cost_terms.append(-0.1 * x[(did, sid)])
                else:
                    pref_cost_terms.append(0.05 * x[(did, sid)])

            pref_cost = pulp.lpSum(pref_cost_terms) if pref_cost_terms else 0

            balance_obj = pulp.lpSum(max_dev_terms) * 100
            prob.setObjective(balance_obj + pref_cost)

            # Solve
            solver = pulp.PULP_CBC_CMD(
                msg=0,
                timeLimit=inp.solver_time_limit_seconds,
                options=["ratioGap 0.05", "secondsPerIteration 30"]
            )
            prob.solve(solver)

            if prob.status != pulp.LpStatusOptimal and prob.status != 1:
                raise Exception(
                    f"CBC did not find feasible solution (status={pulp.LpStatus[prob.status]}). "
                    f"This usually means hard constraints (call coverage, overlap, pairing) "
                    f"conflict and no valid schedule exists with the given inputs.")

            # Extract ILP call+surgical assignments
            ilp_assignments = list(inp.locked_assignments + recurring + overrides)
            seen_locked = {(a.doctor_id, a.slot_id) for a in ilp_assignments}
            for (did, sid), var in x.items():
                val = pulp.value(var)
                if val is not None and val > 0.5:
                    if (did, sid) not in seen_locked:
                        ilp_assignments.append(Assignment(doctor_id=did, slot_id=sid))

            # Phase 2: Greedy office session filling
            # Use ILP call assignments as locked, then fill office sessions.
            # Replay all ILP assignments in chronological order so post_call_since
            # state is correct when the office loop starts.
            doc_map = {d.id: d for d in inp.doctors}
            day_off_dates = inp.day_off_dates
            global_day_off_set = _get_day_off_set(day_off_dates)

            load = _init_load(inp.doctors, inp.offices)
            ilp_by_date = defaultdict(list)
            for a in ilp_assignments:
                slot = slot_map.get(a.slot_id)
                if slot:
                    ilp_by_date[slot.date].append(a)

            assignments = list(ilp_assignments)

            def assign(doc_id: str, slot: ShiftSlot) -> None:
                assignments.append(Assignment(doctor_id=doc_id, slot_id=slot.slot_id))
                _update_load(load, doc_id, slot, hospital_id)

            def is_avail(doc_id: str, slot: ShiftSlot) -> bool:
                return _is_available(doc_id, slot, assignments, slot_map, load,
                                     doc_map, hospital_id, _get_day_off_entries(day_off_dates, doc_id))

            days = get_days_in_month(inp.year, inp.month)
            sessions_by_doc_week = defaultdict(lambda: defaultdict(int))

            office_shift_types = ["office_am", "office_pm", "office_late"]
            prev_date_calls_activated = set()
            for day in days:
                if day['is_weekend'] or day['date'] in global_day_off_set:
                    continue
                date = day['date']
                week_num = day['week_num']
                for prev_date in sorted(ilp_by_date.keys()):
                    if prev_date >= date:
                        break
                    if prev_date not in prev_date_calls_activated:
                        for a in ilp_by_date[prev_date]:
                            slot = slot_map.get(a.slot_id)
                            if slot and slot.shift_type in ("call_day", "call_night",
                                "call_weekend", "call_weekend_sun"):
                                _update_load(load, a.doctor_id, slot, hospital_id)
                        prev_date_calls_activated.add(prev_date)
            day_office_slots = [s for s in slots
                                if s.date == date
                                and s.shift_type in office_shift_types
                                and not any(a.slot_id == s.slot_id
                                            for a in assignments)]
            hosp_slots = [s for s in day_office_slots
                          if s.office_id == hospital_id]
            non_hosp_slots = [s for s in day_office_slots
                              if s.office_id != hospital_id]
            for slot_obj in hosp_slots:
                if any(a.slot_id == slot_obj.slot_id for a in assignments):
                    continue
                avail_docs = [d for d in inp.doctors
                              if is_avail(d.id, slot_obj)]
                avail_docs.sort(
                    key=lambda d: sessions_by_doc_week[d.id].get(week_num, 0))
                for doc in avail_docs:
                    doc_day_off_set = _get_day_off_set(day_off_dates, doc.id)
                    day_off_weekdays = sum(
                        1 for d in doc_day_off_set
                        if d.startswith(
                            f"{inp.year}-{str(inp.month + 1).zfill(2)}"))
                    adjusted_quota = max(
                        0, doc.required_sessions_per_week - day_off_weekdays)
                    week_count = sessions_by_doc_week[doc.id].get(week_num, 0)
                    if week_count >= adjusted_quota:
                        continue
                    assign(doc.id, slot_obj)
                    sessions_by_doc_week[doc.id][week_num] += 1
                    break
            for slot_obj in non_hosp_slots:
                if any(a.slot_id == slot_obj.slot_id for a in assignments):
                    continue
                avail_docs = [d for d in inp.doctors
                              if is_avail(d.id, slot_obj)]
                avail_docs.sort(
                    key=lambda d: sessions_by_doc_week[d.id].get(week_num, 0))
                for doc in avail_docs:
                    doc_day_off_set = _get_day_off_set(day_off_dates, doc.id)
                    day_off_weekdays = sum(
                        1 for d in doc_day_off_set
                        if d.startswith(
                            f"{inp.year}-{str(inp.month + 1).zfill(2)}"))
                    adjusted_quota = max(
                        0, doc.required_sessions_per_week - day_off_weekdays)
                    week_count = sessions_by_doc_week[doc.id].get(week_num, 0)
                    if week_count >= adjusted_quota:
                        continue
                    assign(doc.id, slot_obj)
                    sessions_by_doc_week[doc.id][week_num] += 1
                    break

            # Post-call morning assignments (soft S4)
            for doc in inp.doctors:
                if doc.post_call_preference != "work":
                    continue
                for a in assignments:
                    if a.doctor_id != doc.id:
                        continue
                    slot = slot_map[a.slot_id]
                    if slot.shift_type != "call_night":
                        continue
                    next_day = (dt_class.fromisoformat(slot.date)
                                + timedelta(days=1)).isoformat()
                    next_am = get_slot_by_id(
                        slots, f"{next_day}_{hospital_id}_office_am")
                    if next_am and not any(
                            a2.slot_id == next_am.slot_id for a2 in assignments):
                        if is_avail(doc.id, next_am):
                            for d in days:
                                if d['date'] == next_day:
                                    wn = d['week_num']
                                    if sessions_by_doc_week[doc.id].get(
                                            wn, 0) < doc.required_sessions_per_week:
                                        assign(doc.id, next_am)
                                        sessions_by_doc_week[doc.id][wn] += 1
                                    break

            # Finalize
            violations = validate_schedule(inp, slots, assignments)
            el = [d for d in inp.doctors if d.hospital_call_eligible]
            call_counts = [
                sum(1 for a in assignments
                    if a.doctor_id == d.id
                    and slot_map[a.slot_id].call_balance_group in
                    ("weekday_day", "weekday_night", "friday_night", "weekend_block"))
                for d in el
            ]
            session_counts = [
                sum(1 for a in assignments
                    if a.doctor_id == d.id
                    and slot_map[a.slot_id].shift_type in
                    ("office_am", "office_pm", "office_late", "surgical_am",
                     "surgical_hosp_pm"))
                for d in inp.doctors
            ]
            counts = compute_counts(inp.doctors, inp.offices, assignments, slots,
                                    inp.historical_balance)

            if prob.status == pulp.LpStatusOptimal:
                status_str = "optimal"
            else:
                status_str = pulp.LpStatus.get(prob.status, "unknown")

            return ScheduleResult(
                month_key=f"{inp.year}-{str(inp.month + 1).zfill(2)}",
                assignments=assignments,
                slots=slots,
                solver_status=status_str,
                gini_calls=gini(call_counts) if call_counts else 0.0,
                gini_sessions=gini(session_counts) if session_counts else 0.0,
                unmet_constraints=[{
                    'id': v.constraint_id,
                    'name': v.constraint_name,
                    'severity': v.severity,
                    'description': v.description,
                    'suggestion': v.suggestion,
                    'affected_doctors': v.affected_doctors,
                    'affected_dates': v.affected_dates,
                } for v in violations],
                partial=len(violations) > 0,
                counts=counts
            )

    except Exception as e:
        import traceback
        traceback.print_exc()
        result = schedule_greedy(inp)
        result.solver_status = f"greedy_fallback ({e})"
        return result


def generate_schedule(inp: ScheduleInput) -> ScheduleResult:
    """Main entry point. Tries ILP, falls back to greedy."""
    try:
        return schedule_ilp(inp)
    except Exception:
        return schedule_greedy(inp)
