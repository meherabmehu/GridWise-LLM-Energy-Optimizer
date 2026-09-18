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
from app.models import BatterySpec, DirectiveType, HOURS_PER_DAY

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

OUTPUT: exactly one entry per note in note_index order 0..N-1, never added, merged, split, dropped or reordered.
applies=true for every directive except no_op; no_op requires applies=false and null adjustment.
Use no_op when the note cannot change today's 24-hour schedule: menus, registrations, notices, library hours, bookings, rosters, unrelated maintenance, other days.
Never change demand, solar forecast values, tariff or battery parameters.

Reply JSON only:
{"directives":[{"note_index":0,"applies":true,"directive_type":"...","structured_adjustment":{...},"explanation":"..."}]}"""

#: Upper bound on how long a single rate-limit wait may block a request. The
#: judged timeout is 30s, so a long provider back-off is better served by the
#: deterministic fallback than by making the caller wait.
MAX_RATE_LIMIT_WAIT_SECONDS = 6.0


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


def build_user_prompt(scenario_id: str, notes: Sequence[str], battery: BatterySpec) -> str:
    """Render the compact per-scenario prompt."""
    lines = [
        f"scenario_id: {scenario_id}",
        f"battery_capacity_kwh: {battery.capacity_kwh:g}",
        f"base_minimum_energy_kwh: {battery.minimum_energy_kwh:g}",
        "operator_notes:",
    ]
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
_FALLBACK_CHARGE_OFF = re.compile(
    r"\b(charger|charging|charge)\b[^.]{0,60}?\b(unavailable|disabled|isolated|offline|out of service|"
    r"not available|no longer|suspended|inspection|maintenance|blocked)\b",
    re.IGNORECASE,
)
_FALLBACK_CHARGE_OFF_REVERSE = re.compile(
    r"\b(unavailable|disabled|isolated|offline|out of service|suspended|do not|don't|no)\b"
    r"[^.]{0,60}?\b(charg\w*)\b",
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
    "one-half": 0.5,
    "quarter": 0.25,
    "one-quarter": 0.25,
    "one-fifth": 0.2,
    "fifth": 0.2,
    "one-third": 1 / 3,
    "third": 1 / 3,
    "two-thirds": 2 / 3,
}


def _clock_token_to_hour(hour_text: str, minute_text: Optional[str], meridiem: str) -> int:
    hour = int(hour_text) % 12
    if meridiem.lower() == "pm":
        hour += 12
    return hour


def _parse_window(text: str) -> List[int]:
    """Best-effort whole-hour window extraction for the fallback path."""
    normalized = text.lower().replace("\u2013", "-").replace("\u2014", "-")
    normalized = re.sub(r"\bnoon\b|\bmidday\b", "12 pm", normalized)
    normalized = re.sub(r"\bmidnight\b", "12 am", normalized)

    pattern = re.compile(
        rf"(?:from|between)?\s*{_CLOCK}\s*{_RANGE_SEPARATOR}\s*{_CLOCK}", re.IGNORECASE
    )
    match = pattern.search(normalized)
    if not match:
        pattern = re.compile(rf"{_CLOCK}\s*{_RANGE_SEPARATOR}\s*(\d{{1,2}})(?=\D|$)", re.IGNORECASE)
        match = pattern.search(normalized)
        if not match:
            if re.search(r"\ball day\b|\bwhole day\b|\bthroughout\b|\bentire day\b", normalized):
                return list(range(HOURS_PER_DAY))
            return []
        start = _clock_token_to_hour(match.group(1), match.group(2), match.group(3))
        end = int(match.group(4)) % 24
    else:
        start = _clock_token_to_hour(match.group(1), match.group(2), match.group(3))
        end = _clock_token_to_hour(match.group(4), match.group(5), match.group(6))

    if not 0 <= start < HOURS_PER_DAY or not 0 <= end < HOURS_PER_DAY:
        return []
    if end <= start:
        return list(range(start, HOURS_PER_DAY)) + list(range(0, end))
    return list(range(start, end))


def _fallback_solar_factor(text: str) -> Optional[float]:
    lowered = text.lower()
    percent_match = _FALLBACK_PERCENT.search(lowered)
    reduction_like = re.search(r"\b(reduc\w*|drop\w*|declin\w*|loss|lost|shortfall|cut\w*)\b", lowered)
    if percent_match:
        value = float(percent_match.group(1))
        if reduction_like:
            return round(max(0.0, 1.0 - value / 100.0), 10)
        return round(min(1.0, value / 100.0), 10)
    for word, value in _FALLBACK_WORD_FRACTION.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return value
    return None


def _fallback_directives(notes: Sequence[str], battery: BatterySpec) -> List[Directive]:
    """Conservative rule-based reading used only when the provider is down."""
    directives: List[Directive] = []

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
            number = _FALLBACK_NUMBER.search(note)
            percent = _FALLBACK_PERCENT.search(note)
            reserve: Optional[float] = None
            if number:
                reserve = float(number.group(1))
            elif percent:
                reserve = float(percent.group(1)) / 100.0 * float(battery.capacity_kwh)
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
            await self._client.aclose()
            self._client = None

    # -- public API --------------------------------------------------------
    async def interpret(
        self,
        scenario_id: str,
        notes: Sequence[str],
        battery: BatterySpec,
    ) -> InterpretationOutcome:
        """Interpret every operator note, falling back safely on provider failure."""
        cache_key = self._cache_key(notes, battery)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return InterpretationOutcome(
                directives=list(cached), source="cache", repairs=[]
            )

        raw_payload: Optional[Dict[str, Any]] = None
        source = "llm"
        if self._settings.llm_available:
            try:
                raw_payload = await self._request_model(build_user_prompt(scenario_id, notes, battery))
            except InterpreterUnavailable as exc:
                LOGGER.warning("language model unavailable, using fallback interpreter: %s", exc)
            except Exception as exc:  # defensive: never let a provider bug reach the API
                LOGGER.warning("unexpected interpreter error, using fallback interpreter: %s", type(exc).__name__)

        if raw_payload is None:
            source = "fallback"
            directives = _fallback_directives(notes, battery)
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
    def _cache_key(self, notes: Sequence[str], battery: BatterySpec) -> str:
        payload = json.dumps(
            {
                "model": self._settings.model,
                "notes": list(notes),
                "capacity": round(float(battery.capacity_kwh), 6),
                "minimum": round(float(battery.minimum_energy_kwh), 6),
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

        response = await self._client.post("/chat/completions", json=body)

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
