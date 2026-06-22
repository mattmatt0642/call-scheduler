"""
Comprehensive constraint checker tests using pytest.

Run: PYTHONPATH=backend python3 -m pytest backend/tests/test_constraints.py -v
"""
import pytest
from models import DoctorProfile, Office, ShiftSlot, Assignment, ScheduleInput
from constraint_checker import validate_schedule


@pytest.fixture
def hospital():
    return Office(id="hosp", name="Hospital", is_hospital=True,
                  max_per_shift=2, restricted_tuesday_max=1)


@pytest.fixture
def north_office():
    return Office(id="north", name="North", is_hospital=False,
                  max_per_shift=2, restricted_tuesday_max=2)


@pytest.fixture
def default_doctors():
    return [
        DoctorProfile(id="d0", name="Doctor0",
           allowed_offices=None, office_preferences=[],
           required_sessions_per_week=5,
           hospital_call_eligible=True,
           surgical_assist_eligible=True,
           max_weekday_day_calls=5, max_weekday_night_calls=5,
           max_friday_night_calls=2, max_weekend_blocks=2,
           preferred_call_days=[0, 2],
           post_call_preference="no_preference",
           call_shift_preference="no_preference",
           day_night_preference="balanced",
           am_pm_preference="balanced",
           standing_days_off=[],
           weekend_pairing_preference=True),
        DoctorProfile(id="d1", name="Doctor1",
           allowed_offices=None, office_preferences=[],
           required_sessions_per_week=5,
           hospital_call_eligible=True,
           surgical_assist_eligible=True,
           max_weekday_day_calls=5, max_weekday_night_calls=5,
           max_friday_night_calls=2, max_weekend_blocks=2,
           preferred_call_days=[1, 3],
           post_call_preference="no_preference",
           call_shift_preference="single",
           day_night_preference="balanced",
           am_pm_preference="balanced",
           standing_days_off=[],
           weekend_pairing_preference=True),
    ]


@pytest.fixture
def default_offices(hospital, north_office):
    return [hospital, north_office]


class TestH3CallCoverage:
    """H3: Each call slot must have exactly 1 doctor assigned."""

    def test_call_day_covered_no_violation(self, default_doctors, default_offices):
        """Happy path: call_day with exactly 1 doctor."""
        slots = [
            ShiftSlot(slot_id="2026-09-15_hosp_call_day",
                     date="2026-09-15", office_id="hosp", shift_type="call_day",
                     start_time="07:00", end_time="19:00", max_doctors=1,
                     call_balance_group="weekday_day"),
        ]
        assignments = [
            Assignment(doctor_id="d0", slot_id="2026-09-15_hosp_call_day"),
        ]
        inp = ScheduleInput(year=2026, month=8, doctors=default_doctors,
                           offices=default_offices, global_office_ranking=[],
                           day_off_dates=[], custom_restrictions=[],
                           locked_assignments=[], historical_balance={})
        violations = validate_schedule(inp, slots, assignments)
        h3_violations = [v for v in violations if v.constraint_id == "H3"]
        assert len(h3_violations) == 0

    def test_call_day_uncovered_violation(self, default_doctors, default_offices):
        """Sad path: call_day with 0 doctors."""
        slots = [
            ShiftSlot(slot_id="2026-09-15_hosp_call_day",
                     date="2026-09-15", office_id="hosp", shift_type="call_day",
                     start_time="07:00", end_time="19:00", max_doctors=1,
                     call_balance_group="weekday_day"),
        ]
        assignments = []
        inp = ScheduleInput(year=2026, month=8, doctors=default_doctors,
                           offices=default_offices, global_office_ranking=[],
                           day_off_dates=[], custom_restrictions=[],
                           locked_assignments=[], historical_balance={})
        violations = validate_schedule(inp, slots, assignments)
        h3_violations = [v for v in violations if v.constraint_id == "H3"]
        assert len(h3_violations) == 1
        assert "No doctor assigned to call_day" in h3_violations[0].description


