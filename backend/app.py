from flask import Flask, request, jsonify, Response, send_from_directory, make_response
import traceback, os, secrets, hashlib

from models import (DoctorProfile, Office, ScheduleInput, ScheduleResult,
                    RecurringSlot, OneTimeOverride, CustomRestriction,
                    Assignment, ShiftSlot)
from scheduler import generate_schedule
from constraint_checker import validate_schedule
from metrics import compute_counts
from csv_io import export_balance_csv, import_balance_csv, export_schedule_csv
from database import init_db, load_state, save_state

app = Flask(__name__, static_folder=None)
app.secret_key = secrets.token_hex(32)

init_db()

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend')
SECRET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.secret')


# ---------------------------------------------------------------------------
# Shared secret auth
# ---------------------------------------------------------------------------

def _load_or_create_secret():
    if os.path.isfile(SECRET_FILE):
        with open(SECRET_FILE, 'r') as f:
            return f.read().strip()
    secret = secrets.token_urlsafe(24)
    with open(SECRET_FILE, 'w') as f:
        f.write(secret + '\n')
    os.chmod(SECRET_FILE, 0o600)
    print(f"[auth] Generated new shared secret in {SECRET_FILE}")
    return secret

_SHARED_SECRET = _load_or_create_secret()


def _check_auth_cookie():
    val = request.cookies.get('auth_token', '')
    return val == hashlib.sha256(_SHARED_SECRET.encode()).hexdigest()


def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if _check_auth_cookie():
            return f(*args, **kwargs)
        return jsonify({"error": "Unauthorized"}), 401
    return decorated


# ---------------------------------------------------------------------------
# Frontend static file serving
# ---------------------------------------------------------------------------

@app.route('/')
def serve_index():
    resp = make_response(send_from_directory(FRONTEND_DIR, 'index.html'))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp

@app.route('/<path:path>')
def serve_static(path):
    filepath = os.path.join(FRONTEND_DIR, path)
    if os.path.isfile(filepath):
        resp = make_response(send_from_directory(FRONTEND_DIR, path))
    else:
        resp = make_response(send_from_directory(FRONTEND_DIR, 'index.html'))
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_recurring(raw):
    return RecurringSlot(
        day_of_week=raw.get("dayOfWeek", raw.get("day_of_week", 0)),
        office_id=raw.get("officeId", raw.get("office_id", "")),
        shift_type=raw.get("shiftType", raw.get("shift_type", "")),
        notes=raw.get("notes", "")
    )


def _parse_override(raw):
    return OneTimeOverride(
        date=raw["date"],
        office_id=raw.get("officeId", raw.get("office_id", "")),
        shift_type=raw.get("shiftType", raw.get("shift_type", "")),
        notes=raw.get("notes", "")
    )


def _parse_custom_restriction(raw):
    return CustomRestriction(
        date=raw["date"],
        office_id=raw.get("officeId", raw.get("office_id", "")),
        shift_type=raw.get("shiftType", raw.get("shift_type", "")),
        max_override=raw.get("maxOverride", raw.get("max_override", 0)),
        note=raw.get("note", "")
    )


def _parse_doctor(d: dict) -> DoctorProfile:
    return DoctorProfile(
        id=d["id"],
        name=d["name"],
        allowed_offices=d.get("allowedOffices") or d.get("allowed_offices"),
        office_preferences=d.get("officePreferences", d.get("office_preferences", [])),
        required_sessions_per_week=d.get("requiredSessionsPerWeek", d.get("required_sessions_per_week", 5)),
        hospital_call_eligible=d.get("hospitalCallEligible", d.get("hospital_call_eligible", True)),
        surgical_assist_eligible=d.get("surgicalAssistEligible", d.get("surgical_assist_eligible", True)),
        weekend_call_off=d.get("weekendCallOff", d.get("weekend_call_off", False)),
        max_weekday_day_calls=d.get("maxWeekdayDayCalls", d.get("max_weekday_day_calls", 5)),
        max_weekday_night_calls=d.get("maxWeekdayNightCalls", d.get("max_weekday_night_calls", 5)),
        max_friday_night_calls=d.get("maxFridayNightCalls", d.get("max_friday_night_calls", 2)),
        max_weekend_blocks=d.get("maxWeekendBlocks", d.get("max_weekend_blocks", 2)),
        preferred_call_days=d.get("preferredCallDays", d.get("preferred_call_days", [])),
        post_call_preference=d.get("postCallPreference", d.get("post_call_preference", "no_preference")),
        call_shift_preference=d.get("callShiftPreference", d.get("call_shift_preference", "no_preference")),
        day_night_preference=d.get("dayNightPreference", d.get("day_night_preference", "balanced")),
        am_pm_preference=d.get("amPmPreference", d.get("am_pm_preference", "balanced")),
        standing_days_off=d.get("standingDaysOff", d.get("standing_days_off", [])),
        fixed_recurring=[_parse_recurring(r) for r in d.get("fixedRecurring", d.get("fixed_recurring", []))],
        one_time_overrides=[_parse_override(o) for o in d.get("oneTimeOverrides", d.get("one_time_overrides", []))]
    )


