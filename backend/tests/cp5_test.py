from models import DoctorProfile, Office
from csv_io import export_balance_csv, import_balance_csv

doctors = [DoctorProfile(id="d1", name="Anderson", allowed_offices=None,
                          office_preferences=[], required_sessions_per_week=5,
                          hospital_call_eligible=True, surgical_assist_eligible=False,
                          max_weekday_day_calls=5, max_weekday_night_calls=5,
                          max_friday_night_calls=2, max_weekend_blocks=2,
                          preferred_call_days=[], post_call_preference="no_preference",
                          call_shift_preference="no_preference",
                          day_night_preference="balanced", am_pm_preference="balanced",
                          standing_days_off=[])]
offices = [Office(id="north", name="North Office", is_hospital=False,
                  max_per_shift=3, restricted_tuesday_max=3)]

totals = {"d1": {"weekday_day": 14, "weekday_night": 13, "friday_night": 4,
                  "weekend_blocks": 5, "total_sessions": 89, "am_sessions": 46,
                  "pm_sessions": 33, "late_sessions": 10,
                  "office_visits": {"north": 30}}}

csv_out = export_balance_csv(doctors, offices, totals)
parsed  = import_balance_csv(csv_out)

assert parsed["d1"]["weekday_day"]    == 14
assert parsed["d1"]["friday_night"]   ==  4
assert parsed["d1"]["weekend_blocks"] ==  5
assert parsed["d1"]["total_sessions"] == 89
print("CSV round-trip passed")

print("All checkpoint 5 tests passed")