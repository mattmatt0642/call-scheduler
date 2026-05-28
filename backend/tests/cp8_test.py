"""
CP8 Edge-Case Tests — Boundary conditions, unusual configurations,
polish, and robustness testing.

Run: PYTHONPATH=. .venv/bin/python tests/cp8_test.py
"""
import sys
import json
from datetime import date, timedelta
from collections import defaultdict

from app import app
from models import (
    DoctorProfile, Office, ScheduleInput, ScheduleResult, Assignment,
    ShiftSlot, RecurringSlot, OneTimeOverride, CustomRestriction,
    get_days_in_month, get_nth_tuesdays, get_weekend_blocks,
    is_friday, get_call_balance_group, slot_to_abs_minutes,
    abs_times_overlap, prev_date,
)
from slot_generator import generate_slots, get_slot_by_id
from constraint_checker import validate_schedule
from scheduler import (
    schedule_greedy, schedule_ilp, generate_schedule,
    _init_load, _update_load, _is_available,
    expand_recurring_slots, expand_one_time_overrides,
    call_debt_with_preference, call_debt_balance_only,
)
from metrics import compute_counts, gini
from csv_io import export_balance_csv, import_balance_csv, export_schedule_csv

passed = 0
failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


def make_doctors(n=7, **overrides):
    docs = []
    for i in range(n):
        kw = dict(
            id=f"d{i}", name=f"Doctor{i}",
            allowed_offices=None, office_preferences=[],
            required_sessions_per_week=5,
            hospital_call_eligible=True,
            surgical_assist_eligible=(i < 3),
            max_weekday_day_calls=5, max_weekday_night_calls=5,
            max_friday_night_calls=2, max_weekend_blocks=2,
            preferred_call_days=[0, 2] if i % 2 == 0 else [1, 3],
            post_call_preference="no_preference",
            call_shift_preference="no_preference",
            day_night_preference="balanced", am_pm_preference="balanced",
            standing_days_off=[],
            fixed_recurring=[], one_time_overrides=[],
        )
        kw.update(overrides)
        docs.append(DoctorProfile(**kw))
    return docs


def make_offices():
    return [
        Office(id="hosp", name="Hospital", is_hospital=True,
               max_per_shift=2, restricted_tuesday_max=1),
        Office(id="north", name="North", is_hospital=False,
               max_per_shift=3, restricted_tuesday_max=3),
        Office(id="south", name="South", is_hospital=False,
               max_per_shift=2, restricted_tuesday_max=2),
    ]


def make_input(year=2026, month=8, doctors=None, offices=None, **kw):
    if doctors is None:
        doctors = make_doctors()
    if offices is None:
        offices = make_offices()
    defaults = dict(
        year=year, month=month, doctors=doctors, offices=offices,
        global_office_ranking=["hosp", "north", "south"],
        day_off_dates=[], custom_restrictions=[],
        locked_assignments=[], historical_balance={},
        solver_time_limit_seconds=10,
    )
    defaults.update(kw)
    return ScheduleInput(**defaults)


def make_doctor_json(n=7, **overrides):
    result = []
    for i in range(n):
        d = {
            "id": f"d{i}", "name": f"Doctor{i}",
            "allowedOffices": None, "officePreferences": [],
            "requiredSessionsPerWeek": 5,
            "hospitalCallEligible": True,
            "surgicalAssistEligible": i < 3,
            "maxWeekdayDayCalls": 5, "maxWeekdayNightCalls": 5,
            "maxFridayNightCalls": 2, "maxWeekendBlocks": 2,
            "preferredCallDays": [0, 2] if i % 2 == 0 else [1, 3],
            "postCallPreference": "no_preference",
            "callShiftPreference": "no_preference",
            "dayNightPreference": "balanced", "amPmPreference": "balanced",
            "standingDaysOff": [], "fixedRecurring": [], "oneTimeOverrides": [],
        }
        d.update(overrides)
        result.append(d)
    return result


def make_office_json():
    return [
        {"id": "hosp", "name": "Hospital", "isHospital": True,
         "maxPerShift": 2, "restrictedTuesdayMax": 1},
        {"id": "north", "name": "North", "isHospital": False,
         "maxPerShift": 3, "restrictedTuesdayMax": 3},
        {"id": "south", "name": "South", "isHospital": False,
         "maxPerShift": 2, "restrictedTuesdayMax": 2},
    ]


def make_generate_payload(year=2026, month=8, doctors=None, offices=None,
                           **extra):
    if doctors is None:
        doctors = make_doctor_json()
    if offices is None:
        offices = make_office_json()
    payload = {
        "year": year, "month": month,
        "doctors": doctors, "offices": offices,
        "globalOfficeRanking": ["hosp", "north", "south"],
        "dayOffDates": [], "customRestrictions": [],
        "lockedAssignments": [], "historicalBalance": {},
        "solverTimeLimitSeconds": 10,
    }
    payload.update(extra)
    return payload


client = app.test_client()


# ============================================================
# SECTION A: SINGLE-DOCTOR EDGE CASES
# ============================================================
print("\n=== SECTION A: SINGLE-DOCTOR EDGE CASES ===")

