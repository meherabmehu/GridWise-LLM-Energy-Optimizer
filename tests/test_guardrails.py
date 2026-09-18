"""Unit tests for the deterministic directive guardrails."""

from __future__ import annotations

import math

import pytest

from app.guardrails import normalize_hours, normalize_solar_factor, sanitize_interpretation
from app.models import BatterySpec, DirectiveType


@pytest.fixture
def battery() -> BatterySpec:
    return BatterySpec(
        capacity_kwh=200,
        initial_energy_kwh=70,
        minimum_energy_kwh=30,
        max_charge_kwh_per_hour=55,
        max_discharge_kwh_per_hour=55,
    )


def types(result):
    return [directive.directive_type for directive in result.directives]


def wire(result):
    return [None if d.adjustment is None else d.adjustment.to_wire() for d in result.directives]


class TestHoursNormalisation:
    def test_deduplicates_sorts_and_filters_range(self):
        assert normalize_hours([14, 13, 13, 99, -1, 0]) == [0, 13, 14]

    def test_accepts_numeric_strings(self):
        assert normalize_hours(["7", " 8 ", "25", "abc"]) == [7, 8]

    def test_renders_single_value_as_one_hour(self):
        assert normalize_hours(5) == [5]

    def test_rejects_fractional_and_boolean_values(self):
        assert normalize_hours([3.5, True, False, None, 4]) == [4]

    def test_rejects_unsupported_container(self):
        assert normalize_hours({"hours": [1]}) == []


class TestSolarFactorNormalisation:
    def test_fraction_passes_through(self):
        assert normalize_solar_factor(0.2, "solar drops") == 0.2

    def test_percentage_of_reduction_becomes_the_remainder(self):
        assert normalize_solar_factor(
            80, "Expect an 80% reduction in rooftop solar"
        ) == pytest.approx(0.2)

    def test_percentage_remaining_is_divided_by_one_hundred(self):
        assert normalize_solar_factor(25, "usable solar is 25% of forecast") == pytest.approx(0.25)

    def test_out_of_range_values_are_clamped(self):
        assert normalize_solar_factor(-3, "solar") == 0.0
        assert normalize_solar_factor(500, "solar") == 0.0

    def test_non_numeric_values_are_rejected(self):
        assert normalize_solar_factor("lots", "solar") is None
        assert normalize_solar_factor(float("nan"), "solar") is None
        assert normalize_solar_factor(None, "solar") is None


