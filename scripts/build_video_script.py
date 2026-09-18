#!/usr/bin/env python3
"""Build the three-minute demonstration script as a PDF.

Usage:
    python scripts/build_video_script.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_demo_guides import css  # noqa: E402  (shared stylesheet)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "demo" / "GridWise-3-Minute-Video-Script.pdf"

LIVE = "https://brian-sheffield-surely-fly.trycloudflare.com"
REPO = "https://github.com/meherabmehu/GridWise-LLM-Energy-Optimizer"

# --------------------------------------------------------------------------- beats
BEATS = [
    {
        "time": "0:00 &ndash; 0:15",
        "title": "Open: what this is",
        "screen": "The <span class='mono'>/health</span> page already open in Chrome",
        "say": "Hi &mdash; this is GridWise, our entry for the BUP CSE Fest preliminary round. "
               "Two endpoints: a health probe, and one that turns plain-English operator notes into a "
               "cost-optimal twenty-four hour energy schedule.",
        "do": "Start already standing on the health page. Do not scroll, do not touch the mouse.",
        "note": "Smile, breathe, speak slowly. This is the one sentence you must not rush &mdash; aim for "
                "about two and a half words per second.",
    },
    {
        "time": "0:15 &ndash; 0:45",
        "title": "How it works, in one breath",
        "screen": "Still on the health page",
        "say": "Three ideas hold it together. A real language model reads the notes and returns structured "
               "directives, and nothing else &mdash; it never sees the schedule and never does arithmetic. "
               "Deterministic guardrails clamp that output, so the model cannot change demand, solar, "
               "tariffs or battery limits. A deterministic linear program then solves the schedule, and an "
               "independent validator replays it before anything is returned. The solver runs two passes: "
               "minimum cost, then minimum battery cycling at that same cost &mdash; so we never pay for "
               "useless charge-and-discharge churn.",
        "do": "No mouse movement, no clicks. This is the technical heart of the video.",
        "note": "<b>Land the last sentence clearly.</b> The two-pass solver is a differentiator almost no "
                "other team will have implemented.",
    },
    {
        "time": "0:45 &ndash; 0:58",
        "title": "The two links a judge checks first",
        "screen": "health page, then switch tab to <span class='mono'>/docs</span>",
        "say": "The readiness probe returns status ok &mdash; that is the judge's health check. And "
               "<span class='mono'>/docs</span> is live Swagger, so anyone can run a real request by hand, "
               "exactly as I am about to.",
        "do": "Point at <span class='mono'>{\"status\":\"ok\"}</span>, then switch to the second tab showing "
              "<span class='mono'>/docs</span> and point at both endpoint rows.",
        "note": "Open <span class='mono'>/docs</span> in its own tab before you press record.",
    },
    {
        "time": "0:58 &ndash; 1:25",
        "title": "Case 1 &mdash; official sample SAMPLE-01",
        "screen": "<span class='mono'>/docs</span> &rarr; POST /optimize-energy &rarr; Try it out &rarr; "
                  "paste BODY A &rarr; Execute",
        "say": "Sample one has two notes. The panels get washed from noon to two PM, so usable solar drops "
               "to twenty-five percent in hours twelve and thirteen. The second note is about a "
               "registration deadline &mdash; nothing to do with energy. The interpretation reads solar "
               "reduction, factor zero-point-two-five, hours twelve and thirteen. And the unrelated note "
               "comes back as no-op &mdash; the model refuses to invent a rule where none exists. Totals: "
               "2,692.5 kilowatt-hours, 38,365 BDT, peak 175 &mdash; the organiser's published optimum.",
        "do": "Paste, click Execute, then rest the mouse on <span class='mono'>total_cost_bdt</span> while "
              "you read the total out loud.",
        "note": "Pause one full second after Execute so the response is visible on camera. If a validation "
                "note appears under the box while pasting, ignore it and click Execute anyway.",
    },
    {
        "time": "1:25 &ndash; 1:50",
        "title": "Case 2 &mdash; official sample SAMPLE-05",
        "screen": "same page &rarr; paste BODY B &rarr; Execute",
        "say": "Sample five caps grid import at 155 kilowatt-hours between six and nine PM. The interpreter "
               "resolves that to hours 18, 19 and 20 &mdash; start inclusive, end exclusive, exactly the "
               "convention used in the official data. The plan lands on 33,950 BDT with a 175 peak. "
               "Again, the published optimum.",
        "do": "Point at the <span class='mono'>hours</span> array, then at the total.",
        "note": "Saying &ldquo;start inclusive, end exclusive&rdquo; out loud tells the judge you read the "
                "specification properly. Most teams miss it.",
    },
    {
        "time": "1:50 &ndash; 2:25",
        "title": "Cases 3 to 5 &mdash; the generalisation proof",
        "screen": "paste BODY C, then BODY D, then BODY E",
        "say": "Now the part that matters most. This note is not in the sample set and is worded completely "
               "differently: the feeder is limited, keep hourly grid import under 155. Different words, "
               "same directive &mdash; same hours, same cap. That is generalisation, not phrase matching. "
               "Next, a note with nothing to do with energy &mdash; it returns no-op, so no bogus "
               "constraint ever reaches the solver. And this one is brand new: do not charge the battery "
               "between two and five AM. It returns no-charge-window for hours two, three and four, "
               "dropping the end hour &mdash; exactly as the official samples do.",
        "do": "Three separate pastes and Executes, one second of stillness after each.",
        "note": "<b>This is your highest-scoring segment.</b> The hidden tests are paraphrases, so proving "
                "generalisation live is worth more than re-showing official cases.",
    },
    {
        "time": "2:25 &ndash; 2:45",
        "title": "Case 6 &mdash; robustness, and Docker",
        "screen": "Type <span class='mono'>/optimize-energy</span> and then "
                  "<span class='mono'>/no-such-path</span> in the address bar",
        "say": "Bad input never breaks it. A GET on the POST endpoint gives 405, an unknown path gives 404, "
               "a malformed body gives 400 with a clean JSON error &mdash; no crash, no stack trace, never "
               "the API key. The project also ships as a Docker image: it builds, reports healthy, and "
               "answers with a live model call from inside the container.",
        "do": "Show the two error pages briefly &mdash; two seconds each, no more.",
        "note": "Docker is described verbally because it is not on screen. Say it factually; you have "
                "verified it yourself.",
    },
    {
        "time": "2:45 &ndash; 3:00",
        "title": "Close",
        "screen": "Back on the <span class='mono'>/health</span> page",
        "say": "Same code, same behaviour: locally, inside Docker, and on this public URL. All ten official "
               "cases reproduce the published optimum, and two hundred and twenty two automated tests "
               "pass. The repository and the live link are below. Thank you.",
        "do": "Stop moving the mouse. Look at the camera if you can, otherwise look at the screen and speak "
              "to it like a person.",
        "note": "Land the last two sentences slowly. Do not add anything after &ldquo;thank you&rdquo; "
                "&mdash; stop recording.",
    },
]

DIFFERENTIATORS = [
    ("The model interprets, the solver decides",
     "0:15 beat",
     "The language model only returns structured directives; it never sees the schedule and never does "
     "arithmetic. Say this explicitly &mdash; it is the exact boundary the rubric rewards, and it "
     "pre-empts any suspicion that the AI guessed a plan."),
    ("Two-pass lexicographic solver",
     "0:15 beat",
     "Pass one minimises cost; pass two minimises battery cycling while holding that cost, so the plan has "
     "no pointless charge-and-discharge churn. Very few teams do this, and it is visible in the schedule."),
    ("Independent validator replays every plan",
     "0:15 beat",
     "Before a success response leaves the service, a separate module recomputes all twenty-four balances, "
     "every directive constraint and all three totals. A plan that fails is rejected rather than returned, "
     "so a cheap-but-invalid plan can never reach the judge."),
    ("Start-inclusive, end-exclusive windows",
     "1:25 and 1:50 beats",
     "Say the convention out loud. It matches the official sample data, and it is the kind of detail that "
     "separates a careful team from a lucky one."),
    ("No-op safety",
     "0:58 and 1:50 beats",
     "Unrelated notes must not become constraints. Showing a live no-op proves the interpreter is not "
     "hallucinating rules &mdash; a failure mode judges specifically look for."),
    ("Live generalisation, not phrase matching",
     "1:50 beat",
     "You run a note that is not in the sample set, with completely different wording, and get the same "
     "directive. Since the hidden tests are paraphrases, this is the single most valuable thing you can "
     "show on camera."),
    ("Graceful degradation",
     "optional, 2:45 beat",
     "If a set of directives is jointly infeasible, the service retries with a reduced directive set and "
     "reports the run as degraded instead of failing. It also paces itself on the provider's rate-limit "
     "headers, and if the model is unreachable it falls back deterministically and says so in the log "
     "rather than pretending."),
    ("Strict error taxonomy, no leakage",
     "2:25 beat",
     "400 for unparsable bodies, 422 for schema failures, 413 for oversized payloads, 405 and 404 for "
     "wrong routes. Error bodies carry a type and a message only &mdash; never a key, never a stack trace."),
    ("Verified container, not a claimed one",
     "2:25 beat",
     "The image was built, started, health-checked and exercised with a live model call inside the "
     "container. The image carries no credentials &mdash; that was confirmed by scanning the built image."),
    ("222 automated tests",
     "2:45 beat",
     "195 offline tests that need no key, plus 27 live tests that call the model. Among them are tests "
     "that build deliberately invalid plans and assert that the validator rejects them."),
]

NUMBERS = [
    ("GET /health", '200 {"status":"ok"}', "about 10 ms"),
    ("SAMPLE-01 (official)", "solar_reduction hours [12, 13] factor 0.25 + no_op",
     "2692.50 kWh / 38365.00 BDT / peak 175.00"),
    ("SAMPLE-05 (official)", "max_grid_window hours [18, 19, 20] cap 155 kWh",
     "2430.00 kWh / 33950.00 BDT / peak 175.00"),
    ("Paraphrase of the same cap", "max_grid_window hours [18, 19, 20] cap 155 kWh",
     "2430.00 kWh / 33950.00 BDT / peak 175.00"),
    ("Unrelated note", "no_op, applies false, structured_adjustment null",
     "2430.00 kWh / 33950.00 BDT / peak 175.00"),
    ("Charging ban 2 AM to 5 AM", "no_charge_window hours [2, 3, 4]",
     "2430.00 kWh / 34130.00 BDT / peak 175.00"),
    ("Bad route", '405 {"detail":"Method Not Allowed"}', "instant"),
    ("Unknown path", '404 {"detail":"Not Found"}', "instant"),
    ("Malformed body", '400 {"error":{"type":"malformed_json", ...}}', "instant"),
    ("Cold model call", "language model interpreting the note", "0.3 to 1.8 s"),
    ("Repeat of the same note", "served from the interpretation cache", "about 10 ms"),
]

QA = [
    ("Is the AI doing the optimisation?",
     "No. The language model only converts notes into structured directives. All scheduling and arithmetic "
     "happen in a deterministic linear program, so the same scenario and the same notes always produce the "
     "same plan."),
    ("What if the model returns something nonsense?",
     "Guardrails normalise it before it can reach the solver: hours are snapped to valid slots, factors and "
     "capacities are clamped to physical range, unknown directive types collapse to no_op, and exactly one "
     "entry per note is enforced."),
    ("What if the notes contradict the physics?",
     "If the combined constraint set is infeasible, the service retries with a reduced directive set and "
     "marks the response as degraded, rather than returning an invalid schedule or an error."),
    ("Why this model?",
     "Groq's gpt-oss-20b, an open-weight model. It was the fastest option that returned correct structured "
     "output in our own benchmark, which matters because every request needs a live model call."),
    ("How fast is it, and does it fit the limits?",
     "A cold request is typically under two seconds end to end; a repeated note is about ten milliseconds "
     "from cache. Well inside the thirty-second timeout and the five-second p95 target."),
    ("Is the URL permanent?",
     "It is a live tunnel in front of the running service. The repository ships a Dockerfile and "
     "deployment instructions so it can be placed on a permanent host."),
    ("How did you avoid leaking secrets?",
     "The key lives only in a local .env file that is excluded from git, the built image was scanned and "
     "confirmed to contain no credentials, and error responses never echo request internals."),
]


# --------------------------------------------------------------------------- render
def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text)


def speakable_words() -> int:
    total = 0
    for beat in BEATS:
        clean = strip_tags(beat["say"]).replace("&mdash;", " ").replace("&rsquo;", "'")
        total += len([word for word in clean.split() if any(ch.isalnum() for ch in word)])
    return total


def beats_html() -> str:
    out = []
    for index, beat in enumerate(BEATS, start=1):
        out.append(
            f'<div class="beat">'
            f'<div class="beathead"><span class="clock">{beat["time"]}</span>'
            f'<span class="beatitle">{index}. {beat["title"]}</span></div>'
            f'<div class="row"><span class="lbl">On screen</span><span class="val">{beat["screen"]}</span></div>'
            f'<div class="say"><b>SAY:</b> &ldquo;{beat["say"]}&rdquo;</div>'
            f'<div class="row"><span class="lbl">Do</span><span class="val">{beat["do"]}</span></div>'
            f'<div class="row"><span class="lbl">Delivery</span><span class="val">{beat["note"]}</span></div>'
            f"</div>"
        )
    return "".join(out)


def differentiators_html() -> str:
    rows = "".join(
        f'<tr><td><b>{name}</b></td><td class="small">{where}</td><td class="small">{why}</td></tr>'
        for name, where, why in DIFFERENTIATORS
    )
    return (
        "<table><tr><th>What makes this different</th><th>Where to say it</th>"
        f"<th>Why it earns marks</th></tr>{rows}</table>"
    )


def numbers_html() -> str:
    rows = "".join(
        f'<tr><td>{label}</td><td class="mono small">{value}</td><td class="small">{extra}</td></tr>'
        for label, value, extra in NUMBERS
    )
    return f"<table><tr><th>Check</th><th>Exact result</th><th>Timing / totals</th></tr>{rows}</table>"


def qa_html() -> str:
    return "".join(
        f'<div class="qa"><b>Q. {question}</b><p>{answer}</p></div>' for question, answer in QA
    )


TEMPLATE = """<!doctype html><html><head><meta charset="utf-8"><title>GridWise 3-minute video script</title></head><body>

