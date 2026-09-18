"""Unit tests for the deterministic energy optimizer."""

from __future__ import annotations

import numpy as np
import pytest

from app.directives import (
    Directive,
    MaxGridWindow,
    MinimumBatteryReserve,
    SolarReduction,
    Window,
    build_constraints,
)
from app.models import BatterySpec, DirectiveType, HourEntry
from app.optimizer import OptimizationError, finalize_schedule, solve_schedule
from app.pipeline import to_plan_entries
from app.validator import validate_plan


def make_hours(demand_from=100.0, solar_peak=200.0, prices=None) -> list[HourEntry]:
    prices = prices or [4.0, 5.0, 6.0, 7.0, 9.0, 12.0, 18.0, 28.0, 30.0, 26.0, 20.0, 10.0]
    entries = []
    for hour in range(24):
        solar = max(0.0, solar_peak * (1 - abs(hour - 12) / 8.0)) if 6 <= hour <= 18 else 0.0
        entries.append(
            HourEntry(
                hour=hour,
                demand_kwh=demand_from + 4 * hour,
                solar_kwh=round(solar, 3),
                tariff_bdt_per_kwh=prices[hour % len(prices)],
            )
        )
    return entries


@pytest.fixture
def battery() -> BatterySpec:
    return BatterySpec(
        capacity_kwh=240,
        initial_energy_kwh=120,
        minimum_energy_kwh=30,
        max_charge_kwh_per_hour=60,
        max_discharge_kwh_per_hour=60,
    )


def solve(hours, battery, directives=()):
    constraints = build_constraints(hours, battery, directives)
    schedule = finalize_schedule(solve_schedule(hours, battery, constraints), hours, battery)
    return schedule, constraints


def cost_of(schedule, hours) -> float:
    return float(sum(schedule.grid[h] * hours[h].tariff_bdt_per_kwh for h in range(24)))


def test_plan_is_valid_and_balanced(battery):
    hours = make_hours()
    schedule, constraints = solve(hours, battery)
    plan = to_plan_entries(schedule)
    totals = validate_plan(plan, hours, battery, constraints)

    assert len(plan) == 24
    assert schedule.energy[-1] == pytest.approx(battery.initial_energy_kwh, abs=1e-6)
    assert totals.total_grid_kwh == pytest.approx(float(schedule.grid.sum()), abs=1e-6)


def test_optimizer_beats_naive_grid_only_operation(battery):
    hours = make_hours()
    schedule, _ = solve(hours, battery)
    naive_cost = sum(entry.demand_kwh * entry.tariff_bdt_per_kwh for entry in hours)
    assert cost_of(schedule, hours) < naive_cost


def test_battery_cycles_at_low_tariff_and_returns_energy(battery):
    hours = make_hours()
    schedule, _ = solve(hours, battery)
    charges = np.flatnonzero(schedule.charge > 1e-6)
    discharges = np.flatnonzero(schedule.discharge > 1e-6)
    assert charges.size and discharges.size

    tariffs = np.array([entry.tariff_bdt_per_kwh for entry in hours])
    assert tariffs[charges].mean() < tariffs[discharges].mean()
    assert schedule.charge.sum() == pytest.approx(schedule.discharge.sum(), abs=1e-6)


def test_charge_and_discharge_never_overlap(battery):
    hours = make_hours()
    schedule, _ = solve(hours, battery)
    assert np.all(np.minimum(schedule.charge, schedule.discharge) < 1e-9)


def test_hourly_rate_limits_are_respected(battery):
    hours = make_hours()
    schedule, _ = solve(hours, battery)
    assert schedule.charge.max() <= battery.max_charge_kwh_per_hour + 1e-6
    assert schedule.discharge.max() <= battery.max_discharge_kwh_per_hour + 1e-6


def test_reserve_directive_raises_the_battery_floor(battery):
    hours = make_hours()
    directive = Directive(
        note_index=0,
        directive_type=DirectiveType.MINIMUM_BATTERY_RESERVE,
        adjustment=MinimumBatteryReserve((18, 19, 20, 21), 200.0),
        explanation="reserve",
    )
    schedule, constraints = solve(hours, battery, [directive])
    for hour in (18, 19, 20, 21):
        assert schedule.energy[hour] >= 200.0 - 1e-6
        assert constraints.reserve_floor[hour] == 200.0
    assert schedule.energy[-1] == pytest.approx(battery.initial_energy_kwh, abs=1e-6)


