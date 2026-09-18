"""Deterministic cost-minimizing scheduler for the 24-hour horizon.

The scheduling problem is a compact linear program, so it is solved exactly
with HiGHS through ``scipy.optimize.linprog``: the same optimum is produced on
every run and a solve takes single-digit milliseconds.

Decision variables, laid out hour-major with five variables per hour
--------------------------------------------------------------------
``grid[h]``       grid energy purchased          (>= 0)
``solar[h]``      solar energy used              (0 <= x <= effective solar)
``charge[h]``     battery energy added           (0 <= x <= max charge rate)
``discharge[h]``  battery energy removed         (0 <= x <= max discharge rate)
``energy[h]``     battery energy after the hour  (reserve floor <= x <= capacity)

Constraints
-----------
``grid + solar + discharge == demand + charge``      energy balance, every hour
``energy[h] - energy[h-1] - charge + discharge == 0`` battery state transition
``energy[23] == initial_energy_kwh``                 end-of-day neutrality
``grid[h] <= max_grid_kwh``                          max-grid directive windows
plus every no-charge, no-discharge and reserve window produced by the
operator directives.

Objective
---------
``total_cost_bdt = SUM(grid[h] * tariff[h])``, minimized.

A second lexicographic pass then minimizes battery throughput subject to the
cost found by the first pass. That removes battery cycling that buys nothing
while leaving the optimal cost unchanged to within a floating-point epsilon.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import linprog

from app.directives import DirectiveConstraints
from app.models import HOURS_PER_DAY, BatterySpec, HourEntry

LOGGER = logging.getLogger("gridwise.optimizer")

#: Solver output below this magnitude is floating-point noise.
ZERO_TOLERANCE = 1e-7

#: Slack allowed when pinning the second pass to the optimal cost.
COST_EPSILON = 1e-6

#: Decimals kept in the returned plan. The official tolerance is 0.01, so six
#: decimals leave five orders of magnitude of headroom.
PLAN_PRECISION = 6

VARIABLES_PER_HOUR = 5


class OptimizationError(RuntimeError):
    """Raised when no schedule satisfying the active constraints exists."""


@dataclass
class HourlySchedule:
    """Solver output for all 24 hours, aligned by hour index."""

    grid: np.ndarray
    solar_used: np.ndarray
    charge: np.ndarray
    discharge: np.ndarray
    energy: np.ndarray


@dataclass(frozen=True)
class _Layout:
    grid: np.ndarray
    solar: np.ndarray
    charge: np.ndarray
    discharge: np.ndarray
    energy: np.ndarray

    @property
    def size(self) -> int:
        return HOURS_PER_DAY * VARIABLES_PER_HOUR


def _layout() -> _Layout:
    base = np.arange(HOURS_PER_DAY) * VARIABLES_PER_HOUR
    return _Layout(
        grid=base,
        solar=base + 1,
        charge=base + 2,
        discharge=base + 3,
        energy=base + 4,
    )


def _assemble(
    demand: np.ndarray,
    battery: BatterySpec,
    constraints: DirectiveConstraints,
) -> Tuple[np.ndarray, np.ndarray, List[Tuple[float, Optional[float]]], np.ndarray, np.ndarray, _Layout]:
    """Build the equality system, bounds and grid-cap inequalities for one solve."""
    layout = _layout()
    hours = np.arange(HOURS_PER_DAY)
    size = layout.size

    # Energy balance: grid + solar - charge + discharge = demand
    balance = np.zeros((HOURS_PER_DAY, size))
    balance[hours, layout.grid] = 1.0
    balance[hours, layout.solar] = 1.0
    balance[hours, layout.charge] = -1.0
    balance[hours, layout.discharge] = 1.0

    # Battery transition: energy[h] - energy[h-1] - charge + discharge = 0,
    # with energy[-1] treated as the given initial energy.
    transition = np.zeros((HOURS_PER_DAY, size))
    transition[hours, layout.energy] = 1.0
    transition[hours[1:], layout.energy[:-1]] -= 1.0
    transition[hours, layout.charge] = -1.0
    transition[hours, layout.discharge] = 1.0

    # End-of-day neutrality.
    neutrality = np.zeros((1, size))
    neutrality[0, layout.energy[-1]] = 1.0

    matrix = np.vstack([balance, transition, neutrality])
    rhs = np.concatenate(
        [
            demand,
            np.concatenate([[float(battery.initial_energy_kwh)], np.zeros(HOURS_PER_DAY - 1)]),
            [float(battery.initial_energy_kwh)],
        ]
    )

    max_charge = float(battery.max_charge_kwh_per_hour)
    max_discharge = float(battery.max_discharge_kwh_per_hour)
    capacity = float(battery.capacity_kwh)

    bounds: List[Tuple[float, Optional[float]]] = [(0.0, None)] * size
    for hour in range(HOURS_PER_DAY):
        bounds[layout.solar[hour]] = (0.0, float(constraints.effective_solar[hour]))
        bounds[layout.charge[hour]] = (0.0, max_charge if constraints.charge_allowed[hour] else 0.0)
        bounds[layout.discharge[hour]] = (
            0.0,
            max_discharge if constraints.discharge_allowed[hour] else 0.0,
        )
        bounds[layout.energy[hour]] = (float(constraints.reserve_floor[hour]), capacity)

    # grid[h] <= max_grid_kwh for the capped hours only.
    capped_hours = np.flatnonzero(np.isfinite(constraints.grid_cap))
    cap_matrix = np.zeros((capped_hours.size, size))
    cap_matrix[np.arange(capped_hours.size), layout.grid[capped_hours]] = 1.0
    cap_rhs = constraints.grid_cap[capped_hours].astype(float)

    return matrix, rhs, bounds, cap_matrix, cap_rhs, layout


def solve_schedule(
    hours: Sequence[HourEntry],
    battery: BatterySpec,
    constraints: DirectiveConstraints,
    minimize_throughput: bool = True,
) -> HourlySchedule:
    """Return the cost-optimal schedule satisfying every active constraint."""
    demand = np.array([entry.demand_kwh for entry in hours], dtype=float)
    tariff = np.array([entry.tariff_bdt_per_kwh for entry in hours], dtype=float)

    matrix, rhs, bounds, cap_matrix, cap_rhs, layout = _assemble(demand, battery, constraints)

    cost_vector = np.zeros(layout.size)
    cost_vector[layout.grid] = tariff

    result = linprog(
        c=cost_vector,
        A_eq=matrix,
        b_eq=rhs,
        A_ub=cap_matrix if cap_matrix.size else None,
        b_ub=cap_rhs if cap_matrix.size else None,
        bounds=bounds,
        method="highs",
    )
    if not result.success:
        raise OptimizationError(f"no feasible schedule exists ({result.message})")

    solution = np.asarray(result.x, dtype=float)

    if minimize_throughput:
        solution = _refine_for_throughput(
            solution=solution,
            optimal_cost=float(result.fun),
            cost_vector=cost_vector,
            matrix=matrix,
            rhs=rhs,
            cap_matrix=cap_matrix,
            cap_rhs=cap_rhs,
            bounds=bounds,
            layout=layout,
        )

    return HourlySchedule(
        grid=np.clip(solution[layout.grid], 0.0, None),
        solar_used=np.clip(solution[layout.solar], 0.0, constraints.effective_solar),
        charge=np.clip(solution[layout.charge], 0.0, None),
        discharge=np.clip(solution[layout.discharge], 0.0, None),
        energy=np.asarray(solution[layout.energy], dtype=float),
    )


def _refine_for_throughput(
    solution: np.ndarray,
    optimal_cost: float,
    cost_vector: np.ndarray,
    matrix: np.ndarray,
    rhs: np.ndarray,
    cap_matrix: np.ndarray,
    cap_rhs: np.ndarray,
    bounds: List[Tuple[float, Optional[float]]],
    layout: _Layout,
) -> np.ndarray:
    """Second lexicographic pass: keep the optimal cost, drop useless cycling."""
    throughput = np.zeros(layout.size)
    throughput[layout.charge] = 1.0
    throughput[layout.discharge] = 1.0

    if cap_matrix.size:
        pinned_matrix = np.vstack([matrix, cap_matrix, cost_vector])
        pinned_rhs = np.concatenate([rhs, cap_rhs, [optimal_cost + COST_EPSILON]])
    else:
        pinned_matrix = np.vstack([matrix, cost_vector])
        pinned_rhs = np.concatenate([rhs, [optimal_cost + COST_EPSILON]])

    refined = linprog(
        c=throughput,
        A_eq=pinned_matrix,
        b_eq=pinned_rhs,
        bounds=bounds,
        method="highs",
    )
    if refined.success:
        return np.asarray(refined.x, dtype=float)
    LOGGER.debug("throughput refinement failed, keeping the primary solution")
    return solution


def finalize_schedule(
    schedule: HourlySchedule,
    hours: Sequence[HourEntry],
    battery: BatterySpec,
) -> HourlySchedule:
    """Snap solver output to a clean plan that satisfies the accounting exactly.

    Simultaneous charge and discharge buys nothing at the optimum, so any
    transfer between the two is netted out. ``grid`` is then derived from the
    energy balance and ``energy`` is re-simulated from the transition equation,
    which makes both relationships hold exactly instead of approximately.
    """
    demand = np.array([entry.demand_kwh for entry in hours], dtype=float)

    solar_used = np.round(np.clip(schedule.solar_used, 0.0, None), PLAN_PRECISION)
    charge = np.round(np.clip(schedule.charge, 0.0, None), PLAN_PRECISION)
    discharge = np.round(np.clip(schedule.discharge, 0.0, None), PLAN_PRECISION)

    transfer = np.minimum(charge, discharge)
    charge = charge - transfer
    discharge = discharge - transfer

    solar_used[solar_used < ZERO_TOLERANCE] = 0.0
    charge[charge < ZERO_TOLERANCE] = 0.0
    discharge[discharge < ZERO_TOLERANCE] = 0.0

    solar_used = np.minimum(solar_used, np.round(schedule.solar_used, PLAN_PRECISION))

    grid = np.round(demand + charge - solar_used - discharge, PLAN_PRECISION)
    # Rounding alone can push a nearly zero hour slightly negative; trim solar
    # usage there rather than reporting a negative grid import.
    deficit = grid < 0.0
    if deficit.any():
        solar_used[deficit] = np.round(solar_used[deficit] + grid[deficit], PLAN_PRECISION)
        grid[deficit] = 0.0
    grid[grid < ZERO_TOLERANCE] = 0.0

    energy = np.empty(HOURS_PER_DAY, dtype=float)
    running = float(battery.initial_energy_kwh)
    for hour in range(HOURS_PER_DAY):
        running += charge[hour] - discharge[hour]
        energy[hour] = round(min(max(running, 0.0), float(battery.capacity_kwh)), PLAN_PRECISION)

    return HourlySchedule(
        grid=grid, solar_used=solar_used, charge=charge, discharge=discharge, energy=energy
    )


def build_plan_summary(
    schedule: HourlySchedule,
    hours: Sequence[HourEntry],
    battery: BatterySpec,
    constraints: DirectiveConstraints,
    ignored_notes: int,
    total_cost: float,
    total_grid: float,
    peak_grid: float,
) -> str:
    """Compose the short human-readable strategy description."""
    tariffs = [entry.tariff_bdt_per_kwh for entry in hours]
    cheapest = sorted(range(HOURS_PER_DAY), key=lambda hour: tariffs[hour])[:3]
    priciest = sorted(range(HOURS_PER_DAY), key=lambda hour: tariffs[hour], reverse=True)[:3]
    charging = np.flatnonzero(schedule.charge > ZERO_TOLERANCE)
    discharging = np.flatnonzero(schedule.discharge > ZERO_TOLERANCE)

    parts: List[str] = []
    if constraints.applied_types:
        parts.append(f"Applied operator directives: {constraints.describe()}.")
    else:
        parts.append("No operator directive changed the scheduling problem.")
    if ignored_notes:
        parts.append(f"Ignored {ignored_notes} note(s) unrelated to the 24-hour schedule.")

    if charging.size:
        parts.append(f"Charges in the cheapest hours ({_hour_list(charging)}).")
    if discharging.size:
        parts.append(f"Discharges into the most expensive hours ({_hour_list(discharging)}).")
    if not charging.size and not discharging.size:
        parts.append("The battery stays idle and demand is served by solar and the grid.")

    parts.append(
        f"Cheapest tariff hours are {_hour_list(cheapest)} and the priciest are {_hour_list(priciest)}."
    )
    parts.append(
        f"Totals: {total_grid:.2f} kWh grid import, {total_cost:.2f} BDT, "
        f"{peak_grid:.2f} kWh peak; the battery ends at {schedule.energy[-1]:.2f} kWh "
        f"matching its {battery.initial_energy_kwh:g} kWh starting level."
    )
    return " ".join(parts)


def _hour_list(indices) -> str:
    return ", ".join(f"{int(hour):02d}:00" for hour in indices)
