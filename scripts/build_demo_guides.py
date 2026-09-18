#!/usr/bin/env python3
"""Build the browser-only demo video guide (Bangla + English) as PDF files.

Run from the repository root:

    python scripts/build_demo_guides.py

Writes docs/demo/GridWise-Video-Demo-Guide-{English,Bangla}.pdf
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import copy

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "docs" / "official" / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
OUT = ROOT / "docs" / "demo"

LIVE = "https://brian-sheffield-surely-fly.trycloudflare.com"
REPO = "https://github.com/meherabmehu/GridWise-LLM-Energy-Optimizer"
RAW = "https://raw.githubusercontent.com/meherabmehu/GridWise-LLM-Energy-Optimizer/main"
FILENAMES = {
    "A": "case-1-sample-01-solar-and-unrelated-note.json",
    "B": "case-2-sample-05-grid-cap.json",
    "C": "case-3-paraphrased-grid-cap.json",
    "D": "case-4-unrelated-note.json",
    "E": "case-5-no-charge-window.json",
}


# --------------------------------------------------------------------------- data
def render_body(payload: dict) -> str:
    """JSON with one hour per line, so no line is longer than the page width."""
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


def build_bodies() -> dict[str, str]:
    cases = json.loads(SAMPLES.read_text(encoding="utf-8"))["cases"]
    bodies = {
        "A": copy.deepcopy(cases[0]["input"]),
        "B": copy.deepcopy(cases[4]["input"]),
    }
    bodies["C"] = copy.deepcopy(cases[4]["input"])
    bodies["C"]["scenario_id"] = "DEMO-03"
    bodies["C"]["operator_notes"] = [
        "Between 6 PM and 9 PM the campus feeder is limited, so keep hourly grid import under 155 kWh."
    ]
    bodies["D"] = copy.deepcopy(cases[4]["input"])
    bodies["D"]["scenario_id"] = "DEMO-04"
    bodies["D"]["operator_notes"] = ["The library extended its opening hours during exam week."]
    bodies["E"] = copy.deepcopy(cases[4]["input"])
    bodies["E"]["scenario_id"] = "DEMO-05"
    bodies["E"]["operator_notes"] = ["Please don't charge the battery between 2 AM and 5 AM."]

    rendered = {}
    for key, payload in bodies.items():
        text = render_body(payload)
        json.loads(text)  # validity gate before it ever reaches the PDF
        rendered[key] = text
    return rendered


OFFICIAL_TABLE = [
    ("SAMPLE-01", "2692.50", "38365.00", "175.00"),
    ("SAMPLE-02", "2915.00", "42885.00", "180.00"),
    ("SAMPLE-03", "2430.00", "35480.00", "205.00"),
    ("SAMPLE-04", "2645.00", "40495.00", "225.00"),
    ("SAMPLE-05", "2430.00", "33950.00", "175.00"),
    ("SAMPLE-06", "2395.00", "34090.00", "175.00"),
    ("SAMPLE-07", "2560.00", "38550.00", "185.00"),
    ("SAMPLE-08", "2490.00", "37665.00", "210.00"),
    ("SAMPLE-09", "2504.00", "34873.00", "170.00"),
    ("SAMPLE-10", "2715.00", "41620.00", "190.00"),
]


# --------------------------------------------------------------------------- css
CSS = """
@page { size: A4 portrait; margin: 14mm 14mm 16mm 14mm; }
@page json { size: A4 landscape; margin: 10mm 10mm 12mm 10mm; }