def test_no_charge_window_forbids_charging_in_those_hours(battery):
    hours = make_hours()
    directive = Directive(
        note_index=0,
        directive_type=DirectiveType.NO_CHARGE_WINDOW,
        adjustment=Window((2, 3, 4)),
        explanation="charger isolated",
    )
    schedule, constraints = solve(hours, battery, [directive])
    for hour in (2, 3, 4):
        assert schedule.charge[hour] == 0.0
        assert not constraints.charge_allowed[hour]
    assert schedule.charge.sum() > 0.0


def test_no_discharge_window_forbids_discharging_in_those_hours(battery):
    hours = make_hours()
    directive = Directive(
        note_index=0,
        directive_type=DirectiveType.NO_DISCHARGE_WINDOW,
        adjustment=Window((18, 19)),
        explanation="relay testing",
    )
    schedule, _ = solve(hours, battery, [directive])
    for hour in (18, 19):
        assert schedule.discharge[hour] == 0.0


def test_max_grid_directive_caps_import(battery):
    hours = make_hours()
    directive = Directive(
        note_index=0,
        directive_type=DirectiveType.MAX_GRID_WINDOW,
        adjustment=MaxGridWindow((18, 19, 20), 150.0),
        explanation="feeder limit",
    )
    schedule, constraints = solve(hours, battery, [directive])
    for hour in (18, 19, 20):
        assert schedule.grid[hour] <= 150.0 + 1e-6
        assert constraints.grid_cap[hour] == 150.0


def test_solar_reduction_lowers_usable_solar(battery):
    hours = make_hours()
    directive = Directive(
        note_index=0,
        directive_type=DirectiveType.SOLAR_REDUCTION,
        adjustment=SolarReduction((11, 12), 0.25),
        explanation="panel cleaning",
    )
    schedule, constraints = solve(hours, battery, [directive])
    for hour in (11, 12):
        assert constraints.effective_solar[hour] == pytest.approx(hours[hour].solar_kwh * 0.25)
        assert schedule.solar_used[hour] <= constraints.effective_solar[hour] + 1e-6


def test_overlapping_directives_combine_strictly(battery):
    hours = make_hours()
    directives = [
        Directive(0, DirectiveType.SOLAR_REDUCTION, SolarReduction((11, 12), 0.5), ""),
        Directive(1, DirectiveType.SOLAR_REDUCTION, SolarReduction((12, 13), 0.5), ""),
        Directive(2, DirectiveType.MINIMUM_BATTERY_RESERVE, MinimumBatteryReserve((12,), 150.0), ""),
        Directive(3, DirectiveType.MAX_GRID_WINDOW, MaxGridWindow((12,), 180.0), ""),
        Directive(4, DirectiveType.MAX_GRID_WINDOW, MaxGridWindow((12,), 160.0), ""),
    ]
    _, constraints = solve(hours, battery, directives)
    assert constraints.effective_solar[11] == pytest.approx(hours[11].solar_kwh * 0.5)
    assert constraints.effective_solar[12] == pytest.approx(hours[12].solar_kwh * 0.25)
    assert constraints.reserve_floor[12] == 150.0
    assert constraints.grid_cap[12] == 160.0


def test_impossible_scenario_raises_rather_than_returning_a_bad_plan():
    hours = make_hours()
    battery = BatterySpec(
        capacity_kwh=100,
        initial_energy_kwh=50,
        minimum_energy_kwh=10,
        max_charge_kwh_per_hour=5,
        max_discharge_kwh_per_hour=5,
    )
    directive = Directive(
        note_index=0,
        directive_type=DirectiveType.MINIMUM_BATTERY_RESERVE,
        adjustment=MinimumBatteryReserve((0,), 100.0),
        explanation="unreachable reserve",
    )
    constraints = build_constraints(hours, battery, [directive])
    with pytest.raises(OptimizationError):
        solve_schedule(hours, battery, constraints)


def test_solution_is_deterministic(battery):
    hours = make_hours()
    first, _ = solve(hours, battery)
    second, _ = solve(hours, battery)
    assert np.allclose(first.grid, second.grid)
    assert np.allclose(first.energy, second.energy)
    assert cost_of(first, hours) == pytest.approx(cost_of(second, hours), abs=1e-12)
