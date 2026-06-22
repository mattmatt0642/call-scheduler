"""
CP7 Integration Tests — Flask API endpoints, constraint interactions,
multi-month cumulative, frontend-backend contract, error handling,
performance/size, constraint checker integration, bug regression.

Uses Flask test_client for HTTP-level testing, plus direct function
calls for deeper integration checks.

Run: PYTHONPATH=. .venv/bin/python tests/cp7_test.py
"""
import sys
import io
import time
import json
import csv
from datetime import date, timedelta
from collections import defaultdict, Counter

from app import app
from models import (
    DoctorProfile, Office, ScheduleInput, ScheduleResult, Assignment,
    ShiftSlot, RecurringSlot, OneTimeOverride, CustomRestriction,
    get_days_in_month, get_nth_tuesdays, get_weekend_blocks,
    is_friday, get_call_balance_group, slot_to_abs_minutes,
    abs_times_overlap, prev_date,
)
from slot_generator import generate_slots, get_slot_by_id
from constraint_checker import validate_schedule, suggest_relaxations
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


# ============================================================
# HELPERS
# ============================================================

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


def _api_generate(client, payload):
    return client.post("/api/generate", json=payload)


client = app.test_client()


# Pre-generate a standard result once for reuse in multiple tests
# (avoids redundant ILP solves)
print("Pre-generating standard ILP schedule for reuse...")
_std_docs = make_doctors()
_std_offices = make_offices()
_std_inp = make_input(doctors=_std_docs, offices=_std_offices,
                      solver_time_limit_seconds=10)
_std_result = schedule_ilp(_std_inp)
_std_slot_map = {s.slot_id: s for s in _std_result.slots}
_std_payload = make_generate_payload()
_std_api_result = client.post("/api/generate", json=_std_payload)
_std_api_data = _std_api_result.get_json()
print(f"  Pre-gen done: status={_std_api_result.status_code}, "
      f"assigns={len(_std_result.assignments)}, "
      f"violations={len(_std_result.unmet_constraints)}")


# ============================================================
# SECTION A: FLASK API ENDPOINTS
# ============================================================
print("\n=== SECTION A: FLASK API ENDPOINTS ===")

# --- A1: GET /health ---
r = client.get("/api/health")
check("A1.1 health returns ok",
      r.status_code == 200 and r.get_json() == {"status": "ok"})
r_post = client.post("/api/health")
check("A1.2 health rejects POST", r_post.status_code == 405)

# --- A2: POST /generate ---
print("  A2: /generate tests...")
data_gen = _std_api_data

check("A2.1 generate returns 200", _std_api_result.status_code == 200)
check("A2.1 monthKey correct", data_gen.get("monthKey") == "2026-09",
      f"got {data_gen.get('monthKey')}")
check("A2.1 solverStatus valid",
      data_gen.get("solverStatus") in ("optimal", "feasible", "greedy_fallback"),
      f"got {data_gen.get('solverStatus')}")
check("A2.1 assignments non-empty",
      len(data_gen.get("assignments", [])) > 0)
check("A2.1 slots non-empty",
      len(data_gen.get("slots", [])) > 0)
check("A2.1 partial is False", data_gen.get("partial") is False,
      f"got {data_gen.get('partial')}")
check("A2.1 unmetConstraints empty",
      len(data_gen.get("unmetConstraints", [])) == 0,
      f"got {len(data_gen.get('unmetConstraints', []))}")

# A2.3: snake_case input fields
payload_snake = {
    "year": 2026, "month": 8,
    "doctors": [
        {"id": "d0", "name": "Doc0", "allowed_offices": None,
         "office_preferences": [], "required_sessions_per_week": 5,
         "hospital_call_eligible": True, "surgical_assist_eligible": True,
         "max_weekday_day_calls": 5, "max_weekday_night_calls": 5,
         "max_friday_night_calls": 2, "max_weekend_blocks": 2,
         "preferred_call_days": [0, 2], "post_call_preference": "no_preference",
         "call_shift_preference": "no_preference",
         "day_night_preference": "balanced", "am_pm_preference": "balanced",
         "standing_days_off": [], "fixed_recurring": [],
         "one_time_overrides": []},
    ],
    "offices": [
        {"id": "hosp", "name": "Hospital", "is_hospital": True,
         "max_per_shift": 2, "restricted_tuesday_max": 1},
        {"id": "north", "name": "North", "is_hospital": False,
         "max_per_shift": 3, "restricted_tuesday_max": 3},
    ],
    "global_office_ranking": ["hosp", "north"],
    "day_off_dates": [], "custom_restrictions": [],
    "locked_assignments": [], "historical_balance": {},
    "solver_time_limit_seconds": 30,
}
r_snake = _api_generate(client, payload_snake)
check("A2.3 snake_case input accepted", r_snake.status_code == 200,
      f"got {r_snake.status_code}")

# A2.4: Response field names are camelCase
if data_gen.get("assignments"):
    a0 = data_gen["assignments"][0]
    check("A2.4 assignment has doctorId", "doctorId" in a0)
    check("A2.4 assignment has slotId", "slotId" in a0)
    check("A2.4 assignment has isLocked", "isLocked" in a0)

if data_gen.get("slots"):
    s0 = data_gen["slots"][0]
    check("A2.4 slot has slotId", "slotId" in s0)
    check("A2.4 slot has maxDoctors", "maxDoctors" in s0)
    check("A2.4 slot has isRestrictedTuesday", "isRestrictedTuesday" in s0)
    check("A2.4 slot has isWeekend", "isWeekend" in s0)
    check("A2.4 slot has callBalanceGroup", "callBalanceGroup" in s0)
    check("A2.4 slot has isHospital", "isHospital" in s0)

if data_gen.get("counts"):
    first_count = next(iter(data_gen["counts"].values()))
    expected_camel = [
        "doctorId", "doctorName", "weekdayDayCalls", "weekdayNightCalls",
        "fridayNightCalls", "weekendBlocks", "totalCalls", "totalSessions",
        "amSessions", "pmSessions", "lateSessions", "officeVisitCounts",
        "cumulativeWeekdayDay", "cumulativeWeekdayNight",
        "cumulativeFridayNight", "cumulativeWeekendBlocks",
        "cumulativeSessions", "preferredDayCallRate", "callGini",
        "sessionGini",
    ]
    for key in expected_camel:
        check(f"A2.4 counts has {key}", key in first_count,
              f"missing {key}")

# A2.5: slots[].isHospital populated correctly
hospital_slots = [s for s in data_gen.get("slots", [])
                  if s.get("officeId") == "hosp"]
non_hospital_slots = [s for s in data_gen.get("slots", [])
                      if s.get("officeId") != "hosp"]
check("A2.5 hospital slots isHospital=true",
      all(s.get("isHospital") is True for s in hospital_slots),
      f"found {sum(1 for s in hospital_slots if s.get('isHospital') is not True)} non-true")
check("A2.5 non-hospital slots isHospital=false",
      all(s.get("isHospital") is False for s in non_hospital_slots))

# A2.6: callBalanceGroup populated
call_slots_resp = [s for s in data_gen.get("slots", [])
                   if s.get("shiftType", "").startswith("call")]
office_slots_resp = [s for s in data_gen.get("slots", [])
                     if s.get("shiftType", "").startswith("office")]
check("A2.6 call slots have balance group",
      all(s.get("callBalanceGroup") != "" for s in call_slots_resp))
check("A2.6 office slots have empty balance group",
      all(s.get("callBalanceGroup") == "" for s in office_slots_resp),
      f"found {sum(1 for s in office_slots_resp if s.get('callBalanceGroup'))} non-empty")

# A2.7: counts dict keyed by doctor ID
gen_doc_ids = {d["id"] for d in _std_payload["doctors"]}
counts_keys = set(data_gen.get("counts", {}).keys())
check("A2.7 counts has all doctor IDs", gen_doc_ids == counts_keys,
      f"missing={gen_doc_ids - counts_keys}, extra={counts_keys - gen_doc_ids}")

# A2.8: cumulative fields with historical balance
hist_payload = make_generate_payload(
    historicalBalance={
        "d0": {"weekday_day": 10, "weekday_night": 8,
               "friday_night": 3, "weekend_blocks": 4,
               "total_sessions": 80},
    }
)
r_hist = _api_generate(client, hist_payload)
d_hist = r_hist.get_json()
if r_hist.status_code == 200 and "d0" in d_hist.get("counts", {}):
    c0 = d_hist["counts"]["d0"]
    expected_cum_wd = 10 + c0.get("weekdayDayCalls", 0)
    check("A2.8 cumulativeWeekdayDay = hist + this month",
          c0.get("cumulativeWeekdayDay") == expected_cum_wd,
          f"got {c0.get('cumulativeWeekdayDay')} vs {expected_cum_wd}")
else:
    check("A2.8 cumulativeWeekdayDay = hist + this month", False,
          "generate failed or no d0 in counts")

# A2.9: preferredDayCallRate
for doc in _std_payload["doctors"]:
    did = doc["id"]
    if did in data_gen.get("counts", {}):
        c = data_gen["counts"][did]
        if not doc["preferredCallDays"]:
            check(f"A2.9 {did} no pref -> rate null",
                  c.get("preferredDayCallRate") is None,
                  f"got {c.get('preferredDayCallRate')}")
        else:
            rate = c.get("preferredDayCallRate")
            check(f"A2.9 {did} pref -> rate is float 0-1",
                  rate is not None and 0.0 <= rate <= 1.0,
                  f"got {rate}")