docs_a = [DoctorProfile(
    id="d0", name="SoloDoc", allowed_offices=None,
    office_preferences=[], required_sessions_per_week=5,
    hospital_call_eligible=True, surgical_assist_eligible=True,
    max_weekday_day_calls=30, max_weekday_night_calls=30,
    max_friday_night_calls=10, max_weekend_blocks=10,
    preferred_call_days=[], post_call_preference="no_preference",
    call_shift_preference="no_preference",
    day_night_preference="balanced", am_pm_preference="balanced",
    standing_days_off=[], fixed_recurring=[], one_time_overrides=[],
)]
inp_a = make_input(doctors=docs_a)
result_a = schedule_greedy(inp_a)
check("A1 single doc generates assignments",
      len(result_a.assignments) > 0,
      f"got {len(result_a.assignments)}")
check("A1 single doc month_key correct",
      result_a.month_key == "2026-09")
sm_a = {s.slot_id: s for s in result_a.slots}
d0_count = sum(1 for a in result_a.assignments if a.doctor_id == "d0")
check("A1 single doc all assignments are d0",
      d0_count == len(result_a.assignments))
check("A1 single doc has call assignments",
      any(sm_a[a.slot_id].shift_type.startswith("call")
          for a in result_a.assignments))

# A2: Single doc via API
r_a2 = client.post("/generate", json=make_generate_payload(
    doctors=[make_doctor_json(1, maxWeekdayDayCalls=30,
                              maxWeekdayNightCalls=30,
                              maxFridayNightCalls=10,
                              maxWeekendBlocks=10)[0]]))
check("A2 single doc API generates",
      r_a2.status_code == 200, f"got {r_a2.status_code}")


# ============================================================
# SECTION B: ALL-DAY-OFF / ALL-BLACKOUT EDGE CASES
# ============================================================
print("\n=== SECTION B: ALL-DAY-OFF / ALL-BLACKOUT EDGE CASES ===")

# B1: All doctors have Friday standing days-off
docs_b1 = make_doctors(7, standing_days_off=[4])
inp_b1 = make_input(doctors=docs_b1)
result_b1 = schedule_greedy(inp_b1)
sm_b1 = {s.slot_id: s for s in result_b1.slots}
d0_fri_office = [a for a in result_b1.assignments
                 if a.doctor_id == "d0"
                 and date.fromisoformat(sm_b1[a.slot_id].date).weekday() == 4
                 and sm_b1[a.slot_id].shift_type.startswith("office")]
check("B1 all-docs Fri off: d0 no office on Fridays",
      len(d0_fri_office) == 0,
      f"found {len(d0_fri_office)}")

# B2: Every weekday is a blackout
days_b2 = get_days_in_month(2026, 8)
all_weekdays_b2 = [d["date"] for d in days_b2 if not d["is_weekend"]]
inp_b2 = make_input(day_off_dates=all_weekdays_b2)
result_b2 = schedule_greedy(inp_b2)
check("B2 all-blackout generates without crash",
      len(result_b2.assignments) >= 0,
      f"assignments={len(result_b2.assignments)}")

# B3: Single day-off date
inp_b3 = make_input(day_off_dates=["2026-09-01"])
slots_b3 = generate_slots(2026, 8, make_offices(), ["2026-09-01"], [])
sep1_office = [s for s in slots_b3
               if s.date == "2026-09-01"
               and s.shift_type.startswith("office")]
check("B3 day-off removes office slots for that date",
      len(sep1_office) == 0,
      f"found {len(sep1_office)} office slots on day-off date")

# B4: Day-off on a weekend date
inp_b4 = make_input(day_off_dates=["2026-09-05"])  # Saturday
slots_b4 = generate_slots(2026, 8, make_offices(), ["2026-09-05"], [])
sat_office = [s for s in slots_b4
              if s.date == "2026-09-05"
              and s.shift_type.startswith("office")]
sat_call = [s for s in slots_b4
            if s.date == "2026-09-05"
            and s.shift_type.startswith("call")]
check("B4 weekend day-off: no office slots",
      len(sat_office) == 0)
check("B4 weekend day-off: call slots still exist",
      len(sat_call) > 0,
      f"got {len(sat_call)} call slots")


# ============================================================
# SECTION C: CUSTOM RESTRICTION EDGE CASES
# ============================================================
print("\n=== SECTION C: CUSTOM RESTRICTION EDGE CASES ===")

# C1: max_override=0 on a call slot
custom_c1 = [CustomRestriction(date="2026-09-01", office_id="hosp",
                                shift_type="call_day", max_override=0)]
slots_c1 = generate_slots(2026, 8, make_offices(), [], custom_c1)
cd_slot = [s for s in slots_c1
           if s.date == "2026-09-01"
           and s.office_id == "hosp"
           and s.shift_type == "call_day"]
check("C1 max_override=0 on call_day: slot exists",
      len(cd_slot) == 1,
      f"found {len(cd_slot)}")
if cd_slot:
    check("C1 max_override=0 -> max_doctors=0",
          cd_slot[0].max_doctors == 0,
          f"got {cd_slot[0].max_doctors}")

# C2: max_override higher than default
custom_c2 = [CustomRestriction(date="2026-09-01", office_id="north",
                                shift_type="office_am", max_override=10)]
