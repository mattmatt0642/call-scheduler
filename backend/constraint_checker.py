from dataclasses import dataclass
from typing import List, Dict, Optional, Set
from datetime import date as dt_class, timedelta
from models import (DoctorProfile, Office, ShiftSlot, Assignment, ScheduleInput,
 abs_times_overlap, get_call_balance_group, get_days_in_month, get_nth_tuesdays, prev_date, SHIFT_TIMES, SHIFT_PERIODS)

CALL_SHIFT_TYPES = {"call_day", "call_night", "call_weekend", "call_weekend_sun"}
CLEARING_SHIFT_TYPES = {"office_am", "office_pm", "office_late", "surgical_am", "surgical_hosp_pm"}
OFFICE_SESSION_TYPES = {"office_am", "office_pm", "office_late", "surgical_am", "surgical_hosp_pm"}

@dataclass
class ConstraintViolation:
    constraint_id: str
    constraint_name: str
    severity: str
    description: str
    affected_doctors: List[str]
    affected_dates: List[str]
    suggestion: str

def validate_schedule(
    inp: 'ScheduleInput',
    slots: List[ShiftSlot],
    assignments: List[Assignment]
) -> List[ConstraintViolation]:
    """
    Run all constraint checks on a completed schedule.
    Returns an empty list of the schedule is valid.
    Returns a list of ConstraintViolation objects for every problem.
    Always run after generations - this is a final check.
    """
    slot_map = {s.slot_id: s for s in slots}
    violations = []
    unknown_assignments = [a for a in assignments if a.slot_id not in slot_map]
    known_assignments = [a for a in assignments if a.slot_id in slot_map]
    if unknown_assignments:
        for a in unknown_assignments:
            violations.append(ConstraintViolation(
                constraint_id = "H1",
                constraint_name = "capacity",
                severity = "hard",
                description = f"Slot {a.slot_id} does not exist in the generated schedule",
                affected_doctors = [a.doctor_id],
                affected_dates = [],
                suggestion = "Remove assignments for non-existent slots"
            ))
    violations += check_h1_capacity(slots, known_assignments, slot_map)
    violations += check_h2_restricted_tuesday(slots, known_assignments, slot_map, inp.offices)
    violations += check_h3_call_coverage(slots, known_assignments, slot_map)
    violations += check_h4_call_double(inp.doctors, known_assignments, slot_map)
    violations += check_h4b_max_call_limits(inp.doctors, known_assignments, slot_map)
    violations += check_h5_call_balance(inp.doctors, known_assignments, slot_map)
    violations += check_h6_no_overlap(inp.doctors, known_assignments, slot_map)
    violations += check_h7_surgical_pairing(known_assignments, slot_map)
    violations += check_h8_post_call_location(inp.doctors, inp.offices, slots, known_assignments, slot_map)
    violations += check_h9_allowed_offices(inp.doctors, known_assignments, slot_map)
    violations += check_h10_days_off(inp.doctors, known_assignments, slot_map, inp.day_off_dates)
    violations += check_h11_locked_preserved(inp, slots, known_assignments, slot_map)
    violations += check_h12_required_sessions(inp.doctors, known_assignments, slot_map, inp.day_off_dates, inp.year, inp.month, inp.offices)
    violations += check_h13_late_shift_distinctness(slots, known_assignments, slot_map)
    violations += check_s1_am_pm_balance(inp.doctors, known_assignments, slot_map, inp.year, inp.month)
    violations += check_s2_office_ranking(inp.doctors, known_assignments, slot_map, inp.global_office_ranking, inp.day_off_dates, inp.offices)
    violations += check_s3_late_shift_balance(inp.doctors, known_assignments, slot_map, inp.year, inp.month, inp.day_off_dates, inp.offices)
    violations += check_s4_post_call_work_preference(inp.doctors, known_assignments, slot_map, inp.offices)
    violations += check_s5_call_shift_preference(inp.doctors, known_assignments, slot_map)
    violations += check_s6_day_night_preference(inp.doctors, known_assignments, slot_map)
    violations += check_s7_office_variety(inp.doctors, known_assignments, slot_map, inp.offices)
    return violations

