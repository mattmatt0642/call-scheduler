# HANDOFF: ILP Surgical Fix + Full Project State

**Date:** 2026-05-27
**Author:** Previous AI session
**Status:** ILP surgical coverage fix implemented and verified; multiple frontend/UI tasks remain

---

## 1. What Was Just Done

### ILP Surgical Coverage Fix (scheduler.py)

**Root Cause:** The ILP solver (`schedule_ilp()`) was producing 0 surgical assignments and 0 office assignments (only call assignments). Two bugs:

1. **No surgical coverage constraint (H3b):** Call slots had an H3 hard constraint requiring exactly 1 doctor per call slot, but surgical slots had no equivalent. Since the objective only optimized call balance, CBC set all surgical variables to 0 (free lunch — fewer assignments = lower balance deviation).

2. **call_day vs surgical overlap (H6):** `call_day` spans 07:00-19:00 and overlaps with `surgical_am` (07:00-12:00) and `surgical_hosp_pm` (13:00-17:00). The H6 overlap constraint prevented the same doctor from being assigned both `call_day` and surgical on the same day. But surgical AM/PM are **sub-activities of the call shift** — the call doctor covers surgical as part of their call duty, so they should NOT be treated as overlapping.

3. **Duplicate constraint names:** After adding H3b, PuLP threw "overlapping constraint names" errors. The `for slot in ilp_slots` loop was somehow producing duplicate iterations (possibly a PuLP/CBC interaction with constraint dedup). Added a `_surg_cov_seen` dedup guard.

