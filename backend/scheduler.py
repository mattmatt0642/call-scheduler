from models import (
    DoctorProfile, Office, ShiftSlot, Assignment, ScheduleInput, ScheduleResult,
    abs_times_overlap, get_days_in_month, get_weekend_blocks,
    get_call_balance_group, is_friday, WeekendCallBlock, CustomRestriction,
    RecurringSlot, OneTimeOverride, SHIFT_TIMES, SHIFT_PERIODS, prev_date
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


def _is_blocked_by_timeoff(entry, slot_type):
    period = entry.get("period", "all_day")
    slot_period = SHIFT_PERIODS.get(slot_type, "all_day")
    if period == "all_day":
        return True
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
            return _times_overlap_strings(shift_times[0], shift_times[1], st, et)
        return True
    return False


def _times_overlap_strings(s1, e1, s2, e2):
    """Check if two time-string intervals overlap. Handles overnight (e < s)."""
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


def _init_load(doctors, offices):
    """
    Initialize per-doctor load tracking dict.
    Keys: doctor_id -> dict with counts, session breakdown, office visits,
    and post_call_restricted boolean.
    """
    load = {}
    for d in doctors:
        load[d.id] = {
            'weekday_day_calls': 0,
            'weekday_night_calls': 0,
            'friday_night_calls': 0,
            'weekend_blocks': 0,
            'sessions': 0,
            'am_sessions': 0,
            'pm_sessions': 0,
            'late_sessions': 0,
            'office_visits': {o.id: 0 for o in offices},
            'post_call_restricted': False,
        }
    return load


def _update_load(load, doctor_id, slot, hospital_id):
    """
    Update load tracking after assigning doctor_id to slot.
    - call_day: weekday_day_calls += 1, post_call_restricted = True
    - call_night: weekday_night_calls or friday_night_calls += 1, post_call_restricted = True
    - call_weekend: weekend_blocks += 1, post_call_restricted = True
    - call_weekend_sun: (counted as part of weekend block, no separate increment)
    - office_am/office_pm/office_late/surgical_am/surgical_hosp_pm:
      sessions += 1, office_visits updated, post_call_restricted cleared if at hospital
    """
    entry = load[doctor_id]
    shift = slot.shift_type
    if shift == 'call_day':
        entry['weekday_day_calls'] += 1
        entry['post_call_restricted'] = True
    elif shift == 'call_night':
        if slot.call_balance_group == 'friday_night':
            entry['friday_night_calls'] += 1
        else:
            entry['weekday_night_calls'] += 1
        entry['post_call_restricted'] = True
    elif shift == 'call_weekend':
        entry['weekend_blocks'] += 1
        entry['post_call_restricted'] = True
    elif shift == 'call_weekend_sun':
        # Sunday of weekend block — reinforce the restriction.
        # The Saturday slot already counted the block; Sunday does not re-count.
        entry['post_call_restricted'] = True
    elif shift in ('office_am', 'surgical_am'):
        entry['am_sessions'] += 1
        entry['sessions'] += 1
        entry['office_visits'][slot.office_id] = entry['office_visits'].get(slot.office_id, 0) + 1
        if entry['post_call_restricted'] and slot.office_id == hospital_id:
            entry['post_call_restricted'] = False
    elif shift in ('office_pm', 'surgical_hosp_pm'):
        entry['pm_sessions'] += 1
        entry['sessions'] += 1
        entry['office_visits'][slot.office_id] = entry['office_visits'].get(slot.office_id, 0) + 1
        if entry['post_call_restricted'] and slot.office_id == hospital_id:
            entry['post_call_restricted'] = False
    elif shift == 'office_late':
        entry['late_sessions'] += 1
        entry['sessions'] += 1
        entry['office_visits'][slot.office_id] = entry['office_visits'].get(slot.office_id, 0) + 1
        if entry['post_call_restricted'] and slot.office_id == hospital_id:
            entry['post_call_restricted'] = False


def _avg_hist(key, eligible_ids, historical_balance) -> float:
    vals = [historical_balance.get(did, {}).get(key, 0) for did in eligible_ids]
    return sum(vals) / max(len(vals), 1)


def call_debt_with_preference(doc_id, date_str, shift_type,
                               load, inp, doc_map) -> float:
    """
    Priority score for weekday_day and weekday_night assignments.
    Higher = higher priority. Preferences apply here.
    Uses cumulative (historical + current) count for fairness.
    """
    doc = doc_map[doc_id]
    dow = dt_class.fromisoformat(date_str).weekday()

    group = "weekday_day" if shift_type == "call_day" else "weekday_night"
    load_key = "weekday_day_calls" if group == "weekday_day" else "weekday_night_calls"

    eligible_ids = [d.id for d in inp.doctors if d.hospital_call_eligible]
    hist = inp.historical_balance.get(doc_id, {}).get(group, 0)
    avg = _avg_hist(group, eligible_ids, inp.historical_balance)
    this_month = load[doc_id][load_key]
    base = (avg - hist) - (this_month * 1.5)

    # Preference: +3.0 preferred, -1.5 non-preferred, 0.0 no preference set
    if doc.preferred_call_days:
        pref = 3.0 if dow in doc.preferred_call_days else -1.5
    else:
        pref = 0.0

    # Day/night nudge (low weight — within weekday groups only)
    nudge = 0.0
    if shift_type == "call_day" and doc.day_night_preference == "day":
        nudge = 0.5
    if shift_type == "call_night" and doc.day_night_preference == "night":
        nudge = 0.5

    return base + pref + nudge


def call_debt_balance_only(doc_id, balance_key, load, inp) -> float:
    """
    Priority score for friday_night and weekend_block assignments.
    Preferences have ZERO influence. Purely historical balance.
    """
    load_key = ("friday_night_calls" if balance_key == "friday_night"
                else "weekend_blocks")
    eligible_ids = [d.id for d in inp.doctors if d.hospital_call_eligible]
    hist = inp.historical_balance.get(doc_id, {}).get(balance_key, 0)
    avg = _avg_hist(balance_key, eligible_ids, inp.historical_balance)
    this_month = load[doc_id][load_key]
    return (avg - hist) - (this_month * 1.5)


def _is_available(doc_id, slot, assignments, slot_map, load,
                  doc_map, hospital_id, doc_day_off_entries):
    """
    Check if doctor doc_id can be assigned to slot.
    Returns False if:
    - Slot date/period conflicts with doctor's time-off entries
    - Doctor has an overlapping assignment
    - Doctor's allowed_offices doesn't include slot.office_id
    - Post-call restriction (H8): doctor has post_call_restricted set and
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

    if doc.weekend_call_off and slot.shift_type in ('call_weekend', 'call_weekend_sun'):
        return False

    if doc.allowed_offices is not None and slot.office_id not in doc.allowed_offices:
        return False

    # Post-call restriction (H8): uses the boolean from load dict
    if load[doc_id]['post_call_restricted']:
        if slot.office_id != hospital_id:
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
    if doc.weekend_call_off:
        if slot.shift_type in ('call_weekend', 'call_weekend_sun'):
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


def _compute_adjusted_quota(doc, week_num, days, day_off_dates):
    reduction = 0
    if isinstance(day_off_dates, dict):
        doc_days_off = day_off_dates.get(doc.id, [])
    else:
        doc_days_off = list(day_off_dates) if day_off_dates else []
    for entry in doc_days_off:
        if isinstance(entry, str):
            d_str = entry
        elif isinstance(entry, dict):
            d_str = entry.get("date", "")
        else:
            continue
        day_info = next((d for d in days if d['date'] == d_str), None)
        if day_info and day_info['week_num'] == week_num:
            reduction += 1
    week_days = [d for d in days if d['week_num'] == week_num and not d['is_weekend']]
    n_weekdays = max(len(week_days), 1)
    if n_weekdays < 5:
        reduction += (5 - n_weekdays)
    adj = doc.required_sessions_per_week - round(reduction * doc.required_sessions_per_week / 5)
    return max(0, adj)


def schedule_greedy(inp: ScheduleInput) -> ScheduleResult:
    """
    Greedy scheduler. Assigns slots in priority order:

    Phase 0: Expand and lock pre-filled assignments. Replay all locked
    assignments through _update_load(). This must happen before any other
    phase so debt calculations and post_call_restricted flags reflect reality.

    Phase 1: Weekend blocks. Assign first — they span two days and are the
    most constrained. Use call_debt_balance_only("weekend_blocks").
    Both Sat and Sun slots must be assigned to the same doctor.

    Phase 2: Surgical pairs. Assign next — surgical_am + surgical_hosp_pm
    must be the same doctor. Assign both atomically (never one without
    the other). Use session debt at the hospital office.

    Phase 3: Weekday call shifts. For each weekday, in calendar order:
      a. Check for double-preference doctors first (if both day and night
         slots are unfilled, and a doctor prefers doubles and is available
         for both: assign both to the same doctor).
      b. Fill day call slot: call_debt_with_preference(shift_type="call_day")
      c. Fill night call slot:
         - Friday: call_debt_balance_only("friday_night") — NO preferences
         - Mon–Thu: call_debt_with_preference(shift_type="call_night")

    Phase 4: Office sessions. For each week of the month, fill each
    doctor's session quota. Process offices in ranked order
    (global/per-doctor preference). Spread sessions across multiple offices
    (not all at one). Proportionally reduce quota for days off in that week.

    Phase 5: Post-call morning assignments (soft preference S4).
    For doctors with post_call_preference="work", after a call_night,
    try to assign the hospital office_am the following morning.

    Phase 6: Mon/Thu late shifts (soft balance S3).
    Distribute office_late slots aiming for ~1 per week per doctor.
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

    # Deduplicate locked assignments
    seen = set()
    deduped = []
    for a in inp.locked_assignments + recurring + overrides:
        k = (a.doctor_id, a.slot_id)
        if k not in seen:
            seen.add(k)
            deduped.append(a)
    assignments = deduped
    load = _init_load(inp.doctors, inp.offices)
    doc_map = {d.id: d for d in inp.doctors}
    global_day_off_set = _get_day_off_set(inp.day_off_dates)

    for a in assignments:
        slot = slot_map.get(a.slot_id)
        if slot:
            _update_load(load, a.doctor_id, slot, hospital_id)

    weekend_blocks_list = get_weekend_blocks(inp.year, inp.month)

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
                already_has_partner = any(a.doctor_id == doc.id and a.slot_id == partner_id for a in assignments)
                if already_has_partner:
                    if doc.call_shift_preference == 'single':
                        continue
                slot_date = dt_class.fromisoformat(slot.date)
                if slot_date.weekday() >= 5:
                    continue
            if p_sun_id:
                sun_slot = slot_map[p_sun_id]
                if not _is_available(doc.id, sun_slot, assignments, slot_map,
                                     load, doc_map, hospital_id, doc_day_off_entries):
                    continue
                if len([a for a in assignments if a.slot_id == p_sun_id]) >= sun_slot.max_doctors:
                    continue
            if slot.call_balance_group in ('friday_night', 'weekend_block'):
                debt = call_debt_balance_only(doc.id, slot.call_balance_group, load, inp)
            else:
                debt = call_debt_with_preference(doc.id, slot.date, slot.shift_type,
                                                  load, inp, doc_map)
            result.append((debt, doc))
        result.sort(key=lambda x: (x[0], -(
            load[x[1].id]['weekday_day_calls'] +
            load[x[1].id]['weekday_night_calls'] +
            load[x[1].id]['friday_night_calls'] +
            load[x[1].id]['weekend_blocks']
        )), reverse=True)
        return result

    def _do_assign(slot, doc, p_sun_id=None):
        assignments.append(Assignment(doctor_id=doc.id, slot_id=slot.slot_id))
        _update_load(load, doc.id, slot, hospital_id)
        if p_sun_id and not any(a.slot_id == p_sun_id for a in assignments):
            sun_slot = slot_map[p_sun_id]
            assignments.append(Assignment(doctor_id=doc.id, slot_id=p_sun_id))
            _update_load(load, doc.id, sun_slot, hospital_id)

    # Phase 1: Weekend blocks — most constrained, assign first
    weekend_call_slots = [s for s in slots
                          if s.shift_type == 'call_weekend']
    weekend_call_slots.sort(key=lambda s: s.date)
    for slot in weekend_call_slots:
        if any(a.slot_id == slot.slot_id for a in assignments):
            continue  # already pre-filled
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
            if load[doc.id]['weekend_blocks'] >= doc.max_weekend_blocks:
                continue
            if p_sun_id and global_day_off_set and \
               slot_map[p_sun_id].date in global_day_off_set:
                continue
            _do_assign(slot, doc, p_sun_id)
            break

    # Phase 2: Surgical pairs — assign before weekday calls so capacity
    # is reserved. Both surgical_am + surgical_hosp_pm must be same doctor.
    surgical_slots = [s for s in slots
                      if s.shift_type in ('surgical_am', 'surgical_hosp_pm')]
    surgical_slots.sort(key=lambda s: (s.date, s.start_time))
    surgical_count = defaultdict(int)
    for slot in surgical_slots:
        existing = [a for a in assignments if a.slot_id == slot.slot_id]
        if len(existing) >= slot.max_doctors:
            continue
        eligible = [d for d in inp.doctors
                    if d.surgical_assist_eligible
                    and _is_available(d.id, slot, assignments, slot_map, load,
                                      doc_map, hospital_id,
                                      _get_day_off_entries(inp.day_off_dates, d.id))]
        # For surgical_am, also check PM availability before assigning
        if slot.shift_type == 'surgical_am':
            pm_id = slot.slot_id.replace('surgical_am', 'surgical_hosp_pm')
            pm_slot = slot_map.get(pm_id)
            if pm_slot:
                eligible = [d for d in eligible
                            if _is_available(d.id, pm_slot, assignments, slot_map,
                                             load, doc_map, hospital_id,
                                             _get_day_off_entries(inp.day_off_dates, d.id))]
            else:
                eligible = []
        elif slot.shift_type == 'surgical_hosp_pm':
            am_id = slot.slot_id.replace('surgical_hosp_pm', 'surgical_am')
            am_slot = slot_map.get(am_id)
            if am_slot:
                am_assigns = [a for a in assignments if a.slot_id == am_id]
                if am_assigns:
                    # AM already assigned — PM must go to same doctor (H7 pairing)
                    am_doc_id = am_assigns[0].doctor_id
                    eligible = [d for d in eligible if d.id == am_doc_id]
        # Sort by session debt at hospital office (spec: use historical balance)
        def sess_debt(did):
            h = inp.historical_balance.get(did, {}).get("total_sessions", 0)
            avg = _avg_hist("total_sessions",
                            [d.id for d in inp.doctors], inp.historical_balance)
            return (avg - h) - load[did]['sessions'] * 1.5
        eligible.sort(key=lambda d: sess_debt(d.id), reverse=True)
        for doc in eligible:
            assignments.append(Assignment(doctor_id=doc.id, slot_id=slot.slot_id))
            _update_load(load, doc.id, slot, hospital_id)
            surgical_count[doc.id] += 1
            if slot.shift_type == 'surgical_am':
                pm_id = slot.slot_id.replace('surgical_am', 'surgical_hosp_pm')
                pm_slot = slot_map.get(pm_id)
                if pm_slot and not any(a.slot_id == pm_id for a in assignments):
                    if _is_available(doc.id, pm_slot, assignments, slot_map,
                                     load, doc_map, hospital_id,
                                     _get_day_off_entries(inp.day_off_dates, doc.id)):
                        assignments.append(Assignment(doctor_id=doc.id, slot_id=pm_id))
                        _update_load(load, doc.id, pm_slot, hospital_id)
            break

    # Phase 3: Weekday call shifts (including friday night)
    # For each weekday in calendar order:
    #   a. Check for double-preference doctors first
    #   b. Fill day call slot
    #   c. Fill night call slot (friday_night uses balance_only)
    days = get_days_in_month(inp.year, inp.month)
    weekday_days = [d for d in days if not d['is_weekend']]
    for day in weekday_days:
        date = day['date']
        day_slot = slot_map.get(f"{date}_{hospital_id}_call_day") if hospital_id else None
        night_slot = slot_map.get(f"{date}_{hospital_id}_call_night") if hospital_id else None

        day_filled = day_slot and any(a.slot_id == day_slot.slot_id for a in assignments)
        night_filled = night_slot and any(a.slot_id == night_slot.slot_id for a in assignments)

        # Phase 3a: Double-preference check — sort by debt for fairness
        if day_slot and night_slot and not day_filled and not night_filled:
            dow = dt_class.fromisoformat(date).weekday()
            if dow < 5:
                double_eligible = []
                for doc in inp.doctors:
                    if not doc.hospital_call_eligible:
                        continue
                    if doc.call_shift_preference != 'double':
                        continue
                    doc_day_off_entries = _get_day_off_entries(inp.day_off_dates, doc.id)
                    if (not _is_available(doc.id, day_slot, assignments, slot_map,
                                          load, doc_map, hospital_id, doc_day_off_entries)
                        or not _is_available(doc.id, night_slot, assignments, slot_map,
                                              load, doc_map, hospital_id, doc_day_off_entries)):
                        continue
                    if len([a for a in assignments if a.slot_id == day_slot.slot_id]) >= day_slot.max_doctors:
                        continue
                    if len([a for a in assignments if a.slot_id == night_slot.slot_id]) >= night_slot.max_doctors:
                        continue
                    # Check max call limits for doubles
                    if load[doc.id]['weekday_day_calls'] >= doc.max_weekday_day_calls:
                        continue
                    if dow == 4:  # Friday
                        if load[doc.id]['friday_night_calls'] >= doc.max_friday_night_calls:
                            continue
                    else:
                        if load[doc.id]['weekday_night_calls'] >= doc.max_weekday_night_calls:
                            continue
                    debt = call_debt_with_preference(doc.id, date, "call_day",
                                                      load, inp, doc_map)
                    double_eligible.append((debt, doc))
                if double_eligible:
                    double_eligible.sort(key=lambda x: x[0], reverse=True)
                    chosen = double_eligible[0][1]
                    _do_assign(day_slot, chosen)
                    _do_assign(night_slot, chosen)
                    day_filled = True
                    night_filled = True

        # Phase 3b: Fill day call slot (with max limit check)
        if day_slot and not day_filled:
            for debt, doc in _find_eligible(day_slot):
                if len([a for a in assignments if a.slot_id == day_slot.slot_id]) >= day_slot.max_doctors:
                    break
                if load[doc.id]['weekday_day_calls'] >= doc.max_weekday_day_calls:
                    continue
                _do_assign(day_slot, doc)
                break

        # Phase 3c: Fill night call slot (with max limit check)
        if night_slot and not night_filled:
            for debt, doc in _find_eligible(night_slot):
                if len([a for a in assignments if a.slot_id == night_slot.slot_id]) >= night_slot.max_doctors:
                    break
                if is_friday(date):
                    if load[doc.id]['friday_night_calls'] >= doc.max_friday_night_calls:
                        continue
                else:
                    if load[doc.id]['weekday_night_calls'] >= doc.max_weekday_night_calls:
                        continue
                _do_assign(night_slot, doc)
                break

    # Retry any unfilled call slots (coverage > balance)
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
                already_has_partner = any(a.doctor_id == doc.id and a.slot_id == partner_id
                                          for a in assignments)
                if already_has_partner:
                    if doc.call_shift_preference == 'single':
                        continue
                slot_date = dt_class.fromisoformat(slot.date)
                if slot_date.weekday() >= 5:
                    continue
            if p_sun_id:
                sun_slot = slot_map[p_sun_id]
                if not _is_available(doc.id, sun_slot, assignments, slot_map,
                                     load, doc_map, hospital_id,
                                     doc_day_off_entries):
                    continue
            _do_assign(slot, doc, p_sun_id)
            break

    # Phase 3.5: Post-call hospital office — assign post-call doctors to
    # next-day hospital office AM/PM to clear H8 restriction before
    # general office filling can take those slots.
    if hospital_id:
        # Snapshot assignments to avoid iterating while mutating
        current_assignments = list(assignments)
        for doc in inp.doctors:
            for a in current_assignments:
                if a.doctor_id != doc.id:
                    continue
                slot = slot_map[a.slot_id]
                if slot.shift_type not in ('call_day', 'call_night',
                                           'call_weekend', 'call_weekend_sun'):
                    continue
                next_day_dt = dt_class.fromisoformat(slot.date) + timedelta(days=1)
                while next_day_dt.weekday() >= 5:
                    next_day_dt += timedelta(days=1)
                next_day = next_day_dt.isoformat()
                if next_day not in global_day_off_set:
                    doc_day_off_entries = _get_day_off_entries(inp.day_off_dates, doc.id)
                    already_has_hosp_am = any(
                        a2.doctor_id == doc.id and
                        slot_map.get(a2.slot_id, None) is not None and
                        slot_map[a2.slot_id].date == next_day and
                        slot_map[a2.slot_id].office_id == hospital_id and
                        slot_map[a2.slot_id].shift_type == 'office_am'
                        for a2 in assignments)
                    if already_has_hosp_am:
                        day_info = next((d for d in days if d['date'] == next_day), None)
                        wn = day_info['week_num'] if day_info else 0
                        doc_nh = {slot_map[a.slot_id].office_id for a in assignments
                                  if a.doctor_id == doc.id
                                  and slot_map.get(a.slot_id) is not None
                                  and slot_map[a.slot_id].office_id != hospital_id
                                  and slot_map[a.slot_id].date[:4] == next_day[:4]} - {hospital_id}
                    # Try to assign hospital AM then PM to clear H8 restriction.
                    cleared = False
                    for ampm in ('office_am', 'office_pm'):
                        hs_id = f"{next_day}_{hospital_id}_{ampm}"
                        hs = slot_map.get(hs_id)
                        if not hs:
                            continue
                        if sum(1 for a2 in assignments if a2.slot_id == hs_id) >= hs.max_doctors:
                            continue
                        if _is_available(doc.id, hs, assignments, slot_map,
                                         load, doc_map, hospital_id, doc_day_off_entries):
                            assignments.append(Assignment(doctor_id=doc.id, slot_id=hs_id))
                            _update_load(load, doc.id, hs, hospital_id)
                            cleared = True
                            break
                    if cleared:
                        continue
    def _office_phase_key(slot_obj):
        if slot_obj.office_id == hospital_id:
            return (0, 0)
        ranking = inp.global_office_ranking
        if ranking and slot_obj.office_id in ranking:
            return (1, ranking.index(slot_obj.office_id))
        return (1, len(ranking) if ranking else 0)


    # Phase 4: Office sessions — ranked order, proportional day-off reduction
    all_office_shift_types = ['office_am', 'office_pm', 'office_late',
        'surgical_am', 'surgical_hosp_pm']
    office_shift_types = ['office_am', 'office_pm', 'office_late']
    sessions_by_doc_week = defaultdict(lambda: defaultdict(int))
    office_variety_by_doc_week = defaultdict(lambda: defaultdict(set))
    am_by_doc_week = defaultdict(lambda: defaultdict(int))
    pm_by_doc_week = defaultdict(lambda: defaultdict(int))

    for a in assignments:
        s = slot_map.get(a.slot_id)
        if not s or s.shift_type not in all_office_shift_types:
            continue
        day_info = next((d for d in days if d['date'] == s.date), None)
        if not day_info:
            continue
        wn = day_info['week_num']
        sessions_by_doc_week[a.doctor_id][wn] += 1
        office_variety_by_doc_week[a.doctor_id][wn].add(s.office_id)
        if s.shift_type in ('office_am', 'surgical_am'):
            am_by_doc_week[a.doctor_id][wn] += 1
        elif s.shift_type in ('office_pm', 'office_late', 'surgical_hosp_pm'):
            pm_by_doc_week[a.doctor_id][wn] += 1

    def _is_post_call_restricted(doc_id):
        return load[doc_id]['post_call_restricted']

    def _compute_post_call_restricted_for_slot(doc_id, date_str, start_time):
        from datetime import date as dt_date, timedelta
        most_recent_call = None
        for a in assignments:
            if a.doctor_id != doc_id:
                continue
            s = slot_map.get(a.slot_id)
            if not s or s.date > date_str:
                continue
            if s.shift_type in ('call_day', 'call_night', 'call_weekend', 'call_weekend_sun'):
                if most_recent_call is None or s.date > most_recent_call.date or \
                   (s.date == most_recent_call.date and s.start_time > most_recent_call.start_time):
                    most_recent_call = s
        if most_recent_call is None:
            return False
        call_times = SHIFT_TIMES.get(most_recent_call.shift_type, ('00:00', '23:59'))
        call_end_time = call_times[1]
        call_date = most_recent_call.date
        if most_recent_call.shift_type == 'call_night':
            call_end_date = str(dt_date.fromisoformat(call_date) + timedelta(days=1))
        else:
            call_end_date = call_date
        for a in assignments:
            if a.doctor_id != doc_id:
                continue
            s = slot_map.get(a.slot_id)
            if not s or s.date > date_str:
                continue
            if s.office_id != hospital_id:
                continue
            if s.shift_type not in ('office_am', 'office_pm', 'office_late',
                                     'surgical_am', 'surgical_hosp_pm'):
                continue
            if s.start_time > start_time:
                continue
            if s.date > call_end_date:
                return False
            if s.date == call_end_date and s.start_time >= call_end_time:
                return False
        return True

    # Track per-office weekly sessions to enforce variety
    # Cap each doctor at max 3 sessions per non-hospital office per week
    # to force spreading across multiple offices
    OFFICE_WEEKLY_CAP = 1
    sessions_by_doc_office_week = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    # Build office processing order: non-hospital first (in ranked order), then hospital
    # This ensures non-hospital offices get filled before hospital takes all slots
    office_order = []
    ranking = inp.global_office_ranking or []
    for oid in ranking:
        if oid != hospital_id:
            office_order.append(oid)
    for o in inp.offices:
        if o.id != hospital_id and o.id not in office_order:
            office_order.append(o.id)
    if hospital_id:
        office_order.append(hospital_id)

    # Phase 4: For each day, for each office in order, fill AM then PM to capacity
    for day in days:
        if day['is_weekend'] or day['date'] in global_day_off_set:
            continue
        date = day['date']
        week_num = day['week_num']

        for office_id in office_order:
            office_slots = [s for s in slots
                           if s.date == date
                           and s.office_id == office_id
                           and s.shift_type in ('office_am', 'office_pm')
                           and sum(1 for a in assignments if a.slot_id == s.slot_id) < s.max_doctors]
            office_slots.sort(key=lambda s: 0 if s.shift_type == 'office_am' else 1)

            for slot_obj in office_slots:
                while True:
                    cur = sum(1 for a in assignments if a.slot_id == slot_obj.slot_id)
                    if cur >= slot_obj.max_doctors:
                        break
                    avail_docs = [d for d in inp.doctors
                                  if _is_available(d.id, slot_obj, assignments,
                                                   slot_map, load, doc_map,
                                                   hospital_id,
                                                   _get_day_off_entries(
                                                       inp.day_off_dates, d.id))
                                  and not _compute_post_call_restricted_for_slot(
                                      d.id, date, slot_obj.start_time)]
                    if not avail_docs:
                        break

                    def _session_debt(d):
                        adj = _compute_adjusted_quota(d, week_num, days, inp.day_off_dates)
                        return adj - sessions_by_doc_week[d.id].get(week_num, 0)

                    def _am_pm_bal(d):
                        imb = am_by_doc_week[d.id].get(week_num, 0) - pm_by_doc_week[d.id].get(week_num, 0)
                        is_am = slot_obj.shift_type == 'office_am'
                        if d.am_pm_preference == "balanced" and abs(imb) >= 1:
                            return -1 if (imb > 0 and not is_am) or (imb < 0 and is_am) else 1
                        return 0

                    if slot_obj.office_id == hospital_id:
                        def _nh_count(d):
                            return len(office_variety_by_doc_week[d.id].get(week_num, set()) - {hospital_id})
                        avail_docs.sort(key=lambda d: (
                            -_session_debt(d), -_nh_count(d), _am_pm_bal(d)))
                    else:
                        def _nh_var(d):
                            return len(office_variety_by_doc_week[d.id].get(week_num, set()) - {hospital_id})
                        avail_docs.sort(key=lambda d: (
                            -_session_debt(d), _nh_var(d), _am_pm_bal(d)))

                    chosen = None
                    for d in avail_docs:
                        adj = _compute_adjusted_quota(d, week_num, days, inp.day_off_dates)
                        if sessions_by_doc_week[d.id].get(week_num, 0) >= adj:
                            continue
                        # Enforce per-office weekly cap for non-hospital offices
                        if slot_obj.office_id != hospital_id:
                            office_week_sess = sessions_by_doc_office_week[d.id][week_num].get(slot_obj.office_id, 0)
                            if office_week_sess >= OFFICE_WEEKLY_CAP:
                                continue
                        chosen = d
                        break
                    if chosen is None:
                        break

                    assignments.append(Assignment(doctor_id=chosen.id,
                        slot_id=slot_obj.slot_id))
                    _update_load(load, chosen.id, slot_obj, hospital_id)
                    sessions_by_doc_week[chosen.id][week_num] += 1
                    office_variety_by_doc_week[chosen.id][week_num].add(slot_obj.office_id)
                    sessions_by_doc_office_week[chosen.id][week_num][slot_obj.office_id] += 1
                    if slot_obj.shift_type == 'office_am':
                        am_by_doc_week[chosen.id][week_num] += 1
                    else:
                        pm_by_doc_week[chosen.id][week_num] += 1

    # Phase 4b: Fill office slots to max_doctors (second pass)
    for day in days:
        if day['is_weekend'] or day['date'] in global_day_off_set:
            continue
        date = day['date']
        week_num = day['week_num']
        day_office_slots = [s for s in slots
                            if s.date == date
                            and s.shift_type in office_shift_types
                            and sum(1 for a in assignments if a.slot_id == s.slot_id) < s.max_doctors]
        day_office_slots.sort(key=lambda s: (
            0 if s.shift_type == 'office_am' and s.office_id == hospital_id else
            1 if s.shift_type == 'office_am' and s.office_id != hospital_id else
            2 if s.shift_type == 'office_pm' and s.office_id == hospital_id else
            3 if s.shift_type == 'office_pm' else 4,
            _office_phase_key(s), s.start_time))
        for slot_obj in day_office_slots:
            def _am_pm_sort_key_4b(d):
                imbalance = am_by_doc_week[d.id].get(week_num, 0) - pm_by_doc_week[d.id].get(week_num, 0)
                is_am = 1 if slot_obj.shift_type == 'office_am' else 0
                is_pm = 1 if slot_obj.shift_type in ('office_pm', 'office_late') else 0
                if d.am_pm_preference == "balanced" and abs(imbalance) >= 1:
                    return 1 if (imbalance > 0 and is_am) or (imbalance < 0 and is_pm) else 0
                if d.am_pm_preference == "am" and imbalance < 0:
                    return 1 if is_pm else 0
                if d.am_pm_preference == "pm" and imbalance > 0:
                    return 1 if is_am else 0
                return 0
            avail_docs = [d for d in inp.doctors
                if _is_available(d.id, slot_obj, assignments,
                    slot_map, load, doc_map, hospital_id,
                    _get_day_off_entries(inp.day_off_dates, d.id))]
            if slot_obj.office_id != hospital_id:
                avail_docs = [d for d in avail_docs
                              if not _compute_post_call_restricted_for_slot(d.id, date, slot_obj.start_time)]
            if slot_obj.office_id == hospital_id:
                def _variety_deficit_4b(d):
                    all_off = office_variety_by_doc_week[d.id].get(week_num, set())
                    n_nh = len(all_off - {hospital_id})
                    n_sess = sessions_by_doc_week[d.id].get(week_num, 0)
                    deficit = max(0, 2 - n_nh)
                    if deficit > 0 and n_sess >= 2:
                        deficit += 1
                    if n_nh <= 1 and n_sess >= 6:
                        deficit = max(deficit, 1)
                    return deficit
                avail_docs.sort(key=lambda d: (
                    0 if _is_post_call_restricted(d.id) else 1,
                    _am_pm_sort_key_4b(d),
                    _variety_deficit_4b(d),
                    1 if slot_obj.office_id in office_variety_by_doc_week[d.id].get(week_num, set()) else 0,
                    -len(office_variety_by_doc_week[d.id].get(week_num, set())),
                    sessions_by_doc_week[d.id].get(week_num, 0)))
            else:
                def _variety_deficit_non_hosp_4b(d):
                    all_off = office_variety_by_doc_week[d.id].get(week_num, set())
                    n_nh = len(all_off - {hospital_id})
                    n_sess = sessions_by_doc_week[d.id].get(week_num, 0)
                    deficit = max(0, 2 - n_nh)
                    if deficit > 0 and n_sess >= 1:
                        deficit += 1
                    return deficit
                avail_docs.sort(key=lambda d: (
                    0 if len(office_variety_by_doc_week[d.id].get(week_num, set()) - {hospital_id}) == 0 else 1,
                    _am_pm_sort_key_4b(d),
                    -_variety_deficit_non_hosp_4b(d),
                    1 if slot_obj.office_id in office_variety_by_doc_week[d.id].get(week_num, set()) else 0,
                    -len(office_variety_by_doc_week[d.id].get(week_num, set())),
                    sessions_by_doc_week[d.id].get(week_num, 0)))
                for doc in avail_docs:
                    adjusted_quota = _compute_adjusted_quota(doc, week_num, days, inp.day_off_dates)
                    week_count = sessions_by_doc_week[doc.id].get(week_num, 0)
                    if week_count >= adjusted_quota:
                        continue
                    cur = sum(1 for a in assignments if a.slot_id == slot_obj.slot_id)
                    if cur >= slot_obj.max_doctors:
                        break
                    assignments.append(Assignment(doctor_id=doc.id,
                        slot_id=slot_obj.slot_id))
                    _update_load(load, doc.id, slot_obj, hospital_id)
                    sessions_by_doc_week[doc.id][week_num] += 1
                    office_variety_by_doc_week[doc.id][week_num].add(slot_obj.office_id)
                    if slot_obj.shift_type == 'office_am':
                        am_by_doc_week[doc.id][week_num] += 1
                    else:
                        pm_by_doc_week[doc.id][week_num] += 1
                    if cur + 1 >= slot_obj.max_doctors:
                        break

    # Phase 5: Post-call morning assignments (soft preference S4).
    # For doctors with post_call_preference="work", after a call shift,
    # try to assign the hospital office AM the following morning.
    # Note: H8 clearing (hospital AM/PM + non-hospital PM) is already
    # handled in Phase 3.5. This phase only handles the S4 preference.
    if hospital_id:
        # Snapshot assignments to avoid iterating while mutating
        current_assignments = list(assignments)
        for doc in inp.doctors:
            if doc.post_call_preference != "work":
                continue
            for a in current_assignments:
                if a.doctor_id != doc.id:
                    continue
                slot = slot_map[a.slot_id]
                if slot.shift_type not in ('call_night', 'call_day',
                                           'call_weekend', 'call_weekend_sun'):
                    continue
                next_day_dt = dt_class.fromisoformat(slot.date) + timedelta(days=1)
                while next_day_dt.weekday() >= 5:
                    next_day_dt += timedelta(days=1)
                next_day = next_day_dt.isoformat()
                if next_day in global_day_off_set:
                    continue
                next_am_id = f"{next_day}_{hospital_id}_office_am"
                next_am = slot_map.get(next_am_id)
                if not next_am:
                    continue
                if sum(1 for a2 in assignments
                       if a2.slot_id == next_am_id) >= next_am.max_doctors:
                    continue
                if any(a2.doctor_id == doc.id and a2.slot_id == next_am_id for a2 in assignments):
                    continue
                doc_day_off_entries = _get_day_off_entries(inp.day_off_dates, doc.id)
                if _is_available(doc.id, next_am, assignments, slot_map,
                                 load, doc_map, hospital_id, doc_day_off_entries):
                    assignments.append(Assignment(doctor_id=doc.id,
                                                  slot_id=next_am_id))
                    _update_load(load, doc.id, next_am, hospital_id)
                    day_info = next((d for d in days if d['date'] == next_day), None)
                    if day_info:
                        wn = day_info['week_num']
                        sessions_by_doc_week[doc.id][wn] += 1
                        office_variety_by_doc_week[doc.id][wn].add(hospital_id)
                        am_by_doc_week[doc.id][wn] += 1
                    break

    # Phase 6: Mon/Thu late shift balance (soft balance S3)
    late_slots = [s for s in slots if s.shift_type == 'office_late']
    late_slots.sort(key=lambda s: (_office_phase_key(s), s.date))
    late_by_doc = defaultdict(int)
    for a in assignments:
        slot = slot_map.get(a.slot_id)
        if slot and slot.shift_type == 'office_late':
            late_by_doc[a.doctor_id] += 1

    for slot_obj in late_slots:
        if sum(1 for a in assignments if a.slot_id == slot_obj.slot_id) >= slot_obj.max_doctors:
            continue
        avail_docs = [d for d in inp.doctors
                      if _is_available(d.id, slot_obj, assignments,
                                       slot_map, load, doc_map,
                                       hospital_id,
                                       _get_day_off_entries(
                                           inp.day_off_dates, d.id))]
        avail_docs = [d for d in avail_docs
                      if not _compute_post_call_restricted_for_slot(d.id, slot_obj.date, slot_obj.start_time)]
        avail_docs.sort(key=lambda d: late_by_doc.get(d.id, 0))
        for doc in avail_docs:
            day_info = next((dd for dd in days if dd['date'] == slot_obj.date), None)
            if not day_info:
                continue
            wn = day_info['week_num']
            adjusted_quota = _compute_adjusted_quota(doc, wn, days, inp.day_off_dates)
            if sessions_by_doc_week[doc.id].get(wn, 0) >= adjusted_quota + 1:
                continue
            assignments.append(Assignment(doctor_id=doc.id,
                slot_id=slot_obj.slot_id))
            _update_load(load, doc.id, slot_obj, hospital_id)
            sessions_by_doc_week[doc.id][wn] += 1
            late_by_doc[doc.id] += 1
            office_variety_by_doc_week[doc.id][wn].add(slot_obj.office_id)
            pm_by_doc_week[doc.id][wn] += 1
            if sum(1 for a in assignments
                   if a.slot_id == slot_obj.slot_id) >= slot_obj.max_doctors:
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

        # H12: Office variety — each doctor must use at least 1 non-hospital
        # office in any week where they have 3+ sessions (hard constraint).
        # Build binary variables tracking non-hospital office usage per doctor-week.
        office_shift_types_ilp = {'office_am', 'office_pm', 'office_late',
                                   'surgical_am', 'surgical_hosp_pm'}
        nh_office_ids = [o.id for o in inp.offices if o.id != hospital_id]

        _ilp_first_dow = dt_class(inp.year, inp.month + 1, 1).weekday()
        _ilp_day_to_week = {}
        for s in ilp_slots:
            day_num = int(s.date.split('-')[2])
            _ilp_day_to_week[s.date] = (day_num + _ilp_first_dow - 1) // 7
        _ilp_max_week = max(_ilp_day_to_week.values(), default=0) if _ilp_day_to_week else 0

        uses_off_vars = {}
        for doc in inp.doctors:
            for wn in range(_ilp_max_week + 1):
                for off_id in nh_office_ids:
                    var = pulp.LpVariable(
                        f"uses_off_{doc.id}_wk{wn}_{off_id}",
                        cat="Binary"
                    )
                    uses_off_vars[(doc.id, wn, off_id)] = var

        for doc in inp.doctors:
            for wn in range(_ilp_max_week + 1):
                for off_id in nh_office_ids:
                    var = uses_off_vars.get((doc.id, wn, off_id))
                    if not var:
                        continue
                    off_slots = [s for s in ilp_slots
                                 if s.shift_type in office_shift_types_ilp
                                 and s.office_id == off_id
                                 and _ilp_day_to_week.get(s.date) == wn
                                 and (doc.id, s.slot_id) in x]
                    for slot in off_slots:
                        prob += (
                            var >= x[(doc.id, slot.slot_id)],
                            f"h12_link_{doc.id}_wk{wn}_{off_id}_{slot.slot_id}"
                        )

        for doc in inp.doctors:
            for wn in range(_ilp_max_week + 1):
                week_off_vars = [uses_off_vars[(doc.id, wn, o)]
                                 for o in nh_office_ids
                                 if (doc.id, wn, o) in uses_off_vars]
                if not week_off_vars:
                    continue
                doc_week_slots = [s for s in ilp_slots
                                  if s.shift_type in office_shift_types_ilp
                                  and _ilp_day_to_week.get(s.date) == wn
                                  and (doc.id, s.slot_id) in x]
                sessions_in_week = pulp.lpSum(
                    x[(doc.id, s.slot_id)] for s in doc_week_slots
                )
                prob += (
                    sessions_in_week - 3 <= 1000 * (1 - pulp.lpSum(week_off_vars)),
                    f"h12_variety_{doc.id}_wk{wn}"
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
        _surg_pair_added = set()
        for day_item in get_days_in_month(inp.year, inp.month):
            if day_item['day_of_week'] in (1, 2, 3) and hospital_id:
                surg_am_id = f"{day_item['date']}_{hospital_id}_surgical_am"
                surg_pm_id = f"{day_item['date']}_{hospital_id}_surgical_hosp_pm"
                for doc in inp.doctors:
                    cname = f"surg_pair_{doc.id}_{day_item['date']}"
                    if cname in _surg_pair_added:
                        continue
                    if (doc.id, surg_am_id) in x and (doc.id, surg_pm_id) in x:
                        prob += (
                            x[(doc.id, surg_am_id)] == x[(doc.id, surg_pm_id)],
                            cname
                        )
                        _surg_pair_added.add(cname)

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
                # Hard limit: no doctor can have more than ceil(avg+1) in any group
                max_allowed = (len(group_slots) + len(eligible) - 1) // len(eligible)
                prob += (total_per_doc[d.id] <= max_allowed,
                         f"bal_hard_{group}_{d.id}")

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
                pref_cost_terms.append(-3.0 * x[(did, sid)])
            else:
                pref_cost_terms.append(1.5 * x[(did, sid)])

        pref_cost = pulp.lpSum(pref_cost_terms) if pref_cost_terms else 0

        max_session_dev = pulp.LpVariable("max_session_dev", lowBound=0)
        session_eligible = inp.doctors
        office_ilp_slots = [s for s in ilp_slots
                            if s.shift_type in ("surgical_am", "surgical_hosp_pm")]
        if office_ilp_slots and session_eligible:
            sess_total_per_doc = {
                d.id: pulp.lpSum(
                    x.get((d.id, s.slot_id), 0) for s in office_ilp_slots
                ) for d in session_eligible
            }
            sess_avg = pulp.lpSum(sess_total_per_doc.values()) / len(session_eligible)
            for d in session_eligible:
                if d.id in sess_total_per_doc:
                    prob += (sess_total_per_doc[d.id] - sess_avg <= max_session_dev,
                        f"sess_bal_upper_{d.id}")
                    prob += (sess_avg - sess_total_per_doc[d.id] <= max_session_dev,
                        f"sess_bal_lower_{d.id}")

        balance_obj = pulp.lpSum(max_dev_terms) * 10
        session_balance_obj = max_session_dev * 5
        prob.setObjective(balance_obj + session_balance_obj + pref_cost)

        # Solve
        solver = pulp.PULP_CBC_CMD(
            msg=0,
            timeLimit=inp.solver_time_limit_seconds,
            options=["ratioGap 0.02", "cuts on", "presolve on"]
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
        # Replay all ILP assignments in chronological order so post_call_restricted
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

        def _compute_post_call_restricted_ilp_for_slot(doc_id, date_str, start_time):
            from datetime import date as dt_date, timedelta
            most_recent_call = None
            for a in assignments:
                if a.doctor_id != doc_id:
                    continue
                s = slot_map.get(a.slot_id)
                if not s or s.date > date_str:
                    continue
                if s.shift_type in ('call_day', 'call_night', 'call_weekend', 'call_weekend_sun'):
                    if most_recent_call is None or s.date > most_recent_call.date or \
                       (s.date == most_recent_call.date and s.start_time > most_recent_call.start_time):
                        most_recent_call = s
            if most_recent_call is None:
                return False
            call_times = SHIFT_TIMES.get(most_recent_call.shift_type, ('00:00', '23:59'))
            call_end_time = call_times[1]
            call_date = most_recent_call.date
            if most_recent_call.shift_type == 'call_night':
                call_end_date = str(dt_date.fromisoformat(call_date) + timedelta(days=1))
            else:
                call_end_date = call_date
            for a in assignments:
                if a.doctor_id != doc_id:
                    continue
                s = slot_map.get(a.slot_id)
                if not s or s.date > date_str:
                    continue
                if s.office_id != hospital_id:
                    continue
                if s.shift_type not in ('office_am', 'office_pm', 'office_late',
                                         'surgical_am', 'surgical_hosp_pm'):
                    continue
                if s.start_time > start_time:
                    continue
                if s.date > call_end_date:
                    return False
                if s.date == call_end_date and s.start_time >= call_end_time:
                    return False
            return True

        def _has_hospital_before_slot_ilp(doc_id, date_str, start_time):
            for a in assignments:
                if a.doctor_id != doc_id:
                    continue
                s = slot_map.get(a.slot_id)
                if not s:
                    continue
                if s.date == date_str and s.office_id == hospital_id:
                    if s.start_time <= start_time:
                        return True
            return False

        days = get_days_in_month(inp.year, inp.month)
        all_office_shift_types_ilp = ['office_am', 'office_pm', 'office_late',
            'surgical_am', 'surgical_hosp_pm']
        office_shift_types_ilp = ["office_am", "office_pm", "office_late"]
        sessions_by_doc_week = defaultdict(lambda: defaultdict(int))
        office_variety_ilp = defaultdict(lambda: defaultdict(set))
        am_by_doc_week = defaultdict(lambda: defaultdict(int))
        pm_by_doc_week = defaultdict(lambda: defaultdict(int))

        for a in assignments:
            s = slot_map.get(a.slot_id)
            if not s or s.shift_type not in all_office_shift_types_ilp:
                continue
            day_info = next((d for d in days if d['date'] == s.date), None)
            if not day_info:
                continue
            wn = day_info['week_num']
            sessions_by_doc_week[a.doctor_id][wn] += 1
            office_variety_ilp[a.doctor_id][wn].add(s.office_id)
            if s.shift_type in ('office_am', 'surgical_am'):
                am_by_doc_week[a.doctor_id][wn] += 1
            else:
                pm_by_doc_week[a.doctor_id][wn] += 1

        ranking = inp.global_office_ranking

        def _ilp_office_phase_key(slot_obj):
            if slot_obj.office_id == hospital_id:
                return (0, 0)
            if ranking and slot_obj.office_id in ranking:
                return (1, ranking.index(slot_obj.office_id))
            return (1, len(ranking) if ranking else 0)

        def _ilp_is_post_call_restricted(doc_id):
            """Check if doctor is post-call restricted using the load dict boolean."""
            return load[doc_id]['post_call_restricted']

        all_sorted_dates = sorted(ilp_by_date.keys())
        prev_date_replayed = set()
        for day in days:
            if day['is_weekend'] or day['date'] in global_day_off_set:
                continue
            date = day['date']
            week_num = day['week_num']
            for prev_date_str in all_sorted_dates:
                if prev_date_str >= date:
                    break
                if prev_date_str not in prev_date_replayed:
                    for a in ilp_by_date[prev_date_str]:
                        slot = slot_map.get(a.slot_id)
                        if slot:
                            _update_load(load, a.doctor_id, slot, hospital_id)
                    prev_date_replayed.add(prev_date_str)
            # Phase 3.5: Post-call hospital office — assign post-call
            # doctors to next-day hospital office AM/PM to clear H8
            # restriction, then also assign a non-hospital PM for variety.
            if hospital_id:
                for doc in inp.doctors:
                    if not load[doc.id]['post_call_restricted']:
                        continue
                    doc_day_off_entries = _get_day_off_entries(day_off_dates, doc.id)
                    already_has_hosp_am = any(
                        a2.doctor_id == doc.id and
                        slot_map.get(a2.slot_id, None) is not None and
                        slot_map[a2.slot_id].date == date and
                        slot_map[a2.slot_id].office_id == hospital_id and
                        slot_map[a2.slot_id].shift_type == 'office_am'
                        for a2 in assignments)
                    if already_has_hosp_am:
                        doc_nh_ilp = office_variety_ilp[doc.id].get(week_num, set()) - {hospital_id}
                        nh_offs = [off for off in inp.offices if off.id != hospital_id]
                        nh_offs.sort(key=lambda o: (
                            0 if o.id not in doc_nh_ilp else 1,
                            len([a for a in assignments
                                 if slot_map.get(a.slot_id) is not None
                                 and slot_map[a.slot_id].office_id == o.id
                                 and slot_map[a.slot_id].date.startswith(date[:4])
                                 and a.doctor_id == doc.id])))
                        for off in nh_offs:
                            pm_id = f"{date}_{off.id}_office_pm"
                            pm_slot = slot_map.get(pm_id)
                            if not pm_slot:
                                continue
                            if sum(1 for a2 in assignments
                                   if a2.slot_id == pm_id) >= pm_slot.max_doctors:
                                continue
                            if is_avail(doc.id, pm_slot):
                                assign(doc.id, pm_slot)
                                sessions_by_doc_week[doc.id][week_num] += 1
                                office_variety_ilp[doc.id][week_num].add(off.id)
                                pm_by_doc_week[doc.id][week_num] += 1
                                break
                        continue
                    for ampm in ('office_am', 'office_pm'):
                        hs_id = f"{date}_{hospital_id}_{ampm}"
                        hs = slot_map.get(hs_id)
                        if not hs:
                            continue
                        if sum(1 for a2 in assignments if a2.slot_id == hs_id) >= hs.max_doctors:
                            continue
                        if is_avail(doc.id, hs):
                            assign(doc.id, hs)
                            sessions_by_doc_week[doc.id][week_num] += 1
                            office_variety_ilp[doc.id][week_num].add(hospital_id)
                            if ampm == 'office_am':
                                am_by_doc_week[doc.id][week_num] += 1
                            else:
                                pm_by_doc_week[doc.id][week_num] += 1
                            if ampm == 'office_am':
                                doc_nh_ilp_am = office_variety_ilp[doc.id].get(week_num, set()) - {hospital_id}
                                nh_offs = [off for off in inp.offices if off.id != hospital_id]
                                nh_offs.sort(key=lambda o: (
                                    0 if o.id not in doc_nh_ilp_am else 1,
                                    len([a for a in assignments
                                         if slot_map.get(a.slot_id) is not None
                                         and slot_map[a.slot_id].office_id == o.id
                                         and slot_map[a.slot_id].date.startswith(date[:4])
                                         and a.doctor_id == doc.id])))
                                for off in nh_offs:
                                    pm_id = f"{date}_{off.id}_office_pm"
                                    pm_slot = slot_map.get(pm_id)
                                    if not pm_slot:
                                        continue
                                    if sum(1 for a2 in assignments
                                           if a2.slot_id == pm_id) >= pm_slot.max_doctors:
                                        continue
                                    if is_avail(doc.id, pm_slot):
                                        assign(doc.id, pm_slot)
                                        sessions_by_doc_week[doc.id][week_num] += 1
                                        office_variety_ilp[doc.id][week_num].add(off.id)
                                        pm_by_doc_week[doc.id][week_num] += 1
                                        break
                            break
            day_office_slots = [s for s in slots
                if s.date == date
                and s.shift_type in office_shift_types_ilp
                and sum(1 for a in assignments
                        if a.slot_id == s.slot_id) < s.max_doctors]
            day_office_slots.sort(key=lambda s: (
                0 if s.shift_type == 'office_am' and s.office_id == hospital_id else
                1 if s.shift_type == 'office_am' and s.office_id != hospital_id else
                2 if s.shift_type == 'office_pm' and s.office_id == hospital_id else
                3 if s.shift_type == 'office_pm' else 4,
                _ilp_office_phase_key(s), s.start_time))

            for slot_obj in day_office_slots:
                cur = sum(1 for a in assignments if a.slot_id == slot_obj.slot_id)
                if cur >= slot_obj.max_doctors:
                    continue
                avail_docs = [d for d in inp.doctors
                    if is_avail(d.id, slot_obj)]
                if slot_obj.office_id != hospital_id:
                    avail_docs = [d for d in avail_docs
                                  if not _compute_post_call_restricted_ilp_for_slot(d.id, date, slot_obj.start_time)]
                def _am_pm_sort_key_ilp(d):
                    imbalance = am_by_doc_week[d.id].get(week_num, 0) - pm_by_doc_week[d.id].get(week_num, 0)
                    is_am = slot_obj.shift_type == 'office_am'
                    is_pm = slot_obj.shift_type in ('office_pm', 'office_late')
                    if d.am_pm_preference == "balanced" and abs(imbalance) >= 1:
                        return 1 if (imbalance > 0 and is_am) or (imbalance < 0 and is_pm) else 0
                    if d.am_pm_preference == "am" and imbalance < 0:
                        return 1 if is_pm else 0
                    if d.am_pm_preference == "pm" and imbalance > 0:
                        return 1 if is_am else 0
                    return 0

                if slot_obj.office_id == hospital_id:
                    def _variety_deficit_ilp(d):
                        all_off = office_variety_ilp[d.id].get(week_num, set())
                        n_nh = len(all_off - {hospital_id})
                        n_sess = sessions_by_doc_week[d.id].get(week_num, 0)
                        deficit = max(0, 2 - n_nh)
                        if deficit > 0 and n_sess >= 2:
                            deficit += 1
                        if n_nh <= 1 and n_sess >= 6:
                            deficit = max(deficit, 1)
                        return deficit
                    avail_docs.sort(key=lambda d: (
                        0 if _ilp_is_post_call_restricted(d.id) else 1,
                        _am_pm_sort_key_ilp(d),
                        _variety_deficit_ilp(d),
                        1 if slot_obj.office_id in office_variety_ilp[d.id].get(week_num, set()) else 0,
                        -len(office_variety_ilp[d.id].get(week_num, set())),
                        sessions_by_doc_week[d.id].get(week_num, 0)))
                else:
                    def _variety_deficit_non_hosp_ilp(d):
                        all_off = office_variety_ilp[d.id].get(week_num, set())
                        n_nh = len(all_off - {hospital_id})
                        n_sess = sessions_by_doc_week[d.id].get(week_num, 0)
                        deficit = max(0, 2 - n_nh)
                        if deficit > 0 and n_sess >= 1:
                            deficit += 1
                        return deficit
                    avail_docs.sort(key=lambda d: (
                        0 if len(office_variety_ilp[d.id].get(week_num, set()) - {hospital_id}) == 0 else 1,
                        _am_pm_sort_key_ilp(d),
                        -_variety_deficit_non_hosp_ilp(d),
                        1 if slot_obj.office_id in office_variety_ilp[d.id].get(week_num, set()) else 0,
                        -len(office_variety_ilp[d.id].get(week_num, set())),
                        sessions_by_doc_week[d.id].get(week_num, 0)))

                for doc in avail_docs:
                    adjusted_quota = _compute_adjusted_quota(doc, week_num, days, day_off_dates)
                    week_count = sessions_by_doc_week[doc.id].get(week_num, 0)
                    if week_count >= adjusted_quota:
                        continue
                    cur = sum(1 for a in assignments if a.slot_id == slot_obj.slot_id)
                    if cur >= slot_obj.max_doctors:
                        break
                    assign(doc.id, slot_obj)
                    sessions_by_doc_week[doc.id][week_num] += 1
                    office_variety_ilp[doc.id][week_num].add(slot_obj.office_id)
                    if slot_obj.shift_type == 'office_am':
                        am_by_doc_week[doc.id][week_num] += 1
                    else:
                        pm_by_doc_week[doc.id][week_num] += 1
                    break

        # Phase 4b: Fill office slots to max_doctors (second pass)
        for day in days:
            if day['is_weekend'] or day['date'] in global_day_off_set:
                continue
            date = day['date']
            week_num = day['week_num']
            hosp_office_today = [s for s in slots
                if s.date == date and s.office_id == hospital_id
                and s.shift_type in office_shift_types_ilp]
            if hosp_office_today:
                all_full = all(
                    sum(1 for a in assignments
                        if a.slot_id == hs.slot_id) >= hs.max_doctors
                    for hs in hosp_office_today)
                if all_full:
                    for d in inp.doctors:
                        if load[d.id]['post_call_restricted']:
                            load[d.id]['post_call_restricted'] = False
            day_office_slots = [s for s in slots
                if s.date == date
                and s.shift_type in office_shift_types_ilp
                and sum(1 for a in assignments if a.slot_id == s.slot_id) < s.max_doctors]
            day_office_slots.sort(key=lambda s: (
                0 if s.shift_type == 'office_am' and s.office_id == hospital_id else
                1 if s.shift_type == 'office_am' and s.office_id != hospital_id else
                2 if s.shift_type == 'office_pm' and s.office_id == hospital_id else
                3 if s.shift_type == 'office_pm' else 4,
                _ilp_office_phase_key(s), s.start_time))
            for slot_obj in day_office_slots:
                def _am_pm_sort_key_ilp_4b(d):
                    imbalance = am_by_doc_week[d.id].get(week_num, 0) - pm_by_doc_week[d.id].get(week_num, 0)
                    is_am = 1 if slot_obj.shift_type == 'office_am' else 0
                    is_pm = 1 if slot_obj.shift_type in ('office_pm', 'office_late') else 0
                    if d.am_pm_preference == "balanced" and abs(imbalance) >= 1:
                        return 1 if (imbalance > 0 and is_am) or (imbalance < 0 and is_pm) else 0
                    if d.am_pm_preference == "am" and imbalance < 0:
                        return 1 if is_pm else 0
                    if d.am_pm_preference == "pm" and imbalance > 0:
                        return 1 if is_am else 0
                    return 0
                avail_docs = [d for d in inp.doctors
                    if is_avail(d.id, slot_obj)]
                if slot_obj.office_id != hospital_id:
                    avail_docs = [d for d in avail_docs
                                  if not _compute_post_call_restricted_ilp_for_slot(d.id, date, slot_obj.start_time)]
                if slot_obj.office_id == hospital_id:
                    def _variety_deficit_ilp_4b(d):
                        all_off = office_variety_ilp[d.id].get(week_num, set())
                        n_nh = len(all_off - {hospital_id})
                        n_sess = sessions_by_doc_week[d.id].get(week_num, 0)
                        deficit = max(0, 2 - n_nh)
                        if deficit > 0 and n_sess >= 2:
                            deficit += 1
                        if n_nh <= 1 and n_sess >= 6:
                            deficit = max(deficit, 1)
                        return deficit
                    avail_docs.sort(key=lambda d: (
                        0 if _ilp_is_post_call_restricted(d.id) else 1,
                        _am_pm_sort_key_ilp_4b(d),
                        _variety_deficit_ilp_4b(d),
                        1 if slot_obj.office_id in office_variety_ilp[d.id].get(week_num, set()) else 0,
                        -len(office_variety_ilp[d.id].get(week_num, set())),
                        sessions_by_doc_week[d.id].get(week_num, 0)))
                else:
                    def _variety_deficit_non_hosp_ilp_4b(d):
                        all_off = office_variety_ilp[d.id].get(week_num, set())
                        n_nh = len(all_off - {hospital_id})
                        n_sess = sessions_by_doc_week[d.id].get(week_num, 0)
                        deficit = max(0, 2 - n_nh)
                        if deficit > 0 and n_sess >= 1:
                            deficit += 1
                        return deficit
                    avail_docs.sort(key=lambda d: (
                        0 if len(office_variety_ilp[d.id].get(week_num, set()) - {hospital_id}) == 0 else 1,
                        _am_pm_sort_key_ilp_4b(d),
                        -_variety_deficit_non_hosp_ilp_4b(d),
                        1 if slot_obj.office_id in office_variety_ilp[d.id].get(week_num, set()) else 0,
                        -len(office_variety_ilp[d.id].get(week_num, set())),
                        sessions_by_doc_week[d.id].get(week_num, 0)))
                for doc in avail_docs:
                    adjusted_quota = _compute_adjusted_quota(doc, week_num, days, day_off_dates)
                    week_count = sessions_by_doc_week[doc.id].get(week_num, 0)
                    if week_count >= adjusted_quota:
                        continue
                    cur = sum(1 for a in assignments if a.slot_id == slot_obj.slot_id)
                    if cur >= slot_obj.max_doctors:
                        break
                    assign(doc.id, slot_obj)
                    sessions_by_doc_week[doc.id][week_num] += 1
                    office_variety_ilp[doc.id][week_num].add(slot_obj.office_id)
                    if slot_obj.shift_type == 'office_am':
                        am_by_doc_week[doc.id][week_num] += 1
                    else:
                        pm_by_doc_week[doc.id][week_num] += 1
                    if cur + 1 >= slot_obj.max_doctors:
                        break

        # Phase 5: Post-call morning assignments — clear H8 restriction
        # by assigning hospital office AM after call, plus non-hospital
        # PM for variety if doctor has only 1 office so far.
        if hospital_id:
            for doc in inp.doctors:
                if doc.post_call_preference != "work":
                    continue
                for a in assignments:
                    if a.doctor_id != doc.id:
                        continue
                    slot = slot_map[a.slot_id]
                    if slot.shift_type not in ('call_night', 'call_day',
                        'call_weekend', 'call_weekend_sun'):
                        continue
                    next_day_dt = dt_class.fromisoformat(slot.date) + timedelta(days=1)
                    while next_day_dt.weekday() >= 5:
                        next_day_dt += timedelta(days=1)
                    next_day = next_day_dt.isoformat()
                    if next_day in global_day_off_set:
                        continue
                    next_am_id = f"{next_day}_{hospital_id}_office_am"
                    next_am = slot_map.get(next_am_id)
                    if not next_am:
                        continue
                    if sum(1 for a2 in assignments
                           if a2.slot_id == next_am_id) >= next_am.max_doctors:
                        continue
                    doc_day_off_entries = _get_day_off_entries(day_off_dates, doc.id)
                    if is_avail(doc.id, next_am):
                        assign(doc.id, next_am)
                        for d in days:
                            if d['date'] == next_day:
                                wn = d['week_num']
                                sessions_by_doc_week[doc.id][wn] += 1
                                office_variety_ilp[doc.id][wn].add(hospital_id)
                                am_by_doc_week[doc.id][wn] += 1
                                non_hosp_pm = None
                                doc_nh_ilp_5 = office_variety_ilp[doc.id].get(wn, set()) - {hospital_id}
                                nh_offs = [off for off in inp.offices if off.id != hospital_id]
                                nh_offs.sort(key=lambda o: (
                                    0 if o.id not in doc_nh_ilp_5 else 1,
                                    len([a for a in assignments
                                         if slot_map.get(a.slot_id) is not None
                                         and slot_map[a.slot_id].office_id == o.id
                                         and slot_map[a.slot_id].date.startswith(next_day[:4])
                                         and a.doctor_id == doc.id])))
                                for off in nh_offs:
                                    pm_id = f"{next_day}_{off.id}_office_pm"
                                    pm_slot = slot_map.get(pm_id)
                                    if not pm_slot:
                                        continue
                                    if sum(1 for a2 in assignments
                                           if a2.slot_id == pm_id) >= pm_slot.max_doctors:
                                        continue
                                    if is_avail(doc.id, pm_slot):
                                        non_hosp_pm = (pm_id, pm_slot, off.id)
                                        break
                                if non_hosp_pm:
                                    pm_id, pm_slot, off_id = non_hosp_pm
                                    assign(doc.id, pm_slot)
                                    sessions_by_doc_week[doc.id][wn] += 1
                                    office_variety_ilp[doc.id][wn].add(off_id)
                                    pm_by_doc_week[doc.id][wn] += 1
                                break

        # Late shift balance (S3) — Mon/Thu office_late distribution
        late_slots = [s for s in slots if s.shift_type == 'office_late']
        late_slots.sort(key=lambda s: (_ilp_office_phase_key(s), s.date))
        late_by_doc = defaultdict(int)
        for a in assignments:
            sl = slot_map.get(a.slot_id)
            if sl and sl.shift_type == 'office_late':
                late_by_doc[a.doctor_id] += 1
        for slot_obj in late_slots:
            if sum(1 for a in assignments
                   if a.slot_id == slot_obj.slot_id) >= slot_obj.max_doctors:
                continue
            avail_docs = [d for d in inp.doctors
                if is_avail(d.id, slot_obj)]
            if not avail_docs:
                continue
            avail_docs.sort(key=lambda d: late_by_doc.get(d.id, 0))
            for doc in avail_docs:
                day_info = next((dd for dd in days if dd['date'] == slot_obj.date), None)
                if not day_info:
                    continue
                wn = day_info['week_num']
                adjusted_quota = _compute_adjusted_quota(doc, wn, days, day_off_dates)
                if sessions_by_doc_week[doc.id].get(wn, 0) >= adjusted_quota + 1:
                    continue
                assign(doc.id, slot_obj)
                late_by_doc[doc.id] += 1
                for d in days:
                    if d['date'] == slot_obj.date:
                        wn = d['week_num']
                        sessions_by_doc_week[doc.id][wn] += 1
                        office_variety_ilp[doc.id][wn].add(slot_obj.office_id)
                        pm_by_doc_week[doc.id][wn] += 1
                        break
                if sum(1 for a in assignments
                       if a.slot_id == slot_obj.slot_id) >= slot_obj.max_doctors:
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
    """Main entry point. Tries ILP and greedy, picks better result."""
    results = []
    try:
        results.append(('ilp', schedule_ilp(inp)))
    except Exception:
        pass
    try:
        results.append(('greedy', schedule_greedy(inp)))
    except Exception:
        pass
    if not results:
        raise RuntimeError("Both ILP and greedy schedulers failed")
    if len(results) == 1:
        return results[0][1]
    best = min(results, key=lambda x: (
        sum(1 for v in x[1].unmet_constraints if v['severity'] == 'hard'),
        len(x[1].unmet_constraints)))
    return best[1]