slots_c2 = generate_slots(2026, 8, make_offices(), [], custom_c2)
north_c2 = [s for s in slots_c2
            if s.date == "2026-09-01"
            and s.office_id == "north"
            and s.shift_type == "office_am"]
check("C2 max_override=10 on office_am",
      len(north_c2) == 1 and north_c2[0].max_doctors == 10,
      f"got {north_c2[0].max_doctors if north_c2 else 'N/A'}")

# C3: Custom restriction via API
r_c3 = client.post("/generate", json=make_generate_payload(
    customRestrictions=[
        {"date": "2026-09-01", "officeId": "hosp",
         "shiftType": "call_day", "maxOverride": 0}
    ]))
check("C3 API custom restriction accepted",
      r_c3.status_code == 200, f"got {r_c3.status_code}")


# ============================================================
# SECTION D: DOCTOR PREFERENCE EDGE CASES
# ============================================================
print("\n=== SECTION D: DOCTOR PREFERENCE EDGE CASES ===")

# D1: Doctor with all call preferences set
docs_d1 = make_doctors(7)
docs_d1[0] = DoctorProfile(
    id="d0", name="PrefDoc", allowed_offices=None,
    office_preferences=[],
    required_sessions_per_week=5,
    hospital_call_eligible=True, surgical_assist_eligible=True,
    max_weekday_day_calls=5, max_weekday_night_calls=5,
    max_friday_night_calls=2, max_weekend_blocks=2,
    preferred_call_days=[0, 1, 2, 3, 4],
    post_call_preference="no_preference",
    call_shift_preference="day_only",
    day_night_preference="day", am_pm_preference="am",
    standing_days_off=[], fixed_recurring=[], one_time_overrides=[],
)
inp_d1 = make_input(doctors=docs_d1)
result_d1 = schedule_greedy(inp_d1)
check("D1 preference-heavy doc generates",
      len(result_d1.assignments) > 0)

# D2: Doctor with no preferences
docs_d2 = make_doctors(7)
docs_d2[0] = DoctorProfile(
    id="d0", name="NoPrefDoc", allowed_offices=None,
    office_preferences=[],
    required_sessions_per_week=5,
    hospital_call_eligible=True, surgical_assist_eligible=True,
    max_weekday_day_calls=5, max_weekday_night_calls=5,
    max_friday_night_calls=2, max_weekend_blocks=2,
    preferred_call_days=[],
    post_call_preference="no_preference",
    call_shift_preference="no_preference",
    day_night_preference="no_preference",
    am_pm_preference="no_preference",
    standing_days_off=[], fixed_recurring=[], one_time_overrides=[],
)
inp_d2 = make_input(doctors=docs_d2)
result_d2 = schedule_greedy(inp_d2)
check("D2 no-preference doc generates",
      len(result_d2.assignments) > 0)

# D3: Doctor with call_shift_preference="night_only"
docs_d3 = make_doctors(7)
docs_d3[0] = DoctorProfile(
    id="d0", name="NightOwl", allowed_offices=None,
    office_preferences=[],
    required_sessions_per_week=5,
    hospital_call_eligible=True, surgical_assist_eligible=True,
    max_weekday_day_calls=5, max_weekday_night_calls=5,
    max_friday_night_calls=2, max_weekend_blocks=2,
    preferred_call_days=[],
    post_call_preference="no_preference",
    call_shift_preference="night_only",
    day_night_preference="night", am_pm_preference="balanced",
    standing_days_off=[], fixed_recurring=[], one_time_overrides=[],
)
inp_d3 = make_input(doctors=docs_d3)
result_d3 = schedule_greedy(inp_d3)
check("D3 night_only doc generates",
      len(result_d3.assignments) > 0)

# D4: Doctor not hospital-call-eligible
docs_d4 = make_doctors(7)
docs_d4[0] = DoctorProfile(
    id="d0", name="NoCall", allowed_offices=["north", "south"],
    office_preferences=[],
    required_sessions_per_week=5,
    hospital_call_eligible=False, surgical_assist_eligible=False,
    max_weekday_day_calls=0, max_weekday_night_calls=0,
    max_friday_night_calls=0, max_weekend_blocks=0,
    preferred_call_days=[],
    post_call_preference="no_preference",
    call_shift_preference="no_preference",
    day_night_preference="no_preference",
    am_pm_preference="no_preference",
    standing_days_off=[], fixed_recurring=[], one_time_overrides=[],
)
inp_d4 = make_input(doctors=docs_d4)
result_d4 = schedule_greedy(inp_d4)
sm_d4 = {s.slot_id: s for s in result_d4.slots}
d0_call = [a for a in result_d4.assignments
           if a.doctor_id == "d0"
           and sm_d4[a.slot_id].shift_type.startswith("call")]
check("D4 non-call-eligible doc has 0 calls",
      len(d0_call) == 0, f"found {len(d0_call)} call assignments")
d0_hosp = [a for a in result_d4.assignments
           if a.doctor_id == "d0"
           and sm_d4[a.slot_id].office_id == "hosp"
           and sm_d4[a.slot_id].shift_type.startswith("office")]
check("D4 non-call-eligible doc not assigned to hospital office",
      len(d0_hosp) == 0, f"found {len(d0_hosp)} hospital office assignments")