class TestSanitisation:
    def test_one_entry_per_note_is_always_returned(self, battery):
        notes = ["Solar drops to 20% from 1 PM to 3 PM.", "The cafeteria menu changes tomorrow."]
        result = sanitize_interpretation({"directives": []}, notes, battery)
        assert len(result.directives) == len(notes)
        assert types(result) == [DirectiveType.NO_OP, DirectiveType.NO_OP]

    def test_no_op_requires_applies_false_and_null_adjustment(self, battery):
        result = sanitize_interpretation(
            {
                "directives": [
                    {
                        "note_index": 0,
                        "applies": True,
                        "directive_type": "no_op",
                        "structured_adjustment": {"hours": [1]},
                        "explanation": "menu",
                    }
                ]
            },
            ["The cafeteria menu changes tomorrow."],
            battery,
        )
        entry = result.directives[0].to_wire()
        assert entry.applies is False
        assert entry.structured_adjustment is None

    def test_non_no_op_is_forced_to_applies_true(self, battery):
        result = sanitize_interpretation(
            {
                "directives": [
                    {
                        "note_index": 0,
                        "applies": False,
                        "directive_type": "no_charge_window",
                        "structured_adjustment": {"hours": [2, 3]},
                    }
                ]
            },
            ["Charging is disabled from 2 AM until 4 AM."],
            battery,
        )
        assert result.directives[0].to_wire().applies is True

    def test_unsupported_directive_types_become_no_op(self, battery):
        result = sanitize_interpretation(
            {
                "directives": [
                    {
                        "note_index": 0,
                        "directive_type": "reduce_tariff",
                        "structured_adjustment": {"hours": [1], "percent": 10},
                    }
                ]
            },
            ["Please reduce the tariff."],
            battery,
        )
        assert types(result) == [DirectiveType.NO_OP]
        assert wire(result) == [None]

    def test_missing_hours_downgrade_the_directive(self, battery):
        result = sanitize_interpretation(
            {"directives": [{"note_index": 0, "directive_type": "no_charge_window", "structured_adjustment": {}}]},
            ["Charging is unavailable."],
            battery,
        )
        assert types(result) == [DirectiveType.NO_OP]

    def test_reserve_above_capacity_is_clamped(self, battery):
        result = sanitize_interpretation(
            {
                "directives": [
                    {
                        "note_index": 0,
                        "directive_type": "minimum_battery_reserve",
                        "structured_adjustment": {"hours": [18, 19], "minimum_energy_kwh": 5000},
                    }
                ]
            },
            ["Keep a large reserve from 6 PM until 8 PM."],
            battery,
        )
        assert wire(result) == [{"hours": [18, 19], "minimum_energy_kwh": 200.0}]

    def test_duplicate_note_indices_keep_the_first_entry(self, battery):
        result = sanitize_interpretation(
            {
                "directives": [
                    {"note_index": 0, "directive_type": "no_charge_window", "structured_adjustment": {"hours": [1]}},
                    {"note_index": 0, "directive_type": "no_discharge_window", "structured_adjustment": {"hours": [5]}},
                ]
            },
            ["Only one note here."],
            battery,
        )
        assert types(result) == [DirectiveType.NO_CHARGE_WINDOW]
        assert len(result.directives) == 1

    def test_out_of_range_indices_fall_back_to_position(self, battery):
        result = sanitize_interpretation(
            {
                "directives": [
                    {"note_index": 9, "directive_type": "no_charge_window", "structured_adjustment": {"hours": [1, 2]}}
                ]
            },
            ["Charging is disabled from 1 AM until 3 AM."],
            battery,
        )
        assert types(result) == [DirectiveType.NO_CHARGE_WINDOW]
        assert result.directives[0].note_index == 0

    def test_extra_entries_are_dropped(self, battery):
        result = sanitize_interpretation(
            {
                "directives": [
                    {"note_index": 0, "directive_type": "no_charge_window", "structured_adjustment": {"hours": [1]}},
                    {"note_index": 1, "directive_type": "no_charge_window", "structured_adjustment": {"hours": [2]}},
                    {"note_index": 2, "directive_type": "no_charge_window", "structured_adjustment": {"hours": [3]}},
                ]
            },
            ["One note only."],
            battery,
        )
        assert len(result.directives) == 1

    def test_flat_list_and_dict_roots_are_accepted(self, battery):
        flat = sanitize_interpretation(
            [{"note_index": 0, "directive_type": "no_charge_window", "structured_adjustment": {"hours": [4]}}],
            ["Charging disabled at 4 AM."],
            battery,
        )
        nested = sanitize_interpretation(
            {"directives": [{"note_index": 0, "directive_type": "no_charge_window", "structured_adjustment": {"hours": [4]}}]},
            ["Charging disabled at 4 AM."],
            battery,
        )
        assert types(flat) == types(nested) == [DirectiveType.NO_CHARGE_WINDOW]

    @pytest.mark.parametrize("payload", [None, "not json", 42, {"unexpected": True}, [1, 2, 3]])
    def test_malformed_model_output_cannot_crash(self, battery, payload):
        notes = ["Charging is disabled from 2 AM until 4 AM.", "The menu changes."]
        result = sanitize_interpretation(payload, notes, battery)
        assert len(result.directives) == len(notes)
        assert all(directive.directive_type is DirectiveType.NO_OP for directive in result.directives)

    def test_numeric_values_are_always_finite(self, battery):
        result = sanitize_interpretation(
            {
                "directives": [
                    {
                        "note_index": 0,
                        "directive_type": "max_grid_window",
                        "structured_adjustment": {"hours": [19], "max_grid_kwh": float("inf")},
                    }
                ]
            },
            ["Grid import capped at 7 PM."],
            battery,
        )
        assert types(result) == [DirectiveType.NO_OP]

    def test_explanations_are_always_present_and_bounded(self, battery):
        result = sanitize_interpretation(
            {
                "directives": [
                    {
                        "note_index": 0,
                        "directive_type": "no_charge_window",
                        "structured_adjustment": {"hours": [1]},
                        "explanation": "x" * 5000,
                    }
                ]
            },
            ["Charging is disabled at 1 AM."],
            battery,
        )
        explanation = result.directives[0].to_wire().explanation
        assert explanation and len(explanation) <= 400
