from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import date, timedelta
import calendar as calendar

@dataclass
class RecurringSlot:
    day_of_week: int
    office_id: str
    shift_type: str
    notes: str = ""

@dataclass
class OneTimeOverride:
    date: str
    office_id: str
    shift_type: str
    notes: str = ""

@dataclass
class WeekendCallBlock:
    saturday: str
    sunday: str
    week_num: int

@dataclass
class CustomRestriction:
    date: str
    office_id: str
    shift_type: str
    max_override: int
    note: str = ""

@dataclass
class Office:
    id: str
    name: str
    is_hospital: bool
    max_per_shift: int
    restricted_tuesday_max: int
    location_address: str = ""

@dataclass
class DoctorProfile:
    id: str
    name: str
    allowed_offices: Optional[List[str]] = None
    office_preferences: List[str] = field(default_factory=list)
    required_sessions_per_week: int = 5
    hospital_call_eligible: bool = True
    surgical_assist_eligible: bool = True
    weekend_call_off: bool = False  # excluded from weekend call blocks
    max_weekday_day_calls: int = 5
    max_weekday_night_calls: int = 5
    max_friday_night_calls: int = 2
    max_weekend_blocks: int = 2
    preferred_call_days: List[int] = field(default_factory=list)
    post_call_preference: str = "no_preference"
    call_shift_preference: str = "no_preference"
    day_night_preference: str = "balanced"
    am_pm_preference: str = "balanced"
    standing_days_off: List[int] = field(default_factory=list)
    fixed_recurring: List[RecurringSlot] = field(default_factory=list)
    one_time_overrides: List[OneTimeOverride] = field(default_factory=list)

@dataclass
class ShiftSlot:
    slot_id: str
    date: str
    office_id: str
    shift_type: str
    start_time: str
    end_time: str
    max_doctors: int
    is_restricted_tuesday: bool = False
    is_weekend: bool = False
    call_balance_group: str = ""

@dataclass
class Assignment:
    doctor_id: str
    slot_id: str
    is_locked: bool = False

@dataclass
class ScheduleCounts:
    doctor_id: str
    doctor_name: str
    weekday_day_calls: int
    weekday_night_calls: int
    friday_night_calls: int
    weekend_blocks: int
    total_calls: int
    am_sessions: int
    pm_sessions: int
    late_sessions: int
    total_sessions: int
    office_visit_counts: Dict[str, int]
    cumulative_weekday_day: int
    cumulative_weekday_night: int
    cumulative_friday_night: int
    cumulative_weekend_blocks: int
    cumulative_sessions: int
    preferred_day_call_rate: Optional[float]
    call_gini: float
    session_gini: float

@dataclass
class ScheduleInput:
    year: int
    month: int
    doctors: List[DoctorProfile]
    offices: List[Office]
    global_office_ranking: List[str]
    day_off_dates: object  # List[str] (flat) or Dict[str, List[str]] (per-doctor)
    custom_restrictions: List[CustomRestriction]
    locked_assignments: List[Assignment]
    historical_balance: Dict[str, Dict]
    solver_time_limit_seconds: int = 120

@dataclass
class ScheduleResult:
    month_key: str
    assignments: List[Assignment]
    slots: List[ShiftSlot]
    solver_status: str
    gini_calls: float
    gini_sessions: float
    unmet_constraints: List[Dict]
    partial: bool
    counts: Dict[str, ScheduleCounts]

_EPOCH = date(2000, 1, 1)

def slot_to_abs_minutes(slot: 'ShiftSlot') -> tuple:
    """
    Convert a ShiftSlot to (abs_start, abs_end) in minutes w.r.t _EPOCH.

    The shift starts on slot.date at slot.start_time.
    If slot.end_time < slot.start_time (in minutes-since-midnight),
    the shift crosses midnight: abs_end = next_day_offset + end_min.
    Returns: (abs_start, abs_end) both in interger minutes.
    """
    d = date.fromisoformat(slot.date)
    days_from_epoch = (d-_EPOCH).days
    minutes_from_epoch = int(days_from_epoch) * 1440
    start_hours = int(slot.start_time[0:2])
    start_minutes = int(slot.start_time[3:5])
    start_from_epoch = minutes_from_epoch + start_hours * 60 + start_minutes
    end_hours = int(slot.end_time[0:2])
    end_minutes = int(slot.end_time[3:5])
    end_from_epoch = minutes_from_epoch + (end_hours * 60) + end_minutes
    if end_from_epoch < start_from_epoch:
        end_from_epoch += 1440
    return (start_from_epoch, end_from_epoch)

def abs_times_overlap(slot1: 'ShiftSlot', slot2: 'ShiftSlot') -> bool:
    """
    Returns True if slot1 and slot2 have any overlapping time range.
    """
    s1_slot_to_abs_minutes = slot_to_abs_minutes(slot1)
    s2_slot_to_abs_minutes = slot_to_abs_minutes(slot2)
    s1s_abs_min = s1_slot_to_abs_minutes[0]
    s1e_abs_min = s1_slot_to_abs_minutes[1]
    s2s_abs_min = s2_slot_to_abs_minutes[0]
    s2e_abs_min = s2_slot_to_abs_minutes[1]
    if min(s1e_abs_min, s2e_abs_min) > max(s1s_abs_min, s2s_abs_min):
        return True
    return False