# ============================================================
# SECTION E: MONTH BOUNDARY EDGE CASES
# ============================================================
print("\n=== SECTION E: MONTH BOUNDARY EDGE CASES ===")

# E1: January (month=0)
inp_e1 = make_input(year=2026, month=0)
result_e1 = schedule_greedy(inp_e1)
check("E1 January generates",
      len(result_e1.assignments) > 0,
      f"assignments={len(result_e1.assignments)}")
check("E1 January month_key=2026-01",
      result_e1.month_key == "2026-01")

# E2: December (month=11)
inp_e2 = make_input(year=2026, month=11)
result_e2 = schedule_greedy(inp_e2)
check("E2 December generates",
      len(result_e2.assignments) > 0)
check("E2 December month_key=2026-12",
      result_e2.month_key == "2026-12")

# E3: February non-leap (2027, month=1)
inp_e3 = make_input(year=2027, month=1)
result_e3 = schedule_greedy(inp_e3)
check("E3 Feb 2027 generates",
      len(result_e3.assignments) > 0)
check("E3 Feb 2027 month_key=2027-02",
      result_e3.month_key == "2027-02")

# E4: February leap year (2024, month=1)
inp_e4 = make_input(year=2024, month=1)
result_e4 = schedule_greedy(inp_e4)
check("E4 Feb 2024 (leap) generates",
      len(result_e4.assignments) > 0)
days_e4 = get_days_in_month(2024, 1)
check("E4 Feb 2024 has 29 days",
      len(days_e4) == 29, f"got {len(days_e4)}")

# E5: Weekend block crosses month boundary
blocks_e5 = get_weekend_blocks(2026, 9)  # October
check("E5 get_weekend_blocks doesn't crash for October",
      len(blocks_e5) >= 0)

# E6: API December
r_e6 = client.post("/generate", json=make_generate_payload(year=2026, month=11))
check("E6 API December generates",
      r_e6.status_code == 200, f"got {r_e6.status_code}")
d_e6 = r_e6.get_json()
check("E6 API December monthKey=2026-12",
      d_e6.get("monthKey") == "2026-12",
      f"got {d_e6.get('monthKey')}")


# ============================================================
# SECTION F: ALLOWED OFFICES EDGE CASES
# ============================================================
print("\n=== SECTION F: ALLOWED OFFICES EDGE CASES ===")

# F1: Doctor restricted to single office
docs_f1 = make_doctors(7)
docs_f1[0] = DoctorProfile(
    id="d0", name="NorthOnly", allowed_offices=["north"],
    office_preferences=[], required_sessions_per_week=5,
    hospital_call_eligible=True, surgical_assist_eligible=True,
    max_weekday_day_calls=5, max_weekday_night_calls=5,
    max_friday_night_calls=2, max_weekend_blocks=2,
    preferred_call_days=[], post_call_preference="no_preference",
    call_shift_preference="no_preference",
    day_night_preference="balanced", am_pm_preference="balanced",
    standing_days_off=[], fixed_recurring=[], one_time_overrides=[],
)
inp_f1 = make_input(doctors=docs_f1)
result_f1 = schedule_greedy(inp_f1)
sm_f1 = {s.slot_id: s for s in result_f1.slots}
d0_offices = set(sm_f1[a.slot_id].office_id
                 for a in result_f1.assignments if a.doctor_id == "d0")
d0_non_allowed = d0_offices - {"north", "hosp"}
check("F1 allowed_offices=[north]: d0 only at north+hospital",
      len(d0_non_allowed) == 0,
      f"found at: {d0_non_allowed}")

# F2: All doctors restricted to different offices
docs_f2 = []
offices_f2 = make_offices()
for i in range(7):
    office = offices_f2[i % 3].id
    docs_f2.append(DoctorProfile(
        id=f"d{i}", name=f"Doc{i}", allowed_offices=[office],
        office_preferences=[], required_sessions_per_week=5,
        hospital_call_eligible=True, surgical_assist_eligible=True,
        max_weekday_day_calls=5, max_weekday_night_calls=5,
        max_friday_night_calls=2, max_weekend_blocks=2,
        preferred_call_days=[], post_call_preference="no_preference",
        call_shift_preference="no_preference",
        day_night_preference="balanced", am_pm_preference="balanced",
        standing_days_off=[], fixed_recurring=[], one_time_overrides=[],
    ))
inp_f2 = make_input(doctors=docs_f2)
result_f2 = schedule_greedy(inp_f2)
check("F2 multi-restricted offices generates",
      len(result_f2.assignments) > 0)


# ============================================================
# SECTION G: LOCKED ASSIGNMENTS EDGE CASES
# ============================================================
print("\n=== SECTION G: LOCKED ASSIGNMENTS EDGE CASES ===")

# G1: Multiple locked assignments on same day
slots_g1 = generate_slots(2026, 8, make_offices(), [], [])
hosp_am = [s for s in slots_g1
           if s.date == "2026-09-01"
           and s.office_id == "hosp"
           and s.shift_type == "office_am"]
if hosp_am:
    locked_g1 = [
        Assignment(doctor_id="d0", slot_id=hosp_am[0].slot_id,
                   is_locked=True),
    ]
    inp_g1 = make_input(locked_assignments=locked_g1)
    result_g1 = schedule_greedy(inp_g1)
    locked_found = any(a.doctor_id == "d0" and a.is_locked
                       for a in result_g1.assignments
                       if a.slot_id == hosp_am[0].slot_id)
    check("G1 locked assignment preserved", locked_found)