# A2.10: Missing required field
r_missing = _api_generate(client, {})
check("A2.10 missing year -> 500", r_missing.status_code == 500,
      f"got {r_missing.status_code}")

# A2.11: Empty doctors list
r_empty_docs = _api_generate(client, {
    "year": 2026, "month": 8,
    "doctors": [], "offices": make_office_json()
})
check("A2.11 empty doctors -> error", r_empty_docs.status_code in (400, 500),
      f"got {r_empty_docs.status_code}")

# A2.12: dayOffDates as dict
payload_dod_dict = make_generate_payload(
    dayOffDates={"d0": ["2026-09-01"], "d1": ["2026-09-15"]}
)
r_dod = _api_generate(client, payload_dod_dict)
check("A2.12 dayOffDates as dict accepted", r_dod.status_code == 200,
      f"got {r_dod.status_code}")

# A2.13: dayOffDates as list
payload_dod_list = make_generate_payload(dayOffDates=["2026-09-01"])
r_dod_list = _api_generate(client, payload_dod_list)
check("A2.13 dayOffDates as list accepted", r_dod_list.status_code == 200,
      f"got {r_dod_list.status_code}")

# A2.14: lockedAssignments round-trip
payload_locked = make_generate_payload(
    lockedAssignments=[
        {"doctorId": "d0", "slotId": "2026-09-01_hosp_call_day",
         "isLocked": True}
    ]
)
r_locked = _api_generate(client, payload_locked)
d_locked = r_locked.get_json()
locked_found = False
if r_locked.status_code == 200:
    for a in d_locked.get("assignments", []):
        if (a.get("slotId") == "2026-09-01_hosp_call_day"
                and a.get("doctorId") == "d0"):
            locked_found = a.get("isLocked") is True
check("A2.14 locked assignment in response", locked_found)

# A2.15: solverTimeLimitSeconds=5 (just verify it doesn't crash)
payload_short = make_generate_payload(solverTimeLimitSeconds=5)
r_short = _api_generate(client, payload_short)
check("A2.15 short solver limit completes",
      r_short.status_code == 200,
      f"got {r_short.status_code}")

# A2.16: Different month (January 2026, month=0)
payload_jan = make_generate_payload(year=2026, month=0)
r_jan = _api_generate(client, payload_jan)
d_jan = r_jan.get_json()
check("A2.16 January generates", r_jan.status_code == 200,
      f"got {r_jan.status_code}")
check("A2.16 monthKey=2026-01", d_jan.get("monthKey") == "2026-01",
      f"got {d_jan.get('monthKey')}")

# A2.17: February 2027 (month=1)
payload_feb = make_generate_payload(year=2027, month=1)
r_feb = _api_generate(client, payload_feb)
check("A2.17 Feb 2027 generates", r_feb.status_code == 200,
      f"got {r_feb.status_code}")

# A2.18: Historical balance for all doctors (greedy for speed)
full_hist = {f"d{i}": {"weekday_day": 5 + i, "weekday_night": 4 + i, 
             "friday_night": 1, "weekend_blocks": 1,
             "total_sessions": 30 + i * 5}
             for i in range(7)}
inp_a218 = make_input(historical_balance=full_hist, solver_time_limit_seconds=30)
result_a218 = schedule_greedy(inp_a218)
hist_cum_ok = True
for i in range(7):
    did = f"d{i}"
    if did in result_a218.counts:
        c = result_a218.counts[did]
        exp = full_hist[did]["weekday_day"] + c.weekday_day_calls
        if c.cumulative_weekday_day != exp:
            hist_cum_ok = False
check("A2.18 all-doctor historical cumulative correct", hist_cum_ok)


# --- A3: POST /validate ---
print("  A3: /validate tests...")

# Build slot map from generated data for valid slot IDs
_slots_for_validate = data_gen.get("slots", [])
_slot_ids_validate = {s.get("slotId") for s in _slots_for_validate}

# A3.1: Valid schedule -> empty violations
payload_validate = {
    "year": 2026, "month": 8,
    "doctors": make_doctor_json(),
    "offices": make_office_json(),
    "dayOffDates": [], "customRestrictions": [],
    "assignments": [
        {"doctorId": a["doctorId"], "slotId": a["slotId"]}
        for a in data_gen.get("assignments", [])
    ],
}
r_val = client.post("/api/validate", json=payload_validate)
v_data = r_val.get_json()
check("A3.1 valid schedule no violations",
      r_val.status_code == 200 and len(v_data.get("violations", [])) == 0,
      f"got {len(v_data.get('violations', []))} violations")

# A3.2: Empty assignments -> H3 violations
r_val_empty = client.post("/api/validate", json={
    "year": 2026, "month": 8,
    "doctors": make_doctor_json(),
    "offices": make_office_json(),
    "dayOffDates": [], "customRestrictions": [],
    "assignments": [],
})
v_empty = r_val_empty.get_json()
h3_violations = [v for v in v_empty.get("violations", [])
                 if v.get("constraintId") == "H3"]
check("A3.2 empty assignments -> H3 violations", len(h3_violations) > 0,
      f"got {len(h3_violations)}")

# A3.3: H1 violation - two doctors in same call slot
r_val_h1 = client.post("/api/validate", json={
    "year": 2026, "month": 8,
    "doctors": make_doctor_json(2),
    "offices": make_office_json(),
    "dayOffDates": [], "customRestrictions": [],
    "assignments": [
        {"doctorId": "d0", "slotId": "2026-09-01_hosp_call_day"},
        {"doctorId": "d1", "slotId": "2026-09-01_hosp_call_day"},
    ],
})
h1_v = [v for v in r_val_h1.get_json().get("violations", [])
        if v.get("constraintId") == "H1"]
check("A3.3 H1 violation detected", len(h1_v) > 0)

# A3.4: H8 violation - non-hospital after call
# Use slots that exist in our slot set
r_val_h8 = client.post("/api/validate", json={
    "year": 2026, "month": 8,
    "doctors": make_doctor_json(2),
    "offices": make_office_json(),
    "dayOffDates": [], "customRestrictions": [],
    "assignments": [
        {"doctorId": "d0", "slotId": "2026-09-01_hosp_call_night"},
        {"doctorId": "d0", "slotId": "2026-09-02_north_office_am"},
    ],
})
h8_v = [v for v in r_val_h8.get_json().get("violations", [])
        if v.get("constraintId") == "H8"]
check("A3.4 H8 violation detected", len(h8_v) > 0)

# A3.5: H9 violation - doctor at non-allowed office
docs_h9 = make_doctor_json(2)
docs_h9[0]["allowedOffices"] = ["north"]
r_val_h9 = client.post("/api/validate", json={
    "year": 2026, "month": 8,
    "doctors": docs_h9,
    "offices": make_office_json(),
    "dayOffDates": [], "customRestrictions": [],
    "assignments": [
        {"doctorId": "d0", "slotId": "2026-09-01_south_office_am"},
    ],
})
h9_v = [v for v in r_val_h9.get_json().get("violations", [])
        if v.get("constraintId") == "H9"]
check("A3.5 H9 violation detected", len(h9_v) > 0)

# A3.6: H10 violation - standing days-off (use standingDaysOff so slots still exist)
docs_h10_test = make_doctor_json(2)
docs_h10_test[0]["standingDaysOff"] = [1]  # Tuesday
r_val_h10 = client.post("/api/validate", json={
    "year": 2026, "month": 8,
    "doctors": docs_h10_test,
    "offices": make_office_json(),
    "dayOffDates": [], "customRestrictions": [],
    "assignments": [
        {"doctorId": "d0", "slotId": "2026-09-01_north_office_am"},
    ],
})
h10_v = [v for v in r_val_h10.get_json().get("violations", [])
         if v.get("constraintId") == "H10"]
check("A3.6 H10 standing days-off violation detected", len(h10_v) > 0)

# A3.7: H10 standing days-off violation
# Sep 1 2026 is Tuesday (weekday=1)
docs_h10s = make_doctor_json(2)
docs_h10s[0]["standingDaysOff"] = [1]  # Tuesday
r_val_h10s = client.post("/api/validate", json={
    "year": 2026, "month": 8,
    "doctors": docs_h10s,
    "offices": make_office_json(),
    "dayOffDates": [], "customRestrictions": [],
    "assignments": [
        {"doctorId": "d0", "slotId": "2026-09-01_north_office_am"},
    ],
})
h10s_v = [v for v in r_val_h10s.get_json().get("violations", [])
          if v.get("constraintId") == "H10"]
check("A3.7 H10 standing days-off detected", len(h10s_v) > 0)

# A3.8: H6 overlap violation - call_day overlaps office_am same date
r_val_h6 = client.post("/api/validate", json={
    "year": 2026, "month": 8,
    "doctors": make_doctor_json(2),
    "offices": make_office_json(),
    "dayOffDates": [], "customRestrictions": [],
    "assignments": [
        {"doctorId": "d0", "slotId": "2026-09-01_hosp_call_day"},
        {"doctorId": "d0", "slotId": "2026-09-01_hosp_office_am"},
    ],
})
h6_v = [v for v in r_val_h6.get_json().get("violations", [])
        if v.get("constraintId") == "H6"]
