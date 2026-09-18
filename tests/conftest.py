"""Shared pytest fixtures.

The default suite is fully offline: a stub interpreter feeds the *reference*
interpretations from the official sample pack through the real guardrails,
optimizer and validator. That exercises the entire deterministic half of the
pipeline without touching a provider. Tests marked ``live`` call the
configured language model for real.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Sequence

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.guardrails import sanitize_interpretation
from app.llm_interpreter import InterpretationOutcome
from app.main import create_app
from app.models import BatterySpec

ROOT = Path(__file__).resolve().parents[1]
SAMPLES_PATH = ROOT / "docs" / "official" / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"


@pytest.fixture(scope="session")
def sample_pack() -> Dict[str, Any]:
    with SAMPLES_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="session")
def sample_cases(sample_pack: Dict[str, Any]):
    return sample_pack["cases"]


class StubInterpreter:
    """Replays a canned model reply through the real guardrails."""

    def __init__(self, payloads: Dict[str, Any], default: Any = None) -> None:
        self.payloads = payloads
        self.default = default if default is not None else {"directives": []}
        self.calls = 0

    async def interpret(
        self,
        scenario_id: str,
        notes: Sequence[str],
        battery: BatterySpec,
        hours: Sequence[Any] | None = None,
    ) -> InterpretationOutcome:
        self.calls += 1
        payload = self.payloads.get(scenario_id, self.default)
        result = sanitize_interpretation(payload, notes, battery)
        return InterpretationOutcome(
            directives=result.directives, source="stub", repairs=list(result.repairs)
        )


@pytest.fixture
def reference_payloads(sample_cases) -> Dict[str, Any]:
    """Official reference interpretations shaped like a raw model response."""
    return {
        case["input"]["scenario_id"]: {
            "directives": case["expected_output"]["directive_interpretation"]
        }
        for case in sample_cases
    }


@pytest.fixture
def make_client():
    """Build a TestClient with a caller-supplied interpreter."""

    def _make(interpreter: Any):
        app = create_app()
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        client.app.state.interpreter = interpreter
        return client

    created = []

    def factory(interpreter: Any) -> TestClient:
        client = _make(interpreter)
        created.append(client)
        return client

    yield factory

    for client in created:
        client.__exit__(None, None, None)


@pytest.fixture
def offline_client(make_client, reference_payloads) -> TestClient:
    return make_client(StubInterpreter(reference_payloads))


@pytest.fixture(scope="session")
def live_enabled() -> bool:
    settings = load_settings()
    return settings.llm_available and os.getenv("GRIDWISE_DISABLE_LIVE_TESTS", "").lower() not in {
        "1",
        "true",
        "yes",
    }