def _parse_office(o: dict) -> Office:
    return Office(
        id=o["id"],
        name=o["name"],
        is_hospital=o.get("isHospital", o.get("is_hospital", False)),
        max_per_shift=o.get("maxPerShift", o.get("max_per_shift", 2)),
        restricted_tuesday_max=o.get("restrictedTuesdayMax", o.get("restricted_tuesday_max", 1)),
        location_address=o.get("locationAddress", o.get("location_address", ""))
    )


def _serialize_result(result: ScheduleResult, offices: list = None) -> dict:
    hospital_ids = {o.id for o in offices if o.is_hospital} if offices else set()
    return {
        "monthKey": result.month_key,
        "assignments": [
            {"doctorId": a.doctor_id, "slotId": a.slot_id, "isLocked": a.is_locked}
            for a in result.assignments
        ],
        "slots": [
            {
                "slotId": s.slot_id,
                "date": s.date,
                "officeId": s.office_id,
                "shiftType": s.shift_type,
                "startTime": s.start_time,
                "endTime": s.end_time,
                "maxDoctors": s.max_doctors,
                "isRestrictedTuesday": s.is_restricted_tuesday,
                "isWeekend": s.is_weekend,
                "isHospital": s.office_id in hospital_ids,
                "callBalanceGroup": s.call_balance_group
            }
            for s in result.slots
        ],
        "solverStatus": result.solver_status,
        "giniCalls": result.gini_calls,
        "giniSessions": result.gini_sessions,
        "unmetConstraints": result.unmet_constraints,
        "partial": result.partial,
        "counts": {
            doc_id: {
                "doctorId": c.doctor_id,
                "doctorName": c.doctor_name,
                "weekdayDayCalls": c.weekday_day_calls,
                "weekdayNightCalls": c.weekday_night_calls,
                "fridayNightCalls": c.friday_night_calls,
                "weekendBlocks": c.weekend_blocks,
                "totalCalls": c.total_calls,
                "totalSessions": c.total_sessions,
                "amSessions": c.am_sessions,
                "pmSessions": c.pm_sessions,
                "lateSessions": c.late_sessions,
                "officeVisitCounts": c.office_visit_counts,
                "cumulativeWeekdayDay": c.cumulative_weekday_day,
                "cumulativeWeekdayNight": c.cumulative_weekday_night,
                "cumulativeFridayNight": c.cumulative_friday_night,
                "cumulativeWeekendBlocks": c.cumulative_weekend_blocks,
                "cumulativeSessions": c.cumulative_sessions,
                "preferredDayCallRate": c.preferred_day_call_rate,
                "callGini": c.call_gini,
                "sessionGini": c.session_gini,
            }
            for doc_id, c in result.counts.items()
        }
    }


