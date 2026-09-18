"""Paraphrase robustness tests against the live language model.

Hidden judge notes express the same directive with different wording, so the
interpreter has to generalise rather than match phrases. These tests are marked
``live`` and are skipped when no provider is configured. They require an API key
because the deterministic fallback is deliberately not the interpreter.

Every case asserts the directive type, the affected hours under the whole-hour
(start inclusive, end exclusive) convention, and the numeric value where one is
required.
"""

from __future__ import annotations

import pytest

import asyncio
import time
from typing import Any, Callable, Coroutine

from app.config import load_settings
from app.llm_interpreter import LLMInterpreter
from app.models import BatterySpec, HourEntry

DAYLIGHT = [
    HourEntry(
        hour=hour,
        demand_kwh=150.0,
        solar_kwh=0.0 if hour < 6 or hour > 18 else 40.0,
        tariff_bdt_per_kwh=8.0,
    )
    for hour in range(24)
]

BATTERY = BatterySpec(
    capacity_kwh=200,
    initial_energy_kwh=120,
    minimum_energy_kwh=40,
    max_charge_kwh_per_hour=60,
    max_discharge_kwh_per_hour=60,
)


# (note, expected directive type, expected hours, expected numeric value or None)
CASES = [
    # --- solar_reduction, five different ways of saying the same thing ------
    (
        "PV production will drop to about 20% between 13:00 and 15:00.",
        "solar_reduction",
        [13, 14],
        0.2,
    ),
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
        "Cloud cover will halve our solar harvest between 9 AM and 11 AM.",
        "solar_reduction",
        [9, 10],
        0.5,
    ),
    (
        "Solar generation is cut to a quarter of the forecast from 10 AM to noon.",
        "solar_reduction",
        [10, 11],
        0.25,
    ),
    # --- minimum_battery_reserve -------------------------------------------
    (
        "Keep at least 120 kWh in reserve from 6 PM until 9 PM.",
        "minimum_battery_reserve",
        [18, 19, 20],
        120.0,
    ),
    (
        "The data centre requires at least 80 kWh to remain in the battery from 6 PM until 10 PM.",
        "minimum_battery_reserve",
        [18, 19, 20, 21],
        80.0,
    ),
    (
        "Hold at least half of the battery capacity in reserve between 6 PM and 9 PM.",
        "minimum_battery_reserve",
        [18, 19, 20],
        100.0,
    ),
    (
        "Emergency generators need a floor of 150 kWh stored from 5 PM to 8 PM.",
        "minimum_battery_reserve",
        [17, 18, 19],
        150.0,
    ),
    # --- no_charge_window ---------------------------------------------------
    (
        "The charger is out of service between 2 AM and 5 AM.",
        "no_charge_window",
        [2, 3, 4],
        None,
    ),
    (
        "Battery charging is disabled from 11 AM until 1 PM while technicians inspect the charger.",
        "no_charge_window",
        [11, 12],
        None,
    ),
    (
        "Do not charge the battery between 2 PM and 4 PM.",
        "no_charge_window",
        [14, 15],
        None,
    ),
    (
        "No battery top-up is permitted from 14:00 to 16:00.",
        "no_charge_window",
        [14, 15],
        None,
    ),
    # --- no_discharge_window ------------------------------------------------
    (
        "Do not discharge the battery from 5 PM until 7 PM during relay testing.",
        "no_discharge_window",
        [17, 18],
        None,
    ),
    (
        "Battery discharge is unavailable from 6 PM until 8 PM.",
        "no_discharge_window",
        [18, 19],
        None,
    ),
    (
        "For protection testing the battery must not discharge between 7 PM and 9 PM.",
        "no_discharge_window",
        [19, 20],
        None,
    ),
    # --- max_grid_window ----------------------------------------------------
    (
        "Grid intake must stay at or below 190 kWh from 7 PM until 10 PM while the substation is constrained.",
        "max_grid_window",
        [19, 20, 21],
        190.0,
    ),
    (
        "The feeder limit caps campus grid import at 155 kWh from 6 PM until 9 PM.",
        "max_grid_window",
        [18, 19, 20],
        155.0,
    ),
    (
        "Transformer restriction: no more than 180 kWh may be drawn from the grid between 7 PM and 9 PM.",
        "max_grid_window",
        [19, 20],
        180.0,
    ),
    # --- no_op distractors --------------------------------------------------
    ("The cafeteria menu changes tomorrow.", "no_op", None, None),
    ("The library is extending book-return hours next week.", "no_op", None, None),
    ("A seminar room booking was moved to next week.", "no_op", None, None),
    ("Student affairs will publish club notices tomorrow morning.", "no_op", None, None),
    ("The sports office moved next month's registration deadline.", "no_op", None, None),
]