else:
    check("G1 locked assignment preserved", True, "no hosp office_am slot")

# G2: Locked assignment via API
r_g2 = client.post("/generate", json=make_generate_payload(
    lockedAssignments=[
        {"doctorId": "d0", "slotId": "2026-09-01_hosp_call_day",
         "isLocked": True}
    ]))
check("G2 API locked assignment accepted",
      r_g2.status_code == 200, f"got {r_g2.status_code}")
if r_g2.status_code == 200:
    d_g2 = r_g2.get_json()
    locked_g2 = [a for a in d_g2.get("assignments", [])
                 if a.get("slotId") == "2026-09-01_hosp_call_day"
                 and a.get("doctorId") == "d0"]
    check("G2 locked assignment in response",
          len(locked_g2) > 0 and locked_g2[0].get("isLocked") is True)


# ============================================================
# SECTION H: RECURRING + OVERRIDE EDGE CASES
# ============================================================
print("\n=== SECTION H: RECURRING + OVERRIDE EDGE CASES ===")

# H1: Recurring on all standing days
docs_h1 = make_doctors(3)
docs_h1[0] = DoctorProfile(
    id="d0", name="RecurringDoc", allowed_offices=None,
    office_preferences=[], required_sessions_per_week=5,
    hospital_call_eligible=True, surgical_assist_eligible=True,
    max_weekday_day_calls=5, max_weekday_night_calls=5,
    max_friday_night_calls=2, max_weekend_blocks=2,
    preferred_call_days=[], post_call_preference="no_preference",
    call_shift_preference="no_preference",
    day_night_preference="balanced", am_pm_preference="balanced",
    standing_days_off=[],
    fixed_recurring=[
        RecurringSlot(day_of_week=i, office_id="north",
                      shift_type="office_am")
        for i in range(5)
    ],
    one_time_overrides=[],
)
slots_h1 = generate_slots(2026, 8, make_offices(), [], [])
slot_id_set_h1 = {s.slot_id for s in slots_h1}
recurring_h1 = expand_recurring_slots(docs_h1, slots_h1, 2026, 8)
d0_recurring = [a for a in recurring_h1 if a.doctor_id == "d0"]
check("H1 recurring on all 5 weekdays creates assignments",
      len(d0_recurring) > 0, f"got {len(d0_recurring)}")

# H2: Override on non-existent slot
docs_h2 = make_doctors(1)
docs_h2[0] = DoctorProfile(
    id="d0", name="OOBDoc", allowed_offices=None,
    office_preferences=[], required_sessions_per_week=5,
    hospital_call_eligible=True, surgical_assist_eligible=True,
    max_weekday_day_calls=5, max_weekday_night_calls=5,
    max_friday_night_calls=2, max_weekend_blocks=2,
    preferred_call_days=[], post_call_preference="no_preference",
    call_shift_preference="no_preference",
    day_night_preference="balanced", am_pm_preference="balanced",
    standing_days_off=[],
    fixed_recurring=[],
    one_time_overrides=[
        OneTimeOverride(date="2026-09-01", office_id="nonexistent",
                        shift_type="office_am")
    ],
)
overrides_h2 = expand_one_time_overrides(docs_h2, 2026, 8, slot_id_set_h1)
check("H2 override on non-existent office ignored",
      len(overrides_h2) == 0, f"got {len(overrides_h2)}")

# H3: Override via API
r_h3 = client.post("/generate", json=make_generate_payload(
    doctors=[{
        "id": "d0", "name": "OverrideDoc",
        "allowedOffices": None, "officePreferences": [],
        "requiredSessionsPerWeek": 5,
        "hospitalCallEligible": True, "surgicalAssistEligible": True,
        "maxWeekdayDayCalls": 5, "maxWeekdayNightCalls": 5,
        "maxFridayNightCalls": 2, "maxWeekendBlocks": 2,
        "preferredCallDays": [], "postCallPreference": "no_preference",
        "callShiftPreference": "no_preference",
        "dayNightPreference": "balanced", "amPmPreference": "balanced",
        "standingDaysOff": [], "fixedRecurring": [],
        "oneTimeOverrides": [
            {"date": "2026-09-07", "officeId": "south",
             "shiftType": "office_pm"}
        ],
    }] + make_doctor_json(6)
))
check("H3 API override accepted",
      r_h3.status_code == 200, f"got {r_h3.status_code}")


# ============================================================
# SECTION I: SLOT GENERATOR ROBUSTNESS
# ============================================================
print("\n=== SECTION I: SLOT GENERATOR ROBUSTNESS ===")

# I1: Every day in September has call slots
slots_i1 = generate_slots(2026, 8, make_offices(), [], [])
for day_info in get_days_in_month(2026, 8):
    d = day_info["date"]
    day_calls = [s for s in slots_i1 if s.date == d
                 and s.shift_type.startswith("call")]
    if not day_calls:
        check(f"I1 {d} has call slots", False, "no call slots")
        break
else:
    check("I1 every day has call slots", True)

