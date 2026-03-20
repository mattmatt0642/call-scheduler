# Run from backend/ with venv activated: python -c "exec(open('test_cp1.py').read())"

from models import (get_days_in_month, get_nth_tuesdays, get_weekend_blocks,
                    slot_to_abs_minutes, abs_times_overlap, ShiftSlot,
                    is_friday, get_call_balance_group, WeekendCallBlock)

print("Testing get_days_in_month...")
days = get_days_in_month(2026, 8)   # September 2026
assert len(days) == 30, f"September has 30 days, got {len(days)}"
assert days[0]['date'] == "2026-09-01"
assert days[0]['day_of_week'] == 1,  "Sep 1 2026 is Tuesday (1)"
assert days[0]['is_tuesday'] == True
assert days[0]['is_weekend'] == False
assert days[4]['day_of_week'] == 5,  "Sep 5 2026 is Saturday (5)"
assert days[4]['is_weekend'] == True
assert days[5]['day_of_week'] == 6,  "Sep 6 2026 is Sunday (6)"
assert days[5]['is_weekend'] == True
print("  PASSED")

print("Testing get_nth_tuesdays...")
tues = get_nth_tuesdays(2026, 8)
assert "2026-09-01" in tues, "Sep 1 is the 1st Tuesday"
assert "2026-09-15" in tues, "Sep 15 is the 3rd Tuesday"
assert "2026-09-29" in tues, "Sep 29 is the 5th Tuesday"
assert "2026-09-08" not in tues, "Sep 8 (2nd Tuesday) should not be included"
print("  PASSED")

print("Testing get_weekend_blocks...")
blocks = get_weekend_blocks(2026, 8)
assert len(blocks) == 4, f"September 2026 has 4 Saturdays, got {len(blocks)}"
for b in blocks:
    from datetime import date as d, timedelta
    sat = d.fromisoformat(b.saturday)
    sun = d.fromisoformat(b.sunday)
    assert sun == sat + timedelta(days=1), f"Sunday must be Saturday+1: {b}"
print("  PASSED")

print("Testing is_friday...")
assert is_friday("2026-09-04") == True,  "Sep 4 2026 is Friday"
assert is_friday("2026-09-05") == False, "Sep 5 2026 is Saturday"
assert is_friday("2026-09-07") == False, "Sep 7 2026 is Monday"
print("  PASSED")

print("Testing get_call_balance_group...")
assert get_call_balance_group("2026-09-04", "call_night")    == "friday_night"
assert get_call_balance_group("2026-09-07", "call_night")    == "weekday_night"
assert get_call_balance_group("2026-09-07", "call_day")      == "weekday_day"
assert get_call_balance_group("2026-09-05", "call_weekend")  == "weekend_block"
assert get_call_balance_group("2026-09-06", "call_weekend_sun") == "weekend_block"
assert get_call_balance_group("2026-09-01", "office_am")     == ""
print("  PASSED")

print("Testing slot_to_abs_minutes and abs_times_overlap...")

def make_slot(date, start, end, stype="office_am"):
    return ShiftSlot(
        slot_id=f"{date}_{stype}", date=date, office_id="x",
        shift_type=stype, start_time=start, end_time=end,
        max_doctors=1
    )

# --- Basic same-day overlaps ---
assert abs_times_overlap(
    make_slot("2026-09-01", "08:00", "12:00"),
    make_slot("2026-09-01", "11:00", "15:00")
) == True,  "Overlapping same-day shifts"

assert abs_times_overlap(
    make_slot("2026-09-01", "08:00", "12:00"),
    make_slot("2026-09-01", "12:00", "16:00")
) == False, "Touching shifts (12:00 end, 12:00 start) do NOT overlap"

assert abs_times_overlap(
    make_slot("2026-09-01", "08:00", "12:00"),
    make_slot("2026-09-01", "13:00", "17:00")
) == False, "Clearly separate same-day shifts"

# --- Overnight shift: Friday night call ---
fri_night = make_slot("2026-09-04", "19:00", "07:00", "call_night")

# Should NOT overlap with Saturday 08:00+ (call ends at 07:00 Sat)
assert abs_times_overlap(
    fri_night,
    make_slot("2026-09-05", "08:00", "12:00")
) == False, "Friday night ends 07:00 Sat; Sat 08:00 office should NOT overlap"

# Should NOT overlap with Sat 07:00 exactly (touching, not overlapping)
assert abs_times_overlap(
    fri_night,
    make_slot("2026-09-05", "07:00", "11:00")
) == False, "Touching at 07:00 does NOT overlap"

# SHOULD overlap with Sat 06:00 (before 07:00 end of night call)
assert abs_times_overlap(
    fri_night,
    make_slot("2026-09-05", "06:00", "10:00")
) == True,  "Friday night still running at 06:00 Sat — overlap"

# SHOULD overlap with Friday evening (before night call ends)
assert abs_times_overlap(
    fri_night,
    make_slot("2026-09-04", "18:00", "20:00")
) == True,  "Friday 18:00-20:00 overlaps with night call starting 19:00"

# Completely different day — no overlap
assert abs_times_overlap(
    fri_night,
    make_slot("2026-09-06", "08:00", "12:00")
) == False, "Sunday has nothing to do with Friday night call"

# --- Weekend block (00:00–23:59 full day) ---
sat_block = make_slot("2026-09-05", "00:00", "23:59", "call_weekend")

# Any slot on Saturday overlaps with the block
assert abs_times_overlap(
    sat_block,
    make_slot("2026-09-05", "08:00", "12:00")
) == True,  "Saturday office AM overlaps with Saturday weekend block"

# Friday night call bleeds into Saturday — should conflict with Saturday block
assert abs_times_overlap(
    fri_night,
    sat_block
) == True,  "Friday night ends 07:00 Sat; Sat block starts 00:00 Sat — overlap"

# Friday call_day (07:00-19:00) does NOT overlap with Saturday block
assert abs_times_overlap(
    make_slot("2026-09-04", "07:00", "19:00", "call_day"),
    sat_block
) == False, "Friday call_day ends 19:00 Fri; Sat block starts 00:00 Sat — no overlap"

print("  PASSED")
print("\nAll Checkpoint 1 tests passed. Commit and move to Checkpoint 2.")