#!/usr/bin/env python3
"""Build the short (2:30) demo script in English and Bangla, plus the paste pack.

Writes:
    docs/demo/GridWise-Demo-Script-English.pdf
    docs/demo/GridWise-Demo-Script-Bangla.pdf
    docs/demo/GridWise-Demo-Test-Cases.pdf

Usage:
    python scripts/build_short_demo_script.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_demo_guides import css  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "demo"
BODIES = ROOT / "docs" / "test-cases" / "request-bodies"

LIVE = "https://brian-sheffield-surely-fly.trycloudflare.com"
REPO = "https://github.com/meherabmehu/GridWise-LLM-Energy-Optimizer"

# --------------------------------------------------------------------------- script
# Two minutes forty seconds in three parts: intro 30s, what the model does 10s,
# three cases 80s, robustness 25s, close 15s.
BEATS: List[Dict[str, Any]] = [
    {
        "part": "PART 1 &mdash; INTRO",
        "time": "0:00 &ndash; 0:15",
        "title": "The problem, in four lines",
        "screen": "Start on the <span class='mono'>/health</span> page",
        "say": "This is GridWise. A campus needs the cheapest possible plan for the next twenty-four hours "
               "of electricity. Every hour has a demand, some solar, and a price, and there is one battery. "
               "The instructions arrive as a few sentences written in plain English.",
        "bn_say": "ক্যাম্পাসের ২৪ ঘণ্টার বিদ্যুতের সবচেয়ে কম খরচের plan বানাতে হবে। প্রতি ঘণ্টায় demand, solar "
                  "আর দাম আছে; একটা battery আছে। আর আমাদের হাতে শুধু মানুষের লেখা কয়েকটা সাধারণ ইংরেজি বাক্য "
                  "থাকে — operator notes।",
        "do": "Do not scroll. Speak calmly.",
        "tip": "Keep this short. You have only thirty seconds for the whole introduction.",
    },
    {
        "part": "PART 1 &mdash; INTRO",
        "time": "0:15 &ndash; 0:30",
        "title": "Our solution, in four lines",
        "screen": "Still on the health page",
        "say": "Our solution has three parts. A real language model reads the notes and returns only "
               "structured directives &mdash; it never does the maths. Guardrails then check that output, so "
               "it cannot change the data. And a solver builds the cheapest valid plan, which a validator "
               "checks before we reply.",
        "bn_say": "আমাদের সমাধান তিন ভাগে: (১) আসল ভাষা-মডেল note পড়ে শুধু structured directive বের করে — "
                  "হিসাব করে না। (২) guardrail সেই উত্তর যাচাই করে, তাই data বদলানো সম্ভব নয়। (৩) solver "
                  "সবচেয়ে কম খরচের বৈধ plan বানায়, আর reply দেওয়ার আগে validator সেটা মিলিয়ে দেখে।",
        "do": "No mouse movement. This is the only technical sentence in the video.",
        "tip": "Say &ldquo;it never does the maths&rdquo; slowly. That is the line judges listen for.",
    },
    {
        "part": "PART 1 &mdash; THE MODEL",
        "time": "0:30 &ndash; 0:40",
        "title": "What the language model actually does",
        "screen": "Whatever is on screen &mdash; do not move the mouse",
        "say": "So what does the language model actually do? It turns a sentence into structure: which rule, "
               "which hours, which value. Nothing else &mdash; the maths stays with the solver.",
        "bn_say": "তাহলে ভাষা-মডেলটা আসলে কী করে? সে একটা বাক্যকে গঠনে বদলায়: কোন নিয়ম, কোন ঘণ্টা, কত মান। "
                  "এর বেশি কিছু নয় — হিসাবটা solver-এর হাতে থাকে।",
        "do": "Hold still. Ten seconds, no clicks.",
        "tip": "This beat exists because judges specifically ask &ldquo;what is the model doing?&rdquo; "
               "Answer it before they ask.",
    },
    {
        "part": "PART 2 &mdash; CASE 1",
        "time": "0:40 &ndash; 1:05",
        "title": "Official case one: two notes, one of them unrelated",
        "screen": "<span class='mono'>/docs</span> &rarr; POST /optimize-energy &rarr; Try it out &rarr; "
                  "paste CASE 1 &rarr; Execute",
        "say": "First case, an official sample. The panels are washed from noon to two PM, so usable solar "
               "drops to twenty-five percent. The second note is about a registration deadline &mdash; "
               "nothing to do with energy. Solar reduction, factor zero point two five, hours twelve and "
               "thirteen &mdash; and the unrelated note becomes no-op. Total cost: thirty-eight thousand "
               "three hundred sixty-five, the official optimum.",
        "bn_say": "প্রথম case, official sample। দুপুর ১২টা থেকে ২টা প্যানেল ধোয়া, তাই solar ২৫%। দ্বিতীয় note "
                  "বিদ্যুতের সাথে সম্পর্কহীন (registration deadline)। ফল: solar_reduction, factor 0.25, "
                  "hours 12 ও 13 — আর অসম্পর্কিত note → no_op। খরচ ৩৮,৩৬৫ BDT, যেটা official optimum।",
        "do": "Paste, Execute, wait one second, then rest the mouse on the total cost.",
        "tip": "<b>The no-op is the point.</b> Say it clearly &mdash; the model did not invent a rule.",
    },
    {
        "part": "PART 2 &mdash; CASE 2",
        "time": "1:05 &ndash; 1:30",
        "title": "Official case two: a limit on grid import",
        "screen": "Same page &rarr; paste CASE 2 &rarr; Execute",
        "say": "Second case, also official. Grid import is capped at one hundred fifty-five kilowatt-hours "
               "between six and nine in the evening. The interpreter gives hours eighteen, nineteen and "
               "twenty &mdash; the start hour counts, the end hour does not, which is the rule in the "
               "official data. The plan costs thirty-three thousand nine hundred fifty: the official "
               "optimum again.",
        "bn_say": "দ্বিতীয় case-ও official। সন্ধ্যা ৬টা থেকে ৯টা grid import সর্বোচ্চ ১৫৫ kWh। Interpreter দিল "
                  "hours 18, 19, 20 — শুরুর ঘণ্টা ধরা হয়, শেষেরটা নয় (official নিয়ম)। খরচ ৩৩,৯৫০ BDT — "
                  "আবারও official optimum।",
        "do": "Point at the hours list, then at the total cost.",
        "tip": "Saying &ldquo;the end hour does not count&rdquo; shows you read the official rule.",
    },
    {
        "part": "PART 2 &mdash; CASE 3",
        "time": "1:30 &ndash; 2:00",
        "title": "Case three: our language test &mdash; the most important one",
        "screen": "Same page &rarr; paste CASE 3 &rarr; Execute",
        "say": "Third case is the language test. Two sentences, and only the second one matters &mdash; the "
               "first is about the canteen. In casual words it asks us to be gentle on the grid between six "
               "and ten PM, under one hundred fifty kWh an hour. The model ignored the canteen and returned "
               "a grid cap: hours eighteen to twenty-one, limit one hundred fifty. Same meaning, new words "
               "&mdash; that is understanding, not keyword matching.",
        "bn_say": "তৃতীয় case-টাই ভাষার পরীক্ষা। দুইটা বাক্য, কিন্তু কাজের শুধু দ্বিতীয়টা — প্রথমটা canteen নিয়ে। "
                  "ঘরোয়া ভাষায় বলা হয়েছে: সন্ধ্যা ৬টা থেকে ১০টা grid-এর উপর চাপ কম রাখো, ঘণ্টায় ১৫০ kWh-র "
                  "নিচে। মডেল canteen-এর বাক্যটা বাদ দিয়ে দিল grid cap — hours 18–21, limit 150। একই অর্থ, "
                  "নতুন ভাষা — এটা বোঝাপড়া, keyword matching নয়।",
        "do": "Let the response sit on screen for a beat before the last sentence.",
        "tip": "<b>This is the highest-value moment of the video.</b> Slow down and give it your clearest voice.",
    },
    {
        "part": "PART 3 &mdash; ROBUSTNESS",
        "time": "2:00 &ndash; 2:25",
        "title": "Bad input, and two more notes that also work",
        "screen": "Type <span class='mono'>/no-such-path</span>, then <span class='mono'>/optimize-energy</span> "
                  "in the address bar",
        "say": "Bad input never breaks it: a wrong path gives four-oh-four, a GET on the POST endpoint gives "
               "four-oh-five, a broken body gives four hundred with a clean message &mdash; no crash, no API "
               "key. Two more notes work as well: an unrelated one becomes no-op, and a negation &mdash; "
               "charging is fine, but do not top up between four and seven &mdash; becomes a no-charge "
               "window for hours four, five and six.",
        "bn_say": "খারাপ input-এ কিছু ভাঙে না: ভুল path → 404, POST endpoint-এ GET → 405, ভাঙা body → 400 "
                  "পরিষ্কার message দিয়ে; crash নেই, key ফাঁস নেই। আরও দুইটা note কাজ করে: অসম্পর্কিত note → "
                  "no_op, আর একটা negation — “রাতে চার্জ করা ঠিক আছে, তবে ভোর ৪টা থেকে ৭টা নয়” → "
                  "no_charge_window, hours 4, 5, 6।",
        "do": "Show the two error pages briefly &mdash; two seconds each. Do not read the JSON aloud.",
        "tip": "Speak the codes as words: &ldquo;four-oh-four&rdquo;. It sounds natural and is easy to follow.",
    },
    {
        "part": "PART 3 &mdash; CLOSE",
        "time": "2:25 &ndash; 2:40",
        "title": "Close",
        "screen": "Back on the <span class='mono'>/health</span> page",
        "say": "All ten official cases match the published optimum, and a response comes back in under two "
               "seconds. Same code locally, in Docker, and on this public link. Thank you.",
        "bn_say": "Official ১০টা case-ই published optimum-এর সাথে মিলে যায়, আর উত্তর আসে ২ সেকেন্ডের কমে। "
                  "একই code local-এ, Docker-এ আর এই public link-এ চলে। ধন্যবাদ।",
        "do": "Stop moving the mouse. Say the last two sentences slowly, then stop recording.",
        "tip": "Do not add anything after &ldquo;thank you&rdquo;.",
    },
]

# --------------------------------------------------------------------------- cases
CASE_FILES = [
    ("CASE 1", "sample-01.json", "official", True),
    ("CASE 2", "sample-05.json", "official", True),
    ("CASE 3", "l1.json", "LLM test", True),
    ("CASE 4", "p6.json", "fresh paraphrase", False),
    ("CASE 5", "l2.json", "LLM test", False),
]

CASE_META = {
    "CASE 1": {
        "title_en": "Official sample SAMPLE-01 &mdash; solar reduction, plus a note to ignore",
        "title_bn": "Official SAMPLE-01 &mdash; সোলার হ্রাস, সাথে একটা note বাদ দিতে হবে",
        "proves_en": "The model reads two notes at once and returns no-op for the unrelated one.",
        "proves_bn": "মডেল একসাথে দুইটা note পড়ে, আর অসম্পর্কিতটাকে no_op করে দেয়।",
        "expect_en": "solar_reduction (hours [12, 13], factor 0.25) then no_op (applies false)",
        "expect_bn": "solar_reduction (hours [12, 13], factor 0.25), তারপর no_op (applies false)",
        "totals": "2692.50 kWh / 38365.00 BDT / peak 175.00 kWh",
        "official": "official optimum for this case: 2692.50 / 38365.00 / 175",
    },
    "CASE 2": {
        "title_en": "Official sample SAMPLE-05 &mdash; grid import capped from 6 PM to 9 PM",
        "title_bn": "Official SAMPLE-05 &mdash; সন্ধ্যা ৬টা থেকে ৯টা grid import-এর সীমা",
        "proves_en": "A window directive: the start hour counts, the end hour does not.",
        "proves_bn": "Window directive: শুরুর ঘণ্টা ধরা হয়, শেষেরটা নয়।",
        "expect_en": "max_grid_window (hours [18, 19, 20], max_grid_kwh 155.0)",
        "expect_bn": "max_grid_window (hours [18, 19, 20], max_grid_kwh 155.0)",
        "totals": "2430.00 kWh / 33950.00 BDT / peak 175.00 kWh",
        "official": "official optimum for this case: 2430.00 / 33950.00 / 175",
    },
    "CASE 3": {
        "title_en": "Language test &mdash; a distractor sentence, then a casually worded grid limit",
        "title_bn": "ভাষার পরীক্ষা &mdash; প্রথম বাক্যটা অপ্রাসঙ্গিক, দ্বিতীয়টায় ঘরোয়া ভাষায় grid সীমা",
        "proves_en": "The model keeps the real instruction, ignores the canteen sentence, and extracts the "
                     "window and the limit from casual wording. A keyword matcher fails here.",
        "proves_bn": "মডেল আসল নির্দেশনাটা রাখে, canteen-এর বাক্য বাদ দেয়, আর ঘরোয়া ভাষা থেকেই window ও limit "
                     "বের করে। Keyword matching এখানে ফেল করবে।",
        "expect_en": "max_grid_window (hours [18, 19, 20, 21], max_grid_kwh 150.0)",
        "expect_bn": "max_grid_window (hours [18, 19, 20, 21], max_grid_kwh 150.0)",
        "totals": "2430.00 kWh / 33950.00 BDT / peak 175.00 kWh",
        "official": "",
    },
    "CASE 4": {
        "title_en": "Unrelated note &mdash; must produce no_op",
        "title_bn": "অসম্পর্কিত note &mdash; no_op আসতে হবে",
        "proves_en": "No invented rule when a note has nothing to do with energy.",
        "proves_bn": "note বিদ্যুতের সাথে সম্পর্কহীন হলে কোনো বাড়তি নিয়ম বানায় না।",
        "expect_en": "no_op (applies false, structured_adjustment null)",
        "expect_bn": "no_op (applies false, structured_adjustment null)",
        "totals": "2430.00 kWh / 33950.00 BDT / peak 175.00 kWh",
        "official": "",
    },
    "CASE 5": {
        "title_en": "Language test &mdash; negation: night charging is fine, no top-up 4 AM to 7 AM",
        "title_bn": "ভাষার পরীক্ষা &mdash; negation: রাতে চার্জ চলবে, ভোর ৪টা থেকে ৭টা নয়",
        "proves_en": "The model handles negation: it allows overnight charging and blocks only the stated "
                     "window, instead of blocking charging entirely.",
        "proves_bn": "মডেল negation বোঝে: রাতের চার্জ চালু রাখে, শুধু বলা ঘণ্টাগুলো বন্ধ করে — পুরো चाর্জ "
                     "বন্ধ করে দেয় না।".replace("चाর্জ", "চার্জ"),
        "expect_en": "no_charge_window (hours [4, 5, 6])",
        "expect_bn": "no_charge_window (hours [4, 5, 6])",
        "totals": "2430.00 kWh / 34010.00 BDT / peak 175.00 kWh",
        "official": "",
    },
}

ERROR_CHECKS = [
    ("Wrong path", f"Open {LIVE}/no-such-path", '404 {"detail":"Not Found"}'),
    ("GET on the POST endpoint", f"Open {LIVE}/optimize-energy", '405 {"detail":"Method Not Allowed"}'),
    ("Malformed body", "/docs -> POST /optimize-energy -> Try it out -> paste the word boom -> Execute",
     '400 {"error":{"type":"malformed_json","message":"request body is not valid JSON"}}'),
]


# --------------------------------------------------------------------------- helpers
def speakable_words() -> int:
    total = 0
    for beat in BEATS:
        clean = re.sub(r"<[^>]+>", "", beat["say"]).replace("&mdash;", " ")
        total += len([w for w in clean.split() if any(c.isalnum() for c in w)])
    return total


def load_case_bodies() -> Dict[str, str]:
    out = {}
    for label, filename, _, _ in CASE_FILES:
        out[label] = (BODIES / filename).read_text(encoding="utf-8").strip()
    return out


EXTRA_CSS = """
.beat { border: 0.9pt solid #cddbd4; border-left: 3pt solid #0f3d2e; border-radius: 1.6mm;
        padding: 2.6mm 3.2mm; margin: 0 0 3mm 0; page-break-inside: avoid; }