# I2: Restricted Tuesday only on Nth Tuesdays
nth_tues = set(get_nth_tuesdays(2026, 8))
all_tues_i2 = [d for d in get_days_in_month(2026, 8) if d["is_tuesday"]]
for d in all_tues_i2:
    if d["date"] in nth_tues:
        rt_slots = [s for s in slots_i1
                    if s.date == d["date"]
                    and s.is_restricted_tuesday]
        if not rt_slots:
            check(f"I2 {d['date']} Nth Tue has restricted slots", False)
            break
    else:
        rt_slots = [s for s in slots_i1
                    if s.date == d["date"]
                    and s.is_restricted_tuesday]
        if rt_slots:
            check(f"I2 {d['date']} non-Nth Tue has no restricted slots",
                  False, f"found {len(rt_slots)}")
            break
else:
    check("I2 restricted Tuesday only on Nth Tuesdays", True)

# I3: Weekend blocks have Sat+Sun
weekend_blocks_i3 = get_weekend_blocks(2026, 8)
for wb in weekend_blocks_i3:
    sat = date.fromisoformat(wb.saturday)
    sun = date.fromisoformat(wb.sunday)
    check(f"I3 {wb.saturday} Sun=Sat+1",
          sun == sat + timedelta(days=1))
    check(f"I3 {wb.saturday} Sat is Saturday",
          sat.weekday() == 5)
    check(f"I3 {wb.saturday} Sun is Sunday",
          sun.weekday() == 6)

# I4: No duplicate slot IDs
slot_ids_i4 = [s.slot_id for s in slots_i1]
check("I4 no duplicate slot IDs",
      len(slot_ids_i4) == len(set(slot_ids_i4)),
      f"total={len(slot_ids_i4)} unique={len(set(slot_ids_i4))}")

# I5: Surgical slots only on Tue/Wed/Thu
surgical_i5 = [s for s in slots_i1
               if s.shift_type in ("surgical_am", "surgical_hosp_pm")]
all_twt_i5 = all(date.fromisoformat(s.date).weekday() in (1, 2, 3)
                 for s in surgical_i5)
check("I5 surgical slots only Tue/Wed/Thu", all_twt_i5)


# ============================================================
# SECTION J: METRICS ROBUSTNESS
# ============================================================
print("\n=== SECTION J: METRICS ROBUSTNESS ===")

# J1: Gini with identical counts = 0
check("J1 gini([5,5,5]) = 0",
      abs(gini([5, 5, 5])) < 0.001,
      f"got {gini([5, 5, 5])}")

# J2: Gini with one non-zero = ~0.6
gini_j2 = gini([0, 0, 5])
check("J2 gini([0,0,5]) > 0",
      gini_j2 > 0.3, f"got {gini_j2}")

# J3: Gini with empty list = 0
check("J3 gini([]) = 0",
      abs(gini([])) < 0.001)

# J4: Gini with single element = 0
check("J4 gini([10]) = 0",
      abs(gini([10])) < 0.001)

# J5: compute_counts with no assignments
inp_j5 = make_input()
counts_j5 = compute_counts(inp_j5.doctors, inp_j5.offices,
                           [], [], {})
all_zero = all(c.total_calls == 0 and c.total_sessions == 0
               for c in counts_j5.values())
check("J5 compute_counts with no assignments = all zero", all_zero)


# ============================================================
# SECTION K: H6 OVERLAP EDGE CASES
# ============================================================
print("\n=== SECTION K: H6 OVERLAP EDGE CASES ===")

def _mslot(date_str, start, end, stype="office_am", office="x"):
    return ShiftSlot(
        slot_id=f"{date_str}_{office}_{stype}", date=date_str,
        office_id=office, shift_type=stype,
        start_time=start, end_time=end, max_doctors=1,
    )

# K1: call_day (07-19) does NOT overlap office_am next day
s_k1a = _mslot("2026-09-01", "07:00", "19:00", "call_day", "hosp")
s_k1b = _mslot("2026-09-02", "08:00", "12:00", "office_am", "north")
check("K1 call_day vs next-day office_am no overlap",
      abs_times_overlap(s_k1a, s_k1b) is False)

# K2: call_night (19-07) overlaps call_weekend (00-24)
s_k2a = _mslot("2026-09-04", "19:00", "07:00", "call_night", "hosp")
s_k2b = _mslot("2026-09-05", "00:00", "23:59", "call_weekend", "hosp")
check("K2 Fri night vs Sat weekend overlap",
      abs_times_overlap(s_k2a, s_k2b) is True)

# K3: Two office shifts same doctor same day same time = overlap
s_k3a = _mslot("2026-09-01", "08:00", "12:00", "office_am", "north")
s_k3b = _mslot("2026-09-01", "08:00", "12:00", "office_am", "south")
check("K3 same time different offices overlap",
      abs_times_overlap(s_k3a, s_k3b) is True)

# K4: AM and PM touching = no overlap
s_k4a = _mslot("2026-09-01", "08:00", "12:00", "office_am", "north")
s_k4b = _mslot("2026-09-01", "12:00", "17:00", "office_pm", "north")
check("K4 AM-PM touching no overlap",
      abs_times_overlap(s_k4a, s_k4b) is False)

