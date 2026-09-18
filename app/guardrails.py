"""Deterministic guardrails for untrusted model output.

Model output is never trusted as math. Everything the language model returns is
treated as an untrusted suggestion and is re-shaped here before it can reach the
optimizer:

* only the six published directive types survive; anything else becomes ``no_op``
* every note gets exactly one entry, in ``note_index`` order, with no duplicates
* every ``hours`` array is normalised to unique ascending integers in ``0..23``
* numbers are checked for finiteness and range, and repaired or rejected
* ``applies`` is derived from the directive type, never taken from the model
* demand, solar, tariff and battery parameters are read from the request only
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.directives import (
    Directive,
    MaxGridWindow,
    MinimumBatteryReserve,
    SolarReduction,
    Window,
    no_op,
)
from app.models import HOURS_PER_DAY, BatterySpec, DirectiveInterpretationEntry, DirectiveType

LOGGER = logging.getLogger("gridwise.guardrails")

MAX_EXPLANATION_CHARS = 400

DEFAULT_NO_OP_EXPLANATION = "This note does not affect the 24-hour energy schedule."
DEFAULT_APPLIES_EXPLANATION = "Interpreted as an applicable operating directive."
MISSING_ENTRY_EXPLANATION = (
    "The interpreter returned no usable entry for this note; treated as not affecting the schedule."
)

_ALLOWED_TYPES = {member.value for member in DirectiveType}

# Narrow repair heuristic: values above 1 are percentages, and a note that talks
# about a reduction states the size of the loss rather than the remainder.
_REDUCTION_WORDS = re.compile(
    r"\b(reduc\w*|drop\w*|declin\w*|fall\w*|fell|shortfall|cut\w*|loss|lost|less|halved?)\b",
    re.IGNORECASE,
)


class GuardrailResult:
    """Outcome of sanitising one model response."""

    __slots__ = ("directives", "repairs")

    def __init__(self, directives: List[Directive], repairs: List[str]) -> None:
        self.directives = directives
        self.repairs = repairs


def normalize_hours(raw: Any) -> List[int]:
    """Return a sorted list of unique integers in ``0..23`` from an arbitrary value."""
    if raw is None:
        return []
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw = [raw]
    if isinstance(raw, str):
        raw = [part for part in re.split(r"[,\s]+", raw) if part]
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return []

    hours: set[int] = set()
    for item in raw:
        if isinstance(item, bool) or item is None:
            continue
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            try:
                item = float(text)
            except ValueError:
                continue
        if isinstance(item, (int, float)):
            number = float(item)
            if not math.isfinite(number) or number != int(number):
                continue
            value = int(number)
            if 0 <= value < HOURS_PER_DAY:
                hours.add(value)
    return sorted(hours)


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().rstrip("%")
        try:
            value = float(text)
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def normalize_solar_factor(value: Any, note_text: str) -> Optional[float]:
    """Normalise a solar factor to the usable fraction remaining within ``[0, 1]``.

    A value already inside ``[0, 1]`` is used verbatim. A value above 1 is read
    as a percentage; when the note describes a *reduction* the percentage is the
    size of the loss, so the remainder is ``1 - pct/100``.
    """
    number = _coerce_float(value)
    if number is None:
        return None
    if number <= 0:
        return 0.0
    if number <= 1.0:
        return number
    if number <= 100.0:
        if _REDUCTION_WORDS.search(note_text or ""):
            return round(max(0.0, 1.0 - number / 100.0), 10)
        return round(number / 100.0, 10)
    return 0.0


def _normalize_directive_type(value: Any) -> DirectiveType:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s\-]+", "_", text)
    aliases = {
        "noop": DirectiveType.NO_OP,
        "none": DirectiveType.NO_OP,
        "no_operation": DirectiveType.NO_OP,
        "solar_reduction_directive": DirectiveType.SOLAR_REDUCTION,
        "minimum_reserve": DirectiveType.MINIMUM_BATTERY_RESERVE,
        "battery_reserve": DirectiveType.MINIMUM_BATTERY_RESERVE,
        "no_charge": DirectiveType.NO_CHARGE_WINDOW,
        "no_discharge": DirectiveType.NO_DISCHARGE_WINDOW,
        "max_grid": DirectiveType.MAX_GRID_WINDOW,
    }
    if text in aliases:
        return aliases[text]
    if text in _ALLOWED_TYPES:
        return DirectiveType(text)
    return DirectiveType.NO_OP


def _clean_explanation(value: Any, fallback: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return fallback
    if len(text) > MAX_EXPLANATION_CHARS:
        text = text[: MAX_EXPLANATION_CHARS - 3].rstrip() + "..."
    return text


def _raw_adjustment(raw_entry: Dict[str, Any]) -> Dict[str, Any]:
    adjustment = raw_entry.get("structured_adjustment")
    return adjustment if isinstance(adjustment, dict) else {}


def _sanitize_entry(
    raw_entry: Dict[str, Any],
    note_index: int,
    note_text: str,
    battery: BatterySpec,
    repairs: List[str],
) -> Directive:
    """Convert one untrusted model entry into a safe :class:`Directive`."""
    directive_type = _normalize_directive_type(raw_entry.get("directive_type"))

    if directive_type is DirectiveType.NO_OP:
        return no_op(note_index, _clean_explanation(raw_entry.get("explanation"), DEFAULT_NO_OP_EXPLANATION))

    explanation = _clean_explanation(raw_entry.get("explanation"), DEFAULT_APPLIES_EXPLANATION)
    adjustment = _raw_adjustment(raw_entry)
    hours = tuple(normalize_hours(adjustment.get("hours")))

    if not hours:
        repairs.append(f"note {note_index}: {directive_type.value} had no usable hours, downgraded to no_op")
        return no_op(note_index, DEFAULT_NO_OP_EXPLANATION)

    if directive_type is DirectiveType.SOLAR_REDUCTION:
        factor = normalize_solar_factor(adjustment.get("factor"), note_text)
        if factor is None:
            repairs.append(f"note {note_index}: solar_reduction had no usable factor, downgraded to no_op")
            return no_op(note_index, DEFAULT_NO_OP_EXPLANATION)
        raw_factor = _coerce_float(adjustment.get("factor"))
        if raw_factor is not None and raw_factor != factor:
            repairs.append(f"note {note_index}: solar factor {raw_factor} normalised to {factor}")
        return Directive(note_index, directive_type, SolarReduction(hours, factor), explanation)

    if directive_type is DirectiveType.MINIMUM_BATTERY_RESERVE:
        reserve = _coerce_float(adjustment.get("minimum_energy_kwh"))
        if reserve is None:
            repairs.append(f"note {note_index}: reserve directive had no usable value, downgraded to no_op")
            return no_op(note_index, DEFAULT_NO_OP_EXPLANATION)
        if reserve < 0:
            repairs.append(f"note {note_index}: negative reserve {reserve} clamped to 0")
            reserve = 0.0
        if reserve > battery.capacity_kwh:
            repairs.append(
                f"note {note_index}: reserve {reserve} exceeded capacity "
                f"{battery.capacity_kwh}, clamped to capacity"
            )
            reserve = float(battery.capacity_kwh)
        return Directive(note_index, directive_type, MinimumBatteryReserve(hours, reserve), explanation)

    if directive_type in (DirectiveType.NO_CHARGE_WINDOW, DirectiveType.NO_DISCHARGE_WINDOW):
        return Directive(note_index, directive_type, Window(hours), explanation)

    if directive_type is DirectiveType.MAX_GRID_WINDOW:
        cap = _coerce_float(adjustment.get("max_grid_kwh"))
        if cap is None:
            repairs.append(f"note {note_index}: grid cap had no usable value, downgraded to no_op")
            return no_op(note_index, DEFAULT_NO_OP_EXPLANATION)
        if cap < 0:
            repairs.append(f"note {note_index}: negative grid cap {cap} clamped to 0")
            cap = 0.0
        return Directive(note_index, directive_type, MaxGridWindow(hours, cap), explanation)

    repairs.append(f"note {note_index}: unsupported directive {directive_type.value}, downgraded to no_op")
    return no_op(note_index, DEFAULT_NO_OP_EXPLANATION)


def _index_model_entries(raw_entries: Any, note_count: int) -> Dict[int, Dict[str, Any]]:
    """Map the model's entries onto note indices, dropping unusable ones."""
    if isinstance(raw_entries, dict):
        for key in ("directives", "interpretation", "directive_interpretation", "notes", "results"):
            if isinstance(raw_entries.get(key), list):
                raw_entries = raw_entries[key]
                break
        else:
            raw_entries = []

    if not isinstance(raw_entries, list):
        return {}

    indexed: Dict[int, Dict[str, Any]] = {}
    for position, entry in enumerate(raw_entries):
        if not isinstance(entry, dict):
            continue
        candidate = entry.get("note_index")
        index: Optional[int] = None
        if isinstance(candidate, bool):
            index = None
        elif isinstance(candidate, (int, float)) and float(candidate) == int(candidate):
            index = int(candidate)
        elif isinstance(candidate, str) and candidate.strip().lstrip("-").isdigit():
            index = int(candidate.strip())

        if index is None or not 0 <= index < note_count:
            # Fall back to the entry's position when the model omitted or
            # mangled note_index and the ordering still lines up.
            if position < note_count and position not in indexed:
                index = position
            else:
                continue
        if index in indexed:
            continue
        indexed[index] = entry
    return indexed


def sanitize_interpretation(
    raw_entries: Any,
    notes: Sequence[str],
    battery: BatterySpec,
) -> GuardrailResult:
    """Turn a raw interpreter response into exactly one directive per note."""
    indexed = _index_model_entries(raw_entries, len(notes))
    repairs: List[str] = []
    directives: List[Directive] = []

    for note_index, note_text in enumerate(notes):
        raw_entry = indexed.get(note_index)
        if raw_entry is None:
            repairs.append(f"note {note_index}: missing from model output, treated as no_op")
            directives.append(no_op(note_index, MISSING_ENTRY_EXPLANATION))
            continue
        directives.append(_sanitize_entry(raw_entry, note_index, note_text, battery, repairs))

    if repairs:
        LOGGER.info("guardrails applied repairs: %s", "; ".join(repairs))

    return GuardrailResult(directives=directives, repairs=repairs)


def to_wire(directives: Sequence[Directive]) -> List[DirectiveInterpretationEntry]:
    """Return the directives as response entries, ordered by ``note_index``."""
    return [directive.to_wire() for directive in sorted(directives, key=lambda item: item.note_index)]