class TestH10DaysOff:
    """H10: No assignment on day-off dates or standing days off."""

    def test_blocked_by_day_off(self, default_doctors, default_offices):
        """Sad path: assignment on a day-off date should fail H10."""
        slots = [
            ShiftSlot(slot_id="2026-09-15_hosp_office_am",
                     date="2026-09-15", office_id="hosp", shift_type="office_am",
                     start_time="08:00", end_time="12:00", max_doctors=2),
        ]
        assignments = [
            Assignment(doctor_id="d0", slot_id="2026-09-15_hosp_office_am"),
        ]
        inp = ScheduleInput(year=2026, month=8, doctors=default_doctors,
                           offices=default_offices, global_office_ranking=[],
                           day_off_dates=["2026-09-15"], custom_restrictions=[],
                           locked_assignments=[], historical_balance={})
        violations = validate_schedule(inp, slots, assignments)
        h10_violations = [v for v in violations if v.constraint_id == "H10"]
        assert len(h10_violations) > 0

    def test_allowed_on_standing_day_if_locked(self, default_doctors, default_offices):
        """Locked assignment on standing day off should NOT fail H10."""
        default_doctors[0].standing_days_off = [1]
        slots = [
            ShiftSlot(slot_id="2026-09-15_hosp_office_am",
                     date="2026-09-15", office_id="hosp", shift_type="office_am",
                     start_time="08:00", end_time="12:00", max_doctors=2),
        ]
        assignments = [
            Assignment(doctor_id="d0", slot_id="2026-09-15_hosp_office_am", is_locked=True),
        ]
        inp = ScheduleInput(year=2026, month=8, doctors=default_doctors,
                           offices=default_offices, global_office_ranking=[],
                           day_off_dates=[], custom_restrictions=[],
                           locked_assignments=[], historical_balance={})
        violations = validate_schedule(inp, slots, assignments)
        h10_violations = [v for v in violations if v.constraint_id == "H10"]
        assert len(h10_violations) == 0, "Locked assignments should override standing days off"

    def test_blocked_by_period_aware_day_off(self, default_doctors, default_offices):
        """Sad path: morning assignment blocked by 'morning' day off."""
        slots = [
            ShiftSlot(slot_id="2026-09-15_hosp_office_am",
                     date="2026-09-15", office_id="hosp", shift_type="office_am",
                     start_time="08:00", end_time="12:00", max_doctors=2),
        ]
        assignments = [
            Assignment(doctor_id="d0", slot_id="2026-09-15_hosp_office_am"),
        ]
        day_off = {"d0": [{"date": "2026-09-15", "period": "morning"}]}
        inp = ScheduleInput(year=2026, month=8, doctors=default_doctors,
                           offices=default_offices, global_office_ranking=[],
                           day_off_dates=day_off, custom_restrictions=[],
                           locked_assignments=[], historical_balance={})
        violations = validate_schedule(inp, slots, assignments)
        h10_violations = [v for v in violations if v.constraint_id == "H10"]
        assert len(h10_violations) > 0, "Morning shift should be blocked by morning day off"


