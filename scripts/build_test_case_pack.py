#!/usr/bin/env python3
"""Build the complete test-case pack for the GridWise project.

Produces, under docs/test-cases/:

* all-test-cases.json  - machine-readable manifest (every case, body and expectation)
* all-test-cases.txt   - copy-paste bundle (every request body, one after another)
* request-bodies/      - one JSON file per case, ready to paste
* GridWise-All-Test-Cases-{English,Bangla}.pdf

The pack contains the ten official public sample cases, one fresh paraphrase per
supported directive type, a multi-note case, and the error-handling probes.

Usage:
    python scripts/build_test_case_pack.py
"""

from __future__ import annotations

import copy
import html
import json
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "docs" / "official" / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
BODIES_DIR = ROOT / "docs" / "test-cases" / "request-bodies"
OUT_JSON = ROOT / "docs" / "test-cases" / "all-test-cases.json"
OUT_TXT = ROOT / "docs" / "test-cases" / "all-test-cases.txt"
PDF_DIR = ROOT / "docs" / "test-cases"

LIVE = "https://brian-sheffield-surely-fly.trycloudflare.com"
REPO = "https://github.com/meherabmehu/GridWise-LLM-Energy-Optimizer"

# Every verified result below was measured against the live service; none of the
# numbers in this pack are estimates.
PARAPHRASE_CASES: List[Dict[str, Any]] = [
    {
        "id": "P1",
        "title_en": "solar_reduction - 55% reduction, 9 AM to 11 AM",
        "title_bn": "solar_reduction - ৫৫% হ্রাস, সকাল ৯টা থেকে ১১টা",
        "note": "Expect a 55% reduction in rooftop solar from 9 AM to 11 AM.",
        "expected_en": "solar_reduction, hours [9, 10], factor 0.45",
        "expected_bn": "solar_reduction, hours [9, 10], factor 0.45",
        "totals": "2551.0 kWh / 35757.00 BDT / peak 175.0 kWh",
    },
    {
        "id": "P2",
        "title_en": "minimum_battery_reserve - at least 115 kWh, 7 PM to 10 PM",
        "title_bn": "minimum_battery_reserve - অন্তত ১১৫ kWh, সন্ধ্যা ৭টা থেকে ১০টা",
        "note": "Keep at least 115 kWh in the battery from 7 PM until 10 PM.",
        "expected_en": "minimum_battery_reserve, hours [19, 20, 21], minimum_energy_kwh 115.0",
        "expected_bn": "minimum_battery_reserve, hours [19, 20, 21], minimum_energy_kwh 115.0",
        "totals": "2430.0 kWh / 35190.00 BDT / peak 200.0 kWh",
    },
    {
        "id": "P3",
        "title_en": "no_charge_window - charging blocked, 2 AM to 5 AM",
        "title_bn": "no_charge_window - চার্জ বন্ধ, রাত ২টা থেকে ৫টা",
        "note": "Please don't charge the battery between 2 AM and 5 AM.",
        "expected_en": "no_charge_window, hours [2, 3, 4]",
        "expected_bn": "no_charge_window, hours [2, 3, 4]",
        "totals": "2430.0 kWh / 34130.00 BDT / peak 175.0 kWh",
    },
    {
        "id": "P4",
        "title_en": "no_discharge_window - discharge blocked, 4 PM to 6 PM",
        "title_bn": "no_discharge_window - ডিসচার্জ বন্ধ, বিকাল ৪টা থেকে ৬টা",
        "note": "Battery discharge is prohibited between 4 PM and 6 PM during relay work.",
        "expected_en": "no_discharge_window, hours [16, 17]",
        "expected_bn": "no_discharge_window, hours [16, 17]",
        "totals": "2430.0 kWh / 34070.00 BDT / peak 175.0 kWh",
    },
    {
        "id": "P5",
        "title_en": "max_grid_window - import capped at 155 kWh, 6 PM to 9 PM",
        "title_bn": "max_grid_window - import সর্বোচ্চ ১৫৫ kWh, সন্ধ্যা ৬টা থেকে ৯টা",
        "note": "Between 6 PM and 9 PM the campus feeder is limited, so keep hourly grid import under 155 kWh.",
        "expected_en": "max_grid_window, hours [18, 19, 20], max_grid_kwh 155.0",
        "expected_bn": "max_grid_window, hours [18, 19, 20], max_grid_kwh 155.0",
        "totals": "2430.0 kWh / 33950.00 BDT / peak 175.0 kWh",
    },
    {
        "id": "P6",
        "title_en": "no_op - a note that must be ignored",
        "title_bn": "no_op - যে note বাদ দিতে হবে",
        "note": "The library extended its opening hours during exam week.",
        "expected_en": "no_op, applies false, structured_adjustment null",
        "expected_bn": "no_op, applies false, structured_adjustment null",
        "totals": "2430.0 kWh / 33950.00 BDT / peak 175.0 kWh",
    },
]

