"""Robustness tests: bad input, bad model output and provider failures.

None of these may crash the service, leak internals, or return a 5xx for a
request that is merely invalid rather than unsolvable.
"""

from __future__ import annotations

import copy

import pytest

from app.main import MAX_REQUEST_BYTES
from tests.conftest import StubInterpreter


@pytest.mark.parametrize(
    "body,expected_status",
    [
        (b"{not json", 400),
        (b"", 400),
        (b"[]", 422),
        (b'"a string"', 422),
        (b"null", 422),
    ],
)
def test_malformed_bodies_return_controlled_errors(offline_client, body, expected_status):
    response = offline_client.post(
        "/optimize-energy", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == expected_status
    payload = response.json()
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"type", "message"}


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda p: p.pop("scenario_id"), "missing scenario id"),
        (lambda p: p.pop("operator_notes"), "missing notes"),
        (lambda p: p.pop("hours"), "missing hours"),
        (lambda p: p.pop("battery"), "missing battery"),
        (lambda p: p.update(operator_notes=[]), "empty notes"),
        (lambda p: p.update(operator_notes=["   "]), "blank note"),
        (lambda p: p.update(operator_notes=[123]), "non string note"),
        (lambda p: p.update(hours=p["hours"][:23]), "too few hours"),
        (lambda p: p.update(hours=p["hours"] + [p["hours"][0]]), "duplicate hour"),
        (lambda p: p["battery"].update(capacity_kwh=0), "zero capacity"),
        (lambda p: p["battery"].update(minimum_energy_kwh=10_000), "reserve above capacity"),
        (lambda p: p["battery"].update(initial_energy_kwh=-5), "negative initial energy"),
        (lambda p: p["hours"][0].update(demand_kwh=-1), "negative demand"),
        (lambda p: p["hours"][0].update(solar_kwh="lots"), "non numeric solar"),
        (lambda p: p["hours"][0].update(tariff_bdt_per_kwh=None), "null tariff"),
    ],
)
def test_structurally_invalid_requests_are_rejected(offline_client, sample_cases, mutate, reason):
    payload = copy.deepcopy(sample_cases[0]["input"])
    mutate(payload)
    response = offline_client.post("/optimize-energy", json=payload)
    assert response.status_code == 422, reason


def test_non_finite_numbers_are_rejected(offline_client, sample_cases):
    payload = copy.deepcopy(sample_cases[0]["input"])
    payload["hours"][4]["tariff_bdt_per_kwh"] = "Infinity"
    assert offline_client.post("/optimize-energy", json=payload).status_code == 422


def test_oversized_payload_is_rejected(offline_client):
    response = offline_client.post(
        "/optimize-energy",
        content=b"x" * (MAX_REQUEST_BYTES + 1),
        headers={"content-type": "application/json", "content-length": str(MAX_REQUEST_BYTES + 1)},
    )
    assert response.status_code == 413
    assert response.json()["error"]["type"] == "payload_too_large"


def test_broken_model_output_still_produces_a_valid_plan(make_client, sample_cases):
    """Garbage from the provider must degrade to no_op, never to a crash."""
    client = make_client(StubInterpreter({}, default={"nonsense": "yes"}))
    response = client.post("/optimize-energy", json=sample_cases[0]["input"])
    assert response.status_code == 200

    body = response.json()
    assert all(entry["directive_type"] == "no_op" for entry in body["directive_interpretation"])
    assert all(entry["applies"] is False for entry in body["directive_interpretation"])
    assert all(entry["structured_adjustment"] is None for entry in body["directive_interpretation"])
    assert len(body["hourly_plan"]) == 24


def test_model_returning_extra_entries_only_affects_its_own_index(make_client, sample_cases):
    client = make_client(
        StubInterpreter(
            {},
            default={
                "directives": [
                    {
                        "note_index": 0,
                        "applies": True,
                        "directive_type": "no_charge_window",
                        "structured_adjustment": {"hours": [1, 2]},
                        "explanation": "ok",
                    },
                    {
                        "note_index": 99,
                        "applies": True,
                        "directive_type": "no_charge_window",
                        "structured_adjustment": {"hours": [9]},
                        "explanation": "out of range",
                    },
                ]
            },
        )
    )
    body = client.post("/optimize-energy", json=sample_cases[0]["input"]).json()
    assert [e["note_index"] for e in body["directive_interpretation"]] == list(
        range(len(sample_cases[0]["input"]["operator_notes"]))
    )


def test_provider_exception_is_contained(make_client, sample_cases):
    class ExplodingInterpreter:
        async def interpret(self, *args, **kwargs):
            raise RuntimeError("provider exploded with secret token sk-do-not-leak")

    client = make_client(ExplodingInterpreter())
    response = client.post("/optimize-energy", json=sample_cases[0]["input"])
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["type"] == "internal_error"
    assert "sk-do-not-leak" not in response.text
    assert "Traceback" not in response.text


def test_service_keeps_serving_after_bad_requests(offline_client, sample_cases):
    for body in (b"{bad", b"[]", b'{"scenario_id": 1}'):
        offline_client.post(
            "/optimize-energy", content=body, headers={"content-type": "application/json"}
        )
    healthy = offline_client.get("/health")
    assert healthy.status_code == 200
    good = offline_client.post("/optimize-energy", json=sample_cases[2]["input"])
    assert good.status_code == 200


def test_repeated_requests_are_stable(offline_client, sample_cases):
    payload = sample_cases[5]["input"]
    bodies = [offline_client.post("/optimize-energy", json=payload).json() for _ in range(3)]
    for body in bodies[1:]:
        assert body == bodies[0]


def test_error_responses_do_not_leak_configuration(offline_client, sample_cases):
    payload = copy.deepcopy(sample_cases[0]["input"])
    payload["battery"]["capacity_kwh"] = "nan"
    text = offline_client.post("/optimize-energy", json=payload).text.lower()
    for leak in ("traceback", "api_key", "authorization", "bearer", "password"):
        assert leak not in text