class TestS8WeekendPairing:
    """S8: Soft preference for paired weekend blocks."""

    def test_different_doctors_flagged_when_preferred(self, default_doctors, default_offices):
        """Sad path: different doctors on Sat/Sun when doctor prefers pairing."""
        slots = [
            ShiftSlot(slot_id="2026-09-12_hosp_call_weekend",
                     date="2026-09-12", office_id="hosp", shift_type="call_weekend",
                     start_time="00:00", end_time="23:59", max_doctors=1,
                     call_balance_group="weekend_block", is_weekend=True),
            ShiftSlot(slot_id="2026-09-13_hosp_call_weekend_sun",
                     date="2026-09-13", office_id="hosp", shift_type="call_weekend_sun",
                     start_time="00:00", end_time="23:59", max_doctors=1,
                     call_balance_group="weekend_block", is_weekend=True),
        ]
        assignments = [
            Assignment(doctor_id="d0", slot_id="2026-09-12_hosp_call_weekend"),
            Assignment(doctor_id="d1", slot_id="2026-09-13_hosp_call_weekend_sun"),
        ]
        inp = ScheduleInput(year=2026, month=8, doctors=default_doctors,
                           offices=default_offices, global_office_ranking=[],
                           day_off_dates=[], custom_restrictions=[],
                           locked_assignments=[], historical_balance={})
        violations = validate_schedule(inp, slots, assignments)
        s8_violations = [v for v in violations if v.constraint_id == "S8"]
        assert len(s8_violations) > 0

    def test_different_doctors_allowed_when_not_preferred(self, default_doctors, default_offices):
        """Happy path: different doctors on Sat/Sun when doctor does not prefer pairing."""
        default_doctors[0].weekend_pairing_preference = False
        default_doctors[1].weekend_pairing_preference = False
        slots = [
            ShiftSlot(slot_id="2026-09-12_hosp_call_weekend",
                     date="2026-09-12", office_id="hosp", shift_type="call_weekend",
                     start_time="00:00", end_time="23:59", max_doctors=1,
                     call_balance_group="weekend_block", is_weekend=True),
            ShiftSlot(slot_id="2026-09-13_hosp_call_weekend_sun",
                     date="2026-09-13", office_id="hosp", shift_type="call_weekend_sun",
                     start_time="00:00", end_time="23:59", max_doctors=1,
                     call_balance_group="weekend_block", is_weekend=True),
        ]
        assignments = [
            Assignment(doctor_id="d0", slot_id="2026-09-12_hosp_call_weekend"),
            Assignment(doctor_id="d1", slot_id="2026-09-13_hosp_call_weekend_sun"),
        ]
        inp = ScheduleInput(year=2026, month=8, doctors=default_doctors,
                           offices=default_offices, global_office_ranking=[],
                           day_off_dates=[], custom_restrictions=[],
                           locked_assignments=[], historical_balance={})
        violations = validate_schedule(inp, slots, assignments)
        s8_violations = [v for v in violations if v.constraint_id == "S8"]
        assert len(s8_violations) == 0


class TestH4CallDouble:
    """H4: No call doubles on weekends; single-preference doctors never get doubles."""

    def test_call_double_weekday_allowed(self, default_doctors, default_offices):
        """Happy path: call_day + call_night on same weekday for double-preference doctor."""
        slots = [
            ShiftSlot(slot_id="2026-09-15_hosp_call_day",
                     date="2026-09-15", office_id="hosp", shift_type="call_day",
                     start_time="07:00", end_time="19:00", max_doctors=1,
                     call_balance_group="weekday_day"),
            ShiftSlot(slot_id="2026-09-15_hosp_call_night",
                     date="2026-09-15", office_id="hosp", shift_type="call_night",
                     start_time="19:00", end_time="07:00", max_doctors=1,
                     call_balance_group="weekday_night"),
        ]
        # d0 has call_shift_preference="no_preference" (default)
        assignments = [
            Assignment(doctor_id="d0", slot_id="2026-09-15_hosp_call_day"),
            Assignment(doctor_id="d0", slot_id="2026-09-15_hosp_call_night"),
        ]
        inp = ScheduleInput(year=2026, month=8, doctors=default_doctors,
                           offices=default_offices, global_office_ranking=[],
                           day_off_dates=[], custom_restrictions=[],
                           locked_assignments=[], historical_balance={})
        violations = validate_schedule(inp, slots, assignments)
        h4_violations = [v for v in violations if v.constraint_id == "H4"]
        assert len(h4_violations) == 0, "Double-preference doctor can have weekday call double"

    def test_call_double_single_preference_blocked(self, default_doctors, default_offices):
        """Sad path: single-preference doctor has call_day + call_night."""
        slots = [
            ShiftSlot(slot_id="2026-09-15_hosp_call_day",
                     date="2026-09-15", office_id="hosp", shift_type="call_day",
                     start_time="07:00", end_time="19:00", max_doctors=1,
                     call_balance_group="weekday_day"),
            ShiftSlot(slot_id="2026-09-15_hosp_call_night",
                     date="2026-09-15", office_id="hosp", shift_type="call_night",
                     start_time="19:00", end_time="07:00", max_doctors=1,
                     call_balance_group="weekday_night"),
        ]
        # d1 has call_shift_preference="single"
        assignments = [
            Assignment(doctor_id="d1", slot_id="2026-09-15_hosp_call_day"),
            Assignment(doctor_id="d1", slot_id="2026-09-15_hosp_call_night"),
        ]
        inp = ScheduleInput(year=2026, month=8, doctors=default_doctors,
                           offices=default_offices, global_office_ranking=[],
                           day_off_dates=[], custom_restrictions=[],
                           locked_assignments=[], historical_balance={})
        violations = validate_schedule(inp, slots, assignments)
        h4_violations = [v for v in violations if v.constraint_id.startswith("H4")]
        assert len(h4_violations) > 0, "Single-preference doctor should not have call double"