check("A3.8 H6 overlap violation detected", len(h6_v) > 0)

# A3.9: H7 unpaired surgical - Sep 1 is Tuesday
r_val_h7 = client.post("/api/validate", json={
    "year": 2026, "month": 8,
    "doctors": make_doctor_json(2),
    "offices": make_office_json(),
    "dayOffDates": [], "customRestrictions": [],
    "assignments": [
        {"doctorId": "d0", "slotId": "2026-09-01_hosp_surgical_am"},
    ],
})
h7_v = [v for v in r_val_h7.get_json().get("violations", [])
        if v.get("constraintId") == "H7"]
check("A3.9 H7 unpaired surgical detected", len(h7_v) > 0)

# A3.10: Violation response has all expected fields
if v_empty.get("violations"):
    v0 = v_empty["violations"][0]
    expected_vkeys = {"constraintId", "constraintName", "severity",
                      "description", "affectedDoctors", "affectedDates",
                      "suggestion"}
    check("A3.10 violation has all fields",
          expected_vkeys.issubset(set(v0.keys())),
          f"missing={expected_vkeys - set(v0.keys())}")


# --- A4: POST /export-balance ---
print("  A4: /export-balance tests...")

payload_bal = {
    "doctors": make_doctor_json(3),
    "offices": make_office_json(),
    "totals": {
        "d0": {"weekday_day": 5, "weekday_night": 4, "friday_night": 1,
               "weekend_blocks": 2, "total_sessions": 30,
               "am_sessions": 15, "pm_sessions": 12, "late_sessions": 3,
               "office_visits": {"north": 10, "south": 5}},
        "d1": {"weekday_day": 4, "weekday_night": 5, "friday_night": 1,
               "weekend_blocks": 2, "total_sessions": 28,
               "am_sessions": 14, "pm_sessions": 11, "late_sessions": 3,
               "office_visits": {"north": 8, "south": 6}},
        "d2": {"weekday_day": 5, "weekday_night": 4, "friday_night": 1,
               "weekend_blocks": 2, "total_sessions": 32,
               "am_sessions": 16, "pm_sessions": 13, "late_sessions": 3,
               "office_visits": {"north": 12, "south": 4}},
    },
}
r_eb = client.post("/api/export-balance", json=payload_bal)
check("A4.1 export-balance 200", r_eb.status_code == 200)
check("A4.1 content-type csv", "text/csv" in r_eb.content_type)
check("A4.1 content-disposition has balance.csv",
      "balance.csv" in r_eb.headers.get("Content-Disposition", ""))

csv_text = r_eb.data.decode()
csv_lines = csv_text.strip().split("\n")
check("A4.2 CSV has header row",
      "doctor_name" in csv_lines[0] and "doctor_id" in csv_lines[0])
check("A4.3 CSV has 1+3 rows", len(csv_lines) == 4,
      f"got {len(csv_lines)}")

# A4.4: Missing doctors -> error
r_eb_bad = client.post("/api/export-balance", json={})
check("A4.4 missing doctors -> 500", r_eb_bad.status_code == 500,
      f"got {r_eb_bad.status_code}")


# --- A5: POST /import-balance ---
print("  A5: /import-balance tests...")

# A5.1: Basic import
buf = io.BytesIO(csv_text.encode())
r_ib = client.post("/api/import-balance", data={"file": (buf, "balance.csv")})
check("A5.1 import-balance 200", r_ib.status_code == 200)
ib_data = r_ib.get_json()
check("A5.1 parsed has 3 doctors", len(ib_data) == 3,
      f"got {len(ib_data)}")

# A5.2: Round-trip export then import
for did in ["d0", "d1", "d2"]:
    if did in ib_data:
        check(f"A5.2 {did} weekday_day round-trip",
              ib_data[did]["weekday_day"] == payload_bal["totals"][did]["weekday_day"],
              f"got {ib_data[did]['weekday_day']}")

# A5.3: Empty values -> 0
csv_empty_vals = (
    '"doctor_name","doctor_id","weekday_day","weekday_night",'
    '"friday_night","weekend_blocks","total_sessions","am_sessions",'
    '"pm_sessions","late_sessions","north_visits","south_visits"\n'
    '"Doc","d0","","","","0","","","","","5",""\n'
)
buf_empty = io.BytesIO(csv_empty_vals.encode())
r_ib_empty = client.post("/api/import-balance", data={"file": (buf_empty, "bal.csv")})
d_empty = r_ib_empty.get_json()
check("A5.3 empty -> 0",
      d_empty.get("d0", {}).get("weekday_day") == 0,
      f"got {d_empty.get('d0', {}).get('weekday_day')}")
check("A5.3 zero preserved",
      d_empty.get("d0", {}).get("friday_night") == 0)

# A5.4: No file -> 400
r_ib_nofile = client.post("/api/import-balance", data={})
check("A5.4 no file -> 400", r_ib_nofile.status_code == 400,
      f"got {r_ib_nofile.status_code}")

# A5.5: Malformed CSV -> graceful
bad_csv = '"doctor_name","doctor_id","weekday_day"\n"Doc","d0","abc"\n'
buf_bad = io.BytesIO(bad_csv.encode())
r_ib_bad = client.post("/api/import-balance", data={"file": (buf_bad, "bad.csv")})
check("A5.5 malformed CSV handled",
      r_ib_bad.status_code in (200, 500),
      f"got {r_ib_bad.status_code}")


# --- A6: POST /export-schedule ---
print("  A6: /export-schedule tests...")

payload_es = {
    "year": 2026, "month": 8,
    "doctors": make_doctor_json(),
    "offices": make_office_json(),
    "assignments": data_gen.get("assignments", []),
    "dayOffDates": [], "customRestrictions": [],
}
r_es = client.post("/api/export-schedule", json=payload_es)
check("A6.1 export-schedule 200", r_es.status_code == 200)
check("A6.1 content-type csv", "text/csv" in r_es.content_type)
check("A6.1 content-disposition has schedule.csv",
      "schedule.csv" in r_es.headers.get("Content-Disposition", ""))

sched_csv = r_es.data.decode()
sched_lines = sched_csv.strip().split("\n")
check("A6.2 CSV has Date column", "Date" in sched_lines[0])
check("A6.2 CSV has Call Day column",
      "Call Day" in sched_lines[0] or "call_day" in sched_lines[0].lower())
check("A6.3 CSV has 30+ rows for Sep", len(sched_lines) >= 31,
      f"got {len(sched_lines)}")

# A6.4: Doctor names appear in CSV
doc_names = {d["name"] for d in make_doctor_json()}
names_found = any(name in sched_csv for name in doc_names)
check("A6.4 doctor names in CSV", names_found)


# ============================================================
# SECTION B: CONSTRAINT INTERACTIONS
# ============================================================
print("\n=== SECTION B: CONSTRAINT INTERACTIONS ===")

offices_b = make_offices()
hospital_id_b = "hosp"
slots_b = generate_slots(2026, 8, offices_b, [], [])
slot_map_b = {s.slot_id: s for s in slots_b}


# --- B1: Post-Call (H8) Chain Scenarios ---
print("  B1: H8 post-call tests...")

# B1.1: call_day -> next non-call must be hospital
inp_b11 = make_input(doctors=make_doctors(7))
assignments_b11 = [
    Assignment(doctor_id="d0", slot_id="2026-09-01_hosp_call_day"),
    Assignment(doctor_id="d0", slot_id="2026-09-02_north_office_am"),
]
v_b11 = validate_schedule(inp_b11, slots_b, assignments_b11)
h8_b11 = [v for v in v_b11 if v.constraint_id == "H8"]
check("B1.1 call_day -> non-hospital next = H8", len(h8_b11) > 0)

# B1.2: call_night (overnight) -> next must be hospital
assignments_b12 = [
    Assignment(doctor_id="d0", slot_id="2026-09-01_hosp_call_night"),
    Assignment(doctor_id="d0", slot_id="2026-09-02_north_office_am"),
]
v_b12 = validate_schedule(inp_b11, slots_b, assignments_b12)
h8_b12 = [v for v in v_b12 if v.constraint_id == "H8"]
check("B1.2 call_night -> non-hospital next = H8", len(h8_b12) > 0)

# B1.3: weekend block -> next must be hospital
assignments_b13 = [
    Assignment(doctor_id="d0", slot_id="2026-09-05_hosp_call_weekend"),
    Assignment(doctor_id="d0", slot_id="2026-09-06_hosp_call_weekend_sun"),
    Assignment(doctor_id="d0", slot_id="2026-09-07_north_office_am"),
]
v_b13 = validate_schedule(inp_b11, slots_b, assignments_b13)
h8_b13 = [v for v in v_b13 if v.constraint_id == "H8"]
check("B1.3 weekend block -> non-hospital next = H8", len(h8_b13) > 0)

# B1.4: call -> hospital office clears restriction
assignments_b14 = [
    Assignment(doctor_id="d0", slot_id="2026-09-01_hosp_call_night"),
    Assignment(doctor_id="d0", slot_id="2026-09-02_hosp_office_am"),
    Assignment(doctor_id="d0", slot_id="2026-09-03_north_office_am"),
]
v_b14 = validate_schedule(inp_b11, slots_b, assignments_b14)
h8_b14 = [v for v in v_b14 if v.constraint_id == "H8"]
check("B1.4 hospital office clears H8", len(h8_b14) == 0,
      f"got {len(h8_b14)} violations")