<div class="cover">
  <h1>GridWise &mdash; Three-Minute Demonstration Script</h1>
  <p class="lead">A complete, ready-to-read narration for the walkthrough video: eight timed beats with the
     exact words to say, what should be on screen, and where each differentiator lands. Everything is done in
     the browser using only the public link &mdash; no terminal, no editor.</p>
  <div class="meta">
    <div><span class="k">Live URL</span><span class="mono">@@LIVE@@</span></div>
    <div><span class="k">Repository</span><span class="mono">@@REPO@@</span></div>
    <div><span class="k">Runtime</span>3:00 &mdash; 8 beats, 9 screen actions</div>
    <div><span class="k">Word budget</span>@@WORDS@@ spoken words, about 165 words per minute</div>
  </div>
</div>

<h2>Before you press record</h2>
<ol class="tight">
  <li>The tunnel window stays open, the laptop stays on the charger, and sleep is disabled. The link dies
      within seconds if any of those change.</li>
  <li>Open <span class="mono">@@LIVE@@/health</span> in Chrome tab one and
      <span class="mono">@@LIVE@@/docs</span> in tab two, then confirm tab one shows
      <span class="mono">{"status":"ok"}</span>.</li>
  <li>Chrome zoom 110&ndash;125 percent, bookmarks bar hidden, notifications off, personal tabs closed, and
      record the browser in full screen (F11).</li>
  <li>Keep this PDF open in a third tab. You will paste five request bodies &mdash; BODY A to BODY E from the
      companion demo guide.</li>
  <li>Rehearse once with a stopwatch, then record. Do not record the first run.</li>
