from dataclasses import dataclass
from typing import List, Dict
from models import (DoctorProfile, ShiftSlot, Assignment, ScheduleInput,
                    abs_times_overlap, get_call_balance_group)

@dataclass
class ConstraintViolation:
    constraint_id:    str
    constraint_name:  str
    severity:         str
    description:      str
    affected_doctors: List[str]
    affected_dates:   List[str]
    suggestion:       str

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
    violations += check_h1_capacity(slots, assignments, slot_map)
    violations += check_h3_call_coverage(slots, assignments, slot_map)
    violations += check_h5_call_balance(inp.doctors, assignments, slot_map)
    violations += check_h6_no_overlap(inp.doctors, assignments, slot_map)
    violations += check_h7_surgical_pairing(assignments, slot_map)
    violations += check_h8_post_call_location(inp.doctors, slots, assignments, slot_map)
    violations += check_h9_allowed_offices(inp.doctors, assignments, slot_map)
    violations += check_h10_days_off(inp.doctors, assignments, slot_map, inp.day_off_dates)
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

def check_h3_call_coverage(
    slots: List[ShiftSlot],
    assignment: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    H3: Each call slot must have exactly 1 doctor assigned.
    """
    violations = []
    call_slots = [s for s in slots if s.shift_type in ["call_day", "call_night", "call_weekend"]]
    assigned = {}
    for a in assignment:
        slot = slot_map[a.slot_id]
        if slot.shift_type in ["call_day", "call_night", "call_weekend"]:
            assigned.setdefault(a.slot_id, []).append(a.doctor_id)

        
    for slot in call_slots:
        count = len(assigned.get(slot.slot_id, []))
        if count == 0:
            violations.append(ConstraintViolation(
                constraint_id = "H3",
                constraint_name = "call coverage",
                severity = "hard",
                description = f"No doctor assigned to {slot.shift_type} on {slot.date}. (balance group: {slot.call_balance_group})",
                affected_doctors = [],
                affected_dates = [slot.date],
                suggestion = "Check if enought call-eligible doctors are available. Consider reducing max call limits or removing blackout dates."
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
            violations.append(ConstraintViolation(
                constraint_id = f"H5_{group}",
                constraint_name = f"call balance ({group})",
                severity = "hard",
                description = f"Imbalance in {group}: max={max_c}, min={min_c}. Over: {over}. Under: {under}",
                affected_doctors = [d.id for d in eligible],
                affected_dates = [],
                suggestion = f"Reassign one {group} call from an over-assigned doctor to an under-assigned one. Note for friday_night and weekend_block, preferences have no influence - check if blackout dates are causing the imbalance."
            ))
    return violations

def check_h6_no_overlap(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    H6: No doctor may have two assignments whose time ranges overlap
    including overnight spillover to the next calendar day.
    """
    from datetime import date as dt, timedelta
    violations = []
    by_doc_date = {}
    for a in assignments:
        slot = slot_map[a.slot_id]
        key = (a.doctor_id, slot.date)
        by_doc_date.setdefault(key, []).append(slot)

    for (doc_id, date), day_slots in by_doc_date.items():
        for i, s1 in enumerate(day_slots):
            for s2 in day_slots[i+1:]:
                if abs_times_overlap(s1, s2):
                    doc_name = next((d.name for d in doctors if d.id == doc_id), doc_id)
                    violations.append(ConstraintViolation(
                        constraint_id = "H6",
                        constraint_name = "no overlap",
                        severity = "hard",
                        description = f"Dr. {doc_name} has overlapping shifts on {date}: {s1.shift_type} ({s1.start_time}-{s1.end_time}) and {s2.shift_type} ({s2.start_time} - {s2.end_time})",
                        affected_doctors = [doc_id],
                        affected_dates = [date],
                        suggestion = "Check pre-filled assignements for this doctor on this date. One of these assignments must be removed or moved."
                    ))
        overnight = [s for s in day_slots if s.end_time < s.start_time
                      or s.shift_type in ("call_night", "call_weekend")]
        if overnight:
            next_day = str(dt.fromisoformat(date) + timedelta(days=1))
            next_slots = by_doc_date.get((doc_id, next_day), [])
            for s1 in overnight:
                for s2 in next_slots:
                    if abs_times_overlap(s1, s2):
                        doc_name = next((d.name for d in doctors if d.id == doc_id), doc_id)
                        violations.append(ConstraintViolation(
                            constraint_id = "H6",
                            constraint_name = "no overlap",
                            severity = "hard",
                            description = f"Dr. {doc_name} has overlapping shifts on {date}: {s1.shift_type} ({s1.start_time}-{s1.end_time}) and {s2.shift_type} ({s2.start_time} - {s2.end_time})",
                            affected_doctors = [doc_id],
                            affected_dates = [date],
                            suggestion = "Check pre-filled assignements for this doctor on this date. One of these assignments must be removed or moved."
                        ))
    return violations

def check_h7_surgical_pairing(
    assignments: List[Assignment],
    slot_map: Dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    H7: Every surgical_am aassignment must have a corresponding
    surgical_hosp_pm assignment for the same doctor on the same date.
    They are always assigned as a pair - never one without the other.

    Check the reverse: every surgical_hosp_pm must have a paired surgical_am.
    """
    violations = []
    surgical_am = [a for a in assignments if slot_map[a.slot_id].shift_type == "surgical_am"]
    by_doc_date = {(a.doctor_id, slot_map[a.slot_id].date): a for a in assignments if slot_map[a.slot_id].shift_type == "surgical_hosp_pm"}

    for a in surgical_am:
        date = slot_map[a.slot_id].date
        if (a.doctor_id, date) not in by_doc_date:
            violations.append(ConstraintViolation(
                constraint_id = "H7",
                constraint_name = "surgical_pairing",
                severity = "hard",
                description = f"Doctor {a.doctor_id} has surgical AM on {date} but no paired hospical office PM.",
                affected_doctors = [a.doctor_id],    
                affected_dates = [date],
                suggestion = "Assign the same doctor to the hospital office PM slot on this date, or remove the surgical AM assignment.",   
            ))
    return violations

def check_h8_post_call_location(
    doctors: List[DoctorProfile],
    slots: List[Assignment],
    assignments,
    slot_map: Dict[str, ShiftSlot],
) -> List[ConstraintViolation]:
    """
    H8: After any call shift, a doctor's next non-call assignment must be
    at the hospital office. The restiction clears after one hospital office shift.
    """
    violations = []
    hospital_id = next((s.office_id for s in slots if s.shift_type in ["call_day", "call_night"]), None)
    if not hospital_id:
        return violations
    for doc in doctors:
        doc_assignments = sorted([a for a in assignments if a.doctor_id == doc.id],
                                 key = lambda a: (slot_map[a.slot_id].date, slot_map[a.slot_id].start_time))
        post_call = False
        for a in doc_assignments:
            slot = slot_map[a.slot_id]
            if post_call:
                if slot.shift_type not in ["call_day", "call_night", "call_weekend", "call_weekend_sun"]:
                    if slot.office_id != hospital_id:
                        violations.append(ConstraintViolation(
                            constraint_id = "H8",
                            constraint_name = "post-call location",
                            severity = "hard",
                            description = f"Dr. {doc.name} assigned to non-hospital office ({slot.office_id}) on {slot.date} directly after a call. Must complete a hospital office shift first.",
                            affected_doctors = [doc.id],
                            affected_dates = [slot.date],
                            suggestion = "Check pre-filled assignements for this doctor on this date. One of these assignments must be removed or moved."
                        ))
                    else:
                        post_call = False
            if slot.shift_type in ["call_day", "call_night", "call_weekend"]:
                post_call = True
    return violations

def check_h9_allowed_offices(
    doctors: List[DoctorProfile],
    assignments: List[Assignment],
    slot_map: dict[str, ShiftSlot]
) -> List[ConstraintViolation]:
    """
    H9: Doctors with allowed_offices set (not None) may only appear
    at offices in that list.

    Skip is_locked assignments
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
    day_off_dates: List[str]
) -> List[ConstraintViolation]:
    """
    H10: No doctor may be assigned on:
    - Any date in day_off_dates
    - Any date whoes day_of_week is in the doctor's standing_days_off

    Skip is_locked assignments
    """
    from datetime import date as dt_class
    violations = []
    doc_map = {d.id: d for d in doctors}
    day_off_set = set(day_off_dates)

    for a in assignments:
        if a.is_locked:
            continue
        doc = doc_map.get(a.doctor_id)
        if not doc:
            continue
        slot = slot_map[a.slot_id]

        if slot.date in day_off_set:
            violations.append(ConstraintViolation(
                constraint_id = "H10",
                constraint_name = "Days off",
                severity = "hard",
                description = f"Dr. {doc.name} assigned on {slot.date} which is a day-off date.",
                affected_doctors = [doc.id],
                affected_dates = [slot.date],
                suggestion = "Remove this assignment or remove the day-off date."
            ))
            continue
    
        dow = dt_class.fromisoformat(slot.date).weekday()
        if dow in doc.standing_days_off:
            violations.append(ConstraintViolation(
                constraint_id = "H10",
                constraint_name = "Days off",
                severity = "hard",
                description = f"Dr. {doc.name} assigned on {slot.date} (day_of_week={dow}) which is in their standing_days_off: {doc.standing_days_off}.",
                affected_doctors = [doc.id],
                affected_dates = [slot.date],
                suggestion = "Remove this assignment or update standing_days_off."
            ))
    return violations

def suggest_relaxations(violations: List[ConstraintViolation]) -> List[str]:
    """
    Given a list of violations from a partial or infeasible schedule,
    produce human-readable suggestions for what to change in the inputs.

    Group violations by constraint_id, then produce one suggestion per group.
    Include the count of violations in the suggestion so the user knows severity.

    For H5c and H5d, note that doctor preferences have no influence on those
    groups — the user should look at blackout/availability settings instead.
    """
    suggestions = []
    by_id: Dict[str, List[ConstraintViolation]] = {}
    for v in violations:
        by_id.setdefault(v.constraint_id, []).append(v)
    
    if "H3" in by_id:
        n = len(by_id["H3"])
        suggestions.append(
            f"CALL COVERAGE - {n} slot(s) unfilled. "
            f"Options: (1) Reduce max_*_calls limits so doctors can cover more slots. "
            f"(2) Set hospital_call_eligible=True for more doctors."
            f"(3) Remove blackout/day-off dates for call-eligible doctors."
        )
    
    for group in ("weekday_day", "weekday_night", "friday_night", "weekend_block"):
        key = f"H5_{group}"
        if key in by_id:
            pref = (" NOTE: doctor preferences have no influence on this group."
                    if group in ("friday_night", "weekend_block") else "")
            suggestions.append(
                f"CALL BALANCE ({group}){pref}: Balance cannot be achieved. "
                f"Check blackout dates - if some doctors are unavailable for man "
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
    
    return suggestions