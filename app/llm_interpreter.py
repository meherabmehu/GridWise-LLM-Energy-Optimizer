"""Language-model interpretation of natural-language operator notes.

The language model is the *only* component that reads ``operator_notes``. It
converts each note into one structured directive; it never performs scheduling
or arithmetic on the scenario. Everything it returns is passed through
:mod:`app.guardrails` before it can influence the optimizer.

Design notes
------------
* All notes are interpreted in a single request, so one scenario costs one
  network round trip.
* Responses are cached by (model, notes, battery capacity, base reserve) so
  repeated evaluation requests are served instantly.
* Transient provider failures are retried with a short backoff. If the provider
  is still unavailable the request degrades to a conservative deterministic
  interpreter instead of returning an error, because a schema-valid response
  with a valid schedule is always better than a failed request.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

from app.config import Settings
from app.directives import (
    Directive,
    MaxGridWindow,
    MinimumBatteryReserve,
    SolarReduction,
    Window,
    no_op,
)
from app.guardrails import GuardrailResult, sanitize_interpretation
from app.models import BatterySpec, DirectiveType, HOURS_PER_DAY, HourEntry

LOGGER = logging.getLogger("gridwise.interpreter")

USER_AGENT = "GridWise-LLM-Energy-Optimizer/1.0 (+https://github.com/meherabmehu/GridWise-LLM-Energy-Optimizer)"

SYSTEM_PROMPT = """Interpreter for the GridWise campus energy scheduler. Turn each operator note into exactly one directive. Never optimise, never invent scenario data.

TYPES and structured_adjustment
- solar_reduction: {"hours":[...],"factor":f}. f = fraction of forecast solar REMAINING.
  "20% of forecast"->0.2 | "80% reduction"->0.2 | "about half"->0.5 | "one-fifth"->0.2 | "25% of forecast"->0.25
- minimum_battery_reserve: {"hours":[...],"minimum_energy_kwh":n}. If a percentage of battery capacity is given, multiply it by the capacity supplied.
- no_charge_window: {"hours":[...]} charging unavailable
- no_discharge_window: {"hours":[...]} discharging unavailable
- max_grid_window: {"hours":[...],"max_grid_kwh":n} grid import cap
- no_op: structured_adjustment null and applies false

TIME: whole hours 0-23 on a 24h clock (noon=12, 3PM=15, 6PM=18, midnight=0). A window INCLUDES its start hour and EXCLUDES its end hour.
"1 PM to 3 PM"->[13,14] | "6 PM until 9 PM"->[18,19,20] | "2 AM until 5 AM"->[2,3,4] | "noon until 2 PM"->[12,13] | "11 AM until 1 PM"->[11,12]
Hours are unique ascending integers. If a rule clearly applies all day and no window is stated use [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23].

AMBIGUOUS TIMES: if a note is about solar output but the hours you derived contain no daylight from the supplied daylight_hours list, the speaker meant the daytime window - add 12 hours. Panel work is never scheduled at night.

OUTPUT: exactly one entry per note in note_index order 0..N-1, never added, merged, split, dropped or reordered.
applies=true for every directive except no_op; no_op requires applies=false and null adjustment.
Use no_op when the note cannot change today's 24-hour schedule: menus, registrations, notices, library hours, bookings, rosters, unrelated maintenance, other days.
Never change demand, solar forecast values, tariff or battery parameters.

