"""Independent replay and validation of the returned schedule.

A 200 response is only produced when the finished plan passes every check the
official evaluator performs. The judge replays ``hourly_plan`` hour by hour
using the effective solar and the ground-truth directives, so this module
performs the same replay before anything is returned:

* exactly 24 plan entries for hours 0 through 23, in ascending order
* energy balance in every hour
* solar usage within the effective (post-reduction) solar availability
* non-negative grid import and battery bounds, transitions and rate limits
* consistency between ``battery_action`` and ``battery_kwh``
* every no-charge, no-discharge, reserve and grid-cap window respected
* end-of-day battery neutrality
* ``total_grid_kwh``, ``total_cost_bdt`` and ``peak_grid_kwh`` recalculated from
  the plan itself, which is the source of truth for the totals
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

from app.directives import DirectiveConstraints
from app.models import (
    HOURS_PER_DAY,
    BatteryAction,
    BatterySpec,
    HourEntry,
    HourlyPlanEntry,
)

#: Internal tolerance. The official evaluator accepts 0.01 kWh / 0.01 BDT, so
#: this is roughly two orders of magnitude stricter while still absorbing
#: floating-point noise from the solver and from plan rounding.
TOLERANCE = 1e-4


class PlanValidationError(RuntimeError):
    """Raised when a candidate schedule violates a hard constraint."""


@dataclass(frozen=True)
class PlanTotals:
    """Aggregates recalculated from ``hourly_plan``."""

    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float


def compute_totals(
    plan: Sequence[HourlyPlanEntry],
    hours: Sequence[HourEntry],
) -> PlanTotals:
    """Recalculate the response aggregates directly from the returned plan."""
    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0
    for entry in plan:
        tariff = hours[entry.hour].tariff_bdt_per_kwh
        total_grid += entry.grid_kwh
        total_cost += entry.grid_kwh * tariff
        peak_grid = max(peak_grid, entry.grid_kwh)
    return PlanTotals(
        total_grid_kwh=round(total_grid, 6),
        total_cost_bdt=round(total_cost, 6),
        peak_grid_kwh=round(peak_grid, 6),
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PlanValidationError(message)


def validate_plan(
    plan: Sequence[HourlyPlanEntry],
    hours: Sequence[HourEntry],
    battery: BatterySpec,
    constraints: DirectiveConstraints,
) -> PlanTotals:
    """Replay the plan and return the recalculated totals, or raise."""
    _require(len(plan) == HOURS_PER_DAY, f"hourly_plan must contain {HOURS_PER_DAY} entries")

    expected_hours = list(range(HOURS_PER_DAY))
    actual_hours = [entry.hour for entry in plan]
    _require(actual_hours == expected_hours, "hourly_plan hours must be 0..23 in ascending order")

    energy = float(battery.initial_energy_kwh)
    capacity = float(battery.capacity_kwh)
    max_charge = float(battery.max_charge_kwh_per_hour)
    max_discharge = float(battery.max_discharge_kwh_per_hour)

    for entry in plan:
        hour = entry.hour
        demand = hours[hour].demand_kwh
        effective_solar = float(constraints.effective_solar[hour])

        _require(entry.grid_kwh >= -TOLERANCE, f"hour {hour}: grid_kwh is negative")
        _require(entry.solar_used_kwh >= -TOLERANCE, f"hour {hour}: solar_used_kwh is negative")
        _require(entry.battery_kwh >= -TOLERANCE, f"hour {hour}: battery_kwh is negative")
        _require(
            entry.solar_used_kwh <= effective_solar + TOLERANCE,
            f"hour {hour}: solar_used_kwh exceeds effective solar",
        )
        _require(
            entry.battery_kwh <= max_charge + TOLERANCE,
            f"hour {hour}: charge rate above max_charge_kwh_per_hour",
        )
        _require(
            entry.battery_kwh <= max_discharge + TOLERANCE,
            f"hour {hour}: discharge rate above max_discharge_kwh_per_hour",
        )

        if entry.battery_action is BatteryAction.CHARGE:
            charge, discharge = entry.battery_kwh, 0.0
            _require(
                constraints.charge_allowed[hour],
                f"hour {hour}: charging is forbidden by a no_charge_window",
            )
        elif entry.battery_action is BatteryAction.DISCHARGE:
            charge, discharge = 0.0, entry.battery_kwh
            _require(
                constraints.discharge_allowed[hour],
                f"hour {hour}: discharging is forbidden by a no_discharge_window",
            )
        else:
            charge = discharge = 0.0
            _require(
                abs(entry.battery_kwh) <= TOLERANCE,
                f"hour {hour}: battery_kwh must be 0 when the action is idle",
            )

        balance = entry.grid_kwh + entry.solar_used_kwh + discharge - demand - charge
        _require(
            abs(balance) <= TOLERANCE,
            f"hour {hour}: energy balance does not hold (off by {balance:.6f} kWh)",
        )

        cap = constraints.grid_cap[hour]
        if cap < float("inf"):
            _require(
                entry.grid_kwh <= cap + TOLERANCE,
                f"hour {hour}: grid_kwh exceeds the max_grid_window cap of {cap}",
            )

        energy = energy + charge - discharge
        _require(
            energy >= constraints.reserve_floor[hour] - TOLERANCE,
            f"hour {hour}: battery energy {energy:.6f} is below the required reserve "
            f"{constraints.reserve_floor[hour]:.6f}",
        )
        _require(energy <= capacity + TOLERANCE, f"hour {hour}: battery energy exceeds capacity")
        _require(
            abs(entry.battery_energy_after_kwh - energy) <= TOLERANCE,
            f"hour {hour}: battery_energy_after_kwh does not match the replayed battery state",
        )

    _require(
        abs(energy - float(battery.initial_energy_kwh)) <= TOLERANCE,
        "end-of-day battery energy must equal initial_energy_kwh",
    )

    return compute_totals(plan, hours)


def verify_reported_totals(reported: PlanTotals, recomputed: PlanTotals) -> None:
    """Ensure the reported aggregates match a recalculation from ``hourly_plan``."""
    pairs: Tuple[Tuple[str, float, float], ...] = (
        ("total_grid_kwh", reported.total_grid_kwh, recomputed.total_grid_kwh),
        ("total_cost_bdt", reported.total_cost_bdt, recomputed.total_cost_bdt),
        ("peak_grid_kwh", reported.peak_grid_kwh, recomputed.peak_grid_kwh),
    )
    for name, reported_value, recomputed_value in pairs:
        _require(
            abs(reported_value - recomputed_value) <= TOLERANCE,
            f"{name} does not match the value recalculated from hourly_plan",
        )
