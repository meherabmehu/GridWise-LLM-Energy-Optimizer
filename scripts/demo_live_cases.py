#!/usr/bin/env python3
"""Live demonstration pack for the GridWise service.

Runs a short, presentation-friendly sequence of checks against a running
GridWise endpoint: the readiness probe, official public sample cases, fresh
paraphrased operator notes, an unrelated note and a malformed request.

Usage
-----
    # Against the deployed service
    python scripts/demo_live_cases.py --url https://your-service.example.com

    # Against a locally started service on the default port
    python scripts/demo_live_cases.py

Each case prints what was sent, what the interpreter decided, the plan totals and
how they compare with the published optimum. Cases that involve the language
model are spaced out so a free provider tier does not rate limit the run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import httpx

ROOT = Path(__file__).resolve().parents[1]
SAMPLES_PATH = ROOT / "docs" / "official" / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"

TOLERANCE = 0.01
RULE = "=" * 78


def load_cases() -> List[Dict[str, Any]]:
    with SAMPLES_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)["cases"]


def short(text: str, limit: int = 66) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def describe(directives: Sequence[Dict[str, Any]]) -> str:
    parts = []
    for entry in directives:
        kind = entry.get("directive_type", "?")
        adjustment = entry.get("structured_adjustment") or {}
        if kind == "solar_reduction":
            detail = f"hours {adjustment.get('hours')} factor {adjustment.get('factor')}"
        elif kind in {"no_charge_window", "no_discharge_window"}:
            detail = f"hours {adjustment.get('hours')}"
        elif kind == "minimum_battery_reserve":
            detail = f"hours {adjustment.get('hours')} reserve {adjustment.get('reserve_kwh')}"
        elif kind == "max_grid_window":
            detail = f"hours {adjustment.get('hours')} cap {adjustment.get('max_grid_kwh')}"
        else:
            detail = ""
        parts.append(f"{kind} {detail}".strip())
    return " | ".join(parts)


class Demo:
    def __init__(self, client: httpx.Client, pace: float) -> None:
        self.client = client
        self.pace = pace
        self.passed = 0
        self.failed = 0
        self._calls = 0

    def wait(self) -> None:
        """Space language-model calls so a free provider tier keeps up."""
        if self._calls and self.pace > 0:
            time.sleep(self.pace)
        self._calls += 1

    def header(self, index: int, total: int, title: str, detail: str = "") -> None:
        print()
        print(f"[{index}/{total}] {title}")
        if detail:
            print(f"        {detail}")

    def record(self, ok: bool) -> None:
        if ok:
            self.passed += 1
        else:
            self.failed += 1

    # ------------------------------------------------------------------ cases
    def health(self, index: int, total: int) -> None:
        self.header(index, total, "GET /health", "readiness probe used by the judging harness")
        started = time.perf_counter()
        response = self.client.get("/health")
        elapsed = time.perf_counter() - started
        print(f"        status  : {response.status_code} {response.text.strip()}")
        ok = response.status_code == 200 and response.json().get("status") == "ok"
        print(f"        result  : {'PASS' if ok else 'FAIL'}  ({elapsed:.2f} s)")
        self.record(ok)

    def scenario(
        self,
        index: int,
        total: int,
        title: str,
        payload: Dict[str, Any],
        reference: Optional[Dict[str, Any]] = None,
        expect_types: Optional[Sequence[str]] = None,
    ) -> None:
        self.header(index, total, title)
        for note in payload["operator_notes"]:
            print(f"        note    : \"{short(note)}\"")
        self.wait()
        started = time.perf_counter()
        response = self.client.post("/optimize-energy", json=payload)
        elapsed = time.perf_counter() - started

        if response.status_code != 200:
            print(f"        status  : {response.status_code} {short(response.text, 90)}")
            print("        result  : FAIL")
            self.record(False)
            return

        body = response.json()
        interpretation = body["directive_interpretation"]
        print(f"        decided : {describe(interpretation)}")
        print(
            "        plan    : "
            f"{body['total_grid_kwh']:.2f} kWh | {body['total_cost_bdt']:.2f} BDT | "
            f"peak {body['peak_grid_kwh']:.2f} kWh"
        )

        ok = body["scenario_id"] == payload["scenario_id"] and len(body["hourly_plan"]) == 24

        if reference is not None:
            print(
                "        official: "
                f"{reference['total_grid_kwh']:.2f} kWh | {reference['total_cost_bdt']:.2f} BDT | "
                f"peak {reference['peak_grid_kwh']:.2f} kWh"
            )
            ok = ok and abs(body["total_cost_bdt"] - reference["total_cost_bdt"]) <= TOLERANCE
            ok = ok and abs(body["total_grid_kwh"] - reference["total_grid_kwh"]) <= TOLERANCE

        if expect_types is not None:
            got = [entry["directive_type"] for entry in interpretation]
            print(f"        expected: {list(expect_types)}")
            ok = ok and got == list(expect_types)

        print(f"        result  : {'PASS' if ok else 'FAIL'}  ({elapsed:.2f} s)")
        self.record(ok)

    def malformed(self, index: int, total: int) -> None:
        self.header(index, total, "POST /optimize-energy with an unparsable body", "error handling")
        response = self.client.post(
            "/optimize-energy",
            content=b"this is not json at all",
            headers={"Content-Type": "application/json"},
        )
        print(f"        status  : {response.status_code} {response.text.strip()}")
        leak = "gsk_" in response.text or "Traceback" in response.text
        ok = response.status_code == 400 and not leak
        print(f"        result  : {'PASS' if ok else 'FAIL'}  (no key or stack trace leaked: {not leak})")
        self.record(ok)


def build_pack(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The ordered list of checks shown during a demonstration."""
    def official(index: int) -> Dict[str, Any]:
        return json.loads(json.dumps(cases[index]["input"]))  # deep copy

    def reference(index: int) -> Dict[str, Any]:
        return cases[index]["expected_output"]

    def paraphrase(base_index: int, scenario_id: str, note: str) -> Dict[str, Any]:
        payload = official(base_index)
        payload["scenario_id"] = scenario_id
        payload["operator_notes"] = [note]
        return payload

    return [
        {"kind": "health", "title": "GET /health"},
        {
            "kind": "scenario",
            "title": "SAMPLE-01  (official)  solar reduction + an unrelated note",
            "payload": official(0),
            "reference": reference(0),
            "expect_types": ["solar_reduction", "no_op"],
        },
        {
            "kind": "scenario",
            "title": "SAMPLE-05  (official)  grid import cap 18:00-21:00",
            "payload": official(4),
            "reference": reference(4),
            "expect_types": ["max_grid_window"],
        },
        {
            "kind": "scenario",
            "title": "NEW note, same limit - paraphrased wording (cache defeated)",
            "payload": paraphrase(
                4,
                "DEMO-PARAPHRASE-1",
                "Between 6 PM and 9 PM the campus feeder is limited, "
                "so keep hourly grid import under 155 kWh.",
            ),
            "reference": reference(4),
            "expect_types": ["max_grid_window"],
        },
        {
            "kind": "scenario",
            "title": "NEW unrelated note - must be ignored",
            "payload": paraphrase(
                4,
                "DEMO-PARAPHRASE-2",
                "The library extended its opening hours during exam week.",
            ),
            "expect_types": ["no_op"],
        },
        {
            "kind": "scenario",
            "title": "NEW charging restriction in plain words",
            "payload": paraphrase(
                4,
                "DEMO-PARAPHRASE-3",
                "Please don't charge the battery between 2 AM and 5 AM.",
            ),
            "expect_types": ["no_charge_window"],
        },
        {"kind": "malformed", "title": "malformed request"},
    ]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="base URL of a running GridWise service")
    parser.add_argument("--timeout", type=float, default=60.0, help="per-request timeout in seconds")
    parser.add_argument("--pace", type=float, default=6.0, help="seconds between language-model calls")
    args = parser.parse_args(argv)

    base = args.url.rstrip("/")
    cases = load_cases()
    pack = build_pack(cases)

    print(RULE)
    print("GridWise live demonstration")
    print(f"target: {base}")
    print(RULE)

    demo = Demo(httpx.Client(base_url=base, timeout=args.timeout), args.pace)
    total = len(pack)
    try:
        for index, case in enumerate(pack, start=1):
            if case["kind"] == "health":
                demo.health(index, total)
            elif case["kind"] == "malformed":
                demo.malformed(index, total)
            else:
                demo.scenario(
                    index,
                    total,
                    case["title"],
                    case["payload"],
                    case.get("reference"),
                    case.get("expect_types"),
                )
    except httpx.HTTPError as exc:
        print()
        print(f"connection failed: {type(exc).__name__}: {exc}")
        print("the service may not be running, or the tunnel window was closed")
        return 2

    print()
    print(RULE)
    print(f"{demo.passed}/{total} checks passed" + ("" if not demo.failed else f"  ({demo.failed} failed)"))
    print(RULE)
    return 0 if demo.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