Reply JSON only:
{"directives":[{"note_index":0,"applies":true,"directive_type":"...","structured_adjustment":{...},"explanation":"..."}]}"""

#: Upper bound on how long a single rate-limit wait may block a request. The
#: judged timeout is 30s, so a long provider back-off is better served by the
#: deterministic fallback than by making the caller wait.
MAX_RATE_LIMIT_WAIT_SECONDS = 8.0

#: Longest proactive pause before sending, used to stay inside the provider's
#: per-minute token budget instead of provoking a 429.
MAX_PROACTIVE_WAIT_SECONDS = 4.0

#: Rough characters-per-token ratio used only to estimate prompt cost.
APPROX_CHARS_PER_TOKEN = 3.5


def _parse_duration(text: Optional[str]) -> Optional[float]:
    """Parse provider durations such as ``54.517s`` or ``1h6m14.4s`` into seconds."""
    if not text:
        return None
    match = re.fullmatch(
        r"\s*(?:(?P<hours>[\d.]+)h)?(?:(?P<minutes>[\d.]+)m)?(?:(?P<seconds>[\d.]+)s)?\s*", text
    )
    if not match or not any(match.group(name) for name in ("hours", "minutes", "seconds")):
        return None
    return (
        float(match.group("hours") or 0.0) * 3600.0
        + float(match.group("minutes") or 0.0) * 60.0
        + float(match.group("seconds") or 0.0)
    )


class _TokenGovernor:
    """Paces requests using the provider's own rate-limit headers.

    The provider reports how much of the per-minute token budget is left after
    every call, so the client can pause briefly instead of provoking a 429 and
    then waiting for the retry hint.
    """

    def __init__(self) -> None:
        self._remaining: Optional[float] = None
        self._reset_in: float = 0.0
        self._observed_at: float = 0.0

    def observe(self, response: httpx.Response) -> None:
        remaining = response.headers.get("x-ratelimit-remaining-tokens")
        if remaining is None:
            return
        try:
            self._remaining = float(remaining)
        except ValueError:
            return
        reset = _parse_duration(response.headers.get("x-ratelimit-reset-tokens"))
        if reset is not None:
            self._reset_in = reset
        self._observed_at = time.monotonic()

    async def pause_if_needed(self, estimated_cost: float) -> None:
        if self._remaining is None:
            return
        elapsed = time.monotonic() - self._observed_at
        projected = self._remaining - elapsed * (self._remaining / max(self._reset_in, 1e-3) / 60.0)
        if projected >= estimated_cost:
            return
        logger.debug(
            "token budget low (%.0f remaining, need %.0f), pausing", projected, estimated_cost
        )
        await asyncio.sleep(min(MAX_PROACTIVE_WAIT_SECONDS, max(0.0, self._reset_in)))


class InterpreterUnavailable(RuntimeError):
    """Raised when the language model cannot be reached or keeps failing."""


class _JsonModeRejected(RuntimeError):
    """Raised when the provider refuses the strict JSON response format."""


@dataclass
class InterpretationOutcome:
    """Directives plus provenance, ready for the guardrails and the response."""

    directives: List[Directive]
    source: str
    repairs: List[str] = field(default_factory=list)


def _estimate_token_cost(prompt: str, max_tokens: int) -> float:
    """Rough prompt-plus-completion cost of one request, in tokens."""
    prompt_tokens = (len(SYSTEM_PROMPT) + len(prompt)) / APPROX_CHARS_PER_TOKEN
    return prompt_tokens + max_tokens


def _rate_limit_wait(response: httpx.Response) -> Optional[float]:
    """Read the provider's requested back-off from headers or the error body."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return max(0.0, float(header))
        except ValueError:
            pass
    match = re.search(r"try again in ([\d.]+)\s*(ms|s)\b", response.text or "", re.IGNORECASE)
    if match:
        value = float(match.group(1))
        return value / 1000.0 if match.group(2).lower() == "ms" else value
    return None


def daylight_hours(hours: Optional[Sequence[HourEntry]]) -> List[int]:
    """Hours whose forecast solar output is above zero."""
    if not hours:
        return []
    return [entry.hour for entry in hours if entry.solar_kwh > 0]


