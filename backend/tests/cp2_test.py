from models import Office
from slot_generator import generate_slots

offices = [
    Office(id="hosp",  name="Hospital", is_hospital=True,
           max_per_shift=2, restricted_tuesday_max=1),
    Office(id="north", name="North",    is_hospital=False,
           max_per_shift=3, restricted_tuesday_max=3),
    Office(id="south", name="South",    is_hospital=False,
           max_per_shift=2, restricted_tuesday_max=2),
]

slots = generate_slots(2026, 8, offices, [], [])

# Count each type
call_day   = [s for s in slots if s.shift_type == "call_day"]
call_night = [s for s in slots if s.shift_type == "call_night"]
fri_night  = [s for s in slots if s.shift_type == "call_night"
              and s.call_balance_group == "friday_night"]
wknd_sat   = [s for s in slots if s.shift_type == "call_weekend"]
wknd_sun   = [s for s in slots if s.shift_type == "call_weekend_sun"]
surgical   = [s for s in slots if s.shift_type == "surgical_am"]
late       = [s for s in slots if s.shift_type == "office_late"]
restricted = [s for s in slots if s.is_restricted_tuesday]

# September 2026: Sep 1=Tue. 22 weekdays total. 4 Saturdays. 4 Fridays.
assert len(call_day)   == 22, f"22 weekday call_day slots, got {len(call_day)}"
assert len(call_night) == 22, f"22 weekday call_night slots, got {len(call_night)}"
assert len(fri_night)  ==  4, f"4 Friday nights in Sep 2026, got {len(fri_night)}"
assert len(wknd_sat)   ==  4, f"4 Saturday blocks, got {len(wknd_sat)}"
assert len(wknd_sun)   ==  4, f"4 Sunday blocks paired with Saturday, got {len(wknd_sun)}"

# Weekend slot time representation
for s in wknd_sun:
    assert s.start_time == "00:00", f"{s.slot_id} must start at 00:00"
    assert s.end_time == "23:59", f"{s.slot_id} must end at 23:59"
for s in wknd_sat:
    assert s.start_time == "07:00", f"{s.slot_id} must start at 07:00"
    assert s.end_time == "23:59", f"{s.slot_id} must end at 23:59"

# Sep 2026 Tue/Wed/Thu days: 1,2,3,8,9,10,15,16,17,22,23,24,29,30 = 14 days
assert len(surgical) == 14, f"14 surgical AM slots (Tue+Wed+Thu), got {len(surgical)}"

# Verify each surgical_am has a paired surgical_hosp_pm on the same date
for surg in surgical:
    date = surg.date
    paired = next((s for s in slots
                   if s.date == date and s.shift_type == "surgical_hosp_pm"), None)
    assert paired is not None, f"No surgical_hosp_pm paired with surgical_am on {date}"

# Mon+Thu in Sep 2026: Mon(7,14,21,28)=4, Thu(3,10,17,24)=4 → 8 days
# 2 non-hospital offices → 16 office_late slots
assert len(late) == 16, f"16 late slots (8 Mon/Thu days * 2 offices), got {len(late)}"

# Restricted Tuesdays: Sep 1, 15, 29 → 3 days × 2 hospital office slots (office_am+office_pm) = 6
assert len(restricted) == 6, f"6 restricted Tuesday hospital office slots, got {len(restricted)}"
for s in restricted:
	assert s.shift_type in ("office_am", "office_pm"), f"Restricted should be hospital office shift, got {s.shift_type}"
	assert s.max_doctors == 1, f"Restricted slot {s.slot_id} should have cap=1"
# No call slots should have is_restricted_tuesday
restricted_call = [s for s in slots if s.is_restricted_tuesday and s.shift_type in ("call_day", "call_night")]
assert len(restricted_call) == 0, f"0 call slots should be restricted, got {len(restricted_call)}"

# All slot IDs must be unique
ids = [s.slot_id for s in slots]
assert len(ids) == len(set(ids)), "Duplicate slot_ids found"

# call_balance_group is correctly assigned
for s in slots:
    if s.shift_type in ("call_day","call_night","call_weekend","call_weekend_sun"):
        assert s.call_balance_group != "", f"{s.slot_id} missing call_balance_group"
    else:
        assert s.call_balance_group == "", f"{s.slot_id} should have empty call_balance_group"

print(f"Total slots: {len(slots)}")
print("All Checkpoint 2 tests passed.")