# K5: PM and late touching = no overlap
s_k5a = _mslot("2026-09-01", "12:00", "17:00", "office_pm", "north")
s_k5b = _mslot("2026-09-01", "17:00", "19:00", "office_late", "north")
check("K5 PM-late touching no overlap",
      abs_times_overlap(s_k5a, s_k5b) is False)

# K6: call_night + same-date office_am (overnight boundary)
s_k6a = _mslot("2026-09-01", "19:00", "07:00", "call_night", "hosp")
s_k6b = _mslot("2026-09-01", "08:00", "12:00", "office_am", "hosp")
check("K6 call_night same-date office_am no overlap",
      abs_times_overlap(s_k6a, s_k6b) is False)

# K7: call_day + office_late same day (07-19 vs 17-19) = overlap
s_k7a = _mslot("2026-09-01", "07:00", "19:00", "call_day", "hosp")
s_k7b = _mslot("2026-09-01", "17:00", "19:00", "office_late", "north")
check("K7 call_day vs office_late same day overlap",
      abs_times_overlap(s_k7a, s_k7b) is True)


# ============================================================
# SECTION L: H8 POST-CALL EDGE CASES
# ============================================================
print("\n=== SECTION L: H8 POST-CALL EDGE CASES ===")

offices_l = make_offices()
slots_l = generate_slots(2026, 8, offices_l, [], [])
slot_map_l = {s.slot_id: s for s in slots_l}
inp_l = make_input()

# L1: friday_night -> Monday must be hospital
assignments_l1 = [
    Assignment(doctor_id="d0", slot_id="2026-09-04_hosp_call_night"),
    Assignment(doctor_id="d0", slot_id="2026-09-07_north_office_am"),
]
v_l1 = validate_schedule(inp_l, slots_l, assignments_l1)
h8_l1 = [v for v in v_l1 if v.constraint_id == "H8"]
check("L1 Fri night -> Mon non-hospital = H8",
      len(h8_l1) > 0, f"got {len(h8_l1)}")

# L2: call_day -> same-day non-hospital PM
assignments_l2 = [
    Assignment(doctor_id="d0", slot_id="2026-09-01_hosp_call_day"),
    Assignment(doctor_id="d0", slot_id="2026-09-01_north_office_pm"),
]
v_l2 = validate_schedule(inp_l, slots_l, assignments_l2)
h8_l2 = [v for v in v_l2 if v.constraint_id == "H8"]
check("L2 call_day + same-day non-hospital PM = H8",
      len(h8_l2) > 0, f"got {len(h8_l2)}")

# L3: call_day -> same-day hospital PM is OK
assignments_l3 = [
    Assignment(doctor_id="d0", slot_id="2026-09-01_hosp_call_day"),
    Assignment(doctor_id="d0", slot_id="2026-09-01_hosp_office_pm"),
]
v_l3 = validate_schedule(inp_l, slots_l, assignments_l3)
h8_l3 = [v for v in v_l3 if v.constraint_id == "H8"]
check("L3 call_day + same-day hospital PM OK",
      len(h8_l3) == 0, f"got {len(h8_l3)}")

# L4: Multiple calls in a row
assignments_l4 = [
    Assignment(doctor_id="d0", slot_id="2026-09-01_hosp_call_day"),
    Assignment(doctor_id="d0", slot_id="2026-09-02_hosp_call_day"),
    Assignment(doctor_id="d0", slot_id="2026-09-03_north_office_am"),
]
v_l4 = validate_schedule(inp_l, slots_l, assignments_l4)
h8_l4 = [v for v in v_l4 if v.constraint_id == "H8"]
check("L4 consecutive calls then non-hospital = H8",
      len(h8_l4) > 0, f"got {len(h8_l4)}")

# L5: Surgical_pm at hospital clears H8
assignments_l5 = [
    Assignment(doctor_id="d0", slot_id="2026-09-01_hosp_call_night"),
    Assignment(doctor_id="d0", slot_id="2026-09-02_hosp_surgical_am"),
    Assignment(doctor_id="d0", slot_id="2026-09-02_hosp_surgical_hosp_pm"),
    Assignment(doctor_id="d0", slot_id="2026-09-03_north_office_am"),
]
v_l5 = validate_schedule(inp_l, slots_l, assignments_l5)
h8_l5 = [v for v in v_l5 if v.constraint_id == "H8"]
check("L5 surgical_hosp_pm clears H8",
      len(h8_l5) == 0, f"got {len(h8_l5)}")

# L6: weekend_block -> next weekday non-hospital
assignments_l6 = [
    Assignment(doctor_id="d0", slot_id="2026-09-05_hosp_call_weekend"),
    Assignment(doctor_id="d0", slot_id="2026-09-06_hosp_call_weekend_sun"),
    Assignment(doctor_id="d0", slot_id="2026-09-07_north_office_am"),
]
v_l6 = validate_schedule(inp_l, slots_l, assignments_l6)
h8_l6 = [v for v in v_l6 if v.constraint_id == "H8"]
check("L6 weekend block -> Mon non-hospital = H8",
      len(h8_l6) > 0, f"got {len(h8_l6)}")


# ============================================================
# SECTION M: API ROBUSTNESS
# ============================================================
print("\n=== SECTION M: API ROBUSTNESS ===")

