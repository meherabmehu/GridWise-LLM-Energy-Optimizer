"""Unit tests for the final schedule validator.

The validator is deliberately hard to satisfy: these tests build plans that
break one rule each and confirm the validator catches them.
"""

from __future__ import annotations

import copy

import pytest

from app.directives import (
    Directive,
    MaxGridWindow,
    MinimumBatteryReserve,
    Window,
    build_constraints,
)
from app.models import BatterySpec, DirectiveType
from app.optimizer import finalize_schedule, solve_schedule
from app.pipeline import to_plan_entries
from app.validator import (
    PlanTotals,
    PlanValidationError,
    compute_totals,
    validate_plan,
    verify_reported_totals,
)
from tests.test_optimizer import make_hours


@pytest.fixture
def battery() -> BatterySpec:
    return BatterySpec(
        capacity_kwh=240,
        initial_energy_kwh=120,
        minimum_energy_kwh=30,
        max_charge_kwh_per_hour=60,
        max_discharge_kwh_per_hour=60,
    )


@pytest.fixture
def baseline(battery):
    hours = make_hours()
    constraints = build_constraints(hours, battery, [])
    schedule = finalize_schedule(solve_schedule(hours, battery, constraints), hours, battery)
    return hours, battery, constraints, to_plan_entries(schedule)


def as_dicts(plan):
    return [entry.model_dump() for entry in plan]


def rebuild(plan_dicts):
    from app.models import HourlyPlanEntry

    return [HourlyPlanEntry.model_validate(item) for item in plan_dicts]


def test_valid_plan_passes(baseline):
    hours, battery, constraints, plan = baseline
    totals = validate_plan(plan, hours, battery, constraints)
    assert totals.total_grid_kwh > 0


def test_wrong_number_of_entries_is_rejected(baseline):
    hours, battery, constraints, plan = baseline
    with pytest.raises(PlanValidationError, match="24 entries"):
        validate_plan(plan[:23], hours, battery, constraints)


def test_out_of_order_hours_are_rejected(baseline):
    hours, battery, constraints, plan = baseline
    shuffled = as_dicts(plan)
    shuffled[0], shuffled[1] = shuffled[1], shuffled[0]
    with pytest.raises(PlanValidationError, match="ascending"):
        validate_plan(rebuild(shuffled), hours, battery, constraints)


def test_energy_balance_violation_is_rejected(baseline):
    hours, battery, constraints, plan = baseline
    broken = as_dicts(plan)
    broken[7]["grid_kwh"] += 5.0
    with pytest.raises(PlanValidationError, match="energy balance"):
        validate_plan(rebuild(broken), hours, battery, constraints)


def test_solar_overuse_is_rejected(baseline):
    hours, battery, constraints, plan = baseline
    broken = as_dicts(plan)
    hour = max(range(24), key=lambda h: hours[h].solar_kwh)
    broken[hour]["solar_used_kwh"] = hours[hour].solar_kwh + 10.0
    broken[hour]["grid_kwh"] = max(0.0, broken[hour]["grid_kwh"] - 10.0)
    with pytest.raises(PlanValidationError, match="effective solar"):
        validate_plan(rebuild(broken), hours, battery, constraints)


def test_negative_grid_is_rejected(baseline):
    hours, battery, constraints, plan = baseline
    broken = as_dicts(plan)
    broken[3]["grid_kwh"] = -1.0
    with pytest.raises(PlanValidationError, match="negative"):
        validate_plan(rebuild(broken), hours, battery, constraints)


def test_rate_limit_violation_is_rejected(baseline):
    hours, battery, constraints, plan = baseline
    broken = as_dicts(plan)
    broken[2].update(
        battery_action="charge",
        battery_kwh=battery.max_charge_kwh_per_hour + 20.0,
        grid_kwh=broken[2]["grid_kwh"] + 20.0,
    )
    with pytest.raises(PlanValidationError, match="max_charge"):
        validate_plan(rebuild(broken), hours, battery, constraints)


def test_idle_hour_with_non_zero_magnitude_is_rejected(baseline):
    hours, battery, constraints, plan = baseline
    broken = as_dicts(plan)
    broken[5].update(battery_action="idle", battery_kwh=3.0)
    with pytest.raises(PlanValidationError, match="idle"):
        validate_plan(rebuild(broken), hours, battery, constraints)