def check_h1_capacity(
    slots: List[ShiftSlot],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    H1: The number of doctors assigned to any single lot must not exceed
    slot.max_doctors.
    """
    violations = []
    a_docs = {}

    for a in assignments:
        a_docs.setdefault(a.slot_id, []).append(a.doctor_id)

    for s_id, d_id in a_docs.items():
        if slot_map[s_id].max_doctors < len(d_id):
            violations.append(ConstraintViolation(
                constraint_id = "H1",
                constraint_name = "capacity",
                severity = "hard",
                description = f"Slot {s_id} has {len(d_id)} doctors assigned but max is {slot_map[s_id].max_doctors}",
                affected_doctors = d_id,
                affected_dates = [slot_map[s_id].date],
                suggestion = "Remove one doctor from this shift or increase max_per_shift for this office"
            ))
    return violations

def check_h2_restricted_tuesday(
    slots: List[ShiftSlot],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot],
    offices: List[Office]
) -> List[ConstraintViolation]:
    """
    H2: 1st, 3rd, and 5th Tuesday of each month, hospital office has a lower
    max capacity (restricted_tuesday_max). Applies to both AM and PM slots
    at the hospital office only.
    """
    violations = []
    hospital = next((o for o in offices if o.is_hospital), None)
    if not hospital:
        return violations

    restricted_slots = [s for s in slots if s.is_restricted_tuesday]

    a_docs = {}
    for a in assignments:
        a_docs.setdefault(a.slot_id, []).append(a.doctor_id)

    for slot in restricted_slots:
        if slot.office_id != hospital.id:
            violations.append(ConstraintViolation(
                constraint_id = "H2",
                constraint_name = "Restricted Tuesday",
                severity = "hard",
                description = f"Slot {slot.slot_id} is marked restricted_tuesday but is not at the hospital office ({slot.office_id}).",
                affected_doctors = [],
                affected_dates = [slot.date],
                suggestion = "Check slot_generator: is_restricted_tuesday should only apply to hospital office slots."
            ))
            continue

        if slot.shift_type not in ("office_am", "office_pm"):
            continue

        count = len(a_docs.get(slot.slot_id, []))
        if count > slot.max_doctors:
            violations.append(ConstraintViolation(
                constraint_id = "H2",
                constraint_name = "Restricted Tuesday",
                severity = "hard",
                description = f"Restricted Tuesday slot {slot.slot_id} has {count} doctors assigned but max is {slot.max_doctors} (restricted_tuesday_max={hospital.restricted_tuesday_max}).",
                affected_doctors = a_docs.get(slot.slot_id, []),
                affected_dates = [slot.date],
                suggestion = "Reduce assignments on this restricted Tuesday or increase restricted_tuesday_max."
            ))

        if slot.max_doctors != hospital.restricted_tuesday_max:
            violations.append(ConstraintViolation(
                constraint_id = "H2",
                constraint_name = "Restricted Tuesday",
                severity = "hard",
                description = f"Restricted Tuesday slot {slot.slot_id} has max_doctors={slot.max_doctors} but hospital restricted_tuesday_max={hospital.restricted_tuesday_max}. Slot generator may not have applied the restriction.",
                affected_doctors = [],
                affected_dates = [slot.date],
                suggestion = "Check slot_generator: restricted Tuesday slots must have max_doctors set to restricted_tuesday_max."
            ))

    return violations

def check_h3_call_coverage(
    slots: List[ShiftSlot],
    assignment: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    H3: Each call slot must have exactly 1 doctor assigned.
    """
    violations = []
    call_slots = [s for s in slots if s.shift_type in CALL_SHIFT_TYPES]
    assigned = {}
    for a in assignment:
        slot = slot_map[a.slot_id]
        if slot.shift_type in CALL_SHIFT_TYPES:
            assigned.setdefault(a.slot_id, []).append(a.doctor_id)

    for slot in call_slots:
        count = len(assigned.get(slot.slot_id, []))
        if slot.shift_type == "call_weekend_sun":
            if count == 0:
                sat_date = prev_date(slot.date)
                sat_assigned = len(assigned.get(f"{sat_date}_{slot.office_id}_call_weekend", []))
                if sat_assigned > 0:
                    violations.append(ConstraintViolation(
                        constraint_id = "H3",
                        constraint_name = "call coverage",
                        severity = "hard",
                        description = f"No doctor assigned to call_weekend_sun on {slot.date} but Saturday is assigned. Weekend block pairing broken.",
                        affected_doctors = [],
                        affected_dates = [slot.date],
                        suggestion = "Check weekend block assignment logic. Saturday and Sunday must be same doctor."
                    ))
                else:
                    violations.append(ConstraintViolation(
                        constraint_id = "H3",
                        constraint_name = "call coverage",
                        severity = "hard",
                        description = f"No doctor assigned to call_weekend_sun on {slot.date}. (balance group: weekend_block) (preferences have no influence on this balance group)",
                        affected_doctors = [],
                        affected_dates = [slot.date],
                        suggestion = "Not enough doctors available for all call slots."
                    ))
            elif count > 1:
                violations.append(ConstraintViolation(
                    constraint_id = "H3",
                    constraint_name = "call coverage",
                    severity = "hard",
                    description = f"Slot {slot.slot_id} has {count} doctors assigned - must be exactly 1.",
                    affected_doctors = assigned[slot.slot_id],
                    affected_dates = [slot.date],
                    suggestion = "Solver bug - report with schedule state."
                ))
            continue
        if count == 0:
            pref_note = ""
            if slot.call_balance_group in ("friday_night", "weekend_block"):
                pref_note = " (preferences have no influence on this balance group)"
            violations.append(ConstraintViolation(
                constraint_id = "H3",
                constraint_name = "call coverage",
                severity = "hard",
                description = f"No doctor assigned to {slot.shift_type} on {slot.date}. (balance group: {slot.call_balance_group}){pref_note}",
                affected_doctors = [],
                affected_dates = [slot.date],
                suggestion = "Check if enough call-eligible doctors are available. Consider reducing max call limits or removing blackout dates."
            ))
        elif count > 1:
            violations.append(ConstraintViolation(
                constraint_id = "H3",
                constraint_name = "call coverage",
                severity = "hard",
                description = f"Slot {slot.slot_id} has {count} doctors assigned - must be exactly 1.",
                affected_doctors = assigned[slot.slot_id],
                affected_dates = [slot.date],
                suggestion = "Solver bug - report with schedule state."
            ))
    return violations

def check_h4_call_double(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    H4: A call double = call_day (07:00-19:00) + call_night (19:00-07:00)
    on the SAME calendar date, weekdays (Mon-Thu) only.
    Night->day is never a double. Weekend blocks are not doubles.
    Doctors with call_shift_preference="single" must never get doubles.
    """
    violations = []
    doc_map = {d.id: d for d in doctors}

    by_doc = {}
    for a in assignments:
        slot = slot_map[a.slot_id]
        if slot.shift_type in ("call_day", "call_night"):
            by_doc.setdefault(a.doctor_id, []).append(slot)

    for doc_id, call_slots in by_doc.items():
        doc = doc_map.get(doc_id)
        if not doc:
            continue

        day_by_date = {}
        night_by_date = {}
        for s in call_slots:
            if s.shift_type == "call_day":
                day_by_date[s.date] = s
            elif s.shift_type == "call_night":
                night_by_date[s.date] = s

        for date_str in day_by_date:
            if date_str not in night_by_date:
                continue

            d = dt_class.fromisoformat(date_str)
            dow = d.weekday()

            if dow >= 5:
                violations.append(ConstraintViolation(
                    constraint_id = "H4",
                    constraint_name = "Call double",
                    severity = "hard",
                    description = f"Dr. {doc.name} has call_day + call_night on {date_str} (weekend) - doubles cannot be on weekends.",
                    affected_doctors = [doc.id],
                    affected_dates = [date_str],
                    suggestion = "Weekend call doubles are not allowed. Assign a different doctor to one of these call slots."
                ))

        if doc.call_shift_preference == "single":
            for date_str in day_by_date:
                if date_str not in night_by_date:
                    continue
                d = dt_class.fromisoformat(date_str)
                dow = d.weekday()
                if dow < 5:
                    violations.append(ConstraintViolation(
                    constraint_id = "H4b",
                        constraint_name = "Call double",
                        severity = "hard",
                        description = f"Dr. {doc.name} has call_day + call_night on {date_str} but their call_shift_preference is 'single'.",
                        affected_doctors = [doc.id],
                        affected_dates = [date_str],
                        suggestion = "Change the doctor's call_shift_preference to 'double' or 'no_preference', or reassign one of the call slots."
                    ))

    return violations

def check_h4b_max_call_limits(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    violations = []
    doc_map = {d.id: d for d in doctors}
    counts = {}
    for a in assignments:
        slot = slot_map.get(a.slot_id)
        if not slot or not slot.call_balance_group:
            continue
        if a.doctor_id not in counts:
            counts[a.doctor_id] = {"weekday_day": 0, "weekday_night": 0, "friday_night": 0, "weekend_block": 0}
        if slot.shift_type == "call_weekend":
            counts[a.doctor_id]["weekend_block"] += 1
        elif slot.shift_type != "call_weekend_sun":
            counts[a.doctor_id][slot.call_balance_group] += 1

    for doc_id, group_counts in counts.items():
        doc = doc_map.get(doc_id)
        if not doc:
            continue
        limits = {
            "weekday_day": doc.max_weekday_day_calls,
            "weekday_night": doc.max_weekday_night_calls,
            "friday_night": doc.max_friday_night_calls,
            "weekend_block": doc.max_weekend_blocks,
        }
        for group, limit in limits.items():
            actual = group_counts.get(group, 0)
            if actual > limit:
                violations.append(ConstraintViolation(
                    constraint_id = "H4",
                    constraint_name = "Max call limit",
                    severity = "hard",
                    description = f"Dr. {doc.name} has {actual} {group} calls but max is {limit}.",
                    affected_doctors = [doc.id],
                    affected_dates = [],
                    suggestion = f"Reduce {group} assignments for this doctor or increase their limit."
                ))

    for a in assignments:
        slot = slot_map.get(a.slot_id)
        if not slot:
            continue
        if slot.shift_type in ('call_weekend', 'call_weekend_sun'):
            doc = doc_map.get(a.doctor_id)
            if doc and doc.weekend_call_off:
                violations.append(ConstraintViolation(
                    constraint_id = "H4w",
                    constraint_name = "Weekend call off",
                    severity = "hard",
                    description = f"Dr. {doc.name} has weekend call off but is assigned to {slot.shift_type} on {slot.date}.",
                    affected_doctors = [doc.id],
                    affected_dates = [slot.date],
                    suggestion = "Remove this assignment or disable the 'No Weekend Call' toggle for this doctor."
                ))

    return violations

def check_h5_call_balance(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    H5a/b/c/d: Each of the four call balance groups must be within 1
    across all call-eligible doctors.
    """
    violations = []
    eligible = [d for d in doctors if d.hospital_call_eligible]
    if not eligible:
        return violations
    groups = ["weekday_day", "weekday_night", "friday_night", "weekend_block"]

    counts = {d.id: {g: 0 for g in groups} for d in eligible}
    weekend_seen = set()

    for a in assignments:
        slot = slot_map[a.slot_id]
        if not slot.call_balance_group:
            continue
        if a.doctor_id not in counts:
            continue
        if slot.shift_type == "call_weekend":
            key = (a.doctor_id, slot.date)
            if key not in weekend_seen:
                weekend_seen.add(key)
                counts[a.doctor_id]["weekend_block"] += 1
        elif slot.shift_type == "call_weekend_sun":
            pass
        else:
            counts[a.doctor_id][slot.call_balance_group] += 1

    for group in groups:
        group_counts = [counts[d.id][group] for d in eligible]
        if not group_counts:
            continue
        max_c, min_c = max(group_counts), min(group_counts)
        if max_c - min_c > 1:
            over = [d.name for d in eligible if counts[d.id][group] == max_c]
            under = [d.name for d in eligible if counts[d.id][group] == min_c]
            pref_note = ""
            if group in ("friday_night", "weekend_block"):
                pref_note = " NOTE: preferences have no influence on this group."
            violations.append(ConstraintViolation(
                constraint_id = f"H5_{group}",
                constraint_name = f"call balance ({group})",
                severity = "hard",
                description = f"Imbalance in {group}: max={max_c}, min={min_c}.{pref_note} Over: {over}. Under: {under}",
                affected_doctors = [d.id for d in eligible],
                affected_dates = [],
                suggestion = f"Reassign one {group} call from an over-assigned doctor to an under-assigned one. Check blackout dates."
            ))
    return violations

def check_h6_no_overlap(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    H6: No doctor may have two assignments whose time ranges overlap,
    including overnight spillover to the next calendar day.
    Groups by doctor only, checks every pair using abs_times_overlap.
    """
    violations = []
    by_doctor = {}
    for a in assignments:
        slot = slot_map.get(a.slot_id)
        if slot:
            by_doctor.setdefault(a.doctor_id, []).append(slot)

    doc_name_map = {d.id: d.name for d in doctors}

    _surgical_types = ("surgical_am", "surgical_hosp_pm")
    for doc_id, doc_slots in by_doctor.items():
        for i, s1 in enumerate(doc_slots):
            for s2 in doc_slots[i + 1:]:
                if abs_times_overlap(s1, s2):
                    # call_day + surgical on same date is allowed (call doctor covers surgical)
                    same_date_surgical_call = (
                        s1.date == s2.date
                        and ((s1.shift_type == "call_day" and s2.shift_type in _surgical_types)
                             or (s2.shift_type == "call_day" and s1.shift_type in _surgical_types))
                    )
                    if same_date_surgical_call:
                        continue
                    name = doc_name_map.get(doc_id, doc_id)
                    violations.append(ConstraintViolation(
                        constraint_id = "H6",
                        constraint_name = "no overlap",
                        severity = "hard",
                        description = f"Dr. {name} has overlapping shifts: {s1.shift_type} on {s1.date} and {s2.shift_type} on {s2.date}.",
                        affected_doctors = [doc_id],
                        affected_dates = sorted(list({s1.date, s2.date})),
                        suggestion = "Remove one of the overlapping assignments."
                    ))

    return violations


def check_h7_surgical_pairing(
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    H7: Every surgical_am assignment must have a corresponding
    surgical_hosp_pm assignment for the same doctor on the same date.
    They are always assigned as a pair - never one without the other.

    Also checks reverse: every surgical_hosp_pm must have a paired surgical_am.
    """
    violations = []
    surgical_am = [a for a in assignments if slot_map[a.slot_id].shift_type == "surgical_am"]
    surgical_pm = [a for a in assignments if slot_map[a.slot_id].shift_type == "surgical_hosp_pm"]

    by_doc_date_am = {(a.doctor_id, slot_map[a.slot_id].date): a for a in surgical_am}
    by_doc_date_pm = {(a.doctor_id, slot_map[a.slot_id].date): a for a in surgical_pm}

    for a in surgical_am:
        d = slot_map[a.slot_id].date
        if (a.doctor_id, d) not in by_doc_date_pm:
            violations.append(ConstraintViolation(
                constraint_id = "H7",
                constraint_name = "surgical_pairing",
                severity = "hard",
                description = f"Doctor {a.doctor_id} has surgical AM on {d} but no paired hospital office PM.",
                affected_doctors = [a.doctor_id],
                affected_dates = [d],
                suggestion = "Assign the same doctor to the hospital office PM slot on this date, or remove the surgical AM assignment.",
            ))

    for a in surgical_pm:
        d = slot_map[a.slot_id].date
        if (a.doctor_id, d) not in by_doc_date_am:
            violations.append(ConstraintViolation(
                constraint_id = "H7",
                constraint_name = "surgical_pairing",
                severity = "hard",
                description = f"Doctor {a.doctor_id} has surgical_hosp_pm on {d} but no paired surgical AM.",
                affected_doctors = [a.doctor_id],
                affected_dates = [d],
                suggestion = "Assign the same doctor to the surgical AM slot on this date, or remove the surgical_hosp_pm assignment.",
            ))

    return violations

def check_h8_post_call_location(
    doctors: List[DoctorProfile],
    offices: List[Office],
    slots: List[ShiftSlot],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot],
) -> List[ConstraintViolation]:
    """H8: After any call shift, a doctor's next non-call assignment must be
    at the hospital office. Restriction clears after one hospital office shift.
    """
    violations = []
    hospital_id = next((o.id for o in offices if o.is_hospital), None)
    if not hospital_id:
        return violations

    for doc in doctors:
        doc_slot_list = [(slot_map[a.slot_id], a) for a in assignments if a.doctor_id == doc.id]
        # Sort by date, start_time, then hospital-before-non-hospital for same time
        # This ensures hospital clearing slots are processed before non-hospital slots
        # at the same time on the same date, correctly clearing H8 restriction
        doc_slot_list.sort(key=lambda x: (
            x[0].date, x[0].start_time,
            0 if x[0].office_id == hospital_id else 1
        ))

        post_call_restricted = False
        for slot, _ in doc_slot_list:
            if post_call_restricted:
                if slot.shift_type in CLEARING_SHIFT_TYPES:
                    if slot.office_id == hospital_id:
                        post_call_restricted = False
                    else:
                        violations.append(ConstraintViolation(
                            constraint_id = "H8",
                            constraint_name = "post-call location",
                            severity = "hard",
                            description = f"Dr. {doc.name} assigned to non-hospital office ({slot.office_id}) on {slot.date} ({slot.shift_type}) directly after a call. Must complete a hospital office shift first.",
                            affected_doctors = [doc.id],
                            affected_dates = [slot.date],
                            suggestion = "Insert a hospital office AM or PM shift between the call shift and this assignment."
                        ))
            if slot.shift_type in CALL_SHIFT_TYPES:
                post_call_restricted = True

    return violations

def check_h9_allowed_offices(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    H9: Doctors with allowed_offices set (not None) may only appear
    at offices in that list.
    """
    violations = []
    doc_map = {d.id: d for d in doctors}
    for a in assignments:
        doc = doc_map.get(a.doctor_id)
        if not doc or doc.allowed_offices is None:
            continue
        slot = slot_map[a.slot_id]
        if slot.office_id not in doc.allowed_offices:
            violations.append(ConstraintViolation(
                constraint_id = "H9",
                constraint_name = "Allowed offices",
                severity = "hard",
                description = f"Dr. {doc.name} assigned to office '{slot.office_id}' on {slot.date} but their allowed list is {doc.allowed_offices}.",
                affected_doctors = [doc.id],
                affected_dates = [slot.date],
                suggestion = "Remove this assignment or update the doctor's allowed_offices list."
            ))
    return violations

def check_h10_days_off(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot],
    day_off_dates
) -> List[ConstraintViolation]:
    """
    H10: No doctor may be assigned on:
    - Any date in day_off_dates for THIS doctor (per-doctor if dict), period-aware
    - Any date whose day_of_week is in the doctor's standing_days_off

    Period-aware: all_day blocks all shifts; morning blocks AM shifts;
    afternoon blocks PM shifts; custom blocks overlapping time windows.
    """
    violations = []
    doc_map = {d.id: d for d in doctors}

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

    def _is_blocked_by_entry(entry, slot_type):
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
                return _times_overlap_strings(shift_times[0], shift_times[1], st, et)
            return True
        return False

    for a in assignments:
        if a.is_locked:
            continue
        doc = doc_map.get(a.doctor_id)
        if not doc:
            continue
        slot = slot_map[a.slot_id]

        if isinstance(day_off_dates, dict):
            raw_entries = day_off_dates.get(doc.id, [])
        else:
            raw_entries = list(day_off_dates)

        date_entries = [e for e in raw_entries if (isinstance(e, dict) and e.get("date") == slot.date) or (isinstance(e, str) and e == slot.date)]

        blocked = False
        for e in date_entries:
            if isinstance(e, str):
                blocked = True
                break
            elif isinstance(e, dict):
                if _is_blocked_by_entry(e, slot.shift_type):
                    blocked = True
                    break

        if blocked:
            violations.append(ConstraintViolation(
                constraint_id = "H10",
                constraint_name = "Time off",
                severity = "hard",
                description = f"Dr. {doc.name} assigned on {slot.date} ({slot.shift_type}) which conflicts with their time off.",
                affected_doctors = [doc.id],
                affected_dates = [slot.date],
                suggestion = "Remove this assignment or update the time-off entry."
            ))
            continue

        dow = dt_class.fromisoformat(slot.date).weekday()
        if dow in doc.standing_days_off:
            violations.append(ConstraintViolation(
                constraint_id = "H10",
                constraint_name = "Time off",
                severity = "hard",
                description = f"Dr. {doc.name} assigned on {slot.date} (day_of_week={dow}) which is in their standing_days_off: {doc.standing_days_off}.",
                affected_doctors = [doc.id],
                affected_dates = [slot.date],
                suggestion = "Remove this assignment or update standing_days_off."
            ))
    return violations

def check_h11_locked_preserved(
    inp: ScheduleInput,
    slots: List[ShiftSlot],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    H11: Pre-scheduled assignments (recurring + one-time overrides + locked)
    must be present in the output. The solver cannot move or remove them.
    """
    violations = []

    from scheduler import expand_recurring_slots, expand_one_time_overrides

    slot_id_set = set(slot_map.keys())
    recurring = expand_recurring_slots(inp.doctors, slots, inp.year, inp.month)
    overrides = expand_one_time_overrides(inp.doctors, inp.year, inp.month, slot_id_set)
    all_locked = {(a.doctor_id, a.slot_id) for a in inp.locked_assignments + recurring + overrides}

    actual = {(a.doctor_id, a.slot_id) for a in assignments}
    missing = all_locked - actual

    for doc_id, slot_id in sorted(missing):
        slot = slot_map.get(slot_id)
        date_str = slot.date if slot else "unknown"
        violations.append(ConstraintViolation(
            constraint_id = "H11",
            constraint_name = "Locked assignment",
            severity = "hard",
            description = f"Locked assignment missing: doctor {doc_id} to slot {slot_id} on {date_str}.",
            affected_doctors = [doc_id],
            affected_dates = [date_str] if slot else [],
            suggestion = "The solver removed a pre-scheduled assignment. Check that locked assignments are passed correctly and not overridden by other constraints."
        ))

    return violations

def check_h12_required_sessions(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot],
    day_off_dates,
    year: int,
    month: int,
    offices: List[Office]
) -> List[ConstraintViolation]:
    """
    H12: Each doctor must meet their required_sessions_per_week per week.
    Proportionally reduced for day-off days: each full day off reduces that
    week's requirement by approximately 1 session.
    Sessions must be spread across multiple office locations.
    """
    violations = []
    days = get_days_in_month(year, month)
    max_week = max(d['week_num'] for d in days) if days else 0

    for doc in doctors:
        doc_assignments = [a for a in assignments if a.doctor_id == doc.id]

        sessions_by_week = {}
        offices_by_week = {}
        for a in doc_assignments:
            slot = slot_map[a.slot_id]
            if slot.shift_type not in OFFICE_SESSION_TYPES:
                continue
            day_info = next((d for d in days if d['date'] == slot.date), None)
            if not day_info:
                continue
            wn = day_info['week_num']
            sessions_by_week[wn] = sessions_by_week.get(wn, 0) + 1
            if wn not in offices_by_week:
                offices_by_week[wn] = set()
            offices_by_week[wn].add(slot.office_id)

        day_off_count_by_week = {}
        if isinstance(day_off_dates, dict):
            doc_days_off = day_off_dates.get(doc.id, [])
        else:
            doc_days_off = list(day_off_dates)

        for entry in doc_days_off:
            if isinstance(entry, str):
                d_str = entry
            elif isinstance(entry, dict):
                d_str = entry.get("date", "")
            else:
                continue
            day_info = next((d for d in days if d['date'] == d_str), None)
            if day_info:
                wn = day_info['week_num']
                day_off_count_by_week[wn] = day_off_count_by_week.get(wn, 0) + 1

        for wn in range(max_week + 1):
            week_sessions = sessions_by_week.get(wn, 0)
            day_offs = day_off_count_by_week.get(wn, 0)

            week_days = [d for d in days if d['week_num'] == wn and not d['is_weekend']]
            n_weekdays = len(week_days)
            if n_weekdays < 5:
                day_offs += (5 - n_weekdays)

            work_days_in_week = 5 - day_offs
            if work_days_in_week <= 0:
                continue

            reduction = round(day_offs * doc.required_sessions_per_week / 5)
            adjusted = max(0, doc.required_sessions_per_week - reduction)

            if week_sessions < adjusted:
                violations.append(ConstraintViolation(
                    constraint_id = "H12",
                    constraint_name = "Required sessions",
                    severity = "soft",
                    description = f"Dr. {doc.name} has {week_sessions} office sessions in week {wn} but required is {adjusted} (base={doc.required_sessions_per_week}, day_offs={day_offs}, reduction={reduction}).",
                    affected_doctors = [doc.id],
                    affected_dates = [],
                    suggestion = "Add more office sessions for this doctor in this week, or reduce required_sessions_per_week, or reduce day-off dates."
                ))

            week_offices = offices_by_week.get(wn, set())
            eligible_offices = set()
            if doc.allowed_offices is not None:
                eligible_offices = set(doc.allowed_offices)
            else:
                eligible_offices = {o.id for o in offices}

            if len(eligible_offices) >= 2 and week_sessions >= 3 and len(week_offices) < 2:
                violations.append(ConstraintViolation(
                    constraint_id = "H12",
                    constraint_name = "Required sessions (variety)",
                    severity = "soft",
                    description = f"Dr. {doc.name} has {week_sessions} sessions in week {wn} but only uses {len(week_offices)} office(s). Must spread across multiple offices.",
                    affected_doctors = [doc.id],
                    affected_dates = [],
                    suggestion = "Assign this doctor to at least 2 different offices in this week."
                ))

    return violations

def check_h13_late_shift_distinctness(
    slots: List[ShiftSlot],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    H13: The Mon/Thu 13:30-18:30 office_late slot is a third independent slot.
    It does NOT replace the 13:00-17:00 PM slot. Both exist and can be filled
    independently. Verifies that for every office_late slot, the corresponding
    office_pm slot also exists in the schedule's slot list.
    """
    violations = []

    late_slots = [s for s in slots if s.shift_type == "office_late"]

    for late_slot in late_slots:
        pm_slot_id = f"{late_slot.date}_{late_slot.office_id}_office_pm"
        if pm_slot_id not in slot_map:
            violations.append(ConstraintViolation(
                constraint_id = "H13",
                constraint_name = "Late shift distinctness",
                severity = "hard",
                description = f"office_late slot {late_slot.slot_id} exists but corresponding office_pm slot {pm_slot_id} is missing on {late_slot.date}.",
                affected_doctors = [],
                affected_dates = [late_slot.date],
                suggestion = "Check slot_generator: office_late slots require a paired office_pm slot on the same date and office."
            ))

    return violations

def check_s1_am_pm_balance(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot],
    year: int,
    month: int
) -> List[ConstraintViolation]:
    """
    S1: Weekly soft preference for roughly equal AM and PM sessions.
    AM = office_am. PM = office_pm + office_late.
    """
    violations = []
    days = get_days_in_month(year, month)
    max_week = max(d['week_num'] for d in days) if days else 0

    for doc in doctors:
        am_by_week = {}
        pm_by_week = {}
        for a in assignments:
            if a.doctor_id != doc.id:
                continue
            slot = slot_map[a.slot_id]
            if slot.shift_type not in OFFICE_SESSION_TYPES:
                continue
            day_info = next((d for d in days if d['date'] == slot.date), None)
            if not day_info:
                continue
            wn = day_info['week_num']
            if slot.shift_type in ("office_am", "surgical_am"):
                am_by_week[wn] = am_by_week.get(wn, 0) + 1
            else:
                pm_by_week[wn] = pm_by_week.get(wn, 0) + 1

        for wn in range(max_week + 1):
            am = am_by_week.get(wn, 0)
            pm = pm_by_week.get(wn, 0)
            total = am + pm
            if total < 3:
                continue

            pref = doc.am_pm_preference
            if pref == "balanced" and abs(am - pm) > 2:
                violations.append(ConstraintViolation(
                    constraint_id = "S1",
                    constraint_name = "AM/PM balance",
                    severity = "soft",
                    description = f"Dr. {doc.name} has AM={am}, PM={pm} in week {wn} (preference: balanced). Difference > 2.",
                    affected_doctors = [doc.id],
                    affected_dates = [],
                    suggestion = "Rebalance AM and PM sessions for this doctor in this week."
                ))
            elif pref == "am" and am < pm:
                violations.append(ConstraintViolation(
                    constraint_id = "S1",
                    constraint_name = "AM/PM balance",
                    severity = "soft",
                    description = f"Dr. {doc.name} has AM={am}, PM={pm} in week {wn} (preference: am). AM < PM despite preference.",
                    affected_doctors = [doc.id],
                    affected_dates = [],
                    suggestion = "Assign more AM sessions to this doctor."
                ))
            elif pref == "pm" and pm < am:
                violations.append(ConstraintViolation(
                    constraint_id = "S1",
                    constraint_name = "AM/PM balance",
                    severity = "soft",
                    description = f"Dr. {doc.name} has AM={am}, PM={pm} in week {wn} (preference: pm). PM < AM despite preference.",
                    affected_doctors = [doc.id],
                    affected_dates = [],
                    suggestion = "Assign more PM sessions to this doctor."
                ))

    return violations

def check_s2_office_ranking(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot],
    global_office_ranking: List[str],
    day_off_dates=None,
    offices: List[Office] = None
) -> List[ConstraintViolation]:
    """
    S2: Fill higher-ranked offices before lower-ranked.
    Each doctor has their own ranked preference list, falling back to global default.
    Flags if a doctor is assigned to a lower-ranked office on a date where
    a higher-ranked office has an open slot of the same shift type.
    Skips if the doctor was not actually available for the higher-ranked slot.
    """
    violations = []
    if not global_office_ranking:
        return violations

    hospital_id = None
    if offices:
        for o in offices:
            if o.is_hospital:
                hospital_id = o.id
                break

    doc_day_off_dates = {}
    if day_off_dates is not None:
        if isinstance(day_off_dates, dict):
            for did, entries in day_off_dates.items():
                doc_day_off_dates[did] = set()
                for e in entries:
                    if isinstance(e, str):
                        doc_day_off_dates[did].add(e)
                    elif isinstance(e, dict):
                        doc_day_off_dates[did].add(e.get("date", ""))
        else:
            for did in [d.id for d in doctors]:
                doc_day_off_dates[did] = set()
                for e in day_off_dates:
                    if isinstance(e, str):
                        doc_day_off_dates[did].add(e)
                    elif isinstance(e, dict):
                        doc_day_off_dates[did].add(e.get("date", ""))

    a_by_slot = {}
    doc_assignments_by_id = {}
    for a in assignments:
        a_by_slot.setdefault(a.slot_id, []).append(a.doctor_id)
        doc_assignments_by_id.setdefault(a.doctor_id, []).append(a)

    for doc in doctors:
        ranking = doc.office_preferences if doc.office_preferences else global_office_ranking

        doc_assignments = doc_assignments_by_id.get(doc.id, [])
        for a in doc_assignments:
            slot = slot_map[a.slot_id]
            if slot.shift_type not in OFFICE_SESSION_TYPES:
                continue

            assigned_rank = ranking.index(slot.office_id) if slot.office_id in ranking else len(ranking)

            for better_office in ranking:
                if ranking.index(better_office) >= assigned_rank:
                    break
                better_slot_id = f"{slot.date}_{better_office}_{slot.shift_type}"
                better_slot = slot_map.get(better_slot_id)
                if not better_slot:
                    continue
                better_count = len(a_by_slot.get(better_slot_id, []))
                if better_count < better_slot.max_doctors:
                    if doc.allowed_offices is not None and better_office not in doc.allowed_offices:
                        continue

                    if slot.date in doc_day_off_dates.get(doc.id, set()):
                        continue

                    dow = dt_class.fromisoformat(slot.date).weekday()
                    if dow in doc.standing_days_off:
                        continue

                    overlap = False
                    for oa in doc_assignments:
                        other = slot_map.get(oa.slot_id)
                        if not other or other.date != better_slot.date:
                            continue
                        if abs_times_overlap(better_slot, other):
                            overlap = True
                            break
                    if overlap:
                        continue

                    if hospital_id and better_office != hospital_id:
                        doc_sorted = sorted(
                            [(slot_map[oa.slot_id], oa) for oa in doc_assignments],
                            key=lambda x: (x[0].date, x[0].start_time))
                        post_call = False
                        for sl, _ in doc_sorted:
                            if sl.date > better_slot.date:
                                break
                            if sl.shift_type in CALL_SHIFT_TYPES:
                                if sl.date < better_slot.date or (sl.date == better_slot.date and sl.shift_type in ("call_night",)):
                                    post_call = True
                            if post_call and sl.shift_type in CLEARING_SHIFT_TYPES:
                                if sl.office_id == hospital_id:
                                    post_call = False
                        if post_call:
                            continue

                    violations.append(ConstraintViolation(
                        constraint_id = "S2",
                        constraint_name = "Office ranking",
                        severity = "soft",
                        description = f"Dr. {doc.name} assigned to {slot.office_id} on {slot.date} ({slot.shift_type}) but higher-ranked office {better_office} has available capacity.",
                        affected_doctors = [doc.id],
                        affected_dates = [slot.date],
                        suggestion = f"Consider assigning Dr. {doc.name} to {better_office} instead of {slot.office_id} on this date."
                    ))
                    break

    return violations

def check_s3_late_shift_balance(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot],
    year: int,
    month: int,
    day_off_dates=None,
    offices: List[Office] = None
) -> List[ConstraintViolation]:
    """
    S3: Soft preference for each doctor to have approximately 1 late shift
    per week when available.
    Only flags a violation if the doctor was actually eligible for at least
    one late slot in that week (no overlap with call, no day off, no H8
    restriction blocking non-hospital late).
    """
    violations = []
    days = get_days_in_month(year, month)
    max_week = max(d['week_num'] for d in days) if days else 0

    hospital_id = None
    if offices:
        for o in offices:
            if o.is_hospital:
                hospital_id = o.id
                break

    doc_assignments = {}
    for a in assignments:
        doc_assignments.setdefault(a.doctor_id, []).append(a)

    doc_day_off_dates = {}
    if day_off_dates is not None:
        if isinstance(day_off_dates, dict):
            for did, entries in day_off_dates.items():
                doc_day_off_dates[did] = set()
                for e in entries:
                    if isinstance(e, str):
                        doc_day_off_dates[did].add(e)
                    elif isinstance(e, dict):
                        doc_day_off_dates[did].add(e.get("date", ""))
        else:
            for did in [d.id for d in doctors]:
                doc_day_off_dates[did] = set()
                for e in day_off_dates:
                    if isinstance(e, str):
                        doc_day_off_dates[did].add(e)
                    elif isinstance(e, dict):
                        doc_day_off_dates[did].add(e.get("date", ""))

    for doc in doctors:
        late_by_week = {}
        for a in doc_assignments.get(doc.id, []):
            slot = slot_map[a.slot_id]
            if slot.shift_type == "office_late":
                day_info = next((d for d in days if d['date'] == slot.date), None)
                if day_info:
                    wn = day_info['week_num']
                    late_by_week[wn] = late_by_week.get(wn, 0) + 1

        for wn in range(max_week + 1):
            late_count = late_by_week.get(wn, 0)

            week_dates = [d['date'] for d in days if d['week_num'] == wn]
            late_slots_in_week = [s for s in slot_map.values()
                if s.shift_type == "office_late" and s.date in week_dates
                and (doc.allowed_offices is None or s.office_id in doc.allowed_offices)]

            if len(late_slots_in_week) == 0:
                continue

            if late_count == 0:
                feasible = False
                for ls in late_slots_in_week:
                    blocked = False

                    dow = dt_class.fromisoformat(ls.date).weekday()
                    if dow in doc.standing_days_off:
                        continue

                    if doc.id in doc_day_off_dates and ls.date in doc_day_off_dates[doc.id]:
                        continue

                    for a in doc_assignments.get(doc.id, []):
                        other = slot_map.get(a.slot_id)
                        if not other:
                            continue
                        if other.date != ls.date:
                            continue
                        if abs_times_overlap(ls, other):
                            blocked = True
                            break
                    if blocked:
                        continue

                    if hospital_id and ls.office_id != hospital_id:
                        doc_sorted = sorted(
                            [(slot_map[a.slot_id], a) for a in doc_assignments.get(doc.id, [])],
                            key=lambda x: (x[0].date, x[0].start_time))
                        post_call = False
                        for sl, _ in doc_sorted:
                            if sl.date > ls.date:
                                break
                            if sl.shift_type in CALL_SHIFT_TYPES:
                                if sl.date < ls.date or (sl.date == ls.date and sl.shift_type in ("call_night",)):
                                    post_call = True
                            if post_call and sl.shift_type in CLEARING_SHIFT_TYPES:
                                if sl.office_id == hospital_id:
                                    post_call = False
                        if post_call:
                            continue

                    feasible = True
                    break

                if not feasible:
                    continue

                violations.append(ConstraintViolation(
                    constraint_id = "S3",
                    constraint_name = "Late shift balance",
                    severity = "soft",
                    description = f"Dr. {doc.name} has 0 late shifts in week {wn} when late slots are available.",
                    affected_doctors = [doc.id],
                    affected_dates = [],
                    suggestion = "Consider assigning a late shift to this doctor in this week."
                ))

    return violations

def check_s4_post_call_work_preference(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot],
    offices: List[Office]
) -> List[ConstraintViolation]:
    """
    S4: After a call shift, if a doctor prefers to work, schedule them for
    the 08:00-12:00 hospital office AM slot. Per-doctor setting.
    """
    violations = []
    hospital_id = next((o.id for o in offices if o.is_hospital), None)
    if not hospital_id:
        return violations

    for doc in doctors:
        if doc.post_call_preference == "no_preference":
            continue

        doc_assignments = sorted(
            [(slot_map[a.slot_id], a) for a in assignments if a.doctor_id == doc.id],
            key=lambda x: (x[0].date, x[0].start_time)
        )

        for i, (slot, _) in enumerate(doc_assignments):
            if slot.shift_type not in CALL_SHIFT_TYPES:
                continue
            # Skip call_weekend_sun — the S4 check for weekend blocks
            # is handled from the Saturday call_weekend
            if slot.shift_type == "call_weekend_sun":
                continue

            next_day = str(dt_class.fromisoformat(slot.date) + timedelta(days=1))
            # For weekend blocks, skip to Monday (no office slots on weekends)
            if slot.shift_type in ("call_weekend", "call_night"):
                while dt_class.fromisoformat(next_day).weekday() >= 5:
                    next_day = str(dt_class.fromisoformat(next_day) + timedelta(days=1))

            next_day_assignments = [
                (s, a) for s, a in doc_assignments[i + 1:]
                if s.date == next_day and s.shift_type in CLEARING_SHIFT_TYPES
            ]

            if doc.post_call_preference == "work":
                has_hosp_am = any(
                    s.shift_type in ("office_am", "surgical_am") and s.office_id == hospital_id
                    for s, _ in next_day_assignments
                )
                if next_day_assignments and not has_hosp_am:
                    violations.append(ConstraintViolation(
                        constraint_id = "S4",
                        constraint_name = "Post-call work preference",
                        severity = "soft",
                        description = f"Dr. {doc.name} prefers to work after call but has no hospital AM shift on {next_day} after call on {slot.date}.",
                        affected_doctors = [doc.id],
                        affected_dates = [next_day],
                        suggestion = "Assign a hospital office AM shift to this doctor on the day after their call."
                    ))
            elif doc.post_call_preference == "off":
                if next_day_assignments:
                    violations.append(ConstraintViolation(
                        constraint_id = "S4",
                        constraint_name = "Post-call work preference",
                        severity = "soft",
                        description = f"Dr. {doc.name} prefers off after call but has assignments on {next_day} after call on {slot.date}.",
                        affected_doctors = [doc.id],
                        affected_dates = [next_day],
                        suggestion = "Remove next-day assignments for this doctor, or change their post_call_preference."
                    ))

    return violations

def check_s5_call_shift_preference(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    S5: Single-preference doctors never get doubles. Double-preference
    doctors get paired day+night when balance allows.
    """
    violations = []
    doc_map = {d.id: d for d in doctors}

    by_doc = {}
    for a in assignments:
        slot = slot_map[a.slot_id]
        if slot.shift_type in ("call_day", "call_night"):
            by_doc.setdefault(a.doctor_id, []).append(slot)

    for doc_id, call_slots in by_doc.items():
        doc = doc_map.get(doc_id)
        if not doc or doc.call_shift_preference == "no_preference":
            continue

        day_by_date = {}
        night_by_date = {}
        for s in call_slots:
            if s.shift_type == "call_day":
                day_by_date[s.date] = s
            elif s.shift_type == "call_night":
                night_by_date[s.date] = s

            double_dates = set(day_by_date.keys()) & set(night_by_date.keys())

        if doc.call_shift_preference == "double" and len(double_dates) == 0:
            weekday_day_dates = {d for d, s in day_by_date.items()
                                 if dt_class.fromisoformat(d).weekday() < 5}
            weekday_night_dates = {d for d, s in night_by_date.items()
                                   if dt_class.fromisoformat(d).weekday() < 5}
            dates_with_both = weekday_day_dates & weekday_night_dates
            if not dates_with_both and (weekday_day_dates or weekday_night_dates):
                violations.append(ConstraintViolation(
                    constraint_id = "S5",
                    constraint_name = "Call shift preference",
                    severity = "soft",
                    description = f"Dr. {doc.name} prefers doubles but has no call doubles this month.",
                    affected_doctors = [doc.id],
                    affected_dates = [],
                    suggestion = "Consider assigning this doctor to paired day+night calls when balance allows."
                ))

    return violations

def check_s6_day_night_preference(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    S6: Within the weekday call balance, prefer to give doctors their
    day_night_preference when balanced.
    """
    violations = []
    for doc in doctors:
        if doc.day_night_preference == "balanced":
            continue

        day_calls = 0
        night_calls = 0
        for a in assignments:
            if a.doctor_id != doc.id:
                continue
            slot = slot_map[a.slot_id]
            if slot.call_balance_group == "weekday_day":
                day_calls += 1
            elif slot.call_balance_group == "weekday_night":
                night_calls += 1

        total = day_calls + night_calls
        if total == 0:
            continue

        if doc.day_night_preference == "day" and night_calls > day_calls:
            violations.append(ConstraintViolation(
                constraint_id = "S6",
                constraint_name = "Day/night preference",
                severity = "soft",
                description = f"Dr. {doc.name} prefers day calls but has day={day_calls}, night={night_calls} (night > day).",
                affected_doctors = [doc.id],
                affected_dates = [],
                suggestion = "Reassign some night calls to other doctors or give this doctor more day calls."
            ))
        elif doc.day_night_preference == "night" and day_calls > night_calls:
            violations.append(ConstraintViolation(
                constraint_id = "S6",
                constraint_name = "Day/night preference",
                severity = "soft",
                description = f"Dr. {doc.name} prefers night calls but has day={day_calls}, night={night_calls} (day > night).",
                affected_doctors = [doc.id],
                affected_dates = [],
                suggestion = "Reassign some day calls to other doctors or give this doctor more night calls."
            ))

    return violations

def check_s7_office_variety(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot],
    offices: List[Office]
) -> List[ConstraintViolation]:
    """
    S7: Soft preference to spread sessions across as many eligible offices
    as possible.
    """
    violations = []
    for doc in doctors:
        offices_used = set()
        total_sessions = 0
        for a in assignments:
            if a.doctor_id != doc.id:
                continue
            slot = slot_map[a.slot_id]
            if slot.shift_type in OFFICE_SESSION_TYPES:
                offices_used.add(slot.office_id)
                total_sessions += 1

        if total_sessions < 3:
            continue

        eligible = set()
        if doc.allowed_offices is not None:
            eligible = set(doc.allowed_offices)
        else:
            eligible = {o.id for o in offices}

        unused = eligible - offices_used
        if len(unused) >= 1 and len(offices_used) < len(eligible):
            violations.append(ConstraintViolation(
                constraint_id = "S7",
                constraint_name = "Office variety",
                severity = "soft",
                description = f"Dr. {doc.name} uses {len(offices_used)} office(s) but is eligible for {len(eligible)}. Consider spreading sessions.",
                affected_doctors = [doc.id],
                affected_dates = [],
                suggestion = f"Assign Dr. {doc.name} to additional offices: {sorted(unused)}."
            ))

    return violations

def suggest_relaxations(violations: List[ConstraintViolation]) -> List[str]:
    """
    Given a list of violations from a partial or infeasible schedule,
    produce human-readable suggestions for what to change in the inputs.

    Group violations by constraint_id, then produce one suggestion per group.
    Include the count of violations in the suggestion so the user knows severity.
    """
    suggestions = []
    by_id: Dict[str, List[ConstraintViolation]] = {}
    for v in violations:
        by_id.setdefault(v.constraint_id, []).append(v)

    if "H2" in by_id:
        n = len(by_id["H2"])
        suggestions.append(
            f"RESTRICTED TUESDAY - {n} violation(s). "
            f"Capacity exceeded on restricted Tuesdays. "
            f"Consider increasing restricted_tuesday_max or reducing pre-filled assignments on those dates."
        )

    if "H3" in by_id:
        n = len(by_id["H3"])
        suggestions.append(
            f"CALL COVERAGE - {n} slot(s) unfilled. "
            f"Options: (1) Reduce max_*_calls limits so doctors can cover more slots. "
            f"(2) Set hospital_call_eligible=True for more doctors."
            f"(3) Remove blackout/day-off dates for call-eligible doctors."
        )

    if "H4" in by_id:
        n = len(by_id["H4"])
        suggestions.append(
            f"DOUBLE CALL - {n} violation(s). "
            f"A single-preference doctor has both call_day and call_night on the same date, "
            f"or a double exists on a weekend. Change call_shift_preference or reassign."
        )

    for group in ("weekday_day", "weekday_night", "friday_night", "weekend_block"):
        key = f"H5_{group}"
        if key in by_id:
            pref = (" NOTE: doctor preferences have no influence on this group."
                if group in ("friday_night", "weekend_block") else "")
            suggestions.append(
                f"CALL BALANCE ({group}){pref}: Balance cannot be achieved. "
                f"Check blackout dates - if some doctors are unavailable for many "
                f"of this call type, others must cover the imbalance."
            )

    if "H6" in by_id:
        suggestions.append(
            "OVERLAP - An overnight shift is conflicting with an adjacent-day assignment. "
            "Remember: call_night ends at 07:00 the NEXT calendar day. "
            "No assignments should start before 07:00 on the day after the call_night."
        )

    if "H7" in by_id:
        suggestions.append(
            "SURGICAL PAIRING - surgical_am must always be paired with "
            "surgical_hosp_pm the same day, same doctor. "
            "Check for blackout dates or capacity conflicts on those days."
        )

    if "H8" in by_id:
        n = len(by_id["H8"])
        suggestions.append(
            f"POST-CALL LOCATION - {n} violation(s). "
            f"After a call shift, the doctor must do a hospital office shift before "
            f"going to a non-hospital office. Insert a hospital office AM or PM shift."
        )

    if "H11" in by_id:
        n = len(by_id["H11"])
        suggestions.append(
            f"LOCKED ASSIGNMENT - {n} missing. "
            f"A pre-scheduled assignment was removed by the solver. "
            f"Check that locked assignments are passed correctly and not overridden."
        )

    if "H12" in by_id:
        n = len(by_id["H12"])
        suggestions.append(
            f"SESSION QUOTA - {n} violation(s). "
            f"A doctor has fewer sessions than required_sessions_per_week. "
            f"Reduce day-offs, increase office capacity, or lower required_sessions_per_week."
        )

    if "H13" in by_id:
        n = len(by_id["H13"])
        suggestions.append(
            f"LATE SHIFT DISTINCTNESS - {n} violation(s). "
            f"office_late slot exists without a paired office_pm. "
            f"Check slot_generator logic."
        )

    return suggestions