#: Free provider tiers meter tokens per minute, so the live suite paces itself
#: instead of provoking rate limits that would mask real interpretation errors.
MIN_SECONDS_BETWEEN_CALLS = 7.5
_LAST_CALL = [0.0]


def _pace() -> None:
    elapsed = time.monotonic() - _LAST_CALL[0]
    if elapsed < MIN_SECONDS_BETWEEN_CALLS:
        time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)
    _LAST_CALL[0] = time.monotonic()


def run_live(factory: Callable[[LLMInterpreter], Coroutine[Any, Any, Any]]):
    """Run one live scenario inside a single event loop with a fresh client."""
    settings = load_settings()
    if not settings.llm_available:
        pytest.skip("no language-model provider configured")
    _pace()

    async def _main():
        interpreter = LLMInterpreter(settings)
        try:
            return await factory(interpreter)
        finally:
            await interpreter.aclose()

    return asyncio.run(_main())


@pytest.mark.live
@pytest.mark.parametrize("note,expected_type,expected_hours,expected_value", CASES)
def test_paraphrases_resolve_to_the_same_directive(
    live_enabled, note, expected_type, expected_hours, expected_value
):
    if not live_enabled:
        pytest.skip("live tests disabled")

    async def _interpret(model: LLMInterpreter):
        outcome = await model.interpret("PARAPHRASE", [note], BATTERY, DAYLIGHT)
        return outcome.directives[0]

    directive = run_live(_interpret)

    assert directive.directive_type.value == expected_type, f"{note!r} -> {directive.directive_type}"
    assert directive.applies is (expected_type != "no_op")

    if expected_type == "no_op":
        assert directive.adjustment is None
        return

    wire = directive.adjustment.to_wire()
    assert wire["hours"] == expected_hours, f"{note!r} -> {wire['hours']}"

    if expected_type == "solar_reduction":
        assert wire["factor"] == pytest.approx(expected_value, abs=1e-6)
    elif expected_type == "minimum_battery_reserve":
        assert wire["minimum_energy_kwh"] == pytest.approx(expected_value, abs=1e-6)
    elif expected_type == "max_grid_window":
        assert wire["max_grid_kwh"] == pytest.approx(expected_value, abs=1e-6)


@pytest.mark.live
def test_live_provider_is_actually_used(live_enabled):
    """The language model must be the interpreter, not the deterministic fallback."""
    if not live_enabled:
        pytest.skip("live tests disabled")

    async def _go(model: LLMInterpreter):
        return await model.interpret(
            "LIVE-CHECK",
            ["Battery charging is disabled from 1 AM until 3 AM.", "The menu changes."],
            BATTERY,
            DAYLIGHT,
        )

    outcome = run_live(_go)
    assert outcome.source == "llm"
    assert outcome.directives[0].directive_type.value == "no_charge_window"
    assert outcome.directives[0].adjustment.to_wire()["hours"] == [1, 2]
    assert outcome.directives[1].directive_type.value == "no_op"


@pytest.mark.live
@pytest.mark.parametrize(
    "notes,expected",
    [
        (
            [
                "Panel cleaning from noon until 2 PM leaves about a quarter of normal solar.",
                "The charger will be offline from 2 AM until 5 AM.",
                "The cafeteria menu changes tomorrow.",
            ],
            [("solar_reduction", [12, 13]), ("no_charge_window", [2, 3, 4]), ("no_op", None)],
        ),
        (
            [
                "Keep at least 90 kWh in the battery from 6 PM until 10 PM.",
                "The evening transformer limit is 180 kWh of grid import from 7 PM until 9 PM.",
            ],
            [("minimum_battery_reserve", [18, 19, 20, 21]), ("max_grid_window", [19, 20])],
        ),
    ],
)
def test_multi_note_paraphrases_keep_order_and_mapping(live_enabled, notes, expected):
    if not live_enabled:
        pytest.skip("live tests disabled")

    async def _go(model: LLMInterpreter):
        return await model.interpret("MULTI", notes, BATTERY, DAYLIGHT)

    outcome = run_live(_go)
    assert len(outcome.directives) == len(notes)

    for index, (directive, (kind, hours)) in enumerate(zip(outcome.directives, expected)):
        assert directive.note_index == index
        assert directive.directive_type.value == kind
        if hours is None:
            assert directive.adjustment is None
        else:
            assert directive.adjustment.to_wire()["hours"] == hours