MULTI_NOTE = {
    "id": "M1",
    "title_en": "Two notes at once - solar reduction and a battery reserve",
    "title_bn": "একসাথে দুইটা note - সোলার হ্রাস আর battery reserve",
    "notes": [
        "Expect a 55% reduction in rooftop solar from 9 AM to 11 AM.",
        "Keep at least 115 kWh in the battery from 7 PM until 10 PM.",
    ],
    "expected_en": "solar_reduction [9, 10] factor 0.45 then minimum_battery_reserve [19, 20, 21] 115.0",
    "expected_bn": "solar_reduction [9, 10] factor 0.45, তারপর minimum_battery_reserve [19, 20, 21] 115.0",
    "totals": "2551.0 kWh / 36997.00 BDT / peak 200.0 kWh",
}

ERROR_CASES = [
    {
        "id": "E1",
        "title_en": "GET on a POST-only endpoint",
        "title_bn": "POST-only endpoint-এ GET",
        "how_en": f"Open {LIVE}/optimize-energy in the browser",
        "how_bn": f"ব্রাউজারে {LIVE}/optimize-energy খোলো",
        "expected_en": "405 {\"detail\":\"Method Not Allowed\"}",
        "expected_bn": "405 {\"detail\":\"Method Not Allowed\"}",
    },
    {
        "id": "E2",
        "title_en": "Unknown path",
        "title_bn": "অজানা path",
        "how_en": f"Open {LIVE}/no-such-path in the browser",
        "how_bn": f"ব্রাউজারে {LIVE}/no-such-path খোলো",
        "expected_en": "404 {\"detail\":\"Not Found\"}",
        "expected_bn": "404 {\"detail\":\"Not Found\"}",
    },
    {
        "id": "E3",
        "title_en": "Empty request body",
        "title_bn": "ফাঁকা request body",
        "how_en": "/docs -> POST /optimize-energy -> Try it out -> clear the body -> Execute",
        "how_bn": "/docs → POST /optimize-energy → Try it out → body খালি করে দাও → Execute",
        "expected_en": "422 {\"error\":{\"type\":\"invalid_request\",...}} - a clean error, no crash, no key",
        "expected_bn": "422 {\"error\":{\"type\":\"invalid_request\",...}} - পরিষ্কার error, crash নেই, key ফাঁস নেই",
    },
]


# --------------------------------------------------------------------------- helpers
def render_body(payload: Dict[str, Any]) -> str:
    """JSON with one hour per line so it fits the page and stays copyable."""
    lines = ["{"]
    lines.append(f'  "scenario_id": {json.dumps(payload["scenario_id"])},')
    lines.append('  "operator_notes": [')
    notes = payload["operator_notes"]
    for index, note in enumerate(notes):
        lines.append(f'    {json.dumps(note)}' + ("," if index < len(notes) - 1 else ""))
    lines.append("  ],")
    lines.append('  "hours": [')
    hours = payload["hours"]
    for index, hour in enumerate(hours):
        lines.append("    " + json.dumps(hour, separators=(", ", ": ")) + ("," if index < len(hours) - 1 else ""))
    lines.append("  ],")
    battery = payload["battery"]
    lines.append('  "battery": {')
    keys = [
        "capacity_kwh",
        "initial_energy_kwh",
        "minimum_energy_kwh",
        "max_charge_kwh_per_hour",
        "max_discharge_kwh_per_hour",
    ]
    for index, key in enumerate(keys):
        lines.append(f'    "{key}": {battery[key]}' + ("," if index < len(keys) - 1 else ""))
    lines += ["  }", "}"]
    return "\n".join(lines)


def describe(directives: List[Dict[str, Any]]) -> str:
    parts = []
    for entry in directives:
        kind = entry["directive_type"]
        adjustment = entry.get("structured_adjustment") or {}
        if kind == "no_op":
            parts.append("no_op")
            continue
        detail = ", ".join(f"{key} {value}" for key, value in adjustment.items())
        parts.append(f"{kind} ({detail})")
    return " | ".join(parts)


def base_payload() -> Dict[str, Any]:
    cases = json.loads(SAMPLES.read_text(encoding="utf-8"))["cases"]
    payload = copy.deepcopy(cases[4]["input"])  # SAMPLE-05 scenario data
    payload.pop("scenario_id", None)
    return payload