* { box-sizing: border-box; }
body { font-family: FONTSTACK; font-size: BODYSIZE; line-height: 1.55; color: #16211c; margin: 0; }
h1 { font-size: 21pt; line-height: 1.25; margin: 0 0 2mm 0; color: #0f3d2e; }
h2 { font-size: 13.5pt; margin: 7mm 0 2mm 0; padding-bottom: 1.2mm; border-bottom: 1.1pt solid #0f3d2e; color: #0f3d2e; }
h3 { font-size: 11pt; margin: 4.5mm 0 1.5mm 0; color: #14342a; }
h4 { font-size: 10pt; margin: 3mm 0 1mm 0; color: #14342a; }
p { margin: 0 0 2.2mm 0; }
ul, ol { margin: 0 0 2.4mm 0; padding-left: 6mm; }
li { margin-bottom: 1.1mm; }
.lead { font-size: BODYSIZE; color: #33443c; }
.cover { border: 1.6pt solid #0f3d2e; border-radius: 2mm; padding: 5mm; margin-bottom: 5mm; background: #f4f9f6; }
.meta { margin-top: 3mm; font-size: 9pt; }
.meta div { margin-bottom: 1mm; }
.k { display: inline-block; min-width: 30mm; color: #4a5a52; }
code, .mono { font-family: "DejaVu Sans Mono", monospace; font-size: 8.6pt; }
.pill { display: inline-block; background: #0f3d2e; color: #ffffff; border-radius: 1.4mm; padding: 0.4mm 1.6mm; font-size: 8.2pt; }
.box { border: 0.9pt solid #b9cec4; border-left: 3pt solid #0f3d2e; background: #f7fbf9; padding: 3mm 3.5mm; border-radius: 1.4mm; margin: 2.6mm 0; }
.warn { border: 0.9pt solid #e3c39a; border-left: 3pt solid #c47a12; background: #fdf7ee; padding: 3mm 3.5mm; border-radius: 1.4mm; margin: 2.6mm 0; }
.case { border: 0.9pt solid #cddbd4; border-radius: 1.6mm; padding: 3mm 3.5mm; margin: 0 0 3.4mm 0; page-break-inside: avoid; }
.case h3 { margin-top: 0; }
.say { background: #eef5f1; border-left: 3pt solid #2f7d5f; padding: 2.4mm 3mm; margin: 2.2mm 0 0 0; font-style: italic; }
.cmd { background: #f2f4f3; border: 0.7pt solid #ccd4d0; border-radius: 1.2mm; padding: 2mm 2.6mm; font-family: "DejaVu Sans Mono", monospace; font-size: 8.4pt; margin: 1.6mm 0; word-break: break-all; }
table { width: 100%; border-collapse: collapse; margin: 2.4mm 0; font-size: 8.8pt; }
th, td { border: 0.7pt solid #c9d6d0; padding: 1.4mm 1.8mm; text-align: left; }
th { background: #eef5f1; color: #14342a; }
td.num { text-align: right; font-family: "DejaVu Sans Mono", monospace; }
.jsonpage { page: json; page-break-before: always; }
.jsonhead { font-size: 12pt; font-weight: bold; color: #0f3d2e; margin-bottom: 1mm; }
.jsonhint { font-size: 8.6pt; color: #4a5a52; margin-bottom: 2mm; }
pre.body { font-family: "DejaVu Sans Mono", monospace; font-size: 7.2pt; line-height: 1.32; white-space: pre; margin: 0; background: #f7f9f8; border: 0.7pt solid #ccd4d0; border-radius: 1.2mm; padding: 2mm; }
.tight li { margin-bottom: 0.6mm; }
.small { font-size: 8.6pt; color: #4a5a52; }
.yes { color: #14663f; font-weight: bold; }
.no { color: #a3281c; font-weight: bold; }
.footer-note { margin-top: 5mm; border-top: 0.7pt solid #cddbd4; padding-top: 2mm; font-size: 8.4pt; color: #4a5a52; }
"""


def css(font: str, size: str) -> str:
    return CSS.replace("FONTSTACK", font).replace("BODYSIZE", size)


# --------------------------------------------------------------------------- shared blocks
def json_pages(bodies: dict[str, str], lang: str) -> str:
    if lang == "en":
        titles = {
            "A": ("BODY A", "Case 1 - official sample SAMPLE-01 (solar reduction + unrelated note)"),
            "B": ("BODY B", "Case 2 - official sample SAMPLE-05 (grid import cap, 6 PM to 9 PM)"),
            "C": ("BODY C", "Case 3 - brand-new paraphrase of the same grid cap"),
            "D": ("BODY D", "Case 4 - an unrelated note that must become no_op"),
            "E": ("BODY E", "Case 5 - a fresh battery charging restriction"),
        }
        hint = ("Select everything in this block, copy it, and paste it into the Swagger "
                "\u201cRequest body\u201d box. Paste it exactly as it is - do not edit a single character.")
        closing = ("Copy hint: click at the start of the first line, drag to the very end of the last line "
                   "(</span><span class=\"mono\">}</span><span>), then press Ctrl+C.")
        backup = (
            "If copying out of this PDF misbehaves, open the same body in a browser tab instead, press "
            "Ctrl+A then Ctrl+C, and paste that: "
            '<span class="mono">' + RAW + '/docs/demo/bodies/' + '{file}</span>'
        )
    else:
        titles = {
            "A": ("বডি A", "কেস ১ — official sample SAMPLE-01 (সোলার হ্রাস + অসম্পর্কিত note)"),
            "B": ("বডি B", "কেস ২ — official sample SAMPLE-05 (6টা থেকে 9টা পর্যন্ত grid cap)"),
            "C": ("বডি C", "কেস ৩ — একই কথার নতুন ভাষা (paraphrase)"),
            "D": ("বডি D", 'কেস ৪ — অসম্পর্কিত note, "no_op" হওয়া উচিত'),
            "E": ("বডি E", "কেস ৫ — battery চার্জ বন্ধের নতুন note"),
        }
        hint = ("এই ব্লকের পুরো লেখাটা সিলেক্ট করে কপি করবে, তারপর Swagger-এর “Request body” বাক্সে পেস্ট করবে। "
                "হুবহু পেস্ট করবে — একটাও অক্ষর বদলাবে না।")
        closing = ("কপি করার নিয়ম: প্রথম লাইনের শুরুতে ক্লিক করে শেষ লাইনের একদম শেষ পর্যন্ত টেনে সিলেক্ট করো, "
                   "তারপর Ctrl+C।")
        backup = (
            "PDF থেকে কপি করতে সমস্যা হলে ব্রাউজারের নতুন tab-এ এই লিংকটা খোলো, Ctrl+A তারপর Ctrl+C করো, "
            "ওটাই paste করো: "
            '<span class="mono">' + RAW + '/docs/demo/bodies/' + '{file}</span>'
        )

    out = []
    for key in "ABCDE":
        title, subtitle = titles[key]
        out.append(
            f'<div class="jsonpage">'
            f'<div class="jsonhead">{title} &nbsp;&mdash;&nbsp; {subtitle}</div>'
            f'<div class="jsonhint">{hint}</div>'
            f'<pre class="body">{html.escape(bodies[key])}</pre>'
            f'<div class="jsonhint" style="margin-top:2mm">{closing}</div>'
            f'<div class="jsonhint">{backup.format(file=FILENAMES[key])}</div>'
            f"</div>"
        )
    return "".join(out)


def official_table(lang: str) -> str:
    head = (
        "<tr><th>Case</th><th>Grid import (kWh)</th><th>Cost (BDT)</th><th>Peak (kWh)</th></tr>"
        if lang == "en"
        else "<tr><th>কেস</th><th>Grid import (kWh)</th><th>খরচ (BDT)</th><th>Peak (kWh)</th></tr>"
    )
    rows = "".join(
        f'<tr><td>{name}</td><td class="num">{grid}</td><td class="num">{cost}</td><td class="num">{peak}</td></tr>'
        for name, grid, cost, peak in OFFICIAL_TABLE
    )
    return f"<table>{head}{rows}</table>"


# --------------------------------------------------------------------------- English
def english(bodies: dict[str, str]) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>GridWise live demo guide</title></head><body>

<div class="cover">
  <h1>GridWise &mdash; Live Demo Video Guide</h1>
  <p class="lead">Record the whole demonstration in the browser, using only the live link.
     No terminal, no VS Code, no editor &mdash; six tests, click by click, with the exact body to paste
     and the exact result to expect.</p>
  <div class="meta">
    <div><span class="k">Live API</span><span class="mono">{LIVE}</span></div>
    <div><span class="k">Repository</span><span class="mono">{REPO}</span></div>
    <div><span class="k">Tool needed</span>Google Chrome (only)</div>
    <div><span class="k">Video length</span>3 to 5 minutes is plenty</div>
  </div>
</div>

<h2>0. Before you press record &mdash; five checks</h2>
<ol class="tight">
  <li>Leave the Cloudflare tunnel window open on the laptop. If that window closes, the link dies instantly.</li>
  <li>Plug the laptop into the charger and stop it from sleeping. A sleeping laptop kills the link mid-recording.</li>
  <li>Open <span class="mono">{LIVE}/health</span> and confirm <span class="mono">{{"status":"ok"}}</span> &mdash; do this one minute before recording, not hours.</li>
  <li>Chrome zoom to 110&ndash;125% (Ctrl and +), hide the bookmarks bar (Ctrl+Shift+B), close personal tabs, switch on Do Not Disturb.</li>
  <li>Keep this PDF open in a second Chrome tab. You will copy the five JSON bodies from Section 5 while recording.</li>
</ol>
<div class="warn"><b>Important.</b> The live link is a quick tunnel in front of the running service. If the laptop
sleeps, the network drops, or the tunnel window is closed, the URL stops working and a restart produces a
<b>different</b> URL. Check it right before you record, and record in one sitting.</div>

<h2>1. Two links to show first (Clip 1 and Clip 2)</h2>
<div class="case">
  <h3>Clip 1 &mdash; the readiness probe (about 15 seconds)</h3>
  <p>Type in the Chrome address bar:</p>
  <div class="cmd">{LIVE}/health</div>
  <p>The page shows exactly: <span class="mono">{{"status":"ok"}}</span></p>
  <div class="say">Say: &ldquo;This is the readiness probe required by the problem statement. It returns status ok.&rdquo;</div>
</div>
<div class="case">
  <h3>Clip 2 &mdash; the interactive docs (about 15 seconds)</h3>
  <div class="cmd">{LIVE}/docs</div>
  <p>The Swagger UI page opens, listing <span class="mono">GET /health</span> and
     <span class="mono">POST /optimize-energy</span>. Point at both rows with the mouse.</p>
  <div class="say">Say: &ldquo;The service exposes exactly two endpoints, and anyone can run a real request from this page.&rdquo;</div>
</div>

<h2>2. How to run a request from the docs page (the pattern you repeat)</h2>
<ol class="tight">
  <li>Click the grey bar <span class="mono">POST /optimize-energy</span> to expand it.</li>
  <li>Click the <b>Try it out</b> button on the right.</li>
  <li>Click inside the <b>Request body</b> box, select all (Ctrl+A) and delete the sample text.</li>
  <li>Paste the JSON body for the case from Section 5 (Ctrl+V).</li>
  <li>Click the blue <b>Execute</b> button.</li>
  <li>Scroll to <b>Response body</b>. Check the code is <span class="mono">200</span> and point at the numbers.</li>
</ol>
<div class="box"><b>Two things that are completely normal:</b>
  <ul class="tight">
    <li>A red validation note may appear under the box while you paste. Ignore it and click Execute anyway.</li>
    <li>The first Execute after a pause may take a few seconds, because a real language model is being called. Never click Execute twice.</li>
  </ul>
</div>

<h2>3. The six tests &mdash; the story of the video</h2>

<div class="case">
  <h3>Case 1 (Clip 3) &mdash; official sample SAMPLE-01: solar reduction plus an unrelated note</h3>
  <p>Body to paste: <span class="pill">BODY A</span></p>
  <p><b>Expected result</b></p>
  <ul class="tight">
    <li><span class="mono">directive_interpretation[0]</span>: <span class="mono">solar_reduction</span>, <span class="mono">applies: true</span>, hours <span class="mono">[12, 13]</span>, factor <span class="mono">0.25</span></li>
    <li><span class="mono">directive_interpretation[1]</span>: <span class="mono">no_op</span>, <span class="mono">applies: false</span>, <span class="mono">structured_adjustment: null</span></li>
    <li><span class="mono">total_grid_kwh 2692.5</span> &nbsp; <span class="mono">total_cost_bdt 38365.00</span> &nbsp; <span class="mono">peak_grid_kwh 175.0</span></li>
    <li>Published optimum for this case: 2692.5 kWh / 38365.00 BDT / 175 kWh &mdash; exact match</li>
  </ul>
  <div class="say">Say: &ldquo;The first note cuts usable solar to 25 percent during hours 12 and 13. The second note has nothing to do with energy, and the model correctly returns no_op instead of inventing a rule. The optimizer lands on 38,365 BDT, exactly the published optimum.&rdquo;</div>
</div>

<div class="case">
  <h3>Case 2 (Clip 4) &mdash; official sample SAMPLE-05: grid import cap, 6 PM to 9 PM</h3>
  <p>Body to paste: <span class="pill">BODY B</span></p>
  <p><b>Expected result</b></p>
  <ul class="tight">
    <li><span class="mono">max_grid_window</span>, <span class="mono">applies: true</span>, hours <span class="mono">[18, 19, 20]</span>, <span class="mono">max_grid_kwh 155.0</span></li>
    <li><span class="mono">2430.0 kWh</span> &nbsp; <span class="mono">33950.00 BDT</span> &nbsp; peak <span class="mono">175.0 kWh</span> &mdash; published optimum, exact match</li>
  </ul>
  <div class="say">Say: &ldquo;Grid import is capped at 155 kWh in hours 18, 19 and 20. The plan still reaches the published optimum of 33,950 BDT.&rdquo;</div>
</div>

<div class="case">
  <h3>Case 3 (Clip 5) &mdash; a brand-new paraphrase of the same limit</h3>
  <p>Body to paste: <span class="pill">BODY C</span> &nbsp; (note text: <i>&ldquo;Between 6 PM and 9 PM the campus feeder is limited, so keep hourly grid import under 155 kWh.&rdquo;</i>)</p>
  <p><b>Expected result</b>: <span class="mono">max_grid_window</span>, hours <span class="mono">[18, 19, 20]</span>, cap <span class="mono">155.0</span> &mdash; and 33950.00 BDT again.</p>
  <div class="say">Say: &ldquo;This note is not in the sample set and is worded completely differently. The language model still resolves it to the same directive, so it is generalising rather than matching fixed phrases.&rdquo;</div>
</div>

<div class="case">
  <h3>Case 4 (Clip 6) &mdash; an unrelated note that must be ignored</h3>
  <p>Body to paste: <span class="pill">BODY D</span> &nbsp; (note text: <i>&ldquo;The library extended its opening hours during exam week.&rdquo;</i>)</p>
  <p><b>Expected result</b>: <span class="mono">no_op</span>, <span class="mono">applies: false</span>, <span class="mono">structured_adjustment: null</span>,
     totals unchanged at <span class="mono">2430.0 kWh</span> / <span class="mono">33950.00 BDT</span>.</p>
  <div class="say">Say: &ldquo;This note has nothing to do with energy. The model returns no_op, so no bogus constraint ever reaches the optimizer.&rdquo;</div>
</div>

<div class="case">
  <h3>Case 5 (Clip 7) &mdash; a fresh charging restriction</h3>
  <p>Body to paste: <span class="pill">BODY E</span> &nbsp; (note text: <i>&ldquo;Please don't charge the battery between 2 AM and 5 AM.&rdquo;</i>)</p>
  <p><b>Expected result</b>: <span class="mono">no_charge_window</span>, hours <span class="mono">[2, 3, 4]</span>,
     totals <span class="mono">2430.0 kWh</span> / <span class="mono">34130.00 BDT</span> / peak <span class="mono">175.0</span>.</p>
  <div class="say">Say: &ldquo;Charging is blocked for hours 2, 3 and 4. The end of the window is exclusive, which is the convention published in the sample data, and the cost rises to 34,130 BDT because the optimizer has to charge at a more expensive hour.&rdquo;</div>
</div>

<div class="case">
  <h3>Case 6 (Clip 8) &mdash; error handling: bad requests never break the service</h3>
  <p>Type these two links in the address bar, one after the other:</p>
  <div class="cmd">{LIVE}/optimize-energy</div>
  <div class="cmd">{LIVE}/no-such-path</div>
  <p><b>Expected result</b>: the first shows <span class="mono">405 {{"detail":"Method Not Allowed"}}</span> (that endpoint only accepts POST),
     the second shows <span class="mono">404 {{"detail":"Not Found"}}</span>.</p>
  <div class="say">Say: &ldquo;Wrong requests get a clean error response. The service never crashes and never exposes an API key or a stack trace.&rdquo;</div>
</div>

<h2>4. Closing statement (Clip 9, about 25 seconds) &mdash; read this out</h2>
<div class="box"><p>&ldquo;Operator notes are interpreted by a real language model, Groq's gpt-oss-20b, which only returns
structured directives &mdash; it never does the scheduling or the arithmetic. Those directives pass through
deterministic guardrails, and then into a deterministic linear program solved with SciPy's HiGHS solver that
minimises total cost in BDT. Every plan is re-validated before it is returned, and an invalid plan is rejected
instead of being sent to the judge. All ten official public sample cases reproduce the published optimum,
and the project ships with a Docker image that runs the same way. The repository link is below.&rdquo;</p></div>

<h2>5. Reference: the ten official public sample cases</h2>
<p>Optional to show, useful to quote. Every one of these was reproduced exactly, locally, in Docker, and against
this live link.</p>
{official_table('en')}

<h2>6. What to say and what not to say</h2>
<h3>Do say (all verified)</h3>
<ul class="tight">
  <li>The language model interprets the operator notes; the optimizer is deterministic and does the maths.</li>
  <li>All ten official cases match the published optimum; measured end to end under one second, well inside the 30 second limit.</li>
  <li>The final validator rejects any invalid schedule before a success response is returned.</li>
  <li>The project also runs in Docker, and 222 automated tests pass.</li>
</ul>
<h3>Do not say</h3>
<ul class="tight">
  <li><span class="no">Do not claim</span> the URL is permanent or that it is hosted on a cloud platform. It is a tunnel to a running service.</li>
  <li><span class="no">Do not say</span> the AI builds the schedule or does the optimisation &mdash; it only interprets the notes.</li>
  <li><span class="no">Do not read out</span> any API key, and do not open the <span class="mono">.env</span> file on camera.</li>
  <li><span class="no">Do not guess</span> at scores, judging, or numbers you have not seen in this video.</li>
</ul>
<h3>Do not show on camera</h3>
<ul class="tight">
  <li>The terminal, the tunnel window, VS Code, or any folder path on your laptop.</li>
  <li>Personal tabs, bookmarks, or notification pop-ups (turn on Do Not Disturb).</li>
  <li>Your API key anywhere on screen.</li>
  <li>Any editing of the JSON. If you mistype, delete that take and record it again.</li>
</ul>

<h2>7. If something goes wrong during recording</h2>
<table>
  <tr><th>Symptom</th><th>Cause and fix</th></tr>
  <tr><td>The link does not open at all</td><td>The tunnel stopped (laptop slept, the tunnel window was closed, or the network dropped). Restart the tunnel, check the new URL on <span class="mono">/health</span>, and note that the URL changes every time.</td></tr>
  <tr><td>No <span class="mono">Try it out</span> button</td><td>You have not expanded the <span class="mono">POST /optimize-energy</span> row yet. Click the grey bar first.</td></tr>
  <tr><td>Response code is 422</td><td>The pasted JSON was edited, cut short, or pasted twice. Clear the box and paste from Section 5 again.</td></tr>
  <tr><td>The first Execute is slow</td><td>Normal on a free provider tier. Wait for it; do not click twice.</td></tr>
  <tr><td>Numbers differ in the last decimals</td><td>You may see <span class="mono">38365.000001</span> instead of <span class="mono">38365.00</span>. That is the optimizer's tie-break tolerance, within 0.000001 of the published optimum &mdash; mention it only if a judge asks.</td></tr>
</table>

<h2>8. Recording tips</h2>
<ul class="tight">
  <li>Record Chrome full screen (F11). 1080p at 30 frames per second is enough; the numbers must be readable.</li>
  <li>Speak in English, at a calm pace. Keep the whole video between three and five minutes.</li>
  <li>Pause for one full second after each Execute so the result is clearly visible, then move the mouse to the number you are reading out.</li>
  <li>Do the whole run in one sitting, in one tab. Do not switch tabs mid-video.</li>
  <li>Before you stop recording, check that you showed: health, the two official cases, one paraphrase, one no_op, one charging window, the 405 and 404 errors, and the closing statement.</li>
</ul>

<div class="footer-note">Prepared for the BUP CSE Fest 2026 preliminary round submission.
Live URL: <span class="mono">{LIVE}</span> &middot; Repository: <span class="mono">{REPO}</span></div>

{json_pages(bodies, 'en')}

</body></html>"""


# --------------------------------------------------------------------------- Bangla
def bangla(bodies: dict[str, str]) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>GridWise live demo guide</title></head><body>

<div class="cover">
  <h1>GridWise &mdash; Live Demo ভিডিও গাইড</h1>
  <p class="lead">পুরো demonstration শুধু browser-এ করবে, শুধু live link দিয়ে। কোনো terminal নেই, VS Code নেই,
     editor নেই &mdash; ছয়টা test, ঠিক কোন জায়গায় click করবে, কী paste করবে, আর কী result আসবে &mdash; সব ধাপে ধাপে।</p>
  <div class="meta">
    <div><span class="k">Live API</span><span class="mono">{LIVE}</span></div>
    <div><span class="k">Repository</span><span class="mono">{REPO}</span></div>
    <div><span class="k">কী লাগবে</span>শুধু Google Chrome</div>
    <div><span class="k">ভিডিওর দৈর্ঘ্য</span>৩ থেকে ৫ মিনিট যথেষ্ট</div>
  </div>
</div>

<h2>০. Record চাপার আগে &mdash; পাঁচটা জিনিস দেখে নাও</h2>
<ol class="tight">
  <li>laptop-এ tunnel-এর window (যেটায় cloudflared চলছে) <b>খোলা রাখো</b>। ওটা বন্ধ হলে link সঙ্গে সঙ্গে মরে যাবে।</li>
  <li>laptop <b>চার্জারে</b> লাগাও, আর sleep বন্ধ রাখো। record করার মাঝখানে laptop ঘুমিয়ে পড়লে link চলে যাবে।</li>
  <li>Chrome-এ <span class="mono">{LIVE}/health</span> খুলে দেখো <span class="mono">{{"status":"ok"}}</span> আসে কি না &mdash; এটা record করার <b>এক মিনিট আগে</b> দেখবে, কয়েক ঘণ্টা আগে নয়।</li>
  <li>Chrome-এর zoom ১১০–১২৫% করো (Ctrl এবং +), bookmarks bar লুকাও (Ctrl+Shift+B), অপ্রয়োজনীয় tab বন্ধ করো, notification বন্ধ করো (Do Not Disturb)।</li>
  <li><b>এই PDF-টা Chrome-এর দ্বিতীয় একটা tab-এ খোলা রাখো</b> &mdash; section ৫ থেকে ৫টা JSON body কপি করতে হবে।</li>
</ol>
<div class="warn"><b>মনে রাখো।</b> এই live link টা quick tunnel দিয়ে চলছে। laptop ঘুমালে, internet গেলে, বা tunnel-এর window
বন্ধ হলে URL আর কাজ করবে না; আবার চালু করলে <b>নতুন ঠিকানা</b> আসবে। তাই record করার ঠিক আগে link যাচাই করো,
আর পুরো ভিডিওটা <b>এক বসায়</b> record করো।</div>

<h2>১. প্রথমে দেখাবে দুইটা লিংক (Clip ১ ও Clip ২)</h2>
<div class="case">
  <h3>Clip ১ &mdash; readiness probe (প্রায় ১৫ সেকেন্ড)</h3>
  <p>Chrome-এর address bar-এ এটা লেখো:</p>
  <div class="cmd">{LIVE}/health</div>
  <p>পেজে হুবহু দেখাবে: <span class="mono">{{"status":"ok"}}</span></p>
  <div class="say">বলবে: &ldquo;This is the readiness probe required by the problem statement. It returns status ok.&rdquo;</div>
</div>
<div class="case">
  <h3>Clip ২ &mdash; interactive docs (প্রায় ১৫ সেকেন্ড)</h3>
  <div class="cmd">{LIVE}/docs</div>
  <p>Swagger UI পেজ খুলবে, তালিকায় <span class="mono">GET /health</span> আর
     <span class="mono">POST /optimize-energy</span> দেখা যাবে। মাউস দিয়ে দুইটা সারির দিকে দেখাও।</p>
  <div class="say">বলবে: &ldquo;The service exposes exactly two endpoints, and anyone can run a real request from this page.&rdquo;</div>
</div>

<h2>২. Docs পেজ থেকে request চালানোর নিয়ম (এই ধাপটাই বারবার হবে)</h2>
<ol class="tight">
  <li>ধূসর রঙের <span class="mono">POST /optimize-energy</span> সারিতে <b>click</b> করো (খুলে যাবে)।</li>
  <li>ডান দিকে <b>Try it out</b> বাটনে click করো।</li>
  <li><b>Request body</b> বাক্সের ভিতরে click করো, Ctrl+A দিয়ে সব সিলেক্ট করে delete দাও।</li>
  <li>Section ৫ থেকে যে case-এর JSON body লাগবে, সেটা Ctrl+V দিয়ে paste করো।</li>
  <li>নীল <b>Execute</b> বাটনে click করো।</li>
  <li>নিচে scroll করে <b>Response body</b> দেখো। Code <span class="mono">200</span> হওয়া উচিত &mdash; তারপর সংখ্যাগুলোর দিকে আঙুল দেখাও।</li>
</ol>
<div class="box"><b>দুইটা জিনিস একদম স্বাভাবিক:</b>
  <ul class="tight">
    <li>paste করার সময় বাক্সের নিচে লাল সতর্কবার্তা আসতে পারে &mdash; <b>উপেক্ষা করো</b>, Execute তবু কাজ করবে।</li>
    <li>কিছুক্ষণ বিরতির পর প্রথম Execute-এ কয়েক সেকেন্ড লাগতে পারে, কারণ পেছনে আসল ভাষা-মডেল ডাকা হচ্ছে। <b>দুবার Execute চাপবে না।</b></li>
  </ul>
</div>

<h2>৩. ছয়টা test &mdash; ভিডিওর গল্প</h2>

<div class="case">
  <h3>কেস ১ (Clip ৩) &mdash; official SAMPLE-01: সোলার হ্রাস + অসম্পর্কিত note</h3>
  <p>paste করবে: <span class="pill">বডি A</span></p>
  <p><b>প্রত্যাশিত ফল</b></p>
  <ul class="tight">
    <li><span class="mono">directive_interpretation[0]</span>: <span class="mono">solar_reduction</span>, <span class="mono">applies: true</span>, hours <span class="mono">[12, 13]</span>, factor <span class="mono">0.25</span></li>
    <li><span class="mono">directive_interpretation[1]</span>: <span class="mono">no_op</span>, <span class="mono">applies: false</span>, <span class="mono">structured_adjustment: null</span></li>
    <li><span class="mono">total_grid_kwh 2692.5</span> &nbsp; <span class="mono">total_cost_bdt 38365.00</span> &nbsp; <span class="mono">peak_grid_kwh 175.0</span></li>
    <li>এই case-এর official optimum: 2692.5 kWh / 38365.00 BDT / 175 kWh &mdash; হুবহু মিলে গেছে</li>
  </ul>
  <div class="say">বলবে: &ldquo;The first note cuts usable solar to 25 percent during hours 12 and 13. The second note has nothing to do with energy, and the model correctly returns no_op instead of inventing a rule. The optimizer lands on 38,365 BDT, exactly the published optimum.&rdquo;</div>
</div>

<div class="case">
  <h3>কেস ২ (Clip ৪) &mdash; official SAMPLE-05: ৬টা থেকে ৯টা পর্যন্ত grid cap</h3>
  <p>paste করবে: <span class="pill">বডি B</span></p>
  <p><b>প্রত্যাশিত ফল</b></p>
  <ul class="tight">
    <li><span class="mono">max_grid_window</span>, <span class="mono">applies: true</span>, hours <span class="mono">[18, 19, 20]</span>, <span class="mono">max_grid_kwh 155.0</span></li>
    <li><span class="mono">2430.0 kWh</span> &nbsp; <span class="mono">33950.00 BDT</span> &nbsp; peak <span class="mono">175.0 kWh</span> &mdash; official optimum, হুবহু</li>
  </ul>
  <div class="say">বলবে: &ldquo;Grid import is capped at 155 kWh in hours 18, 19 and 20. The plan still reaches the published optimum of 33,950 BDT.&rdquo;</div>
</div>

<div class="case">
  <h3>কেস ৩ (Clip ৫) &mdash; একই কথার সম্পূর্ণ নতুন ভাষা</h3>
  <p>paste করবে: <span class="pill">বডি C</span> &nbsp; (note: <i>&ldquo;Between 6 PM and 9 PM the campus feeder is limited, so keep hourly grid import under 155 kWh.&rdquo;</i>)</p>
  <p><b>প্রত্যাশিত ফল</b>: <span class="mono">max_grid_window</span>, hours <span class="mono">[18, 19, 20]</span>, cap <span class="mono">155.0</span> &mdash; খরচ আবার <span class="mono">33950.00 BDT</span>।</p>
  <div class="say">বলবে: &ldquo;This note is not in the sample set and is worded completely differently. The language model still resolves it to the same directive, so it is generalising rather than matching fixed phrases.&rdquo;</div>
</div>

<div class="case">
  <h3>কেস ৪ (Clip ৬) &mdash; অসম্পর্কিত note-কে বাদ দিতে হবে</h3>
  <p>paste করবে: <span class="pill">বডি D</span> &nbsp; (note: <i>&ldquo;The library extended its opening hours during exam week.&rdquo;</i>)</p>
  <p><b>প্রত্যাশিত ফল</b>: <span class="mono">no_op</span>, <span class="mono">applies: false</span>, <span class="mono">structured_adjustment: null</span>,
     আর মোট খরচ অপরিবর্তিত <span class="mono">2430.0 kWh</span> / <span class="mono">33950.00 BDT</span>।</p>
  <div class="say">বলবে: &ldquo;This note has nothing to do with energy. The model returns no_op, so no bogus constraint ever reaches the optimizer.&rdquo;</div>
</div>

<div class="case">
  <h3>কেস ৫ (Clip ৭) &mdash; চার্জ বন্ধের নতুন note</h3>
  <p>paste করবে: <span class="pill">বডি E</span> &nbsp; (note: <i>&ldquo;Please don't charge the battery between 2 AM and 5 AM.&rdquo;</i>)</p>
  <p><b>প্রত্যাশিত ফল</b>: <span class="mono">no_charge_window</span>, hours <span class="mono">[2, 3, 4]</span>,
     খরচ <span class="mono">2430.0 kWh</span> / <span class="mono">34130.00 BDT</span> / peak <span class="mono">175.0</span>।</p>
  <div class="say">বলবে: &ldquo;Charging is blocked for hours 2, 3 and 4. The end of the window is exclusive, which is the convention used in the sample data, and the cost rises to 34,130 BDT because the battery has to be charged at a more expensive hour.&rdquo;</div>
</div>

<div class="case">
  <h3>কেস ৬ (Clip ৮) &mdash; error handling: খারাপ request-এ service ভাঙে না</h3>
  <p>address bar-এ এই দুইটা লিংক একটা একটা করে লেখো:</p>
  <div class="cmd">{LIVE}/optimize-energy</div>
  <div class="cmd">{LIVE}/no-such-path</div>
  <p><b>প্রত্যাশিত ফল</b>: প্রথমটায় <span class="mono">405 {{"detail":"Method Not Allowed"}}</span> (এই endpoint শুধু POST নেয়),
     দ্বিতীয়টায় <span class="mono">404 {{"detail":"Not Found"}}</span>।</p>
  <div class="say">বলবে: &ldquo;Wrong requests get a clean error response. The service never crashes and never exposes an API key or a stack trace.&rdquo;</div>
</div>

<h2>৪. শেষ কথা (Clip ৯, প্রায় ২৫ সেকেন্ড) &mdash; এইটুকু পড়ে ফেলো</h2>
<div class="box"><p>&ldquo;Operator notes are interpreted by a real language model, Groq's gpt-oss-20b, which only returns
structured directives &mdash; it never does the scheduling or the arithmetic. Those directives pass through
deterministic guardrails, and then into a deterministic linear program solved with SciPy's HiGHS solver that
minimises total cost in BDT. Every plan is re-validated before it is returned, and an invalid plan is rejected
instead of being sent to the judge. All ten official public sample cases reproduce the published optimum,
and the project ships with a Docker image that runs the same way. The repository link is below.&rdquo;</p></div>
<p class="small">(ইংরেজিতে বলাই ভালো, কারণ judges ইংরেজিতে শুনবেন। উপরের লেখাটা হুবহু পড়লেও চলবে।)</p>

<h2>৫. তুলনার টেবিল: official ১০টা case-এর ফল</h2>
<p>ভিডিওতে দেখানো বাধ্যতামূলক নয়, তবে দরকার হলে এই সংখ্যাগুলো বলে দিতে পারবে। প্রতিটা case local-এ, Docker-এ
এবং এই live link-এ &mdash; তিন জায়গাতেই হুবহু মিলেছে।</p>
{official_table('bn')}

<h2>৬. কী বলবে, কী বলবে না</h2>
<h3>বলবে (সবই যাচাই করা)</h3>
<ul class="tight">
  <li>operator note বোঝে ভাষা-মডেল; হিসাব-নিকাশ করে deterministic optimizer।</li>
  <li>official ১০টা case-ই published optimum-এ পৌঁছায়; সময় লাগে এক সেকেন্ডেরও কম, ৩০ সেকেন্ডের সীমার অনেক ভিতরে।</li>
  <li>শেষ validator কোনো অগ্রহণযোগ্য schedule ফেরত দেওয়ার আগেই আটকে দেয়।</li>
  <li>project টা Docker-এও একইভাবে চলে, আর ২২২টা automated test পাস করে।</li>
</ul>
<h3>বলবে না</h3>
<ul class="tight">
  <li><span class="no">বলবে না</span> যে URL টা স্থায়ী, বা কোনো cloud platform-এ hosted। এটা একটা চলন্ত service-এর tunnel।</li>
  <li><span class="no">বলবে না</span> যে AI schedule বানায় বা optimization করে &mdash; সে শুধু note বোঝে।</li>
  <li><span class="no">ক্যামেরায় দেখাবে না</span> কোনো API key, আর <span class="mono">.env</span> file খুলবে না।</li>
  <li><span class="no">আন্দাজে বলবে না</span> কোনো নম্বর, score বা judging নিয়ে &mdash; যেটা এই ভিডিওতে দেখা যায়নি।</li>
</ul>
<h3>ক্যামেরায় যা দেখাবে না</h3>
<ul class="tight">
  <li>terminal, tunnel-এর window, VS Code, অথবা laptop-এর কোনো folder path।</li>
  <li>নিজের ব্যক্তিগত tab, bookmark, বা notification pop-up (Do Not Disturb চালু রাখো)।</li>
  <li>স্ক্রিনের কোথাও API key।</li>
  <li>JSON-এ কোনো edit। ভুল হলে ওই take টা মুছে আবার record করো।</li>
</ul>

<h2>৭. Record করার সময় সমস্যা হলে</h2>
<table>
  <tr><th>যা দেখছ</th><th>কারণ ও সমাধান</th></tr>
  <tr><td>link একদম খুলছে না</td><td>tunnel বন্ধ হয়ে গেছে (laptop ঘুমিয়েছে, tunnel-এর window বন্ধ হয়েছে, বা internet গেছে)। tunnel আবার চালু করো, নতুন URL <span class="mono">/health</span>-এ যাচাই করো &mdash; মনে রাখো প্রতিবার ঠিকানা বদলায়।</td></tr>
  <tr><td><span class="mono">Try it out</span> বাটন দেখা যাচ্ছে না</td><td><span class="mono">POST /optimize-energy</span> সারিটা এখনো খোলনি। আগে ধূসর সারিতে click করো।</td></tr>
  <tr><td>Response code 422</td><td>paste করা JSON-এ হাত পড়েছে, বা অসম্পূর্ণ/দুইবার paste হয়েছে। বাক্সটা খালি করে Section ৫ থেকে আবার paste করো।</td></tr>
  <tr><td>প্রথম Execute ধীরে হচ্ছে</td><td>free tier-এ স্বাভাবিক। অপেক্ষা করো, দুইবার click করো না।</td></tr>
  <tr><td>শেষের দশমিক আলাদা মনে হচ্ছে</td><td>কখনো <span class="mono">38365.000001</span> দেখাবে <span class="mono">38365.00</span>-এর বদলে। এটা optimizer-এর tie-break tolerance, published optimum থেকে পার্থক্য মাত্র ০.০০০০০১ &mdash; judge জিজ্ঞেস করলে তবেই বলো।</td></tr>
</table>

<h2>৮. Record করার টিপস</h2>
<ul class="tight">
  <li>Chrome পুরো স্ক্রিনে (F11) record করো। 1080p, 30fps যথেষ্ট &mdash; সংখ্যাগুলো পড়া যেতে হবে।</li>
  <li>ইংরেজিতে, শান্ত গলায় বলো। পুরো ভিডিও ৩ থেকে ৫ মিনিটের মধ্যে রাখো।</li>
  <li>প্রতিটা Execute-এর পর <b>এক সেকেন্ড</b> থেমে থাকো, যাতে ফলটা স্পষ্ট দেখা যায়; তারপর মাউস নিয়ে যে সংখ্যাটা পড়ছ সেটার দিকে দেখাও।</li>
  <li>পুরোটা এক বসায়, এক tab-এ করো। মাঝখানে tab বদলাবে না।</li>
  <li>record বন্ধ করার আগে মিলিয়ে দেখো এগুলো দেখিয়েছ কি না: health, দুইটা official case, একটা নতুন ভাষার note, একটা <span class="mono">no_op</span>, একটা charging বন্ধের note, 405 ও 404 error, আর শেষ কথা।</li>
</ul>

<div class="footer-note">BUP CSE Fest 2026 preliminary round submission-এর জন্য তৈরি।
Live URL: <span class="mono">{LIVE}</span> &middot; Repository: <span class="mono">{REPO}</span></div>

{json_pages(bodies, 'bn')}

</body></html>"""


def main() -> None:
    bodies = build_bodies()
    OUT.mkdir(parents=True, exist_ok=True)
    from weasyprint import HTML

    english_doc = english(bodies)
    bangla_doc = bangla(bodies)

    en_font = '"DejaVu Sans", "Noto Sans Bengali", sans-serif'
    bn_font = '"Noto Sans Bengali", "DejaVu Sans", sans-serif'

    HTML(string=english_doc).write_pdf(
        OUT / "GridWise-Video-Demo-Guide-English.pdf",
        stylesheets=[__import__("weasyprint").CSS(string=css(en_font, "9.6pt"))],
    )
    HTML(string=bangla_doc).write_pdf(
        OUT / "GridWise-Video-Demo-Guide-Bangla.pdf",
        stylesheets=[__import__("weasyprint").CSS(string=css(bn_font, "10.2pt"))],
    )
    for name in ("GridWise-Video-Demo-Guide-English.pdf", "GridWise-Video-Demo-Guide-Bangla.pdf"):
        path = OUT / name
        print(f"{name}: {path.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
