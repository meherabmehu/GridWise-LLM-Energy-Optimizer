#!/usr/bin/env python3
"""Render the complete test-case pack as a PDF, in English and Bangla.

Imported by ``scripts/build_test_case_pack.py``; the shared stylesheet lives in
``scripts/build_demo_guides.py``.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_demo_guides import css  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "docs" / "test-cases"

LIVE = "https://brian-sheffield-surely-fly.trycloudflare.com"
REPO = "https://github.com/meherabmehu/GridWise-LLM-Energy-Optimizer"

# directive -> (official cases that use it, fresh paraphrase case)
COVERAGE = [
    ("solar_reduction", "SAMPLE-01, SAMPLE-06, SAMPLE-09", "P1"),
    ("minimum_battery_reserve", "SAMPLE-03, SAMPLE-07, SAMPLE-10", "P2"),
    ("no_charge_window", "SAMPLE-02, SAMPLE-06, SAMPLE-08", "P3"),
    ("no_discharge_window", "SAMPLE-04, SAMPLE-08", "P4"),
    ("max_grid_window", "SAMPLE-05, SAMPLE-07, SAMPLE-10", "P5"),
    ("no_op", "SAMPLE-01, SAMPLE-06, SAMPLE-09, SAMPLE-10", "P6"),
]

GROUP_LABEL = {
    "official": "official",
    "paraphrase": "paraphrase",
    "llm": "LLM test",
    "multi-note": "multi-note",
}


def coverage_table(lang: str) -> str:
    if lang == "en":
        head = "<tr><th>Directive type</th><th>Official cases</th><th>Fresh paraphrase</th></tr>"
    else:
        head = "<tr><th>Directive</th><th>official case</th><th>নতুন ভাষার case</th></tr>"
    rows = "".join(
        f'<tr><td class="mono">{name}</td><td>{official}</td><td class="mono">{para}</td></tr>'
        for name, official, para in COVERAGE
    )
    return f"<table>{head}{rows}</table>"


def cards(pack: Dict[str, Any], lang: str, body_offset: int) -> str:
    out: List[str] = []
    for index, case in enumerate(pack["cases"], start=1):
        title = case["title_en"] if lang == "en" else case["title_bn"]
        expected = case["expected_en"] if lang == "en" else case["expected_bn"]
        notes = "".join(f'<li><span class="mono">{html.escape(note)}</span></li>' for note in case["notes"])
        label = GROUP_LABEL[case["group"]]
        page = index + body_offset
        body_hint = f"Body to paste: page {page} of this PDF" if lang == "en" else f"paste করার body: এই PDF-এর পৃষ্ঠা {page}"
        totals_label = "Totals" if lang == "en" else "মোট"
        expected_label = "Expected" if lang == "en" else "প্রত্যাশিত"
        out.append(
            f'<div class="case">'
            f'<h3>{index}. {case["id"]} &nbsp;<span class="pill">{label}</span>&nbsp; {html.escape(title)}</h3>'
            f'<ul class="tight">{notes}</ul>'
            f'<p><b>{expected_label}</b>: <span class="mono">{html.escape(expected)}</span><br>'
            f'<b>{totals_label}</b>: <span class="mono">{case["totals"]}</span><br>'
            f'<b>{body_hint}</b></p>'
            f"</div>"
        )
    return "".join(out)


def error_section(pack: Dict[str, Any], lang: str) -> str:
    if lang == "en":
        head = "<tr><th>ID</th><th>Case</th><th>What to do</th><th>Expected</th></tr>"
    else:
        head = "<tr><th>ID</th><th>কেস</th><th>কী করবে</th><th>প্রত্যাশিত ফল</th></tr>"
    rows = ""
    for case in pack["error_cases"]:
        rows += (
            f'<tr><td>{case["id"]}</td>'
            f'<td>{html.escape(case["title_en"] if lang == "en" else case["title_bn"])}</td>'
            f'<td class="small">{html.escape(case["how_en"] if lang == "en" else case["how_bn"])}</td>'
            f'<td class="small">{html.escape(case["expected_en"] if lang == "en" else case["expected_bn"])}</td></tr>'
        )
    return f"<table>{head}{rows}</table>"


def json_pages(pack: Dict[str, Any], lang: str) -> str:
    if lang == "en":
        hint = ("Select the whole block, copy it, and paste it into the Swagger Request body box. "
                "Paste it exactly - do not edit a single character.")
        backup = "Also available at "
    else:
        hint = ("পুরো ব্লকটা সিলেক্ট করে কপি করো, তারপর Swagger-এর Request body বাক্সে পেস্ট করো। "
                "হুবহু পেস্ট করো - একটাও অক্ষর বদলাবে না।")
        backup = "একই body এখানেও আছে "
    out: List[str] = []
    for case in pack["cases"]:
        heading = case["title_en"] if lang == "en" else case["title_bn"]
        url = f"{REPO}/blob/main/docs/test-cases/request-bodies/{case['id'].lower()}.json"
        out.append(
            f'<div class="jsonpage">'
            f'<div class="jsonhead">CASE {case["id"]} &nbsp;&mdash;&nbsp; {html.escape(heading)}</div>'
            f'<div class="jsonhint">{hint}</div>'
            f'<pre class="body">{html.escape(case["body"])}</pre>'
            f'<div class="jsonhint" style="margin-top:2mm">{backup}'
            f'<span class="mono">{url}</span></div>'
            f"</div>"
        )
    return "".join(out)


def document(pack: Dict[str, Any], lang: str, body_offset: int) -> str:
    total = len(pack["cases"])
    first_body_page = body_offset + 1
    last_body_page = body_offset + total
    if lang == "en":
        title = "GridWise &mdash; Complete Test Case Pack"
        lead = ("Every case used to verify the service: the ten official public sample cases, one freshly worded "
                "case for each supported directive type, a multi-note case, and the error-handling probes. "
                "Each case shows the exact body to paste and the exact result to expect.")
        howto = (
            f"<ol class='tight'>"
            f"<li>Open <span class='mono'>{LIVE}/docs</span> in Chrome.</li>"
            f"<li>Expand <span class='mono'>POST /optimize-energy</span> and click <b>Try it out</b>.</li>"
            f"<li>Clear the Request body box, paste the case body, click <b>Execute</b>.</li>"
            f"<li>Check the response code is <span class='mono'>200</span>, then compare the numbers.</li>"
            f"</ol>"
            f"<p class='small'>The {total} paste-ready bodies are on pages {first_body_page} to {last_body_page}.</p>"
        )
        coverage_note = ("All six directive types from the problem statement are covered twice: once by the "
                         "official sample cases and once by a freshly worded paraphrase.")
        note = ("Totals may show a few trailing decimals, for example 38365.000001 instead of 38365.00. That is the "
                "optimizer tie-break tolerance, within 0.000001 of the published optimum.")
    else:
        title = "GridWise &mdash; সম্পূর্ণ Test Case Pack"
        lead = ("Service যাচাই করার সব case একসাথে: official ১০টা public sample case, প্রতিটা directive-এর জন্য একটা নতুন "
                "ভাষার case, একটা multi-note case, আর error-handling case গুলো। প্রতিটার জন্য হুবহু paste করার body আর "
                "হুবহু প্রত্যাশিত ফল দেওয়া আছে।")
        howto = (
            f"<ol class='tight'>"
            f"<li>Chrome-এ <span class='mono'>{LIVE}/docs</span> খোলো।</li>"
            f"<li><span class='mono'>POST /optimize-energy</span> খুলে <b>Try it out</b> চাপো।</li>"
            f"<li>Request body বাক্স খালি করে case-এর body paste করো, তারপর <b>Execute</b> চাপো।</li>"
            f"<li>Response code <span class='mono'>200</span> কি না দেখো, তারপর নিচের সংখ্যাগুলোর সাথে মিলাও।</li>"
            f"</ol>"
            f"<p class='small'>{total}টা paste-ready body আছে এই PDF-এর পৃষ্ঠা {first_body_page} থেকে {last_body_page} পর্যন্ত।</p>"
        )
        coverage_note = ("Problem statement-এ বলা ছয়টা directive-ই দুইবার cover করা আছে &mdash; একবার official sample case দিয়ে, "
                         "আরেকবার নতুন ভাষার case দিয়ে।")
        note = ("সংখ্যায় শেষে কয়েকটা দশমিক বেশি দেখাতে পারে, যেমন 38365.000001, 38365.00-এর বদলে। এটা optimizer-এর "
                "tie-break tolerance; published optimum থেকে পার্থক্য ০.০০০০০১-এর বেশি নয়।")

    cases_heading = "3. The cases" if lang == "en" else "৩. সব case"
    err_heading = "4. Error-handling cases" if lang == "en" else "৪. Error-handling case"
    cov_heading = "2. Directive coverage" if lang == "en" else "২. Directive coverage"
    how_heading = "1. How to run any case" if lang == "en" else "১. যেকোনো case চালানোর নিয়ম"
    footer = (f"Official sample data: <span class='mono'>docs/official/"
              f"BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json</span> &middot; "
              f"Live URL: <span class='mono'>{LIVE}</span>")

    return (
        f'<!doctype html><html><head><meta charset="utf-8"><title>{title}</title></head><body>'
        f'<div class="cover"><h1>{title}</h1><p class="lead">{lead}</p>'
        f'<div class="meta">'
        f'<div><span class="k">Live API</span><span class="mono">{LIVE}</span></div>'
        f'<div><span class="k">Repository</span><span class="mono">{REPO}</span></div>'
        f'<div><span class="k">Cases</span>{total} request cases + {len(pack["error_cases"])} error cases</div>'
        f"</div></div>"
        f"<h2>{how_heading}</h2>{howto}"
        f"<h2>{cov_heading}</h2><p>{coverage_note}</p>{coverage_table(lang)}"
        f"<h2>{cases_heading}</h2>{cards(pack, lang, body_offset)}"
        f"<h2>{err_heading}</h2>{error_section(pack, lang)}"
        f'<div class="box"><b>{note}</b></div>'
        f'<div class="footer-note">{footer}</div>'
        f"{json_pages(pack, lang)}"
        f"</body></html>"
    )


def write_pdfs(pack: Dict[str, Any]) -> None:
    from weasyprint import CSS, HTML

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    for lang, filename, font, size in (
        ("en", "GridWise-All-Test-Cases-English.pdf", '"DejaVu Sans", "Noto Sans Bengali", sans-serif', "9.6pt"),
        ("bn", "GridWise-All-Test-Cases-Bangla.pdf", '"Noto Sans Bengali", "DejaVu Sans", sans-serif', "10.2pt"),
    ):
        sheet = CSS(string=css(font, size))
        probe = HTML(string=document(pack, lang, 0)).render(stylesheets=[sheet])
        # the paste pages come after the written pages, one page per case
        offset = len(probe.pages) - len(pack["cases"])
        HTML(string=document(pack, lang, offset)).write_pdf(PDF_DIR / filename, stylesheets=[sheet])
        print(f"{filename}: {(PDF_DIR / filename).stat().st_size / 1024:.0f} KB")
