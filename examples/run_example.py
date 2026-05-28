#!/usr/bin/env python3
"""Run the example schedule request against the Flask backend.

Usage:
  1. Start the backend:  cd backend && python app.py
  2. Run this script:    python examples/run_example.py

Or run directly (starts backend automatically):
  python examples/run_example.py --start-server
"""

import json
import sys
import os
import time
import subprocess
import argparse
from pathlib import Path

EXAMPLE_DIR = Path(__file__).parent
INPUT_FILE = EXAMPLE_DIR / "input.json"
PROJECT_ROOT = EXAMPLE_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
API_URL = "http://localhost:5000/generate"


def run_against_server(input_data: dict) -> dict:
    import urllib.request
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(input_data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Cannot connect to {API_URL}: {e.reason}", file=sys.stderr)
        print("Start the backend first: cd backend && python app.py", file=sys.stderr)
        sys.exit(1)


def print_results(result: dict) -> None:
    status = result.get("solverStatus", "unknown")
    partial = result.get("partial", False)
    gini_calls = result.get("giniCalls", 0)
    gini_sessions = result.get("giniSessions", 0)
    assignments = result.get("assignments", [])
    slots = result.get("slots", [])
    counts = result.get("counts", {})
    unmet = result.get("unmetConstraints", [])

    print()
    print("=" * 60)
    print(f"  SCHEDULER RESULTS")
    print("=" * 60)
    print(f"  Solver status:    {status}")
    print(f"  Partial schedule:  {partial}")
    print(f"  Gini (calls):      {gini_calls:.3f}")
    print(f"  Gini (sessions):   {gini_sessions:.3f}")
    print(f"  Total assignments: {len(assignments)}")
    print(f"  Total slots:       {len(slots)}")
    print(f"  Unmet constraints: {len(unmet)}")
    print()

    shift_type_labels = {
        "call_day": "Call Day",
        "call_night": "Call Night",
        "call_weekend": "Wknd Sat",
        "call_weekend_sun": "Wknd Sun",
        "surgical_am": "Surg AM",
        "surgical_hosp_pm": "Surg PM",
        "office_am": "Office AM",
        "office_pm": "Office PM",
        "office_late": "Office Late",
    }

    slot_map = {s["slotId"]: s for s in slots}

    shift_counts = {}
    for a in assignments:
        slot = slot_map.get(a["slotId"])
        if slot:
            st = slot["shiftType"]
            shift_counts[st] = shift_counts.get(st, 0) + 1

    print("  Assignments by shift type:")
    print("  " + "-" * 40)
    for st in ["call_day", "call_night", "call_weekend", "call_weekend_sun",
               "surgical_am", "surgical_hosp_pm",
               "office_am", "office_pm", "office_late"]:
        label = shift_type_labels.get(st, st)
        count = shift_counts.get(st, 0)
        total = sum(1 for s in slots if s["shiftType"] == st)
        bar = "#" * count
        print(f"  {label:<12} {count:>3}/{total:<3}  {bar}")
    print()

    uncovered = [s for s in slots
                 if s["shiftType"] in ("call_day", "call_night", "call_weekend", "call_weekend_sun")
                 and not any(a["slotId"] == s["slotId"] for a in assignments)]
    if uncovered:
        print("  UNCOVERED CALL SLOTS:")
        print("  " + "-" * 40)
        for s in uncovered[:10]:
            label = shift_type_labels.get(s["shiftType"], s["shiftType"])
            print(f"  {s['date']}  {label}")
        if len(uncovered) > 10:
            print(f"  ... and {len(uncovered) - 10} more")
        print()

    if counts:
        print("  Per-doctor call summary:")
        print("  " + "-" * 60)
        print(f"  {'Doctor':<14} {'Day':>4} {'Night':>5} {'FriN':>4} {'Wknd':>4} {'Sess':>5}")
        print("  " + "-" * 60)
        for doc_id, c in sorted(counts.items()):
            name = c.get("doctorName", doc_id)
            print(f"  {name:<14} {c.get('weekdayDayCalls',0):>4} {c.get('weekdayNightCalls',0):>5} "
                  f"{c.get('fridayNightCalls',0):>4} {c.get('weekendBlocks',0):>4} {c.get('totalSessions',0):>5}")
        print()

    if unmet:
        print(f"  Unmet constraints ({len(unmet)}):")
        print("  " + "-" * 60)
        for v in unmet[:5]:
            desc = v.get("description", "")
            sev = v.get("severity", "")
            print(f"  [{sev}] {desc}")
        if len(unmet) > 5:
            print(f"  ... and {len(unmet) - 5} more")
        print()

    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Run example schedule request")
    parser.add_argument("--start-server", action="store_true", help="Start backend server automatically")
    parser.add_argument("--input", type=str, default=str(INPUT_FILE), help="Input JSON file")
    parser.add_argument("--save", type=str, default="", help="Save raw result JSON to this file")
    args = parser.parse_args()

    with open(args.input) as f:
        input_data = json.load(f)

    server_proc = None
    if args.start_server:
        print("Starting backend server...")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(BACKEND_DIR)
        server_proc = subprocess.Popen(
            [sys.executable, str(BACKEND_DIR / "app.py")],
            cwd=str(BACKEND_DIR),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(3)

    try:
        result = run_against_server(input_data)
        print_results(result)
        if args.save:
            with open(args.save, "w") as f:
                json.dump(result, f, indent=2)
            print(f"Raw result saved to {args.save}")
    finally:
        if server_proc:
            server_proc.terminate()
            server_proc.wait()


if __name__ == "__main__":
    main()
