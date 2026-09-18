"""Directive domain model and deterministic constraint resolution.

The language model produces *interpretations*; this module turns the validated
interpretations into the numeric constraint arrays that are handed to the
optimizer. Every rule here comes straight from Section 5.3 of the official
problem statement:

* ``solar_reduction``          - ``effective_solar[h] = original_solar[h] * factor``
* ``minimum_battery_reserve``  - ``battery_energy_after_kwh[h] >= directive minimum``
* ``no_charge_window``         - battery charge amount is 0 in the listed hours
* ``no_discharge_window``      - battery discharge amount is 0 in the listed hours
* ``max_grid_window``          - ``grid_kwh[h] <= max_grid_kwh`` in the listed hours
* ``no_op``                    - no change to the optimization model
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.models import (
    HOURS_PER_DAY,
    BatterySpec,
    DirectiveInterpretationEntry,
    DirectiveType,
    HourEntry,
)


@dataclass(frozen=True)
class StructuredAdjustment:
    """Base class for the machine-checkable directive payloads."""

    def to_wire(self) -> Dict[str, Any]:  # pragma: no cover - overridden
        raise NotImplementedError


@dataclass(frozen=True)
class SolarReduction(StructuredAdjustment):
    """Reduce usable solar during the listed hours by a remaining fraction."""

    hours: Tuple[int, ...]
    factor: float

    def to_wire(self) -> Dict[str, Any]:
        return {"hours": list(self.hours), "factor": round(float(self.factor), 6)}


@dataclass(frozen=True)
class MinimumBatteryReserve(StructuredAdjustment):
    """Raise the battery energy floor during the listed hours."""

    hours: Tuple[int, ...]
    minimum_energy_kwh: float

    def to_wire(self) -> Dict[str, Any]:
        return {
            "hours": list(self.hours),
            "minimum_energy_kwh": round(float(self.minimum_energy_kwh), 6),
        }


@dataclass(frozen=True)
class Window(StructuredAdjustment):
    """An hours-only window used by the no-charge and no-discharge directives."""

    hours: Tuple[int, ...]

    def to_wire(self) -> Dict[str, Any]:
        return {"hours": list(self.hours)}


@dataclass(frozen=True)
class MaxGridWindow(StructuredAdjustment):
    """Cap grid import during the listed hours."""

    hours: Tuple[int, ...]
    max_grid_kwh: float

    def to_wire(self) -> Dict[str, Any]:
        return {
            "hours": list(self.hours),
            "max_grid_kwh": round(float(self.max_grid_kwh), 6),
        }


@dataclass(frozen=True)
class Directive:
    """A validated directive bound to the note it was extracted from."""

    note_index: int
    directive_type: DirectiveType
    adjustment: Optional[StructuredAdjustment]
    explanation: str

    @property
    def applies(self) -> bool:
        return self.directive_type is not DirectiveType.NO_OP

    def to_wire(self) -> DirectiveInterpretationEntry:
        return DirectiveInterpretationEntry(
            note_index=self.note_index,
            applies=self.applies,
            directive_type=self.directive_type,
            structured_adjustment=None if self.adjustment is None else self.adjustment.to_wire(),
            explanation=self.explanation,
        )


def no_op(note_index: int, explanation: str) -> Directive:
    """Build a ``no_op`` directive, the only shape allowed with ``applies=false``."""
    return Directive(
        note_index=note_index,
        directive_type=DirectiveType.NO_OP,
        adjustment=None,
        explanation=explanation,
    )


@dataclass
class DirectiveConstraints:
    """Numeric constraint set the optimizer must satisfy."""

    solar_factor: np.ndarray
    effective_solar: np.ndarray
    reserve_floor: np.ndarray
    charge_allowed: np.ndarray
    discharge_allowed: np.ndarray
    grid_cap: np.ndarray
    applied_types: List[DirectiveType]

    def describe(self) -> str:
        """Short human-readable description used in ``plan_summary``."""
        labels = {
            DirectiveType.SOLAR_REDUCTION: "solar reduction",
            DirectiveType.MINIMUM_BATTERY_RESERVE: "battery reserve",
            DirectiveType.NO_CHARGE_WINDOW: "no-charge window",
            DirectiveType.NO_DISCHARGE_WINDOW: "no-discharge window",
            DirectiveType.MAX_GRID_WINDOW: "grid cap",
        }
        return ", ".join(labels[t] for t in self.applied_types)


def build_constraints(
    hours: Sequence[HourEntry],
    battery: BatterySpec,
    directives: Sequence[Directive],
) -> DirectiveConstraints:
    """Fold every validated directive into the optimizer constraint arrays.

    Overlapping directives combine the way the specification implies: solar
    factors multiply, reserve floors take the strictest value, grid caps take
    the tightest cap, and any no-charge/no-discharge window removes the action
    entirely.
    """
    base_solar = np.array([entry.solar_kwh for entry in hours], dtype=float)

    solar_factor = np.ones(HOURS_PER_DAY, dtype=float)
    reserve_floor = np.full(HOURS_PER_DAY, float(battery.minimum_energy_kwh), dtype=float)
    charge_allowed = np.ones(HOURS_PER_DAY, dtype=bool)
    discharge_allowed = np.ones(HOURS_PER_DAY, dtype=bool)
    grid_cap = np.full(HOURS_PER_DAY, np.inf, dtype=float)
    applied: List[DirectiveType] = []

    for directive in directives:
        adjustment = directive.adjustment
        if not directive.applies or adjustment is None:
            continue

        if isinstance(adjustment, SolarReduction):
            solar_factor[list(adjustment.hours)] *= float(adjustment.factor)
        elif isinstance(adjustment, MinimumBatteryReserve):
            reserve_floor[list(adjustment.hours)] = np.maximum(
                reserve_floor[list(adjustment.hours)], float(adjustment.minimum_energy_kwh)
            )
        elif directive.directive_type is DirectiveType.NO_CHARGE_WINDOW:
            charge_allowed[list(adjustment.hours)] = False
        elif directive.directive_type is DirectiveType.NO_DISCHARGE_WINDOW:
            discharge_allowed[list(adjustment.hours)] = False
        elif isinstance(adjustment, MaxGridWindow):
            grid_cap[list(adjustment.hours)] = np.minimum(
                grid_cap[list(adjustment.hours)], float(adjustment.max_grid_kwh)
            )
        else:  # pragma: no cover - guardrails never emit an unknown pairing
            continue

        applied.append(directive.directive_type)

    effective_solar = base_solar * solar_factor

    return DirectiveConstraints(
        solar_factor=solar_factor,
        effective_solar=effective_solar,
        reserve_floor=reserve_floor,
        charge_allowed=charge_allowed,
        discharge_allowed=discharge_allowed,
        grid_cap=grid_cap,
        applied_types=applied,
    )
