"""Tests for the deterministic fallback interpreter.

The language model is the primary interpreter; the fallback exists so a
provider outage degrades into a slightly weaker answer instead of an error.
These tests keep that safety net honest.
"""

from __future__ import annotations

import pytest

from app.llm_interpreter import _fallback_directives, _parse_window, daylight_hours
from app.models import BatterySpec, HourEntry

BATTERY = BatterySpec(
    capacity_kwh=200,
    initial_energy_kwh=120,
    minimum_energy_kwh=40,
    max_charge_kwh_per_hour=60,
    max_discharge_kwh_per_hour=60,
)

HOURS = [
    HourEntry(
        hour=hour,
        demand_kwh=150.0,
        solar_kwh=0.0 if hour < 6 or hour > 18 else 40.0,
        tariff_bdt_per_kwh=8.0,
    )
    for hour in range(24)
]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("from 6 PM until 9 PM", [18, 19, 20]),
        ("2 AM until 5 AM", [2, 3, 4]),
        ("noon until 2 PM", [12, 13]),
        ("midnight to 2 AM", [0, 1]),
        ("11 AM until 1 PM", [11, 12]),
        ("between 13:00 and 15:00", [13, 14]),
        ("during the 1-3 PM window", [13, 14]),
        ("from 2 PM to 4", [14, 15]),
    ],
)
def test_window_parsing_uses_the_whole_hour_convention(text, expected):
    assert _parse_window(text) == expected


def test_window_parsing_returns_nothing_without_a_time_expression():
    assert _parse_window("The cafeteria menu changes tomorrow.") == []


@pytest.mark.parametrize(
    "note,expected_type,expected_hours,expected_value",
    [
        (
            "Panel washing from one until three will leave roughly one-fifth of normal solar output.",
            "solar_reduction",
            [13, 14],
            0.2,
        ),
        (
            "Expect an 80% reduction in rooftop solar during the 1-3 PM maintenance window.",
            "solar_reduction",
            [13, 14],
            0.2,
        ),
        (
            "PV production will drop to about 20% between 13:00 and 15:00.",
            "solar_reduction",
            [13, 14],
            0.2,
        ),
        (
            "Cloud cover will halve our solar harvest between 9 AM and 11 AM.",
            "solar_reduction",
            [9, 10],
            0.5,
        ),
        (
            "Hold at least half of the battery capacity in reserve between 6 PM and 9 PM.",
            "minimum_battery_reserve",
            [18, 19, 20],
            100.0,
        ),
        (
            "Keep at least 120 kWh in reserve from 6 PM until 9 PM.",
            "minimum_battery_reserve",
            [18, 19, 20],
            120.0,
        ),
        ("The charger is out of service between 2 AM and 5 AM.", "no_charge_window", [2, 3, 4], None),
        ("No battery top-up is permitted from 14:00 to 16:00.", "no_charge_window", [14, 15], None),
        (
            "Do not discharge the battery from 5 PM until 7 PM during relay testing.",
            "no_discharge_window",
            [17, 18],
            None,
        ),
        (
            "Transformer restriction: no more than 180 kWh may be drawn from the grid between 7 PM and 9 PM.",
            "max_grid_window",
            [19, 20],
            180.0,
        ),
        ("The library is extending book-return hours next week.", "no_op", None, None),
        ("A seminar room booking was moved to next week.", "no_op", None, None),
    ],
)
def test_fallback_interprets_representative_notes(note, expected_type, expected_hours, expected_value):
    directive = _fallback_directives([note], BATTERY, HOURS)[0]
    assert directive.directive_type.value == expected_type

    if expected_type == "no_op":
        assert directive.adjustment is None
        assert directive.applies is False
        return

    wire = directive.adjustment.to_wire()
    assert wire["hours"] == expected_hours
    if expected_value is not None:
        key = {
            "solar_reduction": "factor",
            "minimum_battery_reserve": "minimum_energy_kwh",
            "max_grid_window": "max_grid_kwh",
        }[expected_type]
        assert wire[key] == pytest.approx(expected_value, abs=1e-6)


def test_fallback_shifts_night_solar_windows_into_daylight():
    """Solar work stated as 'one until three' must land on daylight hours."""
    directive = _fallback_directives(
        ["Panel washing from one until three will reduce solar to a fifth."], BATTERY, HOURS
    )[0]
    assert directive.adjustment.to_wire()["hours"] == [13, 14]


def test_fallback_returns_one_directive_per_note():
    notes = ["Do not charge the battery between 2 PM and 4 PM.", "The menu changes.", "Not a rule."]
    directives = _fallback_directives(notes, BATTERY, HOURS)
    assert [d.note_index for d in directives] == [0, 1, 2]


def test_daylight_hours_reflects_the_forecast():
    assert daylight_hours(HOURS) == list(range(6, 19))
    assert daylight_hours(None) == []