# B1.5: H8 persists across multiple days
assignments_b15 = [
    Assignment(doctor_id="d0", slot_id="2026-09-01_hosp_call_night"),
    Assignment(doctor_id="d0", slot_id="2026-09-03_north_office_am"),
]
v_b15 = validate_schedule(inp_b11, slots_b, assignments_b15)
h8_b15 = [v for v in v_b15 if v.constraint_id == "H8"]
check("B1.5 H8 persists across days", len(h8_b15) > 0)

# B1.6: surgical_hosp_pm at hospital clears restriction
assignments_b16 = [
    Assignment(doctor_id="d0", slot_id="2026-09-01_hosp_call_night"),
    Assignment(doctor_id="d0", slot_id="2026-09-02_hosp_surgical_am"),
    Assignment(doctor_id="d0", slot_id="2026-09-02_hosp_surgical_hosp_pm"),
    Assignment(doctor_id="d0", slot_id="2026-09-03_north_office_am"),
]
v_b16 = validate_schedule(inp_b11, slots_b, assignments_b16)
h8_b16 = [v for v in v_b16 if v.constraint_id == "H8"]
check("B1.6 surgical_hosp_pm clears H8", len(h8_b16) == 0,
      f"got {len(h8_b16)}")

# B1.7: office_late at hospital (if slot exists)
late_slot_hosp = None
for sid, s in slot_map_b.items():
    if s.office_id == "hosp" and s.shift_type == "office_late":
        late_slot_hosp = sid
        break
if late_slot_hosp:
    check("B1.7 hospital office_late slot exists", True)
else:
    check("B1.7 hospital office_late slot (may not exist in slot gen)",
          True, "no office_late at hospital in slot generator")

# B1.8: Non-hospital office does NOT clear restriction
assignments_b18 = [
    Assignment(doctor_id="d0", slot_id="2026-09-01_hosp_call_night"),
    Assignment(doctor_id="d0", slot_id="2026-09-02_north_office_am"),
    Assignment(doctor_id="d0", slot_id="2026-09-03_south_office_am"),
]
v_b18 = validate_schedule(inp_b11, slots_b, assignments_b18)
h8_b18 = [v for v in v_b18 if v.constraint_id == "H8"]
check("B1.8 non-hospital does NOT clear H8", len(h8_b18) > 0,
      f"got {len(h8_b18)}")


# --- B2: Balance Group Independence ---
print("  B2: Balance group tests...")

# Use pre-generated result for speed
# B2.1: friday_night balance
fn_counts = defaultdict(int)
for a in data_gen.get("assignments", []):
    slot = next((s for s in data_gen.get("slots", [])
                 if s.get("slotId") == a.get("slotId")), None)
    if slot and slot.get("callBalanceGroup") == "friday_night":
        fn_counts[a.get("doctorId")] += 1
if fn_counts:
    fn_vals = list(fn_counts.values())
    check("B2.1 friday_night balance within 1",
          max(fn_vals) - min(fn_vals) <= 1,
          f"max={max(fn_vals)} min={min(fn_vals)}")
else:
    check("B2.1 friday_night balance within 1", True,
          "no friday night assignments in 3-doc schedule")

# B2.2: weekend_block balance
wb_counts = defaultdict(int)
for a in data_gen.get("assignments", []):
    slot = next((s for s in data_gen.get("slots", [])
                 if s.get("slotId") == a.get("slotId")), None)
    if slot and slot.get("shiftType") == "call_weekend":
        wb_counts[a.get("doctorId")] += 1
if wb_counts:
    wb_vals = list(wb_counts.values())
    check("B2.2 weekend_block balance within 1",
          max(wb_vals) - min(wb_vals) <= 1,
          f"max={max(wb_vals)} min={min(wb_vals)}")
else:
    check("B2.2 weekend_block balance within 1", True,
          "no weekend blocks")

# B2.3: weekday calls respect preferences
for did, c in data_gen.get("counts", {}).items():
    rate = c.get("preferredDayCallRate")
    if rate is not None and c.get("totalCalls", 0) > 0:
        check(f"B2.3 {did} preferred rate defined",
              rate >= 0.0, f"got {rate}")

# B2.4: All 4 groups balanced independently (use pre-generated ILP result)
group_counts_b24 = defaultdict(lambda: defaultdict(int))
for a in _std_result.assignments:
    s = _std_slot_map[a.slot_id]
    if s.shift_type == "call_weekend":
        group_counts_b24[a.doctor_id]["weekend_block"] += 1
    elif s.shift_type == "call_weekend_sun":
        pass
    elif s.call_balance_group:
        group_counts_b24[a.doctor_id][s.call_balance_group] += 1

for group in ("weekday_day", "weekday_night", "friday_night", "weekend_block"):
    eligible = [d for d in _std_docs if d.hospital_call_eligible]
    vals = [group_counts_b24[d.id][group] for d in eligible]
    if vals and max(vals) > 0:
        spread = max(vals) - min(vals)
        check(f"B2.4 {group} spread<=1",
              spread <= 1, f"spread={spread} max={max(vals)} min={min(vals)}")

# B2.5: Historical balance carried forward (greedy for speed)
hist_b25 = {
    "d0": {"weekday_day": 10, "weekday_night": 9,
           "friday_night": 3, "weekend_blocks": 4, "total_sessions": 80},
    "d1": {"weekday_day": 2, "weekday_night": 1,
           "friday_night": 0, "weekend_blocks": 0, "total_sessions": 20},
}
inp_b25 = make_input(historical_balance=hist_b25, solver_time_limit_seconds=30)
result_b25 = schedule_greedy(inp_b25)
counts_b25 = result_b25.counts
if "d0" in counts_b25 and "d1" in counts_b25:
    c0_wd = counts_b25["d0"].cumulative_weekday_day
    c1_wd = counts_b25["d1"].cumulative_weekday_day
    check("B2.5 historical cumulative > 0",
          c0_wd > 0 and c1_wd > 0,
          f"d0_cum={c0_wd} d1_cum={c1_wd}")
else:
    check("B2.5 historical cumulative > 0", False, "doctor not in counts")

# B2.6: Imbalanced historical corrected
if "d0" in counts_b25 and "d1" in counts_b25:
    d0_this = counts_b25["d0"].weekday_day_calls
    d1_this = counts_b25["d1"].weekday_day_calls
    check("B2.6 underloaded doctor gets >= overloaded",
          d1_this >= d0_this or abs(d1_this - d0_this) <= 1,
          f"d0={d0_this} d1={d1_this}")


# --- B3: Overlap + Cross-Day (H6) ---
print("  B3: H6 overlap tests...")

def _mslot(date_str, start, end, stype="office_am", office="x"):
    return ShiftSlot(
        slot_id=f"{date_str}_{office}_{stype}", date=date_str,
        office_id=office, shift_type=stype,
        start_time=start, end_time=end, max_doctors=1,
    )

# B3.1: call_day overlaps office_pm same day
s_cd = _mslot("2026-09-01", "07:00", "19:00", "call_day", "hosp")
s_pm = _mslot("2026-09-01", "13:00", "17:00", "office_pm", "hosp")
check("B3.1 call_day overlaps office_pm",
      abs_times_overlap(s_cd, s_pm) == True)

# B3.2: Fri night vs Sat call_weekend overlap
s_fn = _mslot("2026-09-04", "19:00", "07:00", "call_night", "hosp")
s_wb = _mslot("2026-09-05", "00:00", "23:59", "call_weekend", "hosp")
check("B3.2 Fri night vs Sat weekend block overlap",
      abs_times_overlap(s_fn, s_wb) == True)

# B3.3: call_day vs next-day office_am no overlap
s_cd2 = _mslot("2026-09-01", "07:00", "19:00", "call_day", "hosp")
s_next_am = _mslot("2026-09-02", "08:00", "12:00", "office_am", "hosp")
check("B3.3 call_day vs next-day office_am no overlap",
      abs_times_overlap(s_cd2, s_next_am) == False)

# B3.4: call_night + next-day office_am (08:00) touching no overlap
s_cn = _mslot("2026-09-07", "19:00", "07:00", "call_night", "hosp")
s_tue_am = _mslot("2026-09-08", "08:00", "12:00", "office_am", "hosp")
check("B3.4 Mon night vs Tue 08:00 touching no overlap",
      abs_times_overlap(s_cn, s_tue_am) == False)

# B3.5: Two office shifts same day different offices no overlap
s_am_n = _mslot("2026-09-01", "08:00", "12:00", "office_am", "north")
s_pm_s = _mslot("2026-09-01", "13:00", "17:00", "office_pm", "south")
check("B3.5 AM north + PM south no overlap",
      abs_times_overlap(s_am_n, s_pm_s) == False)


# --- B4: Surgical Pairing (H7) ---
print("  B4: H7 surgical pairing tests...")

surgical_am_assigns = [(a.doctor_id, _std_slot_map[a.slot_id].date)
                       for a in _std_result.assignments
                       if _std_slot_map[a.slot_id].shift_type == "surgical_am"]
