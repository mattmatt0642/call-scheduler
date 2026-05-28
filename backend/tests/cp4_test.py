from models import DoctorProfile, Office, ScheduleInput, abs_times_overlap
from slot_generator import generate_slots
from scheduler import schedule_greedy
from constraint_checker import validate_schedule
from models import get_weekend_blocks

doctors = [DoctorProfile(
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
    standing_days_off=[]
) for i in range(7)]

offices = [
    Office(id="hosp",  name="Hospital", is_hospital=True,
           max_per_shift=2, restricted_tuesday_max=1),
    Office(id="north", name="North",    is_hospital=False,
           max_per_shift=3, restricted_tuesday_max=3),
    Office(id="south", name="South",    is_hospital=False,
           max_per_shift=2, restricted_tuesday_max=2),
]

inp = ScheduleInput(
    year=2026, month=8, doctors=doctors, offices=offices,
    global_office_ranking=["hosp","north","south"],
    day_off_dates=[], custom_restrictions=[],
    locked_assignments=[], historical_balance={},
    solver_time_limit_seconds=120
)

result = schedule_greedy(inp)
print(f"Status: {result.solver_status}")
print(f"Call Gini: {result.gini_calls:.3f}")

slot_map = {s.slot_id: s for s in result.slots}

by_doctor = {}
for a in result.assignments:
    by_doctor.setdefault(a.doctor_id, []).append(slot_map[a.slot_id])
for doc_id, doc_slots in by_doctor.items():
    for i, s1 in enumerate(doc_slots):
        for s2 in doc_slots[i+1:]:
            assert not abs_times_overlap(s1, s2), \
                f"Overlap: {doc_id}: {s1.shift_type} {s1.date} vs {s2.shift_type} {s2.date}"
print("No overlaps — passed")

sat_assignments = {a.slot_id: a.doctor_id for a in result.assignments
                   if slot_map[a.slot_id].shift_type == "call_weekend"}
sun_assignments = {a.slot_id: a.doctor_id for a in result.assignments
                   if slot_map[a.slot_id].shift_type == "call_weekend_sun"}
slots_full = generate_slots(2026, 8, offices, [], [])
for block in get_weekend_blocks(2026, 8):
    sat_id = f"{block.saturday}_hosp_call_weekend"
    sun_id = f"{block.sunday}_hosp_call_weekend_sun"
    if sat_id in sat_assignments and sun_id in sun_assignments:
        assert sat_assignments[sat_id] == sun_assignments[sun_id], \
            f"Weekend block {block.saturday}: Sat and Sun assigned to different doctors"
print("Weekend block pairing — passed")

violations = validate_schedule(inp, result.slots, result.assignments)
h6_viols = [v for v in violations if v.constraint_id == "H6"]
assert len(h6_viols) == 0, f"H6 violations found: {[v.description for v in h6_viols]}"
print("No H6 violations — passed")

fri_night_docs = {}
for a in result.assignments:
    slot = slot_map[a.slot_id]
    if slot.call_balance_group == "friday_night":
        fri_night_docs[a.doctor_id] = fri_night_docs.get(a.doctor_id, 0) + 1
if fri_night_docs:
    max_fri = max(fri_night_docs.values())
    min_fri = min(fri_night_docs.get(d.id, 0) for d in doctors if d.hospital_call_eligible)
    assert max_fri - min_fri <= 1, \
        f"Friday night imbalance: max={max_fri}, min={min_fri}"
    print(f"Friday night balance (max={max_fri}, min={min_fri}) — passed")

print("All checkpoint 4 tests passed")