def build_pack() -> Dict[str, Any]:
    cases = json.loads(SAMPLES.read_text(encoding="utf-8"))["cases"]
    base = base_payload()
    entries: List[Dict[str, Any]] = []

    # 1. the ten official cases
    for case in cases:
        payload = copy.deepcopy(case["input"])
        expected = case["expected_output"]
        entries.append(
            {
                "id": case["input"]["scenario_id"],
                "group": "official",
                "title_en": f"{case['input']['scenario_id']} - official public sample case",
                "title_bn": f"{case['input']['scenario_id']} - official public sample case",
                "notes": payload["operator_notes"],
                "body": render_body(payload),
                "expected_en": describe(expected["directive_interpretation"]),
                "expected_bn": describe(expected["directive_interpretation"]),
                "totals": (
                    f"{expected['total_grid_kwh']:.2f} kWh / "
                    f"{expected['total_cost_bdt']:.2f} BDT / peak {expected['peak_grid_kwh']:.2f} kWh"
                ),
                "source": "docs/official/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json",
            }
        )

    # 2. one fresh paraphrase per directive type
    for index, spec in enumerate(PARAPHRASE_CASES, start=1):
        payload = copy.deepcopy(base)
        payload["scenario_id"] = f"PARAPHRASE-{spec['id']}"
        payload["operator_notes"] = [spec["note"]]
        entries.append(
            {
                "id": spec["id"],
                "group": "paraphrase",
                "title_en": spec["title_en"],
                "title_bn": spec["title_bn"],
                "notes": [spec["note"]],
                "body": render_body(payload),
                "expected_en": spec["expected_en"],
                "expected_bn": spec["expected_bn"],
                "totals": spec["totals"],
                "source": "verified against the live service",
            }
        )

    # 3. multi-note case
    payload = copy.deepcopy(base)
    payload["scenario_id"] = "MULTI-1"
    payload["operator_notes"] = MULTI_NOTE["notes"]
    entries.append(
        {
            "id": MULTI_NOTE["id"],
            "group": "multi-note",
            "title_en": MULTI_NOTE["title_en"],
            "title_bn": MULTI_NOTE["title_bn"],
            "notes": MULTI_NOTE["notes"],
            "body": render_body(payload),
            "expected_en": MULTI_NOTE["expected_en"],
            "expected_bn": MULTI_NOTE["expected_bn"],
            "totals": MULTI_NOTE["totals"],
            "source": "verified against the live service",
        }
    )

    for entry in entries:
        json.loads(entry["body"])  # every body must be valid JSON before it ships

    return {
        "live_url": LIVE,
        "repository": REPO,
        "endpoints": {"health": "GET /health", "optimize": "POST /optimize-energy"},
        "directive_types": [
            "solar_reduction",
            "minimum_battery_reserve",
            "no_charge_window",
            "no_discharge_window",
            "max_grid_window",
            "no_op",
        ],
        "cases": entries,
        "error_cases": ERROR_CASES,
    }


def write_files(pack: Dict[str, Any]) -> None:
    BODIES_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    chunk = []
    for case in pack["cases"]:
        slug = case["id"].lower()
        (BODIES_DIR / f"{slug}.json").write_text(case["body"] + "\n", encoding="utf-8")
        chunk.append(
            "\n".join(
                [
                    "=" * 90,
                    f"CASE {case['id']}  ({case['group']})",
                    case["title_en"],
                    "-" * 90,
                    "POST /optimize-energy",
                    "Body to paste:",
                    case["body"],
                    "-" * 90,
                    f"Expected directive interpretation : {case['expected_en']}",
                    f"Expected totals                     : {case['totals']}",
                    "=" * 90,
                ]
            )
        )
    chunk.append(
        "\n".join(
            [
                "=" * 90,
                "ERROR-HANDLING CASES (browser only, no body needed)",
                "=" * 90,
                *[
                    f"{case['id']}. {case['title_en']}\n    do this : {case['how_en']}\n    expect  : {case['expected_en']}"
                    for case in pack["error_cases"]
                ],
                "=" * 90,
            ]
        )
    )
    OUT_TXT.write_text("\n".join(chunk) + "\n", encoding="utf-8")


def main() -> None:
    pack = build_pack()
    write_files(pack)
    official = sum(1 for case in pack["cases"] if case["group"] == "official")
    print(f"all-test-cases.json : {official} official + "
          f"{sum(1 for c in pack['cases'] if c['group'] == 'paraphrase')} paraphrase + "
          f"{sum(1 for c in pack['cases'] if c['group'] == 'multi-note')} multi-note cases, "
          f"{len(pack['error_cases'])} error cases")
    print(f"request bodies      : {len(list(BODIES_DIR.glob('*.json')))} files in docs/test-cases/request-bodies/")
    import test_case_pdf
    test_case_pdf.write_pdfs(pack)


if __name__ == "__main__":
    main()