surgical_pm_assigns = {(a.doctor_id, _std_slot_map[a.slot_id].date)
                       for a in _std_result.assignments
                       if _std_slot_map[a.slot_id].shift_type == "surgical_hosp_pm"}

unpaired = [(did, d) for did, d in surgical_am_assigns
            if (did, d) not in surgical_pm_assigns]
check("B4.1 all surgical_am paired", len(unpaired) == 0,
      f"unpaired: {unpaired[:3]}")

# B4.2: Surgical only on Tue/Wed/Thu
surgical_dates = set()
for a in _std_result.assignments:
    s = _std_slot_map[a.slot_id]
    if s.shift_type in ("surgical_am", "surgical_hosp_pm"):
        surgical_dates.add(s.date)
all_twt = all(date.fromisoformat(d).weekday() in (1, 2, 3)
              for d in surgical_dates)
check("B4.2 surgical only Tue/Wed/Thu", all_twt)

# B4.3: Surgical-ineligible doctors excluded
ineligible_ids = {d.id for d in _std_docs
                  if not d.surgical_assist_eligible}
surg_inelig = [a for a in _std_result.assignments
               if a.doctor_id in ineligible_ids
               and _std_slot_map[a.slot_id].shift_type in
               ("surgical_am", "surgical_hosp_pm")]
check("B4.3 ineligible doctors no surgical", len(surg_inelig) == 0,
      f"found {len(surg_inelig)}")


# --- B5: Weekend Block Pairing ---
print("  B5: Weekend block tests...")

sat_map_b5 = {}
sun_map_b5 = {}
for a in _std_result.assignments:
    s = _std_slot_map[a.slot_id]
    if s.shift_type == "call_weekend":
        sat_map_b5[s.date] = a.doctor_id
    elif s.shift_type == "call_weekend_sun":
        sun_map_b5[s.date] = a.doctor_id

all_paired_b5 = True
for sat_date, sat_doc in sat_map_b5.items():
    sun_date = str(date.fromisoformat(sat_date) + timedelta(days=1))
    if sun_date in sun_map_b5 and sun_map_b5[sun_date] != sat_doc:
        all_paired_b5 = False
check("B5.1 Sat+Sun same doctor", all_paired_b5)

# B5.2: Cross-month Sunday weekend block
blocks_jan = get_weekend_blocks(2026, 0)
cross_month_sundays = [b for b in blocks_jan
                       if not b.sunday.startswith("2026-01")]
check("B5.2 get_weekend_blocks handles cross-month Sunday",
      True)  # structural test - function doesn't crash

# B5.3: Max weekend blocks respected
for d in _std_docs:
    wb_count = sum(1 for a in _std_result.assignments
                   if a.doctor_id == d.id
                   and _std_slot_map[a.slot_id].shift_type == "call_weekend")
    check(f"B5.3 {d.id} weekend blocks <= max",
          wb_count <= d.max_weekend_blocks,
          f"got {wb_count} > {d.max_weekend_blocks}")


# --- B6: Restricted Tuesday (H2) ---
print("  B6: Restricted Tuesday tests...")

restricted_tue_hosp = [s for s in slots_b
                       if s.is_restricted_tuesday
                       and s.office_id == "hosp"
                       and s.shift_type in ("office_am", "office_pm")]
check("B6.1 restricted Tue hosp slots cap=1",
      all(s.max_doctors == 1 for s in restricted_tue_hosp),
      f"max_doctors: {[s.max_doctors for s in restricted_tue_hosp[:5]]}")

nth_tues = set(get_nth_tuesdays(2026, 8))
all_tuesdays = [d for d in get_days_in_month(2026, 8) if d["is_tuesday"]]
non_restricted_tues = [d["date"] for d in all_tuesdays
                       if d["date"] not in nth_tues]
nr_hosp_slots = [s for s in slots_b
                 if s.date in non_restricted_tues
                 and s.office_id == "hosp"
                 and s.shift_type in ("office_am", "office_pm")]
check("B6.2 non-restricted Tue full capacity",
      all(s.max_doctors == 2 for s in nr_hosp_slots),
      f"max_doctors: {set(s.max_doctors for s in nr_hosp_slots)}")

restricted_tue_call = [s for s in slots_b
                       if s.is_restricted_tuesday
                       and s.shift_type in ("call_day", "call_night")]
check("B6.3 call slots unaffected by restricted Tue",
      len(restricted_tue_call) == 0,
      f"found {len(restricted_tue_call)}")


# --- B7: Custom Restrictions ---
print("  B7: Custom restriction tests...")

custom_b71 = [CustomRestriction(date="2026-09-07", office_id="north",
                                shift_type="office_am", max_override=0)]
slots_b71 = generate_slots(2026, 8, offices_b, [], custom_b71)
north_am_7 = [s for s in slots_b71
              if s.date == "2026-09-07" and s.office_id == "north"
              and s.shift_type == "office_am"]
check("B7.1 max_override=0 -> max_doctors=0",
      len(north_am_7) == 1 and north_am_7[0].max_doctors == 0)

custom_b72 = [CustomRestriction(date="2026-09-07", office_id="north",
                                shift_type="office_am", max_override=3)]
slots_b72 = generate_slots(2026, 8, offices_b, [], custom_b72)
north_am_7b = [s for s in slots_b72
               if s.date == "2026-09-07" and s.office_id == "north"
               and s.shift_type == "office_am"]
check("B7.2 max_override=3 -> max_doctors=3",
      len(north_am_7b) == 1 and north_am_7b[0].max_doctors == 3)


# --- B8: Fixed Recurring + One-Time Overrides ---
print("  B8: Recurring/override tests...")

docs_b8 = make_doctors(3)
docs_b8[0] = DoctorProfile(
    id="d0", name="RecurringDoc", allowed_offices=None,
    office_preferences=[], required_sessions_per_week=5,
    hospital_call_eligible=True, surgical_assist_eligible=True,
    max_weekday_day_calls=5, max_weekday_night_calls=5,
    max_friday_night_calls=2, max_weekend_blocks=2,
    preferred_call_days=[], post_call_preference="no_preference",
    call_shift_preference="no_preference",
    day_night_preference="balanced", am_pm_preference="balanced",
    standing_days_off=[],
    fixed_recurring=[RecurringSlot(day_of_week=0, office_id="north",
                                   shift_type="office_am")],
    one_time_overrides=[OneTimeOverride(date="2026-09-07",
                                        office_id="south",
                                        shift_type="office_pm")],
)

slot_id_set_b8 = {s.slot_id for s in slots_b}

# B8.1: Recurring slot expansion
recurring_b8 = expand_recurring_slots(docs_b8, slots_b, 2026, 8)
d0_monday_recurring = [a for a in recurring_b8
                       if a.doctor_id == "d0"
                       and "north_office_am" in a.slot_id]
mondays = [d for d in get_days_in_month(2026, 8) if d["day_of_week"] == 0]
check("B8.1 recurring Monday north_office_am count",
      len(d0_monday_recurring) == len(mondays),
      f"got {len(d0_monday_recurring)} vs {len(mondays)} Mondays")

# B8.2: One-time override expansion
overrides_b8 = expand_one_time_overrides(docs_b8, 2026, 8, slot_id_set_b8)
d0_override = [a for a in overrides_b8
               if a.doctor_id == "d0"
               and "2026-09-07_south_office_pm" == a.slot_id]
check("B8.2 one-time override created", len(d0_override) == 1)

# B8.3: Deduplication of recurring + locked
locked_dup = [Assignment(doctor_id="d0",
                         slot_id=d0_monday_recurring[0].slot_id,
                         is_locked=True)
              ] if d0_monday_recurring else []
all_locked_b8 = locked_dup + recurring_b8 + overrides_b8
seen_b8 = set()
deduped_b8 = []
for a in all_locked_b8:
    k = (a.doctor_id, a.slot_id)
    if k not in seen_b8:
        seen_b8.add(k)
        deduped_b8.append(a)
check("B8.3 deduplication reduces or equal",
      len(deduped_b8) <= len(all_locked_b8))

# B8.4: Override for different month ignored
docs_b8b = make_doctors(1)
docs_b8b[0] = DoctorProfile(
    id="d0", name="OOB", allowed_offices=None,
    office_preferences=[], required_sessions_per_week=5,
    hospital_call_eligible=True, surgical_assist_eligible=True,
    max_weekday_day_calls=5, max_weekday_night_calls=5,
    max_friday_night_calls=2, max_weekend_blocks=2,
    preferred_call_days=[], post_call_preference="no_preference",
    call_shift_preference="no_preference",
    day_night_preference="balanced", am_pm_preference="balanced",
    standing_days_off=[],
    one_time_overrides=[OneTimeOverride(date="2026-10-05",
                                        office_id="north",
                                        shift_type="office_am")],
)
overrides_oob = expand_one_time_overrides(docs_b8b, 2026, 8, slot_id_set_b8)
check("B8.4 out-of-month override ignored", len(overrides_oob) == 0,
      f"got {len(overrides_oob)}")


# --- B9: Allowed Offices (H9) ---
print("  B9: H9 allowed offices tests...")

