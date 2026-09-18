"""Run every official public sample case through the whole pipeline.

Each case is checked on interpretation, directive application, energy balance,
battery behaviour, solar constraints, grid caps, end-of-day neutrality, totals
and response schema, and the recalculated cost must not be worse than the
published optimum.
"""

from __future__ import annotations

import math

import pytest

from app.directives import build_constraints
from app.guardrails import sanitize_interpretation
from app.models import ScenarioRequest
from app.optimizer import finalize_schedule, solve_schedule
from app.pipeline import to_plan_entries
from app.validator import compute_totals, validate_plan

OFFICIAL_TOLERANCE = 0.01

ADJUSTMENT_KEYS = {
    "solar_reduction": {"hours", "factor"},
    "minimum_battery_reserve": {"hours", "minimum_energy_kwh"},
    "no_charge_window": {"hours"},
    "no_discharge_window": {"hours"},
    "max_grid_window": {"hours", "max_grid_kwh"},
}


def _solution_for(case):
    request = ScenarioRequest.model_validate(case["input"])
    reference = case["expected_output"]
    result = sanitize_interpretation(
        {"directives": reference["directive_interpretation"]},
        request.operator_notes,
        request.battery,
    )
    constraints = build_constraints(request.hours, request.battery, result.directives)
    schedule = finalize_schedule(
        solve_schedule(request.hours, request.battery, constraints), request.hours, request.battery
    )
    plan = to_plan_entries(schedule)
    totals = validate_plan(plan, request.hours, request.battery, constraints)
    return request, reference, result, constraints, schedule, plan, totals


def test_sample_pack_is_the_official_one(sample_pack):
    assert sample_pack["_meta"]["case_count"] == len(sample_pack["cases"])
    assert sample_pack["_meta"]["endpoint"] == "POST /optimize-energy"
    assert set(sample_pack["_meta"]["allowed_enums"]["directive_type"]) == {
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op",
    }


@pytest.mark.parametrize("index", range(10))
def test_interpretation_matches_reference(sample_cases, index):
    case = sample_cases[index]
    request, reference, result, *_ = _solution_for(case)

    assert len(result.directives) == len(request.operator_notes)
    for directive, expected in zip(result.directives, reference["directive_interpretation"]):
        assert directive.note_index == expected["note_index"]
        assert directive.directive_type.value == expected["directive_type"]
        assert directive.applies is expected["applies"]

        if expected["structured_adjustment"] is None:
            assert directive.adjustment is None
            continue

        wire = directive.adjustment.to_wire()
        assert set(wire) == ADJUSTMENT_KEYS[expected["directive_type"]]
        assert wire["hours"] == list(expected["structured_adjustment"]["hours"])
        for key, value in expected["structured_adjustment"].items():
            if key != "hours":
                assert math.isclose(wire[key], value, abs_tol=1e-6)


@pytest.mark.parametrize("index", range(10))
def test_schedule_is_valid_and_optimal(sample_cases, index):
    case = sample_cases[index]
    _, reference, _, _, schedule, plan, totals = _solution_for(case)

    assert len(plan) == 24
    assert schedule.energy[-1] == pytest.approx(case["input"]["battery"]["initial_energy_kwh"], abs=1e-6)

    # The published reference is itself optimal, so matching it within tolerance
    # is the strongest possible statement about cost quality.
    assert totals.total_grid_kwh == pytest.approx(reference["total_grid_kwh"], abs=OFFICIAL_TOLERANCE)
    assert totals.total_cost_bdt == pytest.approx(reference["total_cost_bdt"], abs=OFFICIAL_TOLERANCE)
    assert totals.peak_grid_kwh == pytest.approx(reference["peak_grid_kwh"], abs=OFFICIAL_TOLERANCE)


@pytest.mark.parametrize("index", range(10))
def test_reported_totals_match_recalculation(sample_cases, index):
    case = sample_cases[index]
    request, _, _, _, _, plan, totals = _solution_for(case)
    recomputed = compute_totals(plan, request.hours)
    assert recomputed.total_grid_kwh == pytest.approx(totals.total_grid_kwh, abs=1e-6)
    assert recomputed.total_cost_bdt == pytest.approx(totals.total_cost_bdt, abs=1e-6)
    assert recomputed.peak_grid_kwh == pytest.approx(totals.peak_grid_kwh, abs=1e-6)


@pytest.mark.parametrize("index", range(10))
def test_end_to_end_response_schema(offline_client, sample_cases, index):
    case = sample_cases[index]
    response = offline_client.post("/optimize-energy", json=case["input"])
    assert response.status_code == 200

    body = response.json()
    assert set(body) == {
        "scenario_id",
        "directive_interpretation",
        "hourly_plan",
        "total_grid_kwh",
        "total_cost_bdt",
        "peak_grid_kwh",
        "plan_summary",
    }
    assert body["scenario_id"] == case["input"]["scenario_id"]
    assert len(body["hourly_plan"]) == 24
    assert [entry["hour"] for entry in body["hourly_plan"]] == list(range(24))
    assert [entry["note_index"] for entry in body["directive_interpretation"]] == list(
        range(len(case["input"]["operator_notes"]))
    )
    for entry in body["hourly_plan"]:
        assert set(entry) == {
            "hour",
            "grid_kwh",
            "solar_used_kwh",
            "battery_action",
            "battery_kwh",
            "battery_energy_after_kwh",
        }
        assert entry["battery_action"] in {"charge", "discharge", "idle"}
        assert entry["grid_kwh"] >= 0
        assert entry["solar_used_kwh"] >= 0
        assert entry["battery_kwh"] >= 0
        if entry["battery_action"] == "idle":
            assert entry["battery_kwh"] == 0
    assert isinstance(body["plan_summary"], str) and body["plan_summary"]


@pytest.mark.parametrize("index", range(10))
def test_directive_windows_are_actually_applied(sample_cases, index):
    case = sample_cases[index]
    request, reference, _, constraints, _, plan, _ = _solution_for(case)

    for entry in reference["directive_interpretation"]:
        adjustment = entry["structured_adjustment"]
        if adjustment is None:
            continue
        hours = adjustment["hours"]
        kind = entry["directive_type"]

        if kind == "no_charge_window":
            assert all(plan[hour].battery_action.value != "charge" for hour in hours)
        elif kind == "no_discharge_window":
            assert all(plan[hour].battery_action.value != "discharge" for hour in hours)
        elif kind == "max_grid_window":
            assert all(plan[hour].grid_kwh <= adjustment["max_grid_kwh"] + 1e-6 for hour in hours)
        elif kind == "minimum_battery_reserve":
            assert all(
                plan[hour].battery_energy_after_kwh >= adjustment["minimum_energy_kwh"] - 1e-6
                for hour in hours
            )
        elif kind == "solar_reduction":
            for hour in hours:
                base = request.hours[hour].solar_kwh
                assert constraints.effective_solar[hour] == pytest.approx(
                    base * adjustment["factor"], abs=1e-9
                )