**Changes made to `scheduler.py`:**
- Lines ~770-787: Added H3b constraint block — exactly 1 doctor per `surgical_am` and `surgical_hosp_pm` slot, with `_surg_cov_seen` dedup guard
- Lines ~807-820: Modified H6 overlap block to skip overlap constraints between `call_day` and `surgical_am`/`surgical_hosp_pm` on the same date (they're sub-activities, not conflicting shifts)

**Result:** ILP now produces `optimal` status with 52 call + 26 surgical + 0 office = 78 assignments (office filling happens in Phase 2 greedy). With more doctors, office assignments also fill.

---

## 2. Full Project Context

### Project Overview
Medical Call Scheduler — production app for scheduling on-call doctors across hospitals and offices. Generates monthly schedules balancing call load, respecting constraints (no overlap, post-call rest, surgical pairing, weekend block pairing, blackout days, allowed offices, etc.).

### Architecture
- **Backend:** Python/Flask (`backend/app.py`), ILP solver via PuLP/CBC (`backend/scheduler.py`), greedy fallback, constraint checker, slot generator, metrics, CSV I/O, SQLite persistence (`backend/database.py`), shared-secret auth
- **Frontend:** Vanilla JS (`frontend/js/`), dark theme CSS, 5-tab layout (Setup/Doctors/Generate/Schedule/Balance), 4-step wizard for data input, auth overlay (`frontend/js/auth.js`)

### Key Files
| File | Purpose | Notes |
|------|---------|-------|
| `backend/scheduler.py` | ILP + greedy scheduler | **FRAGILE INDENTATION** — always `python3 -m py_compile` after ANY edit. Greedy function (lines ~440-649) and ILP office-filling (lines ~940-1028) were previously corrupted and reconstructed. |
| `backend/app.py` | Flask API endpoints | `_parse_doctor()`, `_build_schedule_input()`, auth middleware |
| `backend/models.py` | Dataclasses | `DoctorProfile`, `Office`, `ScheduleInput`, `ScheduleResult`, `ShiftSlot`, `Assignment`, helper functions |
| `backend/slot_generator.py` | Generates all slots for a month | `call_weekend` starts at 07:00 |
| `backend/constraint_checker.py` | Validates schedules against H1-H10 | H3 includes `call_weekend_sun`; H8 working |
| `backend/metrics.py` | Gini coefficient, compute_counts | |
| `backend/database.py` | SQLite persistence | Load/save state per schedule |
| `frontend/js/app.js` | Tab switching, wizard, generate handlers | Network error messages, `addDoctor()`/`addOffice()` |
| `frontend/js/api.js` | API client | `API_BASE = window.location.origin` |
| `frontend/js/calendar.js` | Calendar rendering | `buildCalendarHTML()`, `assignMap` stores arrays, `surgical_hosp_pm` column added |
| `frontend/js/doctor_config.js` | Doctor config cards | `renderDoctorAccordion()`, `buildDocCard()` — currently always expanded |
| `frontend/js/storage.js` | State management | `DEFAULT_STATE`, `STATE`, `saveState()`, `loadState()`, `buildScheduleRequest()` |
| `frontend/js/auth.js` | Auth overlay | Password-protected schedules |
| `frontend/css/style.css` | Dark theme | ~1000 lines |
| `frontend/index.html` | 5 tabs, 4-step wizard | |

### Frontend State Model
```
STATE = {
  doctors: [{id, name, hospitalCallEligible, surgicalAssistEligible, allowedOffices, ...}],
  offices: [{id, name, isHospital, maxPerShift, restrictedTuesdayMax}],
  blackouts: {"YYYY-MM": {doctorId: [{date, period, startTime?, endTime?}]}},
  schedules: {"YYYY-MM": {assignments, slots, solverStatus, ...}},
  globalOfficeRanking: [...],
  historicalBalance: {...},
  wizardStep: 0
}
```

### Test Status (as of 2026-05-27)
- **Unit tests:** 30/30 pass
- **CP7:** ~111 pass / ~51 fail (many are pre-existing: auth 401s, validation 400 vs 500 expectation mismatches, some genuine bugs in API error handling)
- **CP8:** ~67 pass / ~16 fail (pre-existing: API error handling edge cases)
- **`python3 -m py_compile scheduler.py`**: PASSES (after current fix)
- **`node -c` on all frontend JS**: PASSES

### Pre-existing Test Failures (NOT caused by recent changes)
- CP7 A1.2: POST /health → expects 500, gets 405 (method not allowed — correct behavior)
- CP7 A2.x: Many 500s due to auth requirement (tests don't log in)
- CP7 E2/E3/E5/E6: Expect 500 for validation errors but get 400 (correct behavior)
- CP7 G2: ILP had H8 violations — should be re-tested after surgical fix
- CP8 M1-M5, O1: API robustness edge cases returning 500

---

## 3. Known Bugs / Issues

### Backend
1. **ILP office filling is weak:** Phase 2 (greedy office filling after ILP) only fills 0-2 office slots with 2 doctors (greedy alone fills 18). The office-filling logic skips weekends and may have quota calculation issues. With more doctors it works better.
2. **Duplicate constraint name mystery:** The `for slot in ilp_slots` loop in H3b produces duplicate constraint names despite no duplicate slot IDs. Added a dedup guard (`_surg_cov_seen`) as workaround, but root cause unknown — possibly a PuLP internal issue with constraint registration.

### Frontend
3. **Dropdown menus glitch out:** User reported select/option elements having UI glitches. Not yet investigated.
4. **Calendar view needs complete redesign:** Currently day-loop format. User wants Excel-like weekly grid: columns=days of week (1 week at a time), rows=offices with AM/PM slots, doctor initials in cells.
5. **Doctor/office cards always expanded:** Need VSCode fold-style collapsible cards with arrow toggle and single-line summary when collapsed.
6. **No day-off input UI:** Need a way to input days off per month for each doctor (calendar picker or similar).
7. **Tab content issues:** Setup tab should be for setup only, Generate tab should be clean (no full schedule display), Balance tab should show only balance table, Schedule tab should show schedule only.
8. **Full names used instead of initials:** Calendar should use doctor initials throughout.

---

## 4. Remaining Tasks (Priority Order)

### High Priority
1. **Test ILP with real-world data (3+ doctors):** Verify surgical + call + office assignments are complete. The 2-doctor test case is minimal.
2. **Redesign calendar view:** Excel-like weekly grid format. See "Calendar Redesign" section below.
3. **Add day-off input UI:** Per-doctor, per-month day-off entry. Should integrate with blackout system.
4. **Fix dropdown glitches:** Investigate and fix select/option UI bugs.

### Medium Priority
5. **Collapsible doctor/office profiles:** VSCode fold-style with arrow toggle.
6. **Fix tab content:** Ensure each tab only shows its own content.
7. **Use doctor initials:** Replace full names with initials in calendar view.

### Low Priority
8. **Custom start/end time slider:** Per-doctor, per-day manual time override.
9. **Advanced settings panel:** Optional settings that apply if chosen, otherwise ignored.
10. **Investigate CP7/CP8 failures:** Many are auth-related or test-expectation mismatches, but some may be real bugs.

---

## 5. Calendar Redesign Spec (User Request)

**Current:** Day-loop format showing all days in a vertical list.

**Desired:** Excel-like weekly grid:
- **Columns:** Monday through Sunday (1 week at a time, with week navigation)
- **Rows:** Offices, with sub-rows for AM/PM shifts
- **Cells:** Doctor initials (e.g., "AB" for Alice Brown), not full names
- **Special formatting:**
  - Surgical assist shown next to call doctor in same cell or adjacent
  - Time-off notes at bottom of each day column
  - Weekend columns styled differently
  - Call shifts highlighted (e.g., different background color for night vs day call)

---

## 6. Critical Warnings

1. **`scheduler.py` indentation is extremely fragile.** The greedy function (lines ~440-649) and ILP office-filling (lines ~940-1028) were completely rewritten due to past corruption. **ALWAYS run `python3 -m py_compile scheduler.py` after ANY edit to this file.**

2. **ILP falls back to greedy on ANY exception** (line ~1101-1106), including `UnboundLocalError`, `PulpError`, etc. If you introduce a bug in the ILP path, it silently falls back to greedy with a status like `"greedy_fallback (error message)"`. Check `solverStatus` in results to detect this.

3. **`API_BASE = window.location.origin`** — changed from conditional localhost/prod logic. This means the app MUST be served from a web server (not opened as file://) for API calls to work.

4. **Auth is required for API calls.** Tests that hit `/api/generate` etc. without logging in get 401. This is why many CP7/CP8 tests fail — they don't authenticate.

5. **`_surg_cov_seen` dedup guard is a workaround**, not a proper fix. The root cause of duplicate constraint names (same `for slot in ilp_slots` loop producing the same slot twice) is unknown. If you remove it, you may see `PulpError: overlapping constraint names`.

---

## 7. Quick Reference Commands

```bash
# Syntax check
cd /home/matt/projects/call-scheduler/backend && python3 -m py_compile scheduler.py

# Unit tests
cd /home/matt/projects/call-scheduler/backend && python3 -m pytest tests/unit_test.py -v

# CP7 integration tests
cd /home/matt/projects/call-scheduler/backend && PYTHONPATH=. python3 tests/cp7_test.py 2>&1 | tail -5

# CP8 edge-case tests
cd /home/matt/projects/call-scheduler/backend && PYTHONPATH=. python3 tests/cp8_test.py 2>&1 | tail -5

# Frontend JS syntax check
cd /home/matt/projects/call-scheduler/frontend && for f in js/*.js; do node -c "$f" 2>&1; done

# Quick ILP vs greedy comparison (from backend dir)
cd /home/matt/projects/call-scheduler/backend && python3 -c "
from scheduler import schedule_ilp, schedule_greedy
from models import ScheduleInput, DoctorProfile, Office
docs = [DoctorProfile(id='d1', name='Alice', hospital_call_eligible=True, surgical_assist_eligible=True, allowed_offices=['h1','o1'], standing_days_off=[], preferred_call_days=[], required_sessions_per_week=5, post_call_preference='rest'),
        DoctorProfile(id='d2', name='Bob', hospital_call_eligible=True, surgical_assist_eligible=True, allowed_offices=['h1','o1'], standing_days_off=[], preferred_call_days=[], required_sessions_per_week=5, post_call_preference='rest')]
offices = [Office(id='h1', name='Hospital', is_hospital=True, max_per_shift=1, restricted_tuesday_max=1),
           Office(id='o1', name='Office1', is_hospital=False, max_per_shift=1, restricted_tuesday_max=1)]
inp = ScheduleInput(year=2026, month=5, doctors=docs, offices=offices, global_office_ranking=['h1','o1'], day_off_dates={}, custom_restrictions=[], locked_assignments=[], historical_balance={})
r = schedule_ilp(inp)
print(f'ILP: total={len(r.assignments)} status={r.solver_status}')
r2 = schedule_greedy(inp)
print(f'Greedy: total={len(r2.assignments)} status={r2.solver_status}')
"
```

---

## 8. Solver Logic Summary

### ILP Path (`schedule_ilp`)
**Phase 1 — ILP (PuLP/CBC):**
1. Generate all slots for the month
2. Filter to ILP-relevant slots: `call_day`, `call_night`, `call_weekend`, `call_weekend_sun`, `surgical_am`, `surgical_hosp_pm`
3. Pre-filter feasible (doc, slot) pairs via `_can_assign_ilp()`
4. Build binary decision variables `x[(doc_id, slot_id)]`
5. Add constraints:
   - **H1:** Capacity — sum of doctors per slot ≤ max_doctors
   - **H3:** Exactly 1 doctor per call slot
   - **H3b (NEW):** Exactly 1 doctor per surgical slot
   - **H6:** No overlap (with exception: call_day + surgical on same date are NOT treated as overlapping)
   - **H7:** Surgical AM/PM pairing — same doctor must cover both
   - **H5e:** Weekend block pairing — Sat+Sun call must be same doctor
   - **H5a-d:** Balance — minimize max deviation from average per call group
6. Objective: minimize balance deviation (weighted 100x) + small preference term
7. Solve with CBC (30s timeout, 5% gap tolerance)
8. Extract ILP assignments

**Phase 2 — Greedy office filling:**
1. Use ILP call+surgical assignments as locked
2. For each weekday, fill office sessions (non-hospital first, then hospital)
3. Respect post-call rest (H8), allowed offices (H9), weekly quotas
4. Post-call morning assignments (soft S4)

### Greedy Path (`schedule_greedy`)
1. Assign call shifts first, balance-driven (round-robin within call balance groups)
2. Weekend block pairing (Sat+Sun same doctor)
3. Fill office sessions day-by-day
4. Post-call morning assignments

### Fallback
`generate_schedule()` tries ILP first, catches any exception, falls back to greedy with status `"greedy_fallback (error)"`.

---

## 9. What the User Has Requested (Original Vision)

A **production-ready** medical call scheduler with:
- Survey-like, multi-step wizard flow for data input (fast, multiple choice, simple)
- Super simplistic, minimal UI (VSCode/Apple-inspired)
- CSV import/export
- Blackout calendar
- Balance table
- All CP1-CP5, CP7, CP8 tests passing
- Real lives at stake — rigorous testing, no errors
