"""End-to-end request pipeline.

Incoming JSON
  -> language-model interpretation of ``operator_notes``
  -> deterministic guardrails
  -> directive constraints
  -> linear-programming energy optimizer
  -> independent replay and validation
  -> structured JSON response

The optimizer never sees raw text and the language model never sees the cost
objective, which keeps the two responsibilities strictly separated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Sequence, Tuple

import numpy as np

from app.directives import Directive, DirectiveConstraints, build_constraints
from app.guardrails import to_wire
from app.llm_interpreter import LLMInterpreter
from app.models import (
    HOURS_PER_DAY,
    BatteryAction,
    HourlyPlanEntry,
    OptimizeResponse,
    ScenarioRequest,
)
from app.optimizer import (
    ZERO_TOLERANCE,
    HourlySchedule,
    OptimizationError,
    build_plan_summary,
    finalize_schedule,
    solve_schedule,
)
from app.validator import PlanTotals, validate_plan, verify_reported_totals

LOGGER = logging.getLogger("gridwise.pipeline")


@dataclass
class PipelineResult:
    """Response payload plus provenance useful for logging and diagnostics."""

    response: OptimizeResponse
    interpreter_source: str
    degraded: bool
    repairs: List[str]


def to_plan_entries(schedule: HourlySchedule) -> List[HourlyPlanEntry]:
    """Convert solver arrays into the wire-format hourly plan."""
    plan: List[HourlyPlanEntry] = []
    for hour in range(HOURS_PER_DAY):
        charge = float(schedule.charge[hour])
        discharge = float(schedule.discharge[hour])

        if charge > ZERO_TOLERANCE:
            action = BatteryAction.CHARGE
            magnitude = charge
        elif discharge > ZERO_TOLERANCE:
            action = BatteryAction.DISCHARGE
            magnitude = discharge
        else:
            action = BatteryAction.IDLE
            magnitude = 0.0

        plan.append(
            HourlyPlanEntry(
                hour=hour,
                grid_kwh=round(float(schedule.grid[hour]), 6),
                solar_used_kwh=round(float(schedule.solar_used[hour]), 6),
                battery_action=action,
                battery_kwh=round(magnitude, 6),
                battery_energy_after_kwh=round(float(schedule.energy[hour]), 6),
            )
        )
    return plan


def _solve(
    request: ScenarioRequest,
    directives: Sequence[Directive],
    constraints: DirectiveConstraints,
) -> Tuple[HourlySchedule, DirectiveConstraints]:
    """Solve the schedule, degrading gracefully if the constraints conflict.

    Organizer scoring scenarios are guaranteed feasible, so the degradation
    path is defensive only: it keeps the service returning a valid schedule
    instead of an error when a caller sends contradictory directives.
    """
    try:
        schedule = solve_schedule(request.hours, request.battery, constraints)
        return finalize_schedule(schedule, request.hours, request.battery), constraints
    except OptimizationError as exc:
        LOGGER.warning("full constraint set is infeasible (%s), retrying with fewer directives", exc)

    active = [directive for directive in directives if directive.applies]
    for drop_index in range(len(active)):
        subset = [d for i, d in enumerate(active) if i != drop_index]
        subset_constraints = build_constraints(request.hours, request.battery, subset)
        try:
            schedule = solve_schedule(request.hours, request.battery, subset_constraints)
            return finalize_schedule(schedule, request.hours, request.battery), subset_constraints
        except OptimizationError:
            continue

    bare = build_constraints(request.hours, request.battery, [])
    try:
        schedule = solve_schedule(request.hours, request.battery, bare)
    except OptimizationError as exc:
        raise OptimizationError(
            "the base scenario has no feasible schedule for the supplied battery parameters"
        ) from exc
    return finalize_schedule(schedule, request.hours, request.battery), bare


async def optimize(request: ScenarioRequest, interpreter: LLMInterpreter) -> PipelineResult:
    """Run the full interpretation and optimization pipeline for one scenario."""
    outcome = await interpreter.interpret(
        request.scenario_id, request.operator_notes, request.battery, request.hours
    )

    constraints = build_constraints(request.hours, request.battery, outcome.directives)
    schedule, used_constraints = _solve(request, outcome.directives, constraints)

    plan = to_plan_entries(schedule)
    totals: PlanTotals = validate_plan(plan, request.hours, request.battery, used_constraints)

    tariff = np.array([entry.tariff_bdt_per_kwh for entry in request.hours], dtype=float)
    ignored = sum(1 for directive in outcome.directives if not directive.applies)

    response = OptimizeResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=to_wire(outcome.directives),
        hourly_plan=plan,
        total_grid_kwh=totals.total_grid_kwh,
        total_cost_bdt=totals.total_cost_bdt,
        peak_grid_kwh=totals.peak_grid_kwh,
        plan_summary=build_plan_summary(
            schedule=schedule,
            hours=request.hours,
            battery=request.battery,
            constraints=used_constraints,
            ignored_notes=ignored,
            total_cost=totals.total_cost_bdt,
            total_grid=totals.total_grid_kwh,
            peak_grid=totals.peak_grid_kwh,
        ),
    )

    # Final self-check: the reported aggregates must equal a recalculation from
    # hourly_plan, exactly as the evaluator will do it.
    verify_reported_totals(
        PlanTotals(response.total_grid_kwh, response.total_cost_bdt, response.peak_grid_kwh),
        totals,
    )

    return PipelineResult(
        response=response,
        interpreter_source=outcome.source,
        degraded=used_constraints is not constraints,
        repairs=outcome.repairs,
    )