def build_user_prompt(
    scenario_id: str,
    notes: Sequence[str],
    battery: BatterySpec,
    hours: Optional[Sequence[HourEntry]] = None,
) -> str:
    """Render the compact per-scenario prompt."""
    lines = [
        f"scenario_id: {scenario_id}",
        f"battery_capacity_kwh: {battery.capacity_kwh:g}",
        f"base_minimum_energy_kwh: {battery.minimum_energy_kwh:g}",
    ]
    lit = daylight_hours(hours)
    if lit:
        lines.append(f"daylight_hours: {','.join(str(hour) for hour in lit)}")
    lines.append("operator_notes:")
    for index, note in enumerate(notes):
        lines.append(f"[{index}] {note}")
    return "\n".join(lines)


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Pull the first JSON object out of a model message."""
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*\s*", "", candidate)
        candidate = re.sub(r"\s*```$", "", candidate)

    try:
        parsed = json.loads(candidate)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = candidate.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for position in range(start, len(candidate)):
        char = candidate[position]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(candidate[start : position + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


class _TtlCache:
    """Small bounded cache with per-entry expiry."""

    def __init__(self, max_size: int, ttl_seconds: float) -> None:
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._items: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        if self._max_size <= 0:
            return None
        entry = self._items.get(key)
        if entry is None:
            return None
        stored_at, value = entry
        if self._ttl > 0 and (time.monotonic() - stored_at) > self._ttl:
            self._items.pop(key, None)
            return None
        return value

    def put(self, key: str, value: Any) -> None:
        if self._max_size <= 0:
            return
        if len(self._items) >= self._max_size:
            oldest = min(self._items, key=lambda item: self._items[item][0])
            self._items.pop(oldest, None)
        self._items[key] = (time.monotonic(), value)


# ---------------------------------------------------------------------------
# Deterministic fallback interpreter
#
# This is a safety net for provider outages. It is never the primary path: the
# language model is always tried first and its answer always wins when present.
# ---------------------------------------------------------------------------

_CLOCK = r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
_RANGE_SEPARATOR = r"(?:to|until|till|through|thru|and|-)"
_MERIDIEM_OFFSET = {"am": 0, "pm": 12}

_FALLBACK_SOLAR = re.compile(r"\b(solar|pv|photovoltaic|rooftop|panel)", re.IGNORECASE)
_FALLBACK_GRID = re.compile(
    r"\b(grid|import|intake|feeder|transformer|substation|utility)\b", re.IGNORECASE
)
_FALLBACK_CAP = re.compile(
    r"\b(cap\w*|limit\w*|ceiling|must not exceed|not exceed|no more than|at most|maximum|below)\b",
    re.IGNORECASE,
)
_FALLBACK_RESERVE = re.compile(
    r"\b(reserve|backup|emergency|at least|keep|retain|maintain|remain|minimum)\b", re.IGNORECASE
)
_CHARGE_WORD = r"(?:charg\w*|recharg\w*|top[\s-]?up)"
_FALLBACK_CHARGE_OFF = re.compile(
    rf"\b{_CHARGE_WORD}\b[^.]{{0,60}}?\b(unavailable|disabled|isolated|offline|out of service|"
    r"not available|no longer|suspended|inspection|maintenance|blocked)\b",
    re.IGNORECASE,
)
_FALLBACK_CHARGE_OFF_REVERSE = re.compile(
    rf"\b(unavailable|disabled|isolated|offline|out of service|suspended|do not|don't|cannot|"
    rf"can't|must not|no)\b[^.]{{0,60}}?\b{_CHARGE_WORD}\b",
    re.IGNORECASE,
)
_FALLBACK_DISCHARGE_OFF = re.compile(
    r"\b(discharg\w*)\b[^.]{0,60}?\b(unavailable|disabled|isolated|offline|prohibited|blocked|"
    r"not permitted|not allowed|inspection|maintenance|testing)\b",
    re.IGNORECASE,
)
_FALLBACK_DISCHARGE_OFF_REVERSE = re.compile(
    r"\b(unavailable|disabled|isolated|prohibited|do not|don't|must not|no)\b[^.]{0,60}?\b(discharg\w*)\b",
    re.IGNORECASE,
)
_FALLBACK_NOOP_HINT = re.compile(
    r"\b(menu|menu changes|registration|notice|notices|library|book-return|seminar|booking|"
    r"roster|staffing|holiday|tomorrow|next week|next month|announcement)\b",
    re.IGNORECASE,
)
_FALLBACK_NUMBER = re.compile(r"(\d+(?:\.\d+)?)\s*(?:kwh|kw)", re.IGNORECASE)
_FALLBACK_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(%|percent)", re.IGNORECASE)
_FALLBACK_WORD_FRACTION = {
    "half": 0.5,
    "halved": 0.5,
    "halve": 0.5,
    "halves": 0.5,
    "one-half": 0.5,
    "quarter": 0.25,
    "one-quarter": 0.25,
    "one-fifth": 0.2,
    "fifth": 0.2,
    "one-third": 1 / 3,
    "third": 1 / 3,
    "two-thirds": 2 / 3,
}


_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def _clock_token_to_hour(hour_text: str, minute_text: Optional[str], meridiem: str) -> int:
    hour = int(hour_text) % 12
    if meridiem.lower() == "pm":
        hour += 12
    return hour


def _to_window(start: int, end: int) -> List[int]:
    """Expand an inclusive start / exclusive end pair into whole hours."""
    if not 0 <= start < HOURS_PER_DAY or not 0 <= end < HOURS_PER_DAY:
        return []
    if end == start:
        return [start]
    if end < start:
        return list(range(start, HOURS_PER_DAY)) + list(range(0, end))
    return list(range(start, end))


def _normalize_time_text(text: str) -> str:
    """Lower-case, expand word numerals and common time nouns, and unify dashes."""
    normalized = text.lower().replace("\u2013", "-").replace("\u2014", "-")
    normalized = re.sub(r"\bnoon\b|\bmidday\b", "12 pm", normalized)
    normalized = re.sub(r"\bmidnight\b", "12 am", normalized)
    for word, value in _WORD_NUMBERS.items():
        normalized = re.sub(rf"\b{word}\b", str(value), normalized)
    return normalized


def _parse_window(text: str) -> List[int]:
    """Best-effort whole-hour window extraction for the fallback path."""
    normalized = _normalize_time_text(text)

    def clock(hour: str, minute: Optional[str], meridiem: str) -> int:
        return _clock_token_to_hour(hour, minute, meridiem)

    # "1 PM to 3 PM", "6 PM until 9 PM", "noon until 2 PM"
    match = re.search(
        rf"(?:from|between)?\s*{_CLOCK}\s*{_RANGE_SEPARATOR}\s*{_CLOCK}", normalized
    )
    if match:
        return _to_window(
            clock(match.group(1), match.group(2), match.group(3)),
            clock(match.group(4), match.group(5), match.group(6)),
        )

    # "1-3 PM", "1:00 - 3:00 pm" - one meridiem shared by both ends
    match = re.search(
        r"(\d{1,2})(?::(\d{2}))?\s*-\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)", normalized
    )
    if match:
        meridiem = match.group(5)
        start = clock(match.group(1), match.group(2), meridiem)
        end = clock(match.group(3), match.group(4), meridiem)
        if end <= start and int(match.group(1)) <= 12:
            # "11-1 PM" reads as 11 AM to 1 PM.
            start = int(match.group(1)) % 12
        return _to_window(start, end)

    # "13:00 and 15:00" - explicit 24-hour clock
    match = re.search(r"(\d{1,2}):(\d{2})\s*" + _RANGE_SEPARATOR + r"\s*(\d{1,2}):(\d{2})", normalized)
    if match:
        return _to_window(int(match.group(1)) % 24, int(match.group(3)) % 24)

    # "2 PM until 4" - the end hour inherits the opening meridiem
    match = re.search(rf"{_CLOCK}\s*{_RANGE_SEPARATOR}\s*(\d{{1,2}})(?!\d)", normalized)
    if match:
        meridiem = match.group(3)
        start = clock(match.group(1), match.group(2), meridiem)
        end_value = int(match.group(4))
        end = end_value % 12 + _MERIDIEM_OFFSET[meridiem.lower()]
        if end <= start and meridiem.lower() == "am" and 1 <= end_value <= 12:
            end = end_value + 12
        return _to_window(start, end)

    # Last resort: a bare numeric range such as "1 until 3"
    match = re.search(r"(\d{1,2})\s*" + _RANGE_SEPARATOR + r"\s*(\d{1,2})(?!\d)", normalized)
    if match:
        return _to_window(int(match.group(1)) % 24, int(match.group(2)) % 24)

    if re.search(r"\ball day\b|\bwhole day\b|\bthroughout\b|\bentire day\b", normalized):
        return list(range(HOURS_PER_DAY))
    return []


def _fallback_solar_factor(text: str) -> Optional[float]:
    lowered = text.lower()
    percent_match = _FALLBACK_PERCENT.search(lowered)
    reduction_like = re.search(r"\b(reduc\w*|drop\w*|declin\w*|loss|lost|shortfall|cut\w*)\b", lowered)
    if percent_match:
        value = float(percent_match.group(1))
        before = lowered[max(0, percent_match.start() - 40) : percent_match.start()]
        # "drop to 20% of forecast" states the remainder; "an 80% reduction"
        # or "drop by 20%" states the size of the loss.
        states_remainder = bool(
            re.search(r"\b(to|at|is|are|of|leave\w*|remain\w*)\s*(?:about\s+|roughly\s+|approximately\s+|around\s+)?$", before)
            or re.search(r"\b(forecast|normal|usual|typical|capacity)\b", lowered[percent_match.end() : percent_match.end() + 20])
        )
        if reduction_like and not states_remainder:
            return round(max(0.0, 1.0 - value / 100.0), 10)
        return round(min(1.0, value / 100.0), 10)
    for word, value in _FALLBACK_WORD_FRACTION.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return value
    return None


def _shift_into_daylight(hours: List[int], lit: set[int]) -> List[int]:
    """Move an all-night window of a solar rule into its daytime equivalent."""
    if not hours or not lit or any(hour in lit for hour in hours):
        return hours
    shifted = sorted({(hour + 12) % 24 for hour in hours})
    return shifted if any(hour in lit for hour in shifted) else hours


def _fallback_reserve_value(note: str, battery: BatterySpec) -> Optional[float]:
    """Read a reserve either as an absolute kWh figure or as a share of capacity."""
    lowered = note.lower()
    number = _FALLBACK_NUMBER.search(lowered)
    if number:
        return float(number.group(1))
    percent = _FALLBACK_PERCENT.search(lowered)
    if percent:
        return float(percent.group(1)) / 100.0 * float(battery.capacity_kwh)
    for word, share in _FALLBACK_WORD_FRACTION.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return round(share * float(battery.capacity_kwh), 6)
    return None


def _fallback_directives(
    notes: Sequence[str],
    battery: BatterySpec,
    hours: Optional[Sequence[HourEntry]] = None,
) -> List[Directive]:
    """Conservative rule-based reading used only when the provider is down."""
    directives: List[Directive] = []
    lit = set(daylight_hours(hours))

    for index, note in enumerate(notes):
        hours = _parse_window(note)
        lowered = note.lower()

        if _FALLBACK_CHARGE_OFF.search(note) or _FALLBACK_CHARGE_OFF_REVERSE.search(note):
            directives.append(
                Directive(
                    index,
                    DirectiveType.NO_CHARGE_WINDOW,
                    Window(tuple(hours)) if hours else None,
                    "Fallback interpretation: battery charging is unavailable during the stated window.",
                )
                if hours
                else no_op(index, "Fallback interpretation: charging outage without a usable window.")
            )
            continue

        if _FALLBACK_DISCHARGE_OFF.search(note) or _FALLBACK_DISCHARGE_OFF_REVERSE.search(note):
            directives.append(
                Directive(
                    index,
                    DirectiveType.NO_DISCHARGE_WINDOW,
                    Window(tuple(hours)),
                    "Fallback interpretation: battery discharging is unavailable during the stated window.",
                )
                if hours
                else no_op(index, "Fallback interpretation: discharge outage without a usable window.")
            )
            continue

        if _FALLBACK_SOLAR.search(note) and hours:
            hours = _shift_into_daylight(hours, lit)
            factor = _fallback_solar_factor(note)
            if factor is not None:
                directives.append(
                    Directive(
                        index,
                        DirectiveType.SOLAR_REDUCTION,
                        SolarReduction(tuple(hours), factor),
                        "Fallback interpretation: usable solar is reduced during the stated window.",
                    )
                )
                continue

        if _FALLBACK_GRID.search(note) and _FALLBACK_CAP.search(note) and hours:
            number = _FALLBACK_NUMBER.search(note)
            if number:
                directives.append(
                    Directive(
                        index,
                        DirectiveType.MAX_GRID_WINDOW,
                        MaxGridWindow(tuple(hours), float(number.group(1))),
                        "Fallback interpretation: grid import is capped during the stated window.",
                    )
                )
                continue

        if _FALLBACK_RESERVE.search(note) and hours:
            reserve = _fallback_reserve_value(note, battery)
            if reserve is not None:
                directives.append(
                    Directive(
                        index,
                        DirectiveType.MINIMUM_BATTERY_RESERVE,
                        MinimumBatteryReserve(tuple(hours), min(reserve, float(battery.capacity_kwh))),
                        "Fallback interpretation: a battery reserve is required during the stated window.",
                    )
                )
                continue

        directives.append(
            no_op(index, "Fallback interpretation: this note does not affect the 24-hour energy schedule.")
        )

    return directives


class LLMInterpreter:
    """Provider-agnostic interpreter with caching, retries and a safe fallback."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Optional[httpx.AsyncClient] = None
        self._cache = _TtlCache(settings.cache_size, settings.cache_ttl_seconds)
        self._governor = _TokenGovernor()
        self._json_mode_supported = True

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        if self._client is not None:
            return
        limits = httpx.Limits(max_connections=32, max_keepalive_connections=16)
        self._client = httpx.AsyncClient(
            base_url=self._settings.base_url,
            timeout=httpx.Timeout(self._settings.timeout_seconds),
            limits=limits,
            headers={
                "Authorization": f"Bearer {self._settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except RuntimeError:  # pragma: no cover - loop already closed
                pass
            self._client = None

    # -- public API --------------------------------------------------------
    async def interpret(
        self,
        scenario_id: str,
        notes: Sequence[str],
        battery: BatterySpec,
        hours: Optional[Sequence[HourEntry]] = None,
    ) -> InterpretationOutcome:
        """Interpret every operator note, falling back safely on provider failure."""
        cache_key = self._cache_key(notes, battery, hours)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return InterpretationOutcome(
                directives=list(cached), source="cache", repairs=[]
            )

        raw_payload: Optional[Dict[str, Any]] = None
        source = "llm"
        if self._settings.llm_available:
            try:
                raw_payload = await self._request_model(
                    build_user_prompt(scenario_id, notes, battery, hours)
                )
            except InterpreterUnavailable as exc:
                LOGGER.warning("language model unavailable, using fallback interpreter: %s", exc)
            except Exception as exc:  # defensive: never let a provider bug reach the API
                LOGGER.warning("unexpected interpreter error, using fallback interpreter: %s", type(exc).__name__)

        if raw_payload is None:
            source = "fallback"
            directives = _fallback_directives(notes, battery, hours)
            result = GuardrailResult(directives=directives, repairs=["used fallback interpreter"])
        else:
            result = sanitize_interpretation(raw_payload, notes, battery)

        self._cache.put(cache_key, tuple(result.directives))
        return InterpretationOutcome(
            directives=result.directives, source=source, repairs=result.repairs
        )

    async def warmup(self) -> None:
        """Open the connection pool so the first judged request is not penalised."""
        if not self._settings.llm_available:
            return
        try:
            await self.start()
        except Exception as exc:  # pragma: no cover - startup best effort
            LOGGER.warning("interpreter warmup failed: %s", type(exc).__name__)

    # -- internals ---------------------------------------------------------
    def _cache_key(
        self,
        notes: Sequence[str],
        battery: BatterySpec,
        hours: Optional[Sequence[HourEntry]] = None,
    ) -> str:
        payload = json.dumps(
            {
                "model": self._settings.model,
                "notes": list(notes),
                "capacity": round(float(battery.capacity_kwh), 6),
                "minimum": round(float(battery.minimum_energy_kwh), 6),
                "daylight": daylight_hours(hours),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def _request_model(self, user_prompt: str) -> Dict[str, Any]:
        """Call the provider, retrying transient failures, and parse the JSON reply."""
        await self.start()
        assert self._client is not None

        last_error: Optional[Exception] = None
        delay = 0.3
        pending_wait: Optional[float] = None

        for attempt in range(self._settings.max_attempts):
            if attempt:
                wait = pending_wait if pending_wait is not None else delay
                await asyncio.sleep(wait)
                if pending_wait is None:
                    delay *= 2
                pending_wait = None

            try:
                content = await self._post_chat(user_prompt, self._json_mode_supported)
                payload = extract_json_object(content)
                if payload is None:
                    raise InterpreterUnavailable("model reply did not contain a JSON object")
                return payload
            except _JsonModeRejected:
                self._json_mode_supported = False
                last_error = _JsonModeRejected("provider rejected the strict JSON response format")
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status = exc.response.status_code
                if status == 429:
                    pending_wait = _rate_limit_wait(exc.response)
                    if pending_wait is None or pending_wait > MAX_RATE_LIMIT_WAIT_SECONDS:
                        LOGGER.warning("provider rate limit back-off too long, degrading early")
                        break
                elif status in (400, 404, 422):
                    LOGGER.warning("provider rejected the request with HTTP %s", status)
                    break
            except httpx.TimeoutException as exc:
                last_error = exc
            except (httpx.TransportError, InterpreterUnavailable) as exc:
                last_error = exc

        raise InterpreterUnavailable(
            f"language model call failed after {self._settings.max_attempts} attempt(s): "
            f"{type(last_error).__name__}"
        )

    async def _post_chat(self, user_prompt: str, use_json_mode: bool) -> str:
        assert self._client is not None
        body: Dict[str, Any] = {
            "model": self._settings.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": self._settings.temperature,
            "max_tokens": self._settings.max_tokens,
        }
        if self._settings.reasoning_effort:
            body["reasoning_effort"] = self._settings.reasoning_effort
        if use_json_mode:
            body["response_format"] = {"type": "json_object"}

        await self._governor.pause_if_needed(
            _estimate_token_cost(user_prompt, self._settings.max_tokens)
        )
        response = await self._client.post("/chat/completions", json=body)
        self._governor.observe(response)

        if response.status_code == 400 and use_json_mode:
            detail = response.text.lower()
            if "json" in detail:
                raise _JsonModeRejected(detail[:200])

        response.raise_for_status()
        payload = response.json()
        try:
            return payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise InterpreterUnavailable("unexpected provider response shape") from exc