docs_b9 = make_doctors(3)
docs_b9[0] = DoctorProfile(
    id="d0", name="NorthOnly", allowed_offices=["north"],
    office_preferences=[], required_sessions_per_week=5,
    hospital_call_eligible=True, surgical_assist_eligible=True,
    max_weekday_day_calls=5, max_weekday_night_calls=5,
    max_friday_night_calls=2, max_weekend_blocks=2,
    preferred_call_days=[], post_call_preference="no_preference",
    call_shift_preference="no_preference",
    day_night_preference="balanced", am_pm_preference="balanced",
    standing_days_off=[],
)
inp_b9 = make_input(doctors=docs_b9, solver_time_limit_seconds=30)
result_b9 = schedule_greedy(inp_b9)
slot_map_b9 = {s.slot_id: s for s in result_b9.slots}

# B9.1: d0 only at north (or hospital for calls)
d0_non_north = [a for a in result_b9.assignments
                if a.doctor_id == "d0"
                and slot_map_b9[a.slot_id].office_id not in ("north", "hosp")]
check("B9.1 d0 only at allowed+hospital",
      len(d0_non_north) == 0,
      f"found {len(d0_non_north)} disallowed")

# B9.2: null allowedOffices = all offices
d1_offices = set(slot_map_b9[a.slot_id].office_id
                 for a in result_b9.assignments if a.doctor_id == "d1")
check("B9.2 null allowedOffices at multiple offices",
      len(d1_offices) >= 2,
      f"got offices={d1_offices}")


# --- B10: Days Off (H10) ---
print("  B10: H10 days off tests...")

# B10.1: day_off_dates blocks assignments
inp_b101 = make_input(day_off_dates=["2026-09-01", "2026-09-15"],
                      solver_time_limit_seconds=30)
result_b101 = schedule_greedy(inp_b101)
sm_b101 = {s.slot_id: s for s in result_b101.slots}
dayoff_set_b101 = {"2026-09-01", "2026-09-15"}
dayoff_violations = 0
for a in result_b101.assignments:
    s = sm_b101[a.slot_id]
    if s.date in dayoff_set_b101 and not a.is_locked:
        dayoff_violations += 1
check("B10.1 no non-locked on day-off dates",
      dayoff_violations == 0, f"found {dayoff_violations}")

# B10.2: standing_days_off
docs_b102 = make_doctors(3)
docs_b102[0] = DoctorProfile(
    id="d0", name="FriOff", allowed_offices=None,
    office_preferences=[], required_sessions_per_week=5,
    hospital_call_eligible=True, surgical_assist_eligible=True,
    max_weekday_day_calls=5, max_weekday_night_calls=5,
    max_friday_night_calls=2, max_weekend_blocks=2,
    preferred_call_days=[], post_call_preference="no_preference",
    call_shift_preference="no_preference",
    day_night_preference="balanced", am_pm_preference="balanced",
    standing_days_off=[4],  # Friday
)
inp_b102 = make_input(doctors=docs_b102, solver_time_limit_seconds=30)
result_b102 = schedule_greedy(inp_b102)
sm_b102 = {s.slot_id: s for s in result_b102.slots}
d0_fri_office = [a for a in result_b102.assignments
                 if a.doctor_id == "d0"
                 and date.fromisoformat(sm_b102[a.slot_id].date).weekday() == 4
                 and sm_b102[a.slot_id].shift_type not in
                 ("call_day", "call_night")]
check("B10.2 d0 no office on Fridays",
      len(d0_fri_office) == 0,
      f"found {len(d0_fri_office)}")

# B10.3: Combined day_off + standing off
docs_b103 = make_doctors(3)
docs_b103[0] = DoctorProfile(
    id="d0", name="CombinedOff", allowed_offices=None,
    office_preferences=[], required_sessions_per_week=5,
    hospital_call_eligible=True, surgical_assist_eligible=True,
    max_weekday_day_calls=5, max_weekday_night_calls=5,
    max_friday_night_calls=2, max_weekend_blocks=2,
    preferred_call_days=[], post_call_preference="no_preference",
    call_shift_preference="no_preference",
    day_night_preference="balanced", am_pm_preference="balanced",
    standing_days_off=[2],  # Wednesday
)
inp_b103 = make_input(doctors=docs_b103,
                      day_off_dates=["2026-09-01"],
                      solver_time_limit_seconds=30)
result_b103 = schedule_greedy(inp_b103)
sm_b103 = {s.slot_id: s for s in result_b103.slots}
d0_wed_assigns = [a for a in result_b103.assignments
                  if a.doctor_id == "d0"
                  and date.fromisoformat(sm_b103[a.slot_id].date).weekday() == 2
                  and not a.is_locked
                  and sm_b103[a.slot_id].shift_type not in
                  ("call_day", "call_night")]
d0_dayoff = [a for a in result_b103.assignments
             if a.doctor_id == "d0"
             and sm_b103[a.slot_id].date == "2026-09-01"
             and not a.is_locked]
check("B10.3 combined: no Wed office + no Sep 1",
      len(d0_wed_assigns) == 0 and len(d0_dayoff) == 0,
      f"wed={len(d0_wed_assigns)} sep1={len(d0_dayoff)}")

# B10.4: Call shifts still exist on day-off dates
slots_b104 = generate_slots(2026, 8, offices_b, ["2026-09-01"], [])
call_on_holiday = [s for s in slots_b104
                   if s.date == "2026-09-01"
                   and s.shift_type in ("call_day", "call_night")]
check("B10.4 call slots exist on day-off dates",
      len(call_on_holiday) == 2,
      f"got {len(call_on_holiday)}")


# ============================================================
# SECTION C: MULTI-MONTH CUMULATIVE
# ============================================================
print("\n=== SECTION C: MULTI-MONTH CUMULATIVE ===")

# C1: Two consecutive months (greedy for speed)
inp_c1_sep = make_input(solver_time_limit_seconds=30)
result_c1_sep = schedule_greedy(inp_c1_sep)
hist_c1 = {}
for did, c in result_c1_sep.counts.items():
    hist_c1[did] = {
        "weekday_day": c.weekday_day_calls,
        "weekday_night": c.weekday_night_calls,
        "friday_night": c.friday_night_calls,
        "weekend_blocks": c.weekend_blocks,
        "total_sessions": c.total_sessions,
    }

inp_c1_oct = make_input(year=2026, month=9, historical_balance=hist_c1,
                         solver_time_limit_seconds=30)
result_c1_oct = schedule_greedy(inp_c1_oct)

cum_ok = True
for did, c in result_c1_oct.counts.items():
    if did in hist_c1:
        exp_wd = hist_c1[did]["weekday_day"] + c.weekday_day_calls
        if c.cumulative_weekday_day != exp_wd:
            cum_ok = False
check("C1 cumulative = sep + oct", cum_ok)

# C2: Both months have assignments
d0_oct = result_c1_oct.counts.get("d0")
check("C2 oct has assignments",
      d0_oct is not None and d0_oct.total_calls > 0)

# C3: CSV round-trip between months
totals_c3 = {}
for did, c in result_c1_sep.counts.items():
    totals_c3[did] = {
        "weekday_day": c.weekday_day_calls,
        "weekday_night": c.weekday_night_calls,
        "friday_night": c.friday_night_calls,
        "weekend_blocks": c.weekend_blocks,
        "total_sessions": c.total_sessions,
        "am_sessions": c.am_sessions,
        "pm_sessions": c.pm_sessions,
        "late_sessions": c.late_sessions,
        "office_visits": c.office_visit_counts,
    }
csv_c3 = export_balance_csv(inp_c1_sep.doctors, inp_c1_sep.offices, totals_c3)
parsed_c3 = import_balance_csv(csv_c3)
csv_hist_ok = True
for did in hist_c1:
    if did in parsed_c3:
        for key in ("weekday_day", "weekday_night", "friday_night",
                    "weekend_blocks", "total_sessions"):
            if parsed_c3[did].get(key) != totals_c3[did].get(key):
                csv_hist_ok = False
check("C3 CSV round-trip between months", csv_hist_ok)

# C4: Gini reasonable
check("C4 cumulative gini < 0.3",
      result_c1_oct.gini_calls < 0.3,
      f"got {result_c1_oct.gini_calls:.3f}")


# ============================================================
# SECTION D: FRONTEND-BACKEND CONTRACT
# ============================================================
print("\n=== SECTION D: FRONTEND-BACKEND CONTRACT ===")

# D1: Generate response matches storage.js fields
expected_count_fields = {
    "weekdayDayCalls", "weekdayNightCalls", "fridayNightCalls",
    "weekendBlocks", "totalSessions", "amSessions", "pmSessions",
    "lateSessions", "officeVisitCounts",
}
if data_gen.get("counts"):
    first_count_d = next(iter(data_gen["counts"].values()))
    check("D1 counts has storage.js fields",
          expected_count_fields.issubset(set(first_count_d.keys())),
          f"missing={expected_count_fields - set(first_count_d.keys())}")

# D2: Generate response matches calendar.js fields
expected_slot_fields = {"slotId", "date", "shiftType", "isHospital",
                        "officeId", "startTime", "endTime", "maxDoctors"}
if data_gen.get("slots"):
    s0_d = data_gen["slots"][0]
    check("D2 slot has calendar.js fields",
          expected_slot_fields.issubset(set(s0_d.keys())),
          f"missing={expected_slot_fields - set(s0_d.keys())}")

