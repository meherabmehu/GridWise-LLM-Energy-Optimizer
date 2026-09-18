#!/usr/bin/env python3
"""Run the official public sample cases against a GridWise endpoint.

Usage
-----
    # Against a deployed service
    python scripts/run_public_samples.py --url https://your-service.example.com

    # Against a locally started service
    python scripts/run_public_samples.py --url http://127.0.0.1:8000

    # In-process, using the configured language model directly
    python scripts/run_public_samples.py --in-process

Every case is posted to ``POST /optimize-energy`` and the response is checked
against the official reference interpretation and replayed against the energy,
battery, solar and directive rules. The recalculated cost is compared with the
published optimum.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SAMPLES_PATH = ROOT / "docs" / "official" / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
TOLERANCE = 0.01


class Failure(Exception):
    pass


def load_cases() -> List[Dict[str, Any]]:
    with SAMPLES_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)["cases"]


def compare_interpretation(actual: List[Dict[str, Any]], expected: List[Dict[str, Any]]) -> Optional[str]:
    if len(actual) != len(expected):
        return f"expected {len(expected)} interpretation entries, received {len(actual)}"

    for received, reference in zip(actual, expected):
        if received["note_index"] != reference["note_index"]:
            return f"note_index mismatch: {received['note_index']} != {reference['note_index']}"
        if received["directive_type"] != reference["directive_type"]:
            return (
                f"note {received['note_index']}: directive_type {received['directive_type']} "
                f"!= {reference['directive_type']}"
            )
        if received["applies"] != reference["applies"]:
            return f"note {received['note_index']}: applies {received['applies']} != {reference['applies']}"

        want = reference["structured_adjustment"]
        got = received["structured_adjustment"]
        if want is None:
            if got is not None:
                return f"note {received['note_index']}: adjustment should be null"
            continue
        if got is None:
            return f"note {received['note_index']}: adjustment is missing"
        if list(got.get("hours", [])) != list(want.get("hours", [])):
            return f"note {received['note_index']}: hours {got.get('hours')} != {want.get('hours')}"
        for key, value in want.items():
            if key == "hours":
                continue
            if abs(float(got.get(key, float("nan"))) - float(value)) > 1e-6:
                return f"note {received['note_index']}: {key} {got.get(key)} != {value}"
    return None


def replay_plan(payload: Dict[str, Any], scenario: Dict[str, Any]) -> Tuple[float, Optional[str]]:
    """Replay hourly_plan and return (recalculated cost, error)."""
    plan = payload["hourly_plan"]
    if len(plan) != 24 or [entry["hour"] for entry in plan] != list(range(24)):
        return 0.0, "hourly_plan must contain hours 0..23 exactly once"

    hours = {entry["hour"]: entry for entry in scenario["hours"]}
    battery = scenario["battery"]
    effective = {entry["hour"]: entry["solar_kwh"] for entry in scenario["hours"]}

    for item in payload["directive_interpretation"]:
        adjustment = item.get("structured_adjustment") or {}
        for hour in adjustment.get("hours", []):
            if item["directive_type"] == "solar_reduction":
                effective[hour] = scenario["hours"][hour]["solar_kwh"] * adjustment["factor"]

    energy = float(battery["initial_energy_kwh"])
    cost = 0.0
    for entry in plan:
        hour = entry["hour"]
        demand = hours[hour]["demand_kwh"]
        tariff = hours[hour]["tariff_bdt_per_kwh"]
        action = entry["battery_action"]
        magnitude = entry["battery_kwh"]

        if action == "charge":
            charge, discharge = magnitude, 0.0
        elif action == "discharge":
            charge, discharge = 0.0, magnitude
        else:
            charge = discharge = 0.0
            if magnitude != 0:
                return 0.0, f"hour {hour}: battery_kwh must be 0 when idle"

        balance = entry["grid_kwh"] + entry["solar_used_kwh"] + discharge - demand - charge
        if abs(balance) > TOLERANCE:
            return 0.0, f"hour {hour}: energy balance off by {balance:.4f} kWh"
        if entry["solar_used_kwh"] > effective[hour] + TOLERANCE:
            return 0.0, f"hour {hour}: solar_used_kwh exceeds effective solar"
        if entry["grid_kwh"] < -TOLERANCE:
            return 0.0, f"hour {hour}: negative grid import"

        energy += charge - discharge
        if energy < battery["minimum_energy_kwh"] - TOLERANCE:
            return 0.0, f"hour {hour}: battery below minimum energy"
        if energy > battery["capacity_kwh"] + TOLERANCE:
            return 0.0, f"hour {hour}: battery above capacity"
        if abs(entry["battery_energy_after_kwh"] - energy) > TOLERANCE:
            return 0.0, f"hour {hour}: battery_energy_after_kwh does not match the replay"
        cost += entry["grid_kwh"] * tariff

    if abs(energy - float(battery["initial_energy_kwh"])) > TOLERANCE:
        return 0.0, "end-of-day battery energy does not equal initial_energy_kwh"

    for item in payload["directive_interpretation"]:
        adjustment = item.get("structured_adjustment") or {}
        kind = item["directive_type"]
        for hour in adjustment.get("hours", []):
            entry = plan[hour]
            if kind == "no_charge_window" and entry["battery_action"] == "charge":
                return 0.0, f"hour {hour}: charging during a no-charge window"
            if kind == "no_discharge_window" and entry["battery_action"] == "discharge":
                return 0.0, f"hour {hour}: discharging during a no-discharge window"
            if kind == "max_grid_window" and entry["grid_kwh"] > adjustment["max_grid_kwh"] + TOLERANCE:
                return 0.0, f"hour {hour}: grid import above the cap"
            if (
                kind == "minimum_battery_reserve"
                and entry["battery_energy_after_kwh"] < adjustment["minimum_energy_kwh"] - TOLERANCE
            ):
                return 0.0, f"hour {hour}: battery below the required reserve"

    for name, recomputed in (
        ("total_grid_kwh", sum(entry["grid_kwh"] for entry in plan)),
        ("total_cost_bdt", cost),
        ("peak_grid_kwh", max(entry["grid_kwh"] for entry in plan)),
    ):
        if abs(float(payload[name]) - recomputed) > TOLERANCE:
            return 0.0, f"{name} {payload[name]} does not match the recalculation {recomputed}"

    return cost, None


def post_case(url: str, scenario: Dict[str, Any], timeout: float) -> Tuple[int, Dict[str, Any]]:
    import httpx

    response = httpx.post(f"{url.rstrip('/')}/optimize-energy", json=scenario, timeout=timeout)
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, {}


async def run_in_process(cases: List[Dict[str, Any]]) -> List[Tuple[int, Dict[str, Any]]]:
    from app.config import load_settings
    from app.llm_interpreter import LLMInterpreter
    from app.models import ScenarioRequest
    from app.pipeline import optimize

    settings = load_settings()
    interpreter = LLMInterpreter(settings)
    results = []
    try:
        for case in cases:
            request = ScenarioRequest.model_validate(case["input"])
            outcome = await optimize(request, interpreter)
            results.append((200, outcome.response.model_dump(mode="json")))
    finally:
        await interpreter.aclose()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="base URL of a running GridWise service")
    parser.add_argument("--in-process", action="store_true", help="call the pipeline locally instead of over HTTP")
    parser.add_argument("--timeout", type=float, default=30.0, help="per-request timeout in seconds")
    parser.add_argument("--check-health", action="store_true", help="also probe GET /health")
    args = parser.parse_args()

    if not args.url and not args.in_process:
        parser.error("provide --url or --in-process")

    cases = load_cases()
    print(f"GridWise public sample runner - {len(cases)} cases")

    if args.check_health and args.url:
        import httpx

        health = httpx.get(f"{args.url.rstrip('/')}/health", timeout=args.timeout)
        print(f"GET  /health -> {health.status_code} {health.text.strip()}")
        if health.status_code != 200 or health.json().get("status") != "ok":
            print("health check failed")
            return 1

    if args.in_process:
        import asyncio

        results = asyncio.run(run_in_process(cases))
    else:
        results = [post_case(args.url, case["input"], args.timeout) for case in cases]

    passed = 0
    for case, (status, payload) in zip(cases, results):
        case_id = case["input"]["scenario_id"]
        if status != 200:
            print(f"FAIL {case_id}: HTTP {status}")
            continue

        problems = []
        issue = compare_interpretation(
            payload.get("directive_interpretation", []),
            case["expected_output"]["directive_interpretation"],
        )
        if issue:
            problems.append(f"interpretation: {issue}")

        cost, issue = replay_plan(payload, case["input"])
        if issue:
            problems.append(f"schedule: {issue}")

        reference = case["expected_output"]["total_cost_bdt"]
        if not issue and cost > reference + TOLERANCE:
            problems.append(f"cost {cost:.2f} is worse than the reference optimum {reference:.2f}")

        if problems:
            print(f"FAIL {case_id}")
            for problem in problems:
                print(f"       {problem}")
        else:
            print(
                f"PASS {case_id}  cost={cost:10.2f} BDT  reference={reference:10.2f} BDT  "
                f"peak={payload['peak_grid_kwh']:6.2f} kWh"
            )
            passed += 1

    print(f"\n{passed}/{len(cases)} cases passed")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