def test_misreported_battery_state_is_rejected(baseline):
    hours, battery, constraints, plan = baseline
    broken = as_dicts(plan)
    broken[9]["battery_energy_after_kwh"] += 12.0
    with pytest.raises(PlanValidationError, match="replayed battery state"):
        validate_plan(rebuild(broken), hours, battery, constraints)


def test_broken_end_of_day_neutrality_is_rejected(baseline):
    hours, battery, constraints, plan = baseline
    broken = as_dicts(plan)
    for item in broken:
        if item["battery_action"] == "discharge":
            item["battery_kwh"] = round(item["battery_kwh"] * 0.9, 6)
            item["grid_kwh"] = round(item["grid_kwh"] + item["battery_kwh"] * 0.1, 6)
    with pytest.raises(PlanValidationError):
        validate_plan(rebuild(broken), hours, battery, constraints)


def test_forbidden_charge_window_is_rejected(baseline):
    hours, battery, _, plan = baseline
    charging_hours = tuple(e.hour for e in plan if e.battery_action == "charge")
    assert charging_hours, "baseline schedule should charge at some point"
    constraints = build_constraints(
        hours,
        battery,
        [
            Directive(
                note_index=0,
                directive_type=DirectiveType.NO_CHARGE_WINDOW,
                adjustment=Window(charging_hours),
                explanation="charger isolated",
            )
        ],
    )
    with pytest.raises(PlanValidationError, match="no_charge_window"):
        validate_plan(plan, hours, battery, constraints)


def test_grid_cap_violation_is_rejected(baseline):
    hours, battery, _, plan = baseline
    constraints = build_constraints(
        hours,
        battery,
        [
            Directive(
                note_index=0,
                directive_type=DirectiveType.MAX_GRID_WINDOW,
                adjustment=MaxGridWindow(tuple(range(24)), 10.0),
                explanation="impossible cap",
            )
        ],
    )
    with pytest.raises(PlanValidationError, match="max_grid_window"):
        validate_plan(plan, hours, battery, constraints)


def test_reserve_violation_is_rejected(baseline):
    hours, battery, _, plan = baseline
    constraints = build_constraints(
        hours,
        battery,
        [
            Directive(
                note_index=0,
                directive_type=DirectiveType.MINIMUM_BATTERY_RESERVE,
                adjustment=MinimumBatteryReserve(tuple(range(24)), battery.capacity_kwh),
                explanation="full reserve",
            )
        ],
    )
    with pytest.raises(PlanValidationError, match="reserve"):
        validate_plan(plan, hours, battery, constraints)


def test_totals_are_recalculated_from_the_plan(baseline):
    hours, _, _, plan = baseline
    totals = compute_totals(plan, hours)
    assert totals.total_grid_kwh == pytest.approx(sum(e.grid_kwh for e in plan), abs=1e-6)
    assert totals.peak_grid_kwh == pytest.approx(max(e.grid_kwh for e in plan), abs=1e-6)
    assert totals.total_cost_bdt == pytest.approx(
        sum(e.grid_kwh * hours[e.hour].tariff_bdt_per_kwh for e in plan), abs=1e-6
    )


def test_reported_totals_must_match_recalculation():
    reported = PlanTotals(100.0, 900.0, 12.0)
    verify_reported_totals(reported, PlanTotals(100.0, 900.0, 12.0))
    with pytest.raises(PlanValidationError, match="total_cost_bdt"):
        verify_reported_totals(reported, PlanTotals(100.0, 900.5, 12.0))


def test_validator_is_not_fooled_by_a_cheap_invalid_plan(baseline):
    """A plan that imports less energy than the campus consumes must be rejected."""
    hours, battery, constraints, plan = baseline
    cheap = as_dicts(plan)
    for item in cheap:
        item["grid_kwh"] = round(item["grid_kwh"] * 0.5, 6)
    with pytest.raises(PlanValidationError, match="energy balance"):
        validate_plan(rebuild(cheap), hours, battery, constraints)


def test_plan_dicts_are_not_mutated_by_validation(baseline):
    hours, battery, constraints, plan = baseline
    snapshot = copy.deepcopy(as_dicts(plan))
    validate_plan(plan, hours, battery, constraints)
    assert as_dicts(plan) == snapshot
