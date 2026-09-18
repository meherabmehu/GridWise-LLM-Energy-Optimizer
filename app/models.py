"""Wire-contract models for the GridWise API.

These mirror the canonical request and response schemas from the official
preliminary problem statement. The hourly ``hours`` request array holds
demand, solar and tariff, and its end-hour convention matches the operator-note
whole-hour convention (start inclusive, end exclusive).
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HOURS_PER_DAY = 24
ALL_HOURS = tuple(range(HOURS_PER_DAY))

#: The problem statement specifies 1-3 notes per scenario. A slightly higher cap
#: keeps the service tolerant of a richer harness payload while still bounding
#: the work an unauthenticated caller can request.
MAX_OPERATOR_NOTES = 16


class DirectiveType(str, Enum):
    """Directive types accepted by the canonical specification (Section 04)."""

    SOLAR_REDUCTION = "solar_reduction"
    MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
    NO_CHARGE_WINDOW = "no_charge_window"
    NO_DISCHARGE_WINDOW = "no_discharge_window"
    MAX_GRID_WINDOW = "max_grid_window"
    NO_OP = "no_op"


class BatteryAction(str, Enum):
    """Allowed battery actions in the hourly plan."""

    CHARGE = "charge"
    DISCHARGE = "discharge"
    IDLE = "idle"


def _require_finite(value: float, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be a finite number")
    return number


class HourEntry(BaseModel):
    """One hour of the requested 24-hour scenario."""

    model_config = ConfigDict(extra="ignore")

    hour: int
    demand_kwh: float
    solar_kwh: float
    tariff_bdt_per_kwh: float

    @field_validator("hour")
    @classmethod
    def _check_hour(cls, value: int) -> int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("hour must be an integer")
        if value not in ALL_HOURS:
            raise ValueError("hour must be between 0 and 23")
        return value

    @field_validator("demand_kwh", "solar_kwh", "tariff_bdt_per_kwh")
    @classmethod
    def _check_non_negative(cls, value: float, info) -> float:
        number = _require_finite(value, info.field_name)
        if number < 0:
            raise ValueError(f"{info.field_name} must be non-negative")
        return number


class BatterySpec(BaseModel):
    """Battery parameters supplied with the scenario."""

    model_config = ConfigDict(extra="ignore")

    capacity_kwh: float
    initial_energy_kwh: float
    minimum_energy_kwh: float
    max_charge_kwh_per_hour: float
    max_discharge_kwh_per_hour: float

    @field_validator(
        "capacity_kwh",
        "initial_energy_kwh",
        "minimum_energy_kwh",
        "max_charge_kwh_per_hour",
        "max_discharge_kwh_per_hour",
    )
    @classmethod
    def _check_finite(cls, value: float, info) -> float:
        return _require_finite(value, info.field_name)

    @model_validator(mode="after")
    def _check_consistency(self) -> "BatterySpec":
        if self.capacity_kwh <= 0:
            raise ValueError("capacity_kwh must be greater than zero")
        if self.minimum_energy_kwh < 0:
            raise ValueError("minimum_energy_kwh must be non-negative")
        if self.minimum_energy_kwh > self.capacity_kwh:
            raise ValueError("minimum_energy_kwh must not exceed capacity_kwh")
        if not 0 <= self.initial_energy_kwh <= self.capacity_kwh:
            raise ValueError("initial_energy_kwh must be within [0, capacity_kwh]")
        if self.max_charge_kwh_per_hour < 0 or self.max_discharge_kwh_per_hour < 0:
            raise ValueError("battery hourly rate limits must be non-negative")
        return self


class ScenarioRequest(BaseModel):
    """``POST /optimize-energy`` request body."""

    model_config = ConfigDict(extra="ignore")

    scenario_id: str = Field(min_length=1, max_length=128)
    operator_notes: List[str]
    hours: List[HourEntry]
    battery: BatterySpec

    @field_validator("operator_notes")
    @classmethod
    def _check_notes(cls, notes: List[str]) -> List[str]:
        if not isinstance(notes, list) or not notes:
            raise ValueError("operator_notes must contain at least one note")
        if len(notes) > MAX_OPERATOR_NOTES:
            raise ValueError(f"operator_notes must not contain more than {MAX_OPERATOR_NOTES} notes")
        cleaned: List[str] = []
        for note in notes:
            if not isinstance(note, str):
                raise ValueError("every operator note must be a string")
            text = note.strip()
            if not text:
                raise ValueError("operator notes must not be empty")
            cleaned.append(text)
        return cleaned

    @field_validator("hours")
    @classmethod
    def _check_hours(cls, hours: List[HourEntry]) -> List[HourEntry]:
        if len(hours) != HOURS_PER_DAY:
            raise ValueError(f"hours must contain exactly {HOURS_PER_DAY} entries")
        present = sorted(entry.hour for entry in hours)
        if present != list(ALL_HOURS):
            raise ValueError("hours must contain each hour 0 through 23 exactly once")
        # Keep the payload valid for downstream numpy indexing regardless of the
        # order the caller used.
        return sorted(hours, key=lambda entry: entry.hour)


class DirectiveInterpretationEntry(BaseModel):
    """One machine-checkable interpretation of one operator note."""

    note_index: int
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: Optional[Dict[str, Any]] = None
    explanation: str = ""


class HourlyPlanEntry(BaseModel):
    """One hour of the returned operating schedule."""

    hour: int
    grid_kwh: float
    solar_used_kwh: float
    battery_action: BatteryAction
    battery_kwh: float
    battery_energy_after_kwh: float


class OptimizeResponse(BaseModel):
    """``POST /optimize-energy`` response body."""

    scenario_id: str
    directive_interpretation: List[DirectiveInterpretationEntry]
    hourly_plan: List[HourlyPlanEntry]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str