</ol>
<div class="warn"><b>Pacing is the whole game.</b> Read each beat at about 165 words per minute and pause for
one full second after every Execute. If you finish before 2:50, slow down &mdash; do not add new content. If
you overrun, cut the Docker sentence in beat 7 before cutting anything else.</div>

<h2>The script</h2>
@@BEATS@@

<h2>What makes this project different &mdash; and when to say it</h2>
<p>Ten features worth naming out loud. Do not list them all at once &mdash; each one is already placed in a
beat above. This table is your checklist.</p>
@@DIFFS@@

<h2>Numbers cheat sheet</h2>
<p>Every figure below was measured against the live service. If a number on screen differs in the last
decimals &mdash; for example 38365.000001 instead of 38365.00 &mdash; that is the solver's tie-break
tolerance, within 0.000001 of the published optimum. Do not mention it unless a judge asks.</p>
@@NUMBERS@@

<h2>If something goes wrong mid-recording</h2>
<table>
  <tr><th>Symptom</th><th>What to do</th></tr>
  <tr><td>A request is slow</td><td>Keep talking: &ldquo;the model call is in flight &mdash; that is the
      language model reading the note, not a lookup table.&rdquo; Never click Execute twice.</td></tr>
  <tr><td>Response code is 422</td><td>The paste was edited or cut short. Clear the box, paste again from the
      companion guide, Execute. Cut that take in editing if you prefer.</td></tr>
  <tr><td>Try it out button missing</td><td>You have not expanded the
      <span class="mono">POST /optimize-energy</span> row yet. Click the grey bar first.</td></tr>
  <tr><td>A page will not load at all</td><td>Stop recording. Restart the tunnel, confirm the new link on
      <span class="mono">/health</span>, and start the take again &mdash; the URL changes every restart.</td></tr>
  <tr><td>You stumble on a line</td><td>Pause, breathe, and repeat the sentence from its beginning. Cut the
      pause in editing; it reads as thoughtful, not as a mistake.</td></tr>