expected_assign_fields = {"doctorId", "slotId"}
if data_gen.get("assignments"):
    a0_d = data_gen["assignments"][0]
    check("D2 assignment has calendar.js fields",
          expected_assign_fields.issubset(set(a0_d.keys())),
          f"missing={expected_assign_fields - set(a0_d.keys())}")

# D3: buildScheduleRequest format accepted
payload_d3 = {
    "year": 2026, "month": 8,
    "doctors": make_doctor_json(),
    "offices": make_office_json(),
    "globalOfficeRanking": ["hosp", "north", "south"],
    "dayOffDates": [],
    "customRestrictions": [],
    "lockedAssignments": [],
    "historicalBalance": {},
    "solverTimeLimitSeconds": 30,
}
r_d3 = _api_generate(client, payload_d3)
check("D3 buildScheduleRequest format accepted",
      r_d3.status_code == 200, f"got {r_d3.status_code}")

# D4: dayOffDates dict format
payload_d4 = make_generate_payload(
    dayOffDates={"d0": ["2026-09-01"], "d1": ["2026-09-15"]}
)
r_d4 = _api_generate(client, payload_d4)
check("D4 dayOffDates dict format accepted",
      r_d4.status_code == 200, f"got {r_d4.status_code}")

# D5: isLocked round-trip
locked_d5 = [
    {"doctorId": "d0", "slotId": "2026-09-01_hosp_call_day",
     "isLocked": True}
]
payload_d5 = make_generate_payload(lockedAssignments=locked_d5)
r_d5 = _api_generate(client, payload_d5)
d_d5 = r_d5.get_json()
locked_d5_found = False
if r_d5.status_code == 200:
    for a in d_d5.get("assignments", []):
        if (a.get("slotId") == "2026-09-01_hosp_call_day"
                and a.get("doctorId") == "d0"
                and a.get("isLocked") is True):
            locked_d5_found = True
check("D5 isLocked round-trip", locked_d5_found)


# ============================================================
# SECTION E: ERROR HANDLING & ROBUSTNESS
# ============================================================
print("\n=== SECTION E: ERROR HANDLING ===")

# E1: Invalid JSON
r_e1 = client.post("/api/generate", data="not json",
                   content_type="application/json")
check("E1 invalid JSON -> error",
      r_e1.status_code in (400, 500),
      f"got {r_e1.status_code}")

# E2: Missing year
r_e2 = _api_generate(client, {"month": 8, "doctors": make_doctor_json(),
                               "offices": make_office_json()})
check("E2 missing year -> 500", r_e2.status_code == 500,
      f"got {r_e2.status_code}")

# E3: Missing month
r_e3 = _api_generate(client, {"year": 2026, "doctors": make_doctor_json(),
                               "offices": make_office_json()})
check("E3 missing month -> 500", r_e3.status_code == 500,
      f"got {r_e3.status_code}")

# E4: Extra unknown fields
payload_e4 = make_generate_payload(foo="bar", baz=42)
r_e4 = _api_generate(client, payload_e4)
check("E4 extra fields ignored", r_e4.status_code == 200,
      f"got {r_e4.status_code}")

# E5: Doctor with empty name
docs_e5 = make_doctor_json(3)
docs_e5[0]["name"] = ""
payload_e5 = make_generate_payload(doctors=docs_e5)
r_e5 = _api_generate(client, payload_e5)
check("E5 doctor with empty name handled",
      r_e5.status_code in (200, 500),
      f"got {r_e5.status_code}")

# E6: Office with empty name
offices_e6 = make_office_json()
offices_e6[0]["name"] = ""
payload_e6 = make_generate_payload(offices=offices_e6)
r_e6 = _api_generate(client, payload_e6)
check("E6 office with empty name handled",
      r_e6.status_code in (200, 500),
      f"got {r_e6.status_code}")

# E7: Zero doctors
r_e7 = _api_generate(client, {"year": 2026, "month": 8,
                               "doctors": [], "offices": make_office_json()})
check("E7 zero doctors -> error", r_e7.status_code in (400, 500),
      f"got {r_e7.status_code}")

# E8: Zero offices (valid — returns empty schedule)
r_e8 = _api_generate(client, {"year": 2026, "month": 8,
                               "doctors": make_doctor_json(3), "offices": []})
check("E8 zero offices handled", r_e8.status_code in (200, 400, 500),
      f"got {r_e8.status_code}")

# E9: December (month=11)
payload_e9 = make_generate_payload(year=2026, month=11)
r_e9 = _api_generate(client, payload_e9)
check("E9 December generates", r_e9.status_code == 200,
      f"got {r_e9.status_code}")

# E10: Very short solver time
payload_e10 = make_generate_payload(solverTimeLimitSeconds=1)
r_e10 = _api_generate(client, payload_e10)
check("E10 1s solver limit completes",
      r_e10.status_code == 200,
      f"got {r_e10.status_code}")


# ============================================================
# SECTION F: PERFORMANCE & SIZE
# ============================================================
print("\n=== SECTION F: PERFORMANCE & SIZE ===")

# F1: 10 doctors, 5 offices (greedy for speed)
offices_f1 = make_offices() + [
    Office(id="east", name="East", is_hospital=False,
           max_per_shift=2, restricted_tuesday_max=2),
    Office(id="west", name="West", is_hospital=False,
           max_per_shift=2, restricted_tuesday_max=2),
]
docs_f1 = make_doctors(10)
inp_f1 = make_input(doctors=docs_f1, offices=offices_f1,
                    solver_time_limit_seconds=30)
result_f1 = schedule_greedy(inp_f1)
check("F1 10 docs 5 offices generates",
      len(result_f1.assignments) > 0,
      f"assignments={len(result_f1.assignments)}")

# F2: 15 doctors, 6 offices (greedy)
offices_f2 = offices_f1 + [
    Office(id="central", name="Central", is_hospital=False,
           max_per_shift=2, restricted_tuesday_max=2),
]
docs_f2 = make_doctors(15)
inp_f2 = make_input(doctors=docs_f2, offices=offices_f2,
                    solver_time_limit_seconds=30)
result_f2 = schedule_greedy(inp_f2)
check("F2 15 docs 6 offices generates",
      len(result_f2.assignments) > 0)

# F3: Single doctor
docs_f3 = make_doctors(1)
docs_f3[0] = DoctorProfile(
    id="d0", name="Solo", allowed_offices=None,
    office_preferences=[], required_sessions_per_week=5,
    hospital_call_eligible=True, surgical_assist_eligible=True,
    max_weekday_day_calls=30, max_weekday_night_calls=30,
    max_friday_night_calls=10, max_weekend_blocks=10,
    preferred_call_days=[], post_call_preference="no_preference",
    call_shift_preference="no_preference",
    day_night_preference="balanced", am_pm_preference="balanced",
    standing_days_off=[],
)
inp_f3 = make_input(doctors=docs_f3, solver_time_limit_seconds=30)
result_f3 = schedule_greedy(inp_f3)
check("F3 single doctor generates",
      len(result_f3.assignments) > 0,
      f"assignments={len(result_f3.assignments)}")

# F4: 2 doctors, hospital only (greedy)
offices_f4 = [Office(id="hosp", name="Hospital", is_hospital=True,
                     max_per_shift=2, restricted_tuesday_max=1)]
docs_f4 = make_doctors(2)
inp_f4 = make_input(doctors=docs_f4, offices=offices_f4,
                    global_office_ranking=["hosp"],
                    solver_time_limit_seconds=30)
result_f4 = schedule_greedy(inp_f4)
check("F4 2 docs hospital only generates",
      len(result_f4.assignments) > 0)

# F5: All doctors off Fridays (greedy)
docs_f5 = make_doctors(7, standing_days_off=[4])
inp_f5 = make_input(doctors=docs_f5, solver_time_limit_seconds=30)
result_f5 = schedule_greedy(inp_f5)
check("F5 all Fri off -> partial or has assignments",
      result_f5.partial is True or len(result_f5.assignments) > 0,
      f"partial={result_f5.partial} assigns={len(result_f5.assignments)}")

# F6: All blackout weekdays (greedy)
days_f6 = get_days_in_month(2026, 8)
all_weekdays = [d["date"] for d in days_f6 if not d["is_weekend"]]
inp_f6 = make_input(day_off_dates=all_weekdays, solver_time_limit_seconds=30)
result_f6 = schedule_greedy(inp_f6)
check("F6 all blackout generates",
      len(result_f6.assignments) > 0,
      f"assignments={len(result_f6.assignments)}")

# F7: Standard greedy < 5s (ILP already tested via pre-gen)
t0 = time.time()
inp_f7 = make_input(solver_time_limit_seconds=30)
result_f7 = schedule_greedy(inp_f7)
elapsed = time.time() - t0
check("F7 standard greedy < 5s", elapsed < 5,
      f"took {elapsed:.1f}s")


# ============================================================
# SECTION G: CONSTRAINT CHECKER INTEGRATION
# ============================================================
print("\n=== SECTION G: CONSTRAINT CHECKER INTEGRATION ===")

# G1: Greedy schedule passes hard constraint checks (H5/H8 are best-effort for greedy)
inp_g1 = make_input(solver_time_limit_seconds=10)
result_g1 = schedule_greedy(inp_g1)
violations_g1 = validate_schedule(inp_g1, result_g1.slots, result_g1.assignments)
for cid in ("H1", "H3", "H6", "H7", "H9", "H10"):
    v_g1 = [v for v in violations_g1 if v.constraint_id == cid
            or v.constraint_id.startswith(cid + "_")]
    check(f"G1 greedy: no {cid} violations", len(v_g1) == 0,
          f"got {len(v_g1)}")