# M1: Generate with extra fields
r_m1 = client.post("/generate", json=make_generate_payload(foo="bar"))
check("M1 extra fields ignored",
      r_m1.status_code == 200, f"got {r_m1.status_code}")

# M2: Validate with no assignments
r_m2 = client.post("/validate", json={
    "year": 2026, "month": 8,
    "doctors": make_doctor_json(),
    "offices": make_office_json(),
    "dayOffDates": [], "customRestrictions": [],
    "assignments": [],
})
check("M2 validate empty assignments",
      r_m2.status_code == 200)
v_m2 = r_m2.get_json()
h3_m2 = [v for v in v_m2.get("violations", [])
         if v.get("constraintId") == "H3"]
check("M2 empty assignments has H3 violations",
      len(h3_m2) > 0)

# M3: Export balance with single doctor
r_m3 = client.post("/export-balance", json={
    "doctors": make_doctor_json(1),
    "offices": make_office_json(),
    "totals": {
        "d0": {"weekday_day": 5, "weekday_night": 4,
               "friday_night": 1, "weekend_blocks": 2,
               "total_sessions": 30, "am_sessions": 15,
               "pm_sessions": 12, "late_sessions": 3,
               "office_visits": {"north": 10, "south": 5}},
    },
})
check("M3 export-balance single doctor",
      r_m3.status_code == 200)
csv_m3 = r_m3.data.decode()
check("M3 CSV has header + 1 row",
      len(csv_m3.strip().split("\n")) == 2)

# M4: Export schedule with no assignments
r_m4 = client.post("/export-schedule", json={
    "year": 2026, "month": 8,
    "doctors": make_doctor_json(),
    "offices": make_office_json(),
    "assignments": [],
    "dayOffDates": [], "customRestrictions": [],
})
check("M4 export-schedule no assignments",
      r_m4.status_code == 200)

# M5: Import balance then use as historical
csv_m5 = r_m3.data.decode()
buf_m5 = __import__("io").BytesIO(csv_m5.encode())
r_ib_m5 = client.post("/import-balance", data={"file": (buf_m5, "bal.csv")})
check("M5 import then reuse",
      r_ib_m5.status_code == 200)
ib_m5 = r_ib_m5.get_json()
check("M5 imported data has d0",
      "d0" in ib_m5)


# ============================================================
# SECTION N: BALANCE GROUP INDEPENDENCE
# ============================================================
print("\n=== SECTION N: BALANCE GROUP INDEPENDENCE ===")

# N1: friday_night balance is independent of weekday_day
inp_n1 = make_input()
result_n1 = schedule_greedy(inp_n1)
sm_n1 = {s.slot_id: s for s in result_n1.slots}
fn_counts = defaultdict(int)
wd_counts = defaultdict(int)
for a in result_n1.assignments:
    s = sm_n1[a.slot_id]
    if s.call_balance_group == "friday_night":
        fn_counts[a.doctor_id] += 1
    elif s.call_balance_group == "weekday_day":
        wd_counts[a.doctor_id] += 1
if fn_counts:
    fn_spread = max(fn_counts.values()) - min(fn_counts.values())
    check("N1 friday_night spread",
          fn_spread <= 2, f"spread={fn_spread}")
else:
    check("N1 friday_night spread", True, "no FN assignments")

# N2: weekend_block paired same doctor
sat_docs = {}
for a in result_n1.assignments:
    s = sm_n1[a.slot_id]
    if s.shift_type == "call_weekend":
        sat_docs[s.date] = a.doctor_id
sun_docs = {}
for a in result_n1.assignments:
    s = sm_n1[a.slot_id]
    if s.shift_type == "call_weekend_sun":
        sun_docs[s.date] = a.doctor_id
all_paired_n2 = True
for sat_date, sat_doc in sat_docs.items():
    sun_date = str(date.fromisoformat(sat_date) + timedelta(days=1))
    if sun_date in sun_docs and sun_docs[sun_date] != sat_doc:
        all_paired_n2 = False
check("N2 Sat+Sun paired same doctor", all_paired_n2)


# ============================================================
# SECTION O: CONSTRAINT CHECKER WITH UNKNOWN SLOTS
# ============================================================
print("\n=== SECTION O: CONSTRAINT CHECKER WITH UNKNOWN SLOTS ===")

# O1: Validate with assignment to non-existent slot
r_o1 = client.post("/validate", json={
    "year": 2026, "month": 8,
    "doctors": make_doctor_json(2),
    "offices": make_office_json(),
    "dayOffDates": [], "customRestrictions": [],
    "assignments": [
        {"doctorId": "d0", "slotId": "2026-09-01_nonexistent_office_am"},
    ],
})
check("O1 unknown slot doesn't crash",
      r_o1.status_code == 200, f"got {r_o1.status_code}")
v_o1 = r_o1.get_json()
h1_o1 = [v for v in v_o1.get("violations", [])
         if v.get("constraintId") == "H1"]
check("O1 unknown slot reported as H1 violation",
      len(h1_o1) > 0, f"got {len(h1_o1)}")


# ============================================================
# SUMMARY
# ============================================================
print(f"\n{'='*60}")
print(f"CP8 EDGE-CASE TEST RESULTS: {passed} passed, {failed} failed")
print(f"{'='*60}")
if failed > 0:
    print("SOME TESTS FAILED - review output above")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
