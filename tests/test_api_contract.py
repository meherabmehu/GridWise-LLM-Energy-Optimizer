"""HTTP contract tests for the two judged endpoints."""

from __future__ import annotations

import copy

from app.models import MAX_OPERATOR_NOTES


def test_health_returns_expected_readiness_payload(offline_client):
    response = offline_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_is_reachable_without_a_body_or_auth(offline_client):
    assert offline_client.get("/health").headers["content-type"].startswith("application/json")


def test_optimize_energy_echoes_the_scenario_id(offline_client, sample_cases):
    for case in sample_cases:
        body = offline_client.post("/optimize-energy", json=case["input"]).json()
        assert body["scenario_id"] == case["input"]["scenario_id"]


def test_extra_unknown_fields_are_ignored(offline_client, sample_cases):
    payload = copy.deepcopy(sample_cases[0]["input"])
    payload["debug"] = True
    payload["hours"][0]["unused_field"] = "x"
    response = offline_client.post("/optimize-energy", json=payload)
    assert response.status_code == 200
    assert len(response.json()["hourly_plan"]) == 24


def test_hours_may_arrive_in_any_order(offline_client, sample_cases):
    payload = copy.deepcopy(sample_cases[0]["input"])
    payload["hours"] = list(reversed(payload["hours"]))
    response = offline_client.post("/optimize-energy", json=payload)
    assert response.status_code == 200
    assert [entry["hour"] for entry in response.json()["hourly_plan"]] == list(range(24))


def test_directive_interpretation_uses_only_supported_types(offline_client, sample_cases):
    allowed = {
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op",
    }
    for case in sample_cases:
        body = offline_client.post("/optimize-energy", json=case["input"]).json()
        for entry in body["directive_interpretation"]:
            assert entry["directive_type"] in allowed
            assert entry["applies"] is (entry["directive_type"] != "no_op")
            if entry["directive_type"] == "no_op":
                assert entry["structured_adjustment"] is None
            else:
                assert isinstance(entry["structured_adjustment"], dict)
                assert entry["structured_adjustment"]["hours"] == sorted(
                    set(entry["structured_adjustment"]["hours"])
                )


def test_numeric_totals_are_finite_and_consistent(offline_client, sample_cases):
    for case in sample_cases:
        body = offline_client.post("/optimize-energy", json=case["input"]).json()
        for key in ("total_grid_kwh", "total_cost_bdt", "peak_grid_kwh"):
            assert body[key] >= 0
        assert body["total_grid_kwh"] == sum(e["grid_kwh"] for e in body["hourly_plan"])
        assert body["peak_grid_kwh"] == max(e["grid_kwh"] for e in body["hourly_plan"])


def test_notes_limit_is_enforced(offline_client, sample_cases):
    payload = copy.deepcopy(sample_cases[0]["input"])
    payload["operator_notes"] = ["note"] * (MAX_OPERATOR_NOTES + 1)
    assert offline_client.post("/optimize-energy", json=payload).status_code == 422


def test_openapi_documents_both_endpoints(offline_client):
    schema = offline_client.get("/openapi.json").json()
    assert "/health" in schema["paths"]
    assert "/optimize-energy" in schema["paths"]
    assert "post" in schema["paths"]["/optimize-energy"]
