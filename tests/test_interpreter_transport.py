"""Transport-level tests for the interpreter.

These cover the failure modes that only appear against a real provider: rate
limits, strict-JSON rejections, unparsable replies and transport errors. They use
an in-memory transport, so no network access or API key is required.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, List

import httpx
import pytest

from app.config import Settings, load_settings
from app.llm_interpreter import (
    MAX_PROACTIVE_WAIT_SECONDS,
    InterpreterUnavailable,
    LLMInterpreter,
    _parse_duration,
    _rate_limit_wait,
    _TokenGovernor,
)
from app.models import BatterySpec

BATTERY = BatterySpec(
    capacity_kwh=200,
    initial_energy_kwh=120,
    minimum_energy_kwh=40,
    max_charge_kwh_per_hour=60,
    max_discharge_kwh_per_hour=60,
)

VALID_REPLY = {
    "directives": [
        {
            "note_index": 0,
            "applies": True,
            "directive_type": "no_charge_window",
            "structured_adjustment": {"hours": [2, 3]},
            "explanation": "charger isolated",
        }
    ]
}

NOTES = ["Do not charge the battery between 2 AM and 4 AM."]


def make_interpreter(handler: Callable[[httpx.Request], httpx.Response], **overrides) -> LLMInterpreter:
    settings = load_settings()
    settings = Settings(**{**settings.__dict__, "api_key": "test-key", "max_attempts": 3, **overrides})
    interpreter = LLMInterpreter(settings)
    interpreter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=settings.base_url or "https://example.invalid/v1",
        headers={"Authorization": "Bearer test-key"},
    )
    return interpreter


def json_reply(content: Any, status: int = 200) -> httpx.Response:
    if status != 200:
        return httpx.Response(status, json=content)
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


def rate_limited(seconds: float) -> httpx.Response:
    return httpx.Response(
        429,
        json={"error": {"message": f"Rate limit reached. Please try again in {seconds}s."}},
    )


class TestDurationParsing:
    @pytest.mark.parametrize(
        "text,expected",
        [("54.517s", 54.517), ("31m40.8s", 1900.8), ("1h6m14.4s", 3974.4), ("577.5ms", None), (None, None)],
    )
    def test_parse_duration(self, text, expected):
        result = _parse_duration(text)
        if expected is None:
            assert result is None
        else:
            assert result == pytest.approx(expected, abs=1e-6)

    def test_rate_limit_wait_reads_the_error_body(self):
        response = rate_limited(3.5)
        assert _rate_limit_wait(response) == pytest.approx(3.5)

    def test_rate_limit_wait_prefers_the_header(self):
        response = httpx.Response(429, headers={"retry-after": "2"}, json={})
        assert _rate_limit_wait(response) == pytest.approx(2.0)

    def test_rate_limit_wait_is_none_without_a_hint(self):
        assert _rate_limit_wait(httpx.Response(429, json={"error": {}})) is None


class TestTokenGovernor:
    def test_observes_provider_headers(self):
        governor = _TokenGovernor()
        governor.observe(
            httpx.Response(200, headers={"x-ratelimit-remaining-tokens": "500", "x-ratelimit-reset-tokens": "30s"})
        )
        assert governor._remaining == 500.0

    def test_ignores_responses_without_headers(self):
        governor = _TokenGovernor()
        governor.observe(httpx.Response(200))
        assert governor._remaining is None

    def test_pauses_when_the_budget_is_low(self):
        """Regression: the governor must run without raising when budget is tight."""
        governor = _TokenGovernor()
        governor.observe(
            httpx.Response(200, headers={"x-ratelimit-remaining-tokens": "10", "x-ratelimit-reset-tokens": "1s"})
        )
        started = time.monotonic()
        asyncio.run(governor.pause_if_needed(2000.0))
        assert time.monotonic() - started >= 0.5

    def test_does_not_pause_when_the_budget_is_ample(self):
        governor = _TokenGovernor()
        governor.observe(
            httpx.Response(200, headers={"x-ratelimit-remaining-tokens": "7000", "x-ratelimit-reset-tokens": "60s"})
        )
        started = time.monotonic()
        asyncio.run(governor.pause_if_needed(900.0))
        assert time.monotonic() - started < 0.4

    def test_scan_of_the_pause_bound(self):
        assert MAX_PROACTIVE_WAIT_SECONDS > 0


class TestInterpreterTransport:
    def test_successful_call_returns_llm_directives(self):
        interpreter = make_interpreter(lambda request: json_reply(VALID_REPLY))
        outcome = asyncio.run(interpreter.interpret("T", NOTES, BATTERY))
        assert outcome.source == "llm"
        assert outcome.directives[0].directive_type.value == "no_charge_window"
        assert outcome.directives[0].adjustment.to_wire()["hours"] == [2, 3]

    def test_rate_limit_then_success_still_returns_llm_directives(self):
        calls: List[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return rate_limited(0.2)
            return json_reply(VALID_REPLY)

        interpreter = make_interpreter(handler)
        outcome = asyncio.run(interpreter.interpret("T", NOTES, BATTERY))
        assert outcome.source == "llm"
        assert len(calls) >= 2

    def test_persistent_rate_limit_falls_back_without_raising(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return rate_limited(1.0)

        interpreter = make_interpreter(handler)
        outcome = asyncio.run(interpreter.interpret("T", NOTES, BATTERY))
        assert outcome.source == "fallback"
        assert outcome.directives[0].adjustment is not None

    def test_long_rate_limit_hint_degrades_immediately(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return rate_limited(600.0)

        interpreter = make_interpreter(handler)
        started = time.monotonic()
        outcome = asyncio.run(interpreter.interpret("T", NOTES, BATTERY))
        assert outcome.source == "fallback"
        assert time.monotonic() - started < 5.0

    def test_strict_json_rejection_is_retried_without_the_response_format(self):
        formats: List[bool] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            formats.append("response_format" in body)
            if "response_format" in body:
                return httpx.Response(400, json={"error": {"message": "Failed to validate JSON"}})
            return json_reply(VALID_REPLY)

        interpreter = make_interpreter(handler)
        outcome = asyncio.run(interpreter.interpret("T", NOTES, BATTERY))
        assert outcome.source == "llm"
        assert formats[0] is True and False in formats

    def test_unparsable_reply_falls_back(self):
        interpreter = make_interpreter(lambda request: json_reply("this is not json at all"))
        outcome = asyncio.run(interpreter.interpret("T", NOTES, BATTERY))
        assert outcome.source == "fallback"

    def test_markdown_fenced_reply_is_still_parsed(self):
        fenced = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "```json\n" + json.dumps(VALID_REPLY) + "\n```"}}]},
        )
        interpreter = make_interpreter(lambda request: fenced)
        outcome = asyncio.run(interpreter.interpret("T", NOTES, BATTERY))
        assert outcome.source == "llm"

    def test_transport_error_falls_back(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        interpreter = make_interpreter(handler)
        outcome = asyncio.run(interpreter.interpret("T", NOTES, BATTERY))
        assert outcome.source == "fallback"

    def test_server_error_falls_back(self):
        interpreter = make_interpreter(lambda request: httpx.Response(503, json={"error": "unavailable"}))
        outcome = asyncio.run(interpreter.interpret("T", NOTES, BATTERY))
        assert outcome.source == "fallback"

    def test_repeated_identical_requests_are_served_from_cache(self):
        calls: List[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return json_reply(VALID_REPLY)

        interpreter = make_interpreter(handler)
        first = asyncio.run(interpreter.interpret("T", NOTES, BATTERY))
        second = asyncio.run(interpreter.interpret("T", NOTES, BATTERY))
        assert first.source == "llm"
        assert second.source == "cache"
        assert len(calls) == 1

    def test_cache_key_includes_battery_capacity(self):
        calls: List[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return json_reply(VALID_REPLY)

        interpreter = make_interpreter(handler)
        asyncio.run(interpreter.interpret("T", NOTES, BATTERY))
        larger = BatterySpec(**{**BATTERY.__dict__, "capacity_kwh": 400})
        asyncio.run(interpreter.interpret("T", NOTES, larger))
        assert len(calls) == 2

    def test_a_failing_provider_never_raises_through_interpret(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        interpreter = make_interpreter(handler)
        outcome = asyncio.run(interpreter.interpret("T", NOTES, BATTERY))
        assert len(outcome.directives) == len(NOTES)


def test_interpreter_unavailable_is_a_runtime_error():
    assert issubclass(InterpreterUnavailable, RuntimeError)