def get_days_in_month(year: int, month: int) -> List[Dict]:
    """
    Returns one dict per calendar day in the given month.
    Months are 0-indexed.
    Each dict contains:
        date:        str  — "YYYY-MM-DD"
        day_of_week: int  — 0=Monday, 6=Sunday  (Python's weekday() convention)
        day_num:     int  — 1 through 31
        is_weekend:  bool — Saturday or Sunday
        is_monday:   bool
        is_tuesday:  bool
        is_thursday: bool
        is_friday:   bool
        week_num:    int  — 0-indexed week within the month
    """
    start_day, total_days = calendar.monthrange(year, month+1)
    first_dow = date(year, month+1, 1).weekday()
    days_in_month = []
    for day in range(1, total_days + 1):
        day_of_month = {}
        d = date(year, month+1, day)
        day_of_month['date'] = d.strftime('%Y-%m-%d')
        day_of_month['day_of_week'] = d.weekday()
        day_of_month['day_num'] = day
        day_of_month['is_weekend'] = True if d.weekday() == 5 or d.weekday() == 6 else False
        day_of_month['is_monday'] = True if d.weekday() == 0 else False
        day_of_month['is_tuesday'] = True if d.weekday() == 1 else False
        day_of_month['is_thursday'] = True if d.weekday() == 3 else False
        day_of_month['is_friday'] = True if d.weekday() == 4 else False
        day_of_month['week_num'] = (day + first_dow - 1) // 7
        days_in_month.append(day_of_month)
    return days_in_month

def get_nth_tuesdays(year: int, month: int) -> List[str]:
    """
    Returns the dates of the 1st, 3rd, and 5th Tuesdays in the month.
    Only returns the Tuesdays that actually exist - a month has either 4 or 5 Tuesdays.
    These are the restricted-capacity hspital office days (H2).

    Returns: list of "YYYY-MM-DD" strings, length 2 or 3.
    """
    days_in_month = get_days_in_month(year, month)
    tuesdays = []
    for day in days_in_month:
        if day['is_tuesday']:
            tuesdays.append(day['date'])
    if len(tuesdays) == 5:
        tuesdays = [tuesdays[0], tuesdays[2], tuesdays[4]]
        return tuesdays
    tuesdays = [tuesdays[0], tuesdays[2]]
    return tuesdays


def get_weekend_blocks(year: int, month: int) -> List['WeekendCallBlock']:
    """
    Returns one weekendCallBlock per Saturday in the month.
    Sunday may fall in the folowing month, it will be included.
    """
    days_of_month = get_days_in_month(year, month)
    weekend_pairs = []
    for day in days_of_month:
        if day['day_of_week'] == 5:
            sat_str = day['date']
            sat = date.fromisoformat(sat_str)
            sun = sat + timedelta(days=1)
            sun_str = sun.isoformat()
            week_num = day['week_num']
            weekend_pairs.append(WeekendCallBlock(sat_str, sun_str, week_num))
    return weekend_pairs

def is_friday(date_str: str) -> bool:
    """
    Returns True if date_str ("YYYY-MM-DD") is a Friday.
    """
    d = date.fromisoformat(date_str)
    return d.weekday() == 4


def get_call_balance_group(date_str: str, shift_type: str) -> str:
    """
    Maps a (date, shift_type) pair to one of the four call balance groups.
    Returns "" for non-call shift types.

    Balance groups:
        "weekday_day"   - call_day on any weekday
        "weekday_night" - call_night on Monday through Thursday
        "friday_night"  - call_night on Friday specifically
        "weekend_block" - call_weekend OR call_weekend_sun
    """
    if shift_type[0:4] != 'call':
        return ""
    d = date.fromisoformat(date_str)
    day = d.weekday()
    match day:
        case 0 | 1 | 2 | 3:
            return "weekday_day" if shift_type == 'call_day' else "weekday_night"
        case 4:
            if shift_type == 'call_night':
                return "friday_night"
            return "weekday_day"
        case 5 | 6:
            return "weekend_block"
    return ""
        
                

def prev_date(date_str: str) -> str:
    """
    Returns the date string for the calendar day before date_str.
    """
    d = date.fromisoformat(date_str)
    return (d - timedelta(days=1)).isoformat()


SHIFT_TIMES = {
    "office_am": ("08:00", "12:00"),
    "office_pm": ("13:00", "17:00"),
    "office_late": ("13:30", "18:30"),
    "call_day": ("07:00", "19:00"),
    "call_night": ("19:00", "07:00"),
    "surgical_am": ("07:00", "12:00"),
    "surgical_hosp_pm": ("13:00", "17:00"),
}

SHIFT_PERIODS = {
    "office_am": "morning",
    "office_pm": "afternoon",
    "office_late": "afternoon",
    "call_day": "all_day",
    "call_night": "all_day",
    "surgical_am": "morning",
    "surgical_hosp_pm": "afternoon",
}