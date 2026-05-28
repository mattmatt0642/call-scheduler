# Call Scheduler Examples

## Input Format

The `input.json` file is a POST body for the `/generate` endpoint.

### Key fields

| Field | Type | Description |
|-------|------|-------------|
| `year` | int | Calendar year (e.g., 2026) |
| `month` | int | 0-indexed month (0=January, 7=August) |
| `doctors` | array | Doctor objects (see below) |
| `offices` | array | Office objects; at least one must have `isHospital: true` for call/surgical slots |
| `dayOffDates` | object or array | Per-doctor `{doctorId: ["YYYY-MM-DD"]}` or flat list of dates |
| `solverTimeLimitSeconds` | int | ILP solver timeout (default 120) |

### Doctor fields

| Field | Type | Default | Required | Description |
|-------|------|---------|----------|-------------|
| `id` | string | — | Yes | Unique identifier |
| `name` | string | — | Yes | Display name |
| `hospitalCallEligible` | bool | true | No | Gate for call_day/night/weekend assignments |
| `surgicalAssistEligible` | bool | true | No | Gate for surgical_am/hosp_pm assignments |
| `maxWeekdayDayCalls` | int | 1 | No | Hard cap on weekday day call assignments |
| `maxWeekdayNightCalls` | int | 1 | No | Hard cap on weekday night call assignments |
| `maxFridayNightCalls` | int | 1 | No | Hard cap on Friday night assignments |
| `maxWeekendBlocks` | int | 1 | No | Hard cap on weekend block assignments |
| `requiredSessionsPerWeek` | int | 0 | No | Weekly office session quota |
| `preferredCallDays` | array | [] | No | Weekday indices (0=Mon..6=Sun) for soft preference |
| `standingDaysOff` | array | [] | No | Weekday indices the doctor never works |
| `dayNightPreference` | string | "balanced" | No | "day", "night", or "balanced" |
| `amPmPreference` | string | "balanced" | No | "am", "pm", or "balanced" |
| `postCallPreference` | string | "no_preference" | No | "work" or "no_preference" |
| `callShiftPreference` | string | "no_preference" | No | "double" or "no_preference" |
| `allowedOffices` | null/array | null | No | null = all offices; otherwise list of office IDs |
| `officePreferences` | array | [] | No | Ranked list of office IDs |

### Office fields

| Field | Type | Default | Required | Description |
|-------|------|---------|----------|-------------|
| `id` | string | — | Yes | Unique identifier |
| `name` | string | — | Yes | Display name |
| `isHospital` | bool | false | No | Exactly one office should be the hospital |
| `maxPerShift` | int | 1 | No | Max doctors per office shift |
| `restrictedTuesdayMax` | int | 1 | No | Max doctors on restricted Tuesdays |

## Running

### Option 1: Against a running backend

```bash
# Terminal 1: start the backend
cd backend && python app.py

# Terminal 2: run the example
python examples/run_example.py
```

### Option 2: Self-contained (auto-starts backend)

```bash
python examples/run_example.py --start-server
```

### Option 3: Run the scheduler directly (no HTTP)

```bash
cd backend && PYTHONPATH=. python -c "
from app import _build_schedule_input, _serialize_result, generate_schedule
import json

with open('../examples/input.json') as f:
    data = json.load(f)

inp = _build_schedule_input(data)
result = generate_schedule(inp)

serialized = _serialize_result(result, inp.offices)
with open('../examples/output.json', 'w') as f:
    json.dump(serialized, f, indent=2)

print(f'Status: {result.solver_status}')
print(f'Assignments: {len(result.assignments)}')
"
```

## Example Scenario

The included `input.json` models a 4-doctor, 3-office practice in August 2026:

| Doctor | Hospital Call | Surgical | Standing Days Off | Role |
|--------|:---:|:---:|---|---|
| Dr. Adams | Yes | Yes | — | Full-scope surgeon, takes any call |
| Dr. Baker | Yes | No | — | Call-only, prefers day shifts and AM sessions |
| Dr. Chen | Yes | Yes | Wed | Surgeon, prefers nights, off Wednesdays |
| Dr. Diaz | No | No | — | Office-only, no hospital call |

| Office | Hospital | Location |
|--------|:---:|---|
| Main Hospital | Yes | 100 Hospital Way |
| North Clinic | No | 250 North Ave |
| South Clinic | No | 500 South Blvd |

**Expected output:** All call_day, call_night, call_weekend, and call_weekend_sun slots filled. Office sessions distributed by quota. Dr. Diaz gets office sessions only. Dr. Chen skips Wednesday assignments.

**Known behavior:** Surgical AM/PM slots may remain unfilled if the ILP solver doesn't assign them (they're soft constraints, not hard-mandated like call slots). The greedy backfill only handles office sessions, not surgical pairs.