def _build_schedule_input(data: dict) -> ScheduleInput:
    if 'year' not in data or not (2020 <= data.get('year', 0) <= 2100):
        raise ValueError("year must be between 2020 and 2100")
    if 'month' not in data or not (0 <= data.get('month', -1) <= 11):
        raise ValueError("month must be between 0 (January) and 11 (December)")
    doctors_raw = data.get('doctors', [])
    if not doctors_raw or not isinstance(doctors_raw, list):
        raise ValueError("doctors must be a non-empty list")
    offices_raw = data.get('offices', [])
    if not offices_raw or not isinstance(offices_raw, list):
        raise ValueError("offices must be a non-empty list")
    for d in doctors_raw:
        if not d.get('id') or not d.get('name'):
            raise ValueError("each doctor must have 'id' and 'name'")
    for o in offices_raw:
        if not o.get('id') or not o.get('name'):
            raise ValueError("each office must have 'id' and 'name'")

    doctors = [_parse_doctor(d) for d in doctors_raw]
    offices = [_parse_office(o) for o in offices_raw]
    locked_raw = data.get("lockedAssignments", data.get("locked_assignments", []))
    locked = [Assignment(
        doctor_id=a.get("doctorId", a.get("doctor_id", "")),
        slot_id=a.get("slotId", a.get("slot_id", "")),
        is_locked=a.get("isLocked", a.get("is_locked", False))
    ) for a in locked_raw]
    custom_restrictions = [_parse_custom_restriction(r) for r in data.get("customRestrictions", data.get("custom_restrictions", []))]

    raw_day_offs = data.get("dayOffDates", data.get("day_off_dates", []))
    if isinstance(raw_day_offs, dict):
        day_off_dates = raw_day_offs
    elif isinstance(raw_day_offs, list):
        day_off_dates = raw_day_offs
    else:
        day_off_dates = []

    return ScheduleInput(
        year=data["year"],
        month=data["month"],
        doctors=doctors,
        offices=offices,
        global_office_ranking=data.get("globalOfficeRanking", data.get("global_office_ranking", [])),
        day_off_dates=day_off_dates,
        custom_restrictions=custom_restrictions,
        locked_assignments=locked,
        historical_balance=data.get("historicalBalance", data.get("historical_balance", {})),
        solver_time_limit_seconds=data.get("solverTimeLimitSeconds", data.get("solver_time_limit_seconds", 120))
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    if data.get("password") != _SHARED_SECRET:
        return jsonify({"error": "Wrong password"}), 403
    token = hashlib.sha256(_SHARED_SECRET.encode()).hexdigest()
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie('auth_token', token, httponly=True, samesite='Lax', max_age=86400 * 30)
    return resp


@app.route("/api/auth/check", methods=["GET"])
def auth_check():
    return jsonify({"authenticated": _check_auth_cookie()})


@app.route("/api/state", methods=["GET"])
@require_auth
def get_state():
    return jsonify(load_state())


@app.route("/api/state", methods=["POST"])
@require_auth
def post_state():
    data = request.get_json(force=True)
    save_state(data)
    return jsonify({"ok": True})


@app.route("/api/generate", methods=["POST"])
@require_auth
def generate():
    try:
        data = request.get_json(force=True)
        inp = _build_schedule_input(data)
        hospital_offices = [o for o in inp.offices if o.is_hospital]
        if hospital_offices and not any(d.hospital_call_eligible for d in inp.doctors):
            return jsonify({
                "error": "No doctors are hospital-call-eligible, but a hospital office exists. "
                         "Set hospitalCallEligible=true for at least one doctor."
            }), 400
        result = generate_schedule(inp)
        return jsonify(_serialize_result(result, inp.offices))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/validate", methods=["POST"])
@require_auth
def validate():
    try:
        data = request.get_json(force=True)
        inp = _build_schedule_input(data)
        from slot_generator import generate_slots
        slots = generate_slots(inp.year, inp.month, inp.offices,
                               inp.day_off_dates, inp.custom_restrictions)
        assignments = [Assignment(
            doctor_id=a["doctorId"],
            slot_id=a["slotId"],
            is_locked=a.get("isLocked", False)
        ) for a in data.get("assignments", [])]
        violations = validate_schedule(inp, slots, assignments)
        return jsonify({
            "violations": [
                {
                    "constraintId": v.constraint_id,
                    "constraintName": v.constraint_name,
                    "severity": v.severity,
                    "description": v.description,
                    "affectedDoctors": v.affected_doctors,
                    "affectedDates": v.affected_dates,
                    "suggestion": v.suggestion,
                }
                for v in violations
            ]
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/export-balance", methods=["POST"])
@require_auth
def export_balance():
    try:
        data = request.get_json(force=True)
        doctors = [_parse_doctor(d) for d in data["doctors"]]
        offices = [_parse_office(o) for o in data["offices"]]
        totals = data.get("totals", {})
        csv_str = export_balance_csv(doctors, offices, totals)
        return Response(csv_str, mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=balance.csv"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/import-balance", methods=["POST"])
@require_auth
def import_balance():
    try:
        file = request.files.get("file")
        if not file:
            return jsonify({"error": "No file provided"}), 400
        csv_content = file.read().decode("utf-8")
        parsed = import_balance_csv(csv_content)
        return jsonify(parsed)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/export-schedule", methods=["POST"])
@require_auth
def export_schedule():
    try:
        data = request.get_json(force=True)
        doctors = [_parse_doctor(d) for d in data["doctors"]]
        offices = [_parse_office(o) for o in data["offices"]]
        assignments = [Assignment(
            doctor_id=a["doctorId"],
            slot_id=a["slotId"],
            is_locked=a.get("isLocked", False)
        ) for a in data.get("assignments", [])]
        from slot_generator import generate_slots
        slots = generate_slots(
            data["year"], data["month"], offices,
            data.get("dayOffDates", data.get("day_off_dates", [])),
            [_parse_custom_restriction(r) for r in data.get("customRestrictions", data.get("custom_restrictions", []))]
        )
        csv_str = export_schedule_csv(doctors, offices, assignments, slots)
        return Response(csv_str, mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=schedule.csv"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.errorhandler(ValueError)
def handle_value_error(e):
    return jsonify({"error": str(e)}), 400

@app.errorhandler(Exception)
def handle_generic_error(e):
    traceback.print_exc()
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
