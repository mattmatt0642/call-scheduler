from models import Office, ScheduleInput, DoctorProfile
from slot_generator import generate_slots
from constraint_checker import (validate_schedule, check_h6_no_overlap,
                                 ConstraintViolation)

offices = [Office(id="hosp", name="H", is_hospital=True,
                  max_per_shift=2, restricted_tuesday_max=1)]
slots  = generate_slots(2026, 8, offices, [], [])
inp    = ScheduleInput(year=2026, month=8, doctors=[], offices=offices,
                       global_office_ranking=[], day_off_dates=[],
                       custom_restrictions=[], locked_assignments=[],
                       historical_balance={}, solver_time_limit_seconds=120)

# Empty schedule: every call slot is an H3 violation
violations = validate_schedule(inp, slots, [])
h3 = [v for v in violations if v.constraint_id == "H3"]
# 22 call_day + 22 call_night + 4 call_weekend + 4 call_weekend_sun = 52 slots
assert len(h3) == 52, f"Expected 52 H3 violations on empty schedule, got {len(h3)}"
print(f"H3 check: {len(h3)} violations (expected 52) — PASSED")

# H6: Friday night call + Saturday 08:00 office should NOT be a violation
from models import Assignment, ShiftSlot
doc = DoctorProfile(
    id="d1", name="Test", allowed_offices=None, office_preferences=[],
    required_sessions_per_week=5, hospital_call_eligible=True,
    surgical_assist_eligible=False, max_weekday_day_calls=5,
    max_weekday_night_calls=5, max_friday_night_calls=2,
    max_weekend_blocks=2, preferred_call_days=[],
    post_call_preference="no_preference",
    call_shift_preference="no_preference",
    day_night_preference="balanced", am_pm_preference="balanced",
    standing_days_off=[]
)
slot_map = {s.slot_id: s for s in slots}

fri_night_id = "2026-09-04_hosp_call_night"
sat_am = ShiftSlot(slot_id="2026-09-05_north_office_am",
                   date="2026-09-05", office_id="north",
                   shift_type="office_am", start_time="08:00", end_time="12:00",
                   max_doctors=3)

test_map = dict(slot_map)
test_map[sat_am.slot_id] = sat_am

a1 = Assignment(doctor_id="d1", slot_id=fri_night_id)
a2 = Assignment(doctor_id="d1", slot_id=sat_am.slot_id)

h6_violations = check_h6_no_overlap([doc], [a1, a2], test_map)
assert len(h6_violations) == 0, \
    "Friday night + Saturday 08:00 should NOT be an H6 violation"
print("H6 cross-day non-overlap: PASSED")

# H6: Friday night + Saturday 06:00 SHOULD be a violation
sat_06 = ShiftSlot(slot_id="2026-09-05_north_office_0600",
                   date="2026-09-05", office_id="north",
                   shift_type="office_am", start_time="06:00", end_time="10:00",
                   max_doctors=3)
test_map[sat_06.slot_id] = sat_06
a3 = Assignment(doctor_id="d1", slot_id=sat_06.slot_id)
h6_early = check_h6_no_overlap([doc], [a1, a3], test_map)
assert len(h6_early) > 0, \
    "Friday night + Saturday 06:00 SHOULD be an H6 violation"
print("H6 cross-day overlap detected: PASSED")

# H6: Friday night + Saturday weekend block — call_weekend starts 00:00,
# fri_night ends 07:00, so they DO overlap (00:00 < 07:00) => H6 violation
sat_block_id = "2026-09-05_hosp_call_weekend"
a4 = Assignment(doctor_id="d1", slot_id=sat_block_id)
h6_wknd = check_h6_no_overlap([doc], [a1, a4], test_map)
assert len(h6_wknd) > 0, \
    "Friday night + Saturday block (00:00-23:59) MUST be an H6 violation (spec line 1427)"
print("H6 Friday night vs weekend block overlap detected: PASSED")

print("\nAll Checkpoint 3 tests passed.")