class TestH7SurgicalPairing:
    """H7: Every surgical_am must have paired surgical_hosp_pm same doctor same day."""

    def test_surgical_paired_no_violation(self, default_doctors, default_offices):
        """Happy path: same doctor has surgical_am + surgical_hosp_pm."""
        slots = [
            ShiftSlot(slot_id="2026-09-15_hosp_surgical_am",
                     date="2026-09-15", office_id="hosp", shift_type="surgical_am",
                     start_time="07:00", end_time="12:00", max_doctors=1),
            ShiftSlot(slot_id="2026-09-15_hosp_surgical_hosp_pm",
                     date="2026-09-15", office_id="hosp", shift_type="surgical_hosp_pm",
                     start_time="13:00", end_time="17:00", max_doctors=1),
        ]
        assignments = [
            Assignment(doctor_id="d0", slot_id="2026-09-15_hosp_surgical_am"),
            Assignment(doctor_id="d0", slot_id="2026-09-15_hosp_surgical_hosp_pm"),
        ]
        inp = ScheduleInput(year=2026, month=8, doctors=default_doctors,
                           offices=default_offices, global_office_ranking=[],
                           day_off_dates=[], custom_restrictions=[],
                           locked_assignments=[], historical_balance={})
        violations = validate_schedule(inp, slots, assignments)
        h7_violations = [v for v in violations if v.constraint_id == "H7"]
        assert len(h7_violations) == 0

    def test_surgical_unpaired_violation(self, default_doctors, default_offices):
        """Sad path: surgical_am without paired surgical_hosp_pm."""
        slots = [
            ShiftSlot(slot_id="2026-09-15_hosp_surgical_am",
                     date="2026-09-15", office_id="hosp", shift_type="surgical_am",
                     start_time="07:00", end_time="12:00", max_doctors=1),
            ShiftSlot(slot_id="2026-09-15_hosp_surgical_hosp_pm",
                     date="2026-09-15", office_id="hosp", shift_type="surgical_hosp_pm",
                     start_time="13:00", end_time="17:00", max_doctors=1),
        ]
        assignments = [
            Assignment(doctor_id="d0", slot_id="2026-09-15_hosp_surgical_am"),
            Assignment(doctor_id="d1", slot_id="2026-09-15_hosp_surgical_hosp_pm"),
        ]
        inp = ScheduleInput(year=2026, month=8, doctors=default_doctors,
                           offices=default_offices, global_office_ranking=[],
                           day_off_dates=[], custom_restrictions=[],
                           locked_assignments=[], historical_balance={})
        violations = validate_schedule(inp, slots, assignments)
        h7_violations = [v for v in violations if v.constraint_id == "H7"]
        assert len(h7_violations) > 0, "Unpaired surgical assignments should flag H7"