</table>

<h2>If a judge asks</h2>
@@QA@@

<div class="box"><b>Closing rule.</b> Say only what you can point at on screen. Everything in this script is
verified: the ten official optima, the paraphrase results, the error codes, the Docker run and the test count.
If you are asked about something you did not verify, say so plainly &mdash; judges reward precision far more
than confidence.</div>

<div class="footer-note">Live URL: <span class="mono">@@LIVE@@</span> &middot;
Repository: <span class="mono">@@REPO@@</span></div>

</body></html>"""

EXTRA_CSS = """
.beat { border: 0.9pt solid #cddbd4; border-left: 3pt solid #0f3d2e; border-radius: 1.6mm;
        padding: 2.6mm 3.2mm; margin: 0 0 3mm 0; page-break-inside: avoid; }
.beathead { margin-bottom: 1.6mm; }
.clock { display: inline-block; background: #0f3d2e; color: #ffffff; border-radius: 1.2mm;
         padding: 0.5mm 2mm; font-family: "DejaVu Sans Mono", monospace; font-size: 8.4pt; margin-right: 2mm; }
.beatitle { font-weight: bold; color: #14342a; font-size: 10.4pt; }
.row { margin: 1mm 0; }
.lbl { display: inline-block; min-width: 20mm; color: #4a5a52; font-size: 8.4pt;
       text-transform: uppercase; letter-spacing: 0.3pt; vertical-align: top; }
.val { display: inline-block; width: 148mm; }
.say { background: #f4f9f6; border: 0.7pt solid #b9cec4; border-radius: 1.2mm; padding: 2.2mm 2.6mm;
       margin: 1.6mm 0; font-size: 10pt; }
.qa { border-left: 2.4pt solid #2f7d5f; padding-left: 3mm; margin: 0 0 2.6mm 0; page-break-inside: avoid; }
.qa p { margin: 0.8mm 0 0 0; }
"""


def build() -> Path:
    document = (
        TEMPLATE.replace("@@LIVE@@", LIVE)
        .replace("@@REPO@@", REPO)
        .replace("@@WORDS@@", str(speakable_words()))
        .replace("@@BEATS@@", beats_html())
        .replace("@@DIFFS@@", differentiators_html())
        .replace("@@NUMBERS@@", numbers_html())
        .replace("@@QA@@", qa_html())
    )
    from weasyprint import CSS, HTML

    HTML(string=document).write_pdf(
        OUT,
        stylesheets=[CSS(string=css('"DejaVu Sans", "Noto Sans Bengali", sans-serif', "9.8pt") + EXTRA_CSS)],
    )
    return OUT


if __name__ == "__main__":
    path = build()
    words = speakable_words()
    seconds = words / 165 * 60
    print(f"{path.name}: {path.stat().st_size / 1024:.0f} KB")
    print(f"spoken words: {words} -> {int(seconds) // 60}:{int(seconds) % 60:02d} of narration "
          f"at 165 wpm, plus 9 one-second screen pauses = about 3:01 total")
    for index, beat in enumerate(BEATS, start=1):
        count = len([w for w in strip_tags(beat["say"]).split() if any(ch.isalnum() for ch in w)])
        print(f"  beat {index}: {count:3} words  ({beat['time'].replace('&ndash;', '-')})")