.part { display: inline-block; background: #eef5f1; color: #14342a; border: 0.7pt solid #b9cec4;
        border-radius: 1.2mm; padding: 0.4mm 1.8mm; font-size: 8.2pt; margin-right: 2mm; }
.clock { display: inline-block; background: #0f3d2e; color: #ffffff; border-radius: 1.2mm;
         padding: 0.5mm 2mm; font-family: "DejaVu Sans Mono", monospace; font-size: 8.4pt; margin-right: 2mm; }
.beatitle { font-weight: bold; color: #14342a; font-size: 10.4pt; }
.row { margin: 1mm 0; }
.lbl { display: inline-block; min-width: 19mm; color: #4a5a52; font-size: 8.2pt; letter-spacing: 0.3pt;
       vertical-align: top; }
.val { display: inline-block; width: 150mm; }
.say { background: #f4f9f6; border: 0.7pt solid #b9cec4; border-radius: 1.2mm; padding: 2.2mm 2.6mm;
       margin: 1.6mm 0; font-size: 10.4pt; line-height: 1.5; }
.bn { background: #fbfbf7; border: 0.7pt solid #e0ddd0; border-radius: 1.2mm; padding: 2mm 2.6mm;
      margin: 1.2mm 0 0 0; font-size: 9.4pt; color: #3a4038; }
.casecard { border: 0.9pt solid #cddbd4; border-radius: 1.6mm; padding: 3mm 3.4mm; margin: 0 0 3mm 0;
            page-break-inside: avoid; }
.primary { background: #0f3d2e; color: #fff; border-radius: 1.2mm; padding: 0.4mm 1.8mm; font-size: 8.2pt; }
.optional { background: #c47a12; color: #fff; border-radius: 1.2mm; padding: 0.4mm 1.8mm; font-size: 8.2pt; }
"""


def beats_html(bangla: bool) -> str:
    out = []
    for index, beat in enumerate(BEATS, start=1):
        block = []
        if index == 1 or BEATS[index - 2]["part"] != beat["part"]:
            block.append(f'<h3>{beat["part"]}</h3>')
        say_label = "যা বলবে (ইংরেজিতে)" if bangla else "SAY"
        bn_block = f'<div class="bn">{beat["bn_say"]}</div>' if bangla else ""
        do_label = "স্ক্রিনে" if bangla else "Do"
        tip_label = "খেয়াল রাখো" if bangla else "Tip"
        screen_label = "কোথায়" if bangla else "On screen"
        block.append(
            f'<div class="beat">'
            f'<div><span class="clock">{beat["time"]}</span><span class="beatitle">{beat["title"]}</span></div>'
            f'<div class="row"><span class="lbl">{screen_label}</span><span class="val">{beat["screen"]}</span></div>'
            f'<div class="say"><b>{say_label}:</b> &ldquo;{beat["say"]}&rdquo;</div>'
            f"{bn_block}"
            f'<div class="row" style="margin-top:1.6mm"><span class="lbl">{do_label}</span>'
            f'<span class="val">{beat["do"]}</span></div>'
            f'<div class="row"><span class="lbl">{tip_label}</span><span class="val">{beat["tip"]}</span></div>'
            f"</div>"
        )
        out.append("".join(block))
    return "".join(out)


def case_cards_html(bangla: bool) -> str:
    out = []
    for label, _, _, primary in CASE_FILES:
        meta = CASE_META[label]
        title = meta["title_bn"] if bangla else meta["title_en"]
        proves = meta["proves_bn"] if bangla else meta["proves_en"]
        expect = meta["expect_bn"] if bangla else meta["expect_en"]
        expect_label = "প্রত্যাশিত" if bangla else "Expected"
        totals_label = "খরচ" if bangla else "Totals"
        badge = ('<span class="primary">SHOW IN VIDEO</span>' if primary
                 else '<span class="optional">EXTRA</span>')
        official = f'<br><span class="small">{meta["official"]}</span>' if meta["official"] else ""
        out.append(
            f'<div class="casecard">'
            f'<div><b>{label}</b> &nbsp;{badge}&nbsp; {title}</div>'
            f'<p class="small" style="margin:1.4mm 0 0.8mm 0">{proves}</p>'
            f'<p style="margin:0"><b>{expect_label}</b>: <span class="mono">{expect}</span><br>'
            f'<b>{totals_label}</b>: <span class="mono">{meta["totals"]}</span>{official}</p>'
            f"</div>"
        )
    return "".join(out)


def body_pages_html(bodies: Dict[str, str], bangla: bool) -> str:
    if bangla:
        hint = ("পুরো ব্লকটা সিলেক্ট করে কপি করো, তারপর Swagger-এর Request body বাক্সে পেস্ট করো। "
                "হুবহু পেস্ট করো — একটাও অক্ষর বদলাবে না।")
        back = "একই body এখানেও আছে "
    else:
        hint = ("Select the whole block, copy it, and paste it into the Swagger Request body box. "
                "Paste it exactly &mdash; do not change one character.")
        back = "Also available at "
    out = []
    for label, filename, _, _ in CASE_FILES:
        title = CASE_META[label]["title_en"]
        url = f"{REPO}/blob/main/docs/test-cases/request-bodies/{filename}"
        out.append(
            f'<div class="jsonpage">'
            f'<div class="jsonhead">{label} &nbsp;&mdash;&nbsp; {html.escape(re.sub(r"&mdash;", "-", title))}</div>'
            f'<div class="jsonhint">{hint}</div>'
            f'<pre class="body">{html.escape(bodies[label])}</pre>'
            f'<div class="jsonhint" style="margin-top:2mm">{back}<span class="mono">{url}</span></div>'
            f"</div>"
        )
    return "".join(out)


def error_section(bangla: bool) -> str:
    head = ("<tr><th>What to do</th><th>Expected</th></tr>" if not bangla
            else "<tr><th>কী করবে</th><th>প্রত্যাশিত ফল</th></tr>")
    rows = "".join(
        f'<tr><td class="small">{html.escape(what)}</td><td class="mono small">{html.escape(expect)}</td></tr>'
        for _, what, expect in ERROR_CHECKS
    )
    return f"<table>{head}{rows}</table>"


# --------------------------------------------------------------------------- documents
def script_document(bangla: bool) -> str:
    if bangla:
        title = "GridWise &mdash; ২:৪০ মিনিটের Demo Script"
        lead = ("প্রথম ৩০ সেকেন্ডে সমস্যা ও সমাধান, তারপর ১০ সেকেন্ডে ভাষা-মডেলটা আসলে কী করে, "
                "এরপর ৮০ সেকেন্ডে তিনটা সবচেয়ে গুরুত্বপূর্ণ test case, আর শেষে error handling ও শেষ কথা — "
                "মোট ২:৪০। প্রতিটা ধাপে আছে — স্ক্রিনে কী করবে, ইংরেজিতে হুবহু কী বলবে, আর ছোট করে তার মানে।")
        steps_head = "রেকর্ড করার আগে"
        steps = [
            "tunnel-এর window খোলা রাখো, laptop চার্জারে, sleep বন্ধ।",
            f"tab ১-এ <span class='mono'>{LIVE}/health</span>, tab ২-এ <span class='mono'>{LIVE}/docs</span> খোলা রাখো।",
            "Chrome zoom ১১০–১২৫%, notification বন্ধ, পুরো স্ক্রিনে (F11) রেকর্ড করো।",
            "পাশে <b>Test Cases</b> ফাইলটা খোলা রাখো — ওখান থেকেই CASE 1, 2, 3 কপি করবে।",
        ]
        script_head = "স্ক্রিপ্ট"
        cases_head = "ভিডিওতে যেই তিনটা case দেখাবে"
        error_head = "শেষ ৩০ সেকেন্ডে error দেখানোর ধাপ"
        note = ("<b>সময়ের হিসাব:</b> narration মোট ৪০০ শব্দের মতো — স্বাভাবিক গতিতে ২:৪০। "
                "তাড়াহুড়া করবে না; একটু কম বলে ফেললেও ক্ষতি নেই, কিন্তু তাড়াতাড়ি পড়লে judge কিছু "
                "বুঝতেই পারবেন না।")
        delivery_head = "বলার সময় খেয়াল রাখো"
        delivery = [
            "প্রতি sentence-এর শেষে একটু থামো — বিশেষ করে সংখ্যাগুলোর পরে।",
            "প্রতিটা Execute-এর পর <b>এক সেকেন্ড</b> চুপ থাকো, যাতে ফলটা ক্যামেরায় স্পষ্ট দেখা যায়।",
            "কখনো Execute দুইবার চাপবে না — ধীরে এলেও অপেক্ষা করো।",
            "সংখ্যাগুলো কথা বলে বলো: ৩৮,৩৬৫ মানে &ldquo;thirty-eight thousand three hundred sixty-five&rdquo;।",
        ]
    else:
        title = "GridWise &mdash; 2:40 Demo Script"
        lead = ("The problem and our solution in the first thirty seconds, ten seconds on what the language "
                "model actually does, the three most important test cases in the next eighty seconds, then "
                "error handling and the close. Every beat tells you what to do on screen, exactly what to "
                "say, and how to say it.")
        steps_head = "Before you press record"
        steps = [
            "Tunnel window open, laptop on the charger, sleep disabled.",
            f"Tab one: <span class='mono'>{LIVE}/health</span>. Tab two: <span class='mono'>{LIVE}/docs</span>.",
            "Chrome zoom 110 to 125 percent, notifications off, record in full screen (F11).",
            "Keep the <b>Test Cases</b> file open beside you &mdash; that is where you copy CASE 1, 2 and 3 from.",
        ]
        script_head = "The script"
        cases_head = "The three cases shown in the video"
        error_head = "Error steps for the last thirty seconds"
        note = ("<b>Timing.</b> The narration is about four hundred words, which is 2:40 at a calm pace. "
                "Do not rush. Speaking a little less is fine; speaking too fast loses the judge completely.")
        delivery_head = "Delivery notes"
        delivery = [
            "Pause briefly at the end of every sentence, especially after a number.",
            "Wait <b>one second</b> after each Execute so the result is visible on camera.",
            "Never click Execute twice &mdash; wait for it, even when the model call is slow.",
            "Say numbers as words: &ldquo;thirty-eight thousand three hundred sixty-five&rdquo;.",
        ]

    bullets = "".join(f"<li>{step}</li>" for step in steps)
    delivery_items = "".join(f"<li>{item}</li>" for item in delivery)

    return (
        f'<!doctype html><html><head><meta charset="utf-8"><title>{title}</title></head><body>'
        f'<div class="cover"><h1>{title}</h1><p class="lead">{lead}</p>'
        f'<div class="meta">'
        f'<div><span class="k">Live URL</span><span class="mono">{LIVE}</span></div>'
        f'<div><span class="k">Repository</span><span class="mono">{REPO}</span></div>'
        f'<div><span class="k">Structure</span>0:00 intro &middot; 0:30 the model &middot; 0:40 three cases &middot; 2:00 robustness &middot; 2:25 close</div>'
        f"</div></div>"
        f"<h2>{steps_head}</h2><ul class='tight'>{bullets}</ul>"
        f"<h2>{script_head}</h2>{beats_html(bangla)}"
        f"<h2>{delivery_head}</h2><ul class='tight'>{delivery_items}</ul>"
        f"<h2>{cases_head}</h2>{case_cards_html(bangla)}"
        f"<h2>{error_head}</h2>{error_section(bangla)}"
        f'<div class="box">{note}</div>'
        f"</body></html>"
    )


def cases_document(bodies: Dict[str, str]) -> str:
    title = "GridWise &mdash; Cases to Paste During the Video"
    lead = ("Everything you copy and paste during the recording. Three cases are marked SHOW IN VIDEO and "
            "take ninety seconds together; the two marked EXTRA are the ones you mention out loud. "
            "Each body is on its own page, ready to select and copy.")
    return (
        f'<!doctype html><html><head><meta charset="utf-8"><title>{title}</title></head><body>'
        f'<div class="cover"><h1>{title}</h1><p class="lead">{lead}</p>'
        f'<div class="meta">'
        f'<div><span class="k">Live URL</span><span class="mono">{LIVE}/docs</span></div>'
        f'<div><span class="k">How to paste</span>Expand POST /optimize-energy &rarr; Try it out &rarr; '
        f'clear the box &rarr; paste &rarr; Execute</div>'
        f"</div></div>"
        f"<h2>1. The cases, with what each one proves</h2>{case_cards_html(False)}"
        f"<h2>2. Error-handling checks (no body needed)</h2>{error_section(False)}"
        f'<div class="box"><b>Afterwards.</b> If a result differs in the last decimals &mdash; 38365.000001 '
        f"instead of 38365.00 &mdash; that is the solver tie-break tolerance and is fine. Do not mention it "
        f"unless a judge asks.</div>"
        f'<h2>3. Copy-ready request bodies</h2>'
        f"<p class='small'>Pages below: CASE 1, CASE 2, CASE 3 (video), then CASE 4 and CASE 5 (extra).</p>"
        f"{body_pages_html(bodies, False)}"
        f"</body></html>"
    )


def build() -> None:
    from weasyprint import CSS, HTML

    bodies = load_case_bodies()
    en_css = CSS(string=css('"DejaVu Sans", "Noto Sans Bengali", sans-serif', "9.8pt") + EXTRA_CSS)
    bn_css = CSS(string=css('"Noto Sans Bengali", "DejaVu Sans", sans-serif', "10.2pt") + EXTRA_CSS)

    targets = [
        ("GridWise-Demo-Script-English.pdf", script_document(False), en_css),
        ("GridWise-Demo-Script-Bangla.pdf", script_document(True), bn_css),
        ("GridWise-Demo-Test-Cases.pdf", cases_document(bodies), en_css),
    ]
    for filename, document, sheet in targets:
        path = OUT / filename
        HTML(string=document).write_pdf(path, stylesheets=[sheet])
        print(f"{filename}: {path.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    build()
    words = speakable_words()
    seconds = words / 165 * 60
    print(f"narration: {words} words -> {int(seconds) // 60}:{int(seconds) % 60:02d} at 165 wpm "
          f"(plus screen pauses, target 2:40)")
    for index, beat in enumerate(BEATS, start=1):
        count = len([w for w in re.sub(r"<[^>]+>", "", beat["say"]).split() if any(c.isalnum() for c in w)])
        print(f"  beat {index}: {count:3} words  {beat['time'].replace('&ndash;', '-')}  {beat['title']}")