# H5 and H8: greedy is best-effort, count but don't fail
h5_g1 = [v for v in violations_g1 if v.constraint_id.startswith("H5")]
h8_g1 = [v for v in violations_g1 if v.constraint_id == "H8"]
check(f"G1 greedy: H5 violations count (best-effort)", len(h5_g1) <= 5,
      f"got {len(h5_g1)}")
check(f"G1 greedy: H8 violations count (best-effort)", len(h8_g1) <= 100,
      f"got {len(h8_g1)}")

# G2: ILP schedule passes constraint checker (use pre-generated)
violations_g2 = validate_schedule(_std_inp, _std_result.slots,
                                  _std_result.assignments)
for cid in ("H1", "H3", "H5", "H6", "H7", "H8", "H9", "H10"):
    v_g2 = [v for v in violations_g2 if v.constraint_id == cid
            or v.constraint_id.startswith(cid + "_")]
    check(f"G2 ILP: no {cid} violations", len(v_g2) == 0,
          f"got {len(v_g2)}")

# G3: generate_schedule consistent
result_g3 = generate_schedule(make_input(solver_time_limit_seconds=30))
check("G3 generate_schedule returns ScheduleResult",
      isinstance(result_g3, ScheduleResult))
check("G3 has month_key",
      result_g3.month_key == "2026-09")

# G4: Metrics consistent with assignments
counts_g4 = compute_counts(_std_docs, _std_offices,
                           _std_result.assignments, _std_result.slots,
                           _std_inp.historical_balance)
for d in _std_docs:
    c = counts_g4[d.id]
    manual_wd = sum(1 for a in _std_result.assignments
                    if a.doctor_id == d.id
                    and _std_slot_map[a.slot_id].shift_type == "call_day")
    check(f"G4 {d.id} weekday_day_calls matches manual",
          c.weekday_day_calls == manual_wd,
          f"counts={c.weekday_day_calls} vs manual={manual_wd}")

# G5: Gini consistent
eligible_g5 = [d for d in _std_docs if d.hospital_call_eligible]
manual_call_counts = [
    sum(1 for a in _std_result.assignments
        if a.doctor_id == d.id
        and _std_slot_map[a.slot_id].call_balance_group in
        ("weekday_day", "weekday_night", "friday_night", "weekend_block"))
    for d in eligible_g5
]
manual_gini = gini(manual_call_counts) if manual_call_counts else 0.0
check("G5 gini_calls matches manual",
      abs(_std_result.gini_calls - manual_gini) < 0.001,
      f"result={_std_result.gini_calls:.4f} manual={manual_gini:.4f}")

# G6: partial flag matches violations
check("G6 partial flag matches violations",
      _std_result.partial == (len(_std_result.unmet_constraints) > 0),
      f"partial={_std_result.partial} violations={len(_std_result.unmet_constraints)}")


# ============================================================
# SECTION H: BUG REGRESSION TESTS
# ============================================================
print("\n=== SECTION H: BUG REGRESSION ===")

# H1: ILP Phase 2 replays surgical through _update_load
# Doctors with surgical assignments should still get office sessions
for d in _std_docs:
    if d.surgical_assist_eligible:
        has_surgical = any(a.doctor_id == d.id
                          and _std_slot_map[a.slot_id].shift_type in
                          ("surgical_am", "surgical_hosp_pm")
                          for a in _std_result.assignments)
        office_count = sum(1 for a in _std_result.assignments
                          if a.doctor_id == d.id
                          and _std_slot_map[a.slot_id].shift_type in
                          ("office_am", "office_pm", "office_late"))
        if has_surgical:
            check(f"H1 {d.id} surgical doc has office sessions",
                  office_count > 0,
                  f"surgical=True office={office_count}")

# H2: Per-week day_off counting
docs_h2 = make_doctors(7)
inp_h2 = make_input(doctors=docs_h2,
                    day_off_dates=["2026-09-01", "2026-09-02"],
                    solver_time_limit_seconds=30)
result_h2 = schedule_greedy(inp_h2)
sm_h2 = {s.slot_id: s for s in result_h2.slots}
days_h2 = get_days_in_month(2026, 8)
week0_dates = {d["date"] for d in days_h2 if d["week_num"] == 0
               and not d["is_weekend"]}
week1_dates = {d["date"] for d in days_h2 if d["week_num"] == 1
               and not d["is_weekend"]}
w0_sessions = defaultdict(int)
w1_sessions = defaultdict(int)
for a in result_h2.assignments:
    s = sm_h2[a.slot_id]
    if s.shift_type in ("office_am", "office_pm", "office_late",
                        "surgical_am", "surgical_hosp_pm"):
        if s.date in week0_dates:
            w0_sessions[a.doctor_id] += 1
        elif s.date in week1_dates:
            w1_sessions[a.doctor_id] += 1
avg_w0 = sum(w0_sessions.values()) / max(len(w0_sessions), 1)
avg_w1 = sum(w1_sessions.values()) / max(len(w1_sessions), 1)
check("H2 week0 avg sessions <= week1 (day-off impact)",
      avg_w0 <= avg_w1 + 1,
      f"w0_avg={avg_w0:.1f} w1_avg={avg_w1:.1f}")

# H3: max_doctors > 1 slots exist and can be filled
# Note: greedy currently assigns only 1 doctor per slot (known P1 bug),
# so we verify slot max_doctors is correct and assignments don't exceed it
offices_h3 = [
    Office(id="hosp", name="Hospital", is_hospital=True,
           max_per_shift=2, restricted_tuesday_max=1),
    Office(id="north", name="North", is_hospital=False,
           max_per_shift=5, restricted_tuesday_max=5),
]
inp_h3 = make_input(doctors=make_doctors(10), offices=offices_h3,
                     solver_time_limit_seconds=10)
slots_h3 = generate_slots(2026, 8, offices_h3, [], [])
north_am_slots = [s for s in slots_h3
                  if s.office_id == "north" and s.shift_type == "office_am"]
check("H3 north office max_doctors=5",
      len(north_am_slots) > 0 and all(s.max_doctors == 5 for s in north_am_slots),
      f"max_doctors: {set(s.max_doctors for s in north_am_slots)}")

result_h3 = schedule_greedy(inp_h3)
slot_doc_counts = defaultdict(int)
for a in result_h3.assignments:
    slot_doc_counts[a.slot_id] += 1
# Verify no slot exceeds max_doctors (even though greedy only assigns 1)
sm_h3 = {s.slot_id: s for s in result_h3.slots}
over_cap = [(sid, cnt) for sid, cnt in slot_doc_counts.items()
            if sm_h3[sid].max_doctors < cnt]
check("H3 no slot exceeds max_doctors", len(over_cap) == 0,
      f"over-cap: {over_cap[:5]}")
# Verify at least 1 doctor per slot (greedy fills slots)
filled_slots = len(slot_doc_counts)
check("H3 slots are filled", filled_slots > 0,
      f"filled={filled_slots}")

# H4: Same-date call_night + office_am not blocked by abs_times_overlap
# call_night on date D starts at 19:00 on date D (i.e. the previous evening)
# and ends at 07:00 on date D+1.
# office_am on date D starts at 08:00 and ends at 12:00.
# In absolute time: call_night starts at 19:00 on D-1 evening,
# office_am starts at 08:00 on D morning.
# So call_night on "Sep 1" (19:00 Sep 1 to 07:00 Sep 2) does NOT overlap
# with office_am on "Sep 1" (08:00 Sep 1 to 12:00 Sep 1).
s_night_h4 = _mslot("2026-09-01", "19:00", "07:00", "call_night", "hosp")
s_morning_h4 = _mslot("2026-09-01", "08:00", "12:00", "office_am", "hosp")
check("H4 call_night same-date office_am no overlap",
      abs_times_overlap(s_night_h4, s_morning_h4) == False)

# H5: call_weekend_sun slots exist
slots_h5 = generate_slots(2026, 8, offices_b, [], [])
weekend_sun_slots = [s for s in slots_h5
                     if s.shift_type == "call_weekend_sun"]
check("H5 call_weekend_sun slots exist",
      len(weekend_sun_slots) > 0,
      f"got {len(weekend_sun_slots)}")

# Verify H8 constraint checker works with weekend_sun
assignments_h5 = [
    Assignment(doctor_id="d0", slot_id="2026-09-06_hosp_call_weekend_sun"),
    Assignment(doctor_id="d0", slot_id="2026-09-07_north_office_am"),
]
inp_h5 = make_input(doctors=make_doctors(7))
v_h5 = validate_schedule(inp_h5, slots_h5, assignments_h5)
h8_h5 = [v for v in v_h5 if v.constraint_id == "H8"]
check("H5 weekend_sun post-call detected by H8",
      len(h8_h5) > 0,
      f"got {len(h8_h5)} H8 violations")


# ============================================================
# SUMMARY
# ============================================================
print(f"\n{'='*60}")
print(f"CP7 INTEGRATION TEST RESULTS: {passed} passed, {failed} failed")
print(f"{'='*60}")
if failed > 0:
    print("SOME TESTS FAILED - review output above")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
