# GridWise LLM Energy Optimizer

LLM-assisted operator directive interpretation and deterministic 24-hour energy
optimization for the **BUP CSE Fest 2026 Hackathon — Online Preliminary Round**.

The service reads a synthetic 24-hour campus energy scenario plus one to three
natural-language operator notes, converts every note into a machine-checkable
directive using a language model, validates that interpretation deterministically,
and solves the cost-minimizing hourly schedule.

| | |
| --- | --- |
| Health endpoint | `GET /health` → `{"status": "ok"}` |
| Main endpoint | `POST /optimize-energy` |
| Live API | **https://petition-personality-swing-civil.trycloudflare.com** |
| Language model | Groq — `openai/gpt-oss-20b` (OpenAI-compatible chat completions) |
| Optimizer | Exact linear program solved with HiGHS via `scipy.optimize.linprog` |
| Runtime | Python 3.12 · FastAPI · uvicorn |
| Official samples | 10 / 10 passed, every case matching the published optimum |

> **Live API note.** The URL above is a Cloudflare quick tunnel in front of the
> containerized service and is verified working. Quick tunnels have no uptime
> guarantee and stop when the hosting sandbox stops. For a permanent URL, deploy
> the same image with `deploy/huggingface/push_to_hf_space.sh` or any container
> host — see [Deployment](#deployment). A local run takes under a minute via
> [Local setup](#local-setup).

---

## Table of contents

- [Challenge overview](#challenge-overview)
- [What this service does](#what-this-service-does)
- [Architecture](#architecture)
- [Technology stack](#technology-stack)
- [The language model](#the-language-model)
- [How the language model is used](#how-the-language-model-is-used)
- [Directive types and normalisation](#directive-types-and-normalisation)
- [Guardrails](#guardrails)
- [Optimization method](#optimization-method)
- [Validation](#validation)
- [API reference](#api-reference)
- [Request example](#request-example)
- [Response example](#response-example)
- [Local setup](#local-setup)
- [Environment variables](#environment-variables)
- [Running the tests](#running-the-tests)
- [Docker](#docker)
- [Deployment](#deployment)
- [Project layout](#project-layout)
- [Performance](#performance)
- [Reliability and failure handling](#reliability-and-failure-handling)
- [Limitations](#limitations)
- [Dependencies and credits](#dependencies-and-credits)

---

## Challenge overview

A campus runs on grid electricity, rooftop solar and a battery. Demand, solar
availability and tariff vary hour by hour, and the next 24 hours are given.
Campus operators add short natural-language notes describing temporary operating
conditions. The service has to understand those notes, turn the relevant ones
into structured directives, apply them to the optimization, and return a valid
low-cost operating plan — while ignoring notes that do not affect the schedule.

Two things are scored separately: **did you understand the note**, and **did the
schedule actually obey it**. A cheap plan built on a misread directive scores
nothing.

## What this service does

1. Interprets **every** operator note with a language model — exactly one entry
   per note, in `note_index` order.
2. Re-shapes that untrusted output through deterministic guardrails, downgrading
   anything unsupported to `no_op` rather than inventing a rule.
3. Applies the surviving directives to the optimization model.
4. Solves the 24-hour schedule to cost optimality.
5. Replays and validates the finished plan before returning it.
6. Returns the interpretation and the schedule in one response.

## Architecture

```
Incoming JSON request
        │
        ▼
  Operator notes ─────────────────────────────────┐
        │                                         │
        ▼                                         │
  LLM interpreter  (Groq / OpenAI / Gemini)       │
        │                                         │
        ▼                                         │
  Structured directive interpretation             │
        │                                         │
        ▼                                         │
  Guardrails  (validate, normalise, downgrade)    │
        │                                         │
        ▼                                         │
  Directive constraints ──────────────────────────┤
        │                                         │
        ▼                                         ▼
  Deterministic energy optimizer  ◄──── scenario (demand, solar, tariff, battery)
        │
        ▼
  Final validator  (independent replay)
        │
        ▼
  Structured JSON response
```

The split matters: the language model only ever sees text, and the optimizer
only ever sees numbers. Neither can corrupt the other's job.

| Module | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI app, both endpoints, controlled error responses |
| `app/config.py` | Environment-driven settings and provider defaults |
| `app/models.py` | Request and response schemas |
| `app/llm_interpreter.py` | Provider client, prompt, retries, cache, fallback interpreter |
| `app/guardrails.py` | Deterministic validation and normalisation of model output |
| `app/directives.py` | Directive types and the constraint arrays they produce |
| `app/optimizer.py` | Linear program, schedule finalisation, plan summary |
| `app/validator.py` | Independent replay and total recalculation |
| `app/pipeline.py` | End-to-end orchestration |

## Technology stack

| Layer | Choice | Why |
| --- | --- | --- |
| HTTP | FastAPI + uvicorn | Exact schema enforcement via pydantic, async I/O for the model call |
| Language model | Groq `openai/gpt-oss-20b` | Lowest latency of the models tested (~0.3–0.6 s) with correct structured output |
| HTTP client | httpx | Connection pooling and precise timeout control |
| Optimizer | SciPy `linprog` (HiGHS) | Exact, deterministic, millisecond solves |
| Numerics | NumPy | Vectorised constraint assembly and validation |

## The language model

**Provider:** Groq · **Model:** `openai/gpt-oss-20b` · **Interface:** OpenAI-compatible
`POST /chat/completions` with `response_format={"type": "json_object"}` and
`temperature=0`.

The provider and model are configuration, not code. `LLM_PROVIDER` accepts
`groq`, `openai`, `gemini` or `openai_compatible`, and `LLM_MODEL` / `LLM_BASE_URL`
override the default for any of them, so the service can be pointed at a
different hosted model or a self-hosted OpenAI-compatible endpoint without a code
change. Model selection is documented in `app/config.py`.

## How the language model is used

The rules require a language-capable model on the operator-note path, and they
explicitly disallow hard-coded phrase matching as the sole interpreter, because
hidden cases paraphrase the same directive in different words.

The model is therefore the interpreter, and it is given:

- the six supported directive types and the exact `structured_adjustment` shape
  each one requires;
- the whole-hour convention, with worked examples (`1 PM to 3 PM → [13, 14]`);
- the rule that `factor` is the **usable fraction remaining**, so an 80%
  reduction is `0.2`;
- the rule that a percentage of battery capacity must be multiplied out;
- the instruction to use `no_op` for notes that cannot change today's schedule;
- the scenario's battery capacity and the hours with non-zero forecast solar,
  which is what disambiguates the official example *"panel washing from one until
  three"* into hours `[13, 14]` rather than `[1, 2]`.

All notes in a scenario go in **one** request, so a scenario costs one network
round trip. Responses are cached by a hash of the model, the notes, the battery
capacity and the daylight hours, so repeated evaluation requests are answered
from memory.

The model is never asked for demand, solar values, tariffs, battery parameters,
or the schedule itself. It only produces directives.

## Directive types and normalisation

Times are whole hours on a 24-hour clock. A window **includes its start hour and
excludes its end hour**.

| Note | Directive | `structured_adjustment` |
| --- | --- | --- |
| "Solar output will drop to about 20% from 1 PM to 3 PM." | `solar_reduction` | `{"hours": [13, 14], "factor": 0.2}` |
| "Do not charge the battery between 2 PM and 4 PM." | `no_charge_window` | `{"hours": [14, 15]}` |
| "Keep at least 120 kWh in reserve from 6 PM until 9 PM." | `minimum_battery_reserve` | `{"hours": [18, 19, 20], "minimum_energy_kwh": 120}` |
| "For protection testing the battery must not discharge from 6 PM until 8 PM." | `no_discharge_window` | `{"hours": [18, 19]}` |
| "From 6 PM until 9 PM grid import must not exceed 155 kWh." | `max_grid_window` | `{"hours": [18, 19, 20], "max_grid_kwh": 155}` |
| "The cafeteria menu changes tomorrow." | `no_op` | `null` |

`applies` is `true` for every directive except `no_op`, and `false` for `no_op`,
which is the only type allowed to have `applies = false` and a `null` adjustment.

How each directive changes the maths:

```
solar_reduction          effective_solar[h] = solar_kwh[h] * factor
minimum_battery_reserve  battery_energy_after_kwh[h] >= max(base minimum, directive minimum)
no_charge_window         battery charge amount = 0 in the listed hours
no_discharge_window      battery discharge amount = 0 in the listed hours
max_grid_window          grid_kwh[h] <= max_grid_kwh in the listed hours
no_op                    no change to the optimization model
```

Overlapping directives combine strictly: solar factors multiply, reserve floors
take the highest value, grid caps take the tightest cap, and any no-charge or
no-discharge window removes that action for the hour.

## Guardrails

Model output is treated as untrusted structured data until deterministic
validation passes. `app/guardrails.py` enforces:

| Guardrail | Behaviour |
| --- | --- |
| Allowed types | Anything outside the six published types becomes `no_op` |
| Note mapping | Exactly one entry per note; duplicates dropped, gaps filled, order restored |
| Hours | Unique integers `0..23`, ascending; unusable hour lists downgrade the directive |
| Solar factor | Normalised into `[0, 1]`, including a percentage-reduction repair |
| Reserve values | Finite, non-negative, clamped to battery capacity |
| Grid caps | Finite and non-negative |
| `applies` | Derived from the directive type, never taken from the model |
| No invention | Demand, solar, tariff and battery parameters are read from the request only |

Every repair is logged, so an operator can audit exactly what was changed.

## Optimization method

The scheduling problem is a compact linear program, so it is solved **exactly**
with HiGHS (`scipy.optimize.linprog`). Every run produces the same optimum, and a
solve takes single-digit milliseconds.

Five decision variables per hour — grid import, solar used, battery charge,
battery discharge, battery energy after the hour — subject to:

```
grid_kwh + solar_used_kwh + battery_discharge_kwh = demand_kwh + battery_charge_kwh
battery_energy_after_kwh[h] = battery_energy_after_kwh[h-1] + charge[h] - discharge[h]
battery_energy_after_kwh[23] = initial_energy_kwh
0 <= solar_used_kwh[h] <= effective_solar[h]
amounts <= capacity_kwh, reserve floors, max_charge / max_discharge per hour
grid_kwh[h] <= max_grid_kwh for capped hours
```

with the objective

```
total_cost_bdt = SUM(grid_kwh[h] * tariff_bdt_per_kwh[h])   for h = 0..23
```

minimized. A second lexicographic pass then minimizes battery throughput subject
to the cost found by the first pass, which removes battery cycling that buys
nothing while leaving the optimal cost unchanged to within a floating-point
epsilon. Finally, simultaneous charge and discharge are netted out and the grid
and battery-state series are derived from the balance and transition equations,
so the accounting holds **exactly** rather than approximately.

**Result on the official sample pack: all ten cases reproduce the published
optimal `total_grid_kwh`, `total_cost_bdt` and `peak_grid_kwh` values exactly.**

## Validation

Before any 200 response, `app/validator.py` replays the plan hour by hour the way
the judge does, and raises on:

24 entries for hours 0–23 in ascending order · per-hour energy balance ·
`battery_action` consistency and zero magnitude when idle · effective-solar
ceiling · non-negative grid import · battery capacity, reserve floor, state
transitions and hourly rate limits · no-charge, no-discharge and max-grid windows ·
end-of-day battery neutrality · `total_grid_kwh`, `total_cost_bdt` and
`peak_grid_kwh` recalculated from `hourly_plan`.

The internal tolerance is `1e-4`, two orders of magnitude stricter than the
official `0.01 kWh` / `0.01 BDT`. An invalid plan is never returned as a success.

## API reference

### `GET /health`

```http
HTTP/1.1 200 OK
Content-Type: application/json

{"status": "ok"}
```

### `POST /optimize-energy`

Request fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `scenario_id` | string | Scenario identifier, echoed back |
| `operator_notes` | array of 1–3 strings | Natural-language campus operator notes |
| `hours` | array[24] | `hour` (0–23), `demand_kwh`, `solar_kwh`, `tariff_bdt_per_kwh` |
| `battery` | object | `capacity_kwh`, `initial_energy_kwh`, `minimum_energy_kwh`, `max_charge_kwh_per_hour`, `max_discharge_kwh_per_hour` |

Response fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `scenario_id` | string | Echo of the request value |
| `directive_interpretation` | array | One entry per note, in `note_index` order |
| `hourly_plan` | array[24] | `hour`, `grid_kwh`, `solar_used_kwh`, `battery_action`, `battery_kwh`, `battery_energy_after_kwh` |
| `total_grid_kwh` | number | Sum of `grid_kwh` across the 24 hours |
| `total_cost_bdt` | number | Recalculated grid electricity cost |
| `peak_grid_kwh` | number | Maximum hourly `grid_kwh` |
| `plan_summary` | string | Short human-readable strategy description |

Status codes: `200` success · `400` malformed or empty body · `413` body over
256 KB · `422` well-formed but invalid scenario · `500` controlled internal error
with no stack trace or configuration leakage.

Interactive schema documentation is served at `/docs` and `/openapi.json`.

## Request example

```bash
curl -sS -X POST "https://petition-personality-swing-civil.trycloudflare.com/optimize-energy" \
  -H "Content-Type: application/json" \
  -d '{
    "scenario_id": "GRID-101",
    "operator_notes": [
      "Solar output will drop to about 20% from 1 PM to 3 PM.",
      "Do not charge the battery between 2 PM and 4 PM.",
      "The cafeteria menu changes tomorrow."
    ],
    "hours": [
      {"hour": 0, "demand_kwh": 180, "solar_kwh": 0, "tariff_bdt_per_kwh": 7},
      {"hour": 1, "demand_kwh": 175, "solar_kwh": 0, "tariff_bdt_per_kwh": 6}
    ],
    "battery": {
      "capacity_kwh": 500,
      "initial_energy_kwh": 200,
      "minimum_energy_kwh": 50,
      "max_charge_kwh_per_hour": 100,
      "max_discharge_kwh_per_hour": 100
    }
  }'
```

`hours` must contain all 24 entries. The abbreviated array above is for
readability only; the full request shape is in
`docs/official/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json`.

## Response example

Trimmed to three hours (real responses always carry all 24):

```json
{
  "scenario_id": "SAMPLE-05",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "max_grid_window",
      "structured_adjustment": {"hours": [18, 19, 20], "max_grid_kwh": 155.0},
      "explanation": "Grid import is capped at 155 kWh for each hour in the feeder-restriction window."
    }
  ],
  "hourly_plan": [
    {"hour": 17, "grid_kwh": 125.0, "solar_used_kwh": 10.0, "battery_action": "charge", "battery_kwh": 60.0, "battery_energy_after_kwh": 210.0},
    {"hour": 18, "grid_kwh": 145.0, "solar_used_kwh": 0.0, "battery_action": "discharge", "battery_kwh": 60.0, "battery_energy_after_kwh": 150.0},
    {"hour": 19, "grid_kwh": 155.0, "solar_used_kwh": 0.0, "battery_action": "discharge", "battery_kwh": 60.0, "battery_energy_after_kwh": 90.0}
  ],
  "total_grid_kwh": 2430.0,
  "total_cost_bdt": 33950.0,
  "peak_grid_kwh": 175.0,
  "plan_summary": "Applied operator directives: grid cap. Charges in the cheapest hours (00:00, 01:00, 02:00, 03:00, 04:00, 05:00, 15:00, 16:00, 17:00). Discharges into the most expensive hours (18:00, 19:00, 20:00). ..."
}
```

## Local setup

Requires Python 3.11 or newer.

```bash
# 1. Clone
git clone https://github.com/meherabmehu/GridWise-LLM-Energy-Optimizer.git
cd GridWise-LLM-Energy-Optimizer

# 2. Install
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Configure - copy the template and add your key
cp .env.example .env
#    then set LLM_API_KEY in .env

# 4. Run
set -a && source .env && set +a
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 5. Check readiness (in another shell)
curl -sS http://127.0.0.1:8000/health
# {"status":"ok"}

# 6. Run one official sample case end to end
python3 scripts/run_public_samples.py --url http://127.0.0.1:8000 --check-health
```

Step 6 prints a per-case pass line and finishes with `10/10 cases passed`, each
case reporting the recalculated cost next to the published optimum.

`LLM_PROVIDER` defaults to `groq`; a free key from
[console.groq.com/keys](https://console.groq.com/keys) is enough to run
everything. Without a key the service still starts and answers, using the
deterministic fallback interpreter, but the language-model interpretation step
required by the rules is then not exercised.

## Environment variables

| Name | Required | Default | Purpose |
| --- | --- | --- | --- |
| `LLM_API_KEY` | yes | – | Provider key for operator-note interpretation |
| `LLM_PROVIDER` | no | `groq` | `groq`, `openai`, `gemini`, `openai_compatible` |
| `LLM_MODEL` | no | provider default | Model identifier |
| `LLM_BASE_URL` | no | provider default | Override for a proxy or self-hosted model |
| `LLM_TIMEOUT_SECONDS` | no | `12` | Per-attempt request timeout |
| `LLM_MAX_ATTEMPTS` | no | `3` | Attempts before the fallback interpreter is used |
| `LLM_MAX_TOKENS` | no | `600` | Completion budget per interpretation |
| `LLM_TEMPERATURE` | no | `0` | Sampling temperature |
| `LLM_REASONING_EFFORT` | no | `low` on Groq | Reasoning budget for reasoning-capable models |
| `LLM_CACHE_SIZE` | no | `512` | Cached interpretations kept in memory |
| `LLM_CACHE_TTL_SECONDS` | no | `900` | Cache entry lifetime |
| `LLM_ENABLED` | no | `true` | Set `false` to skip the model entirely |
| `HOST` | no | `0.0.0.0` | Listen address |
| `PORT` | no | `8000` | Listen port (`7860` on Hugging Face Spaces) |
| `LOG_LEVEL` | no | `info` | Log verbosity |

Provider-specific key names also work: `GROQ_API_KEY`, `OPENAI_API_KEY`,
`GEMINI_API_KEY`.

**Never commit real keys.** `.env` is git-ignored and `.env.example` contains
names only. The Docker image bakes in no credentials.

## Running the tests

```bash
pip install -r requirements-dev.txt
python3 -m pytest                       # offline suite, no provider needed
python3 -m pytest -m live               # provider-backed paraphrase tests
```

The offline suite is the default and needs no API key: a stub interpreter feeds
the official reference interpretations through the real guardrails, optimizer and
validator, so the entire deterministic pipeline is exercised. Tests marked `live`
call the configured model for real and are skipped when no key is present.

Coverage: all ten official sample cases end to end, guardrail normalisation and
repair, optimizer optimality, battery and directive constraints, validator
rejection of a crafted invalid plan per rule, HTTP contract, error handling,
rate-limit and provider failure behaviour, the fallback interpreter, and 27
paraphrase cases across every supported directive.

## Docker

```bash
docker build -t gridwise-llm-energy-optimizer:1.0.0 .

docker run --rm -p 8000:8000 \
  -e LLM_PROVIDER=groq \
  -e LLM_API_KEY=gsk_your_key_here \
  gridwise-llm-energy-optimizer:1.0.0

curl -sS http://127.0.0.1:8000/health
```

The image runs as an unprivileged user, binds `0.0.0.0`, reads `PORT` from the
environment, and carries a container healthcheck against `/health`. It contains
no credentials.

## Deployment

Any host that can run a Dockerfile works unchanged — the container needs only
`LLM_API_KEY` and exposes one port.

```bash
# Hugging Face Docker Space (requires a PRO subscription for Docker Spaces)
HF_TOKEN=hf_write_token \
HF_SPACE=your-user/gridwise-llm-energy-optimizer \
LLM_API_KEY=gsk_your_key_here \
bash deploy/huggingface/push_to_hf_space.sh
```

Full instructions for Docker, Hugging Face and generic container hosts are in
[`deploy/README.md`](deploy/README.md).

### Verified deployment

Both endpoints were exercised from outside the development environment against
the live public URL:

```
GET  https://petition-personality-swing-civil.trycloudflare.com/health
     -> 200 {"status":"ok"}                                (0.44 s)

POST https://petition-personality-swing-civil.trycloudflare.com/optimize-energy
     -> 200, scenario SAMPLE-05, max_grid_window [18,19,20] cap 155
        2430.0 kWh, 33950.0 BDT, peak 175.0 kWh              (0.50 s)
```

and the full official sample pack was run against it:

```
PASS SAMPLE-01 .. PASS SAMPLE-10        10/10 cases passed
```

Every one of those responses was produced by the language model rather than the
fallback interpreter — the service logs `source=llm` for all ten scenarios:

```
gridwise scenario SAMPLE-10 solved: 3 directive(s), 2715.00 kWh, 41620.00 BDT, source=llm
```

Uncached end-to-end calls, measured from outside against the same URL with six
fresh operator-note phrasings (one per scenario, cache defeats confirmed):

```
0.78 s  0.50 s  0.45 s  0.40 s  0.81 s  0.63 s      p50 0.56 s, max 0.81 s
```

against the 30 s request timeout and the 5 s p95 target.

## Project layout

```
app/
  main.py             FastAPI app, both endpoints, error handling
  config.py           Environment-driven settings and provider defaults
  models.py           Request and response schemas
  llm_interpreter.py  Provider client, prompt, retries, cache, fallback
  guardrails.py       Deterministic validation and normalisation
  directives.py       Directive types and constraint arrays
  optimizer.py        Linear program, finalisation, plan summary
  validator.py        Independent replay and total recalculation
  pipeline.py         End-to-end orchestration
tests/                Offline and live pytest suites
scripts/              Public sample runner
docs/official/        The three authoritative competition documents
deploy/               Docker, Hugging Face and container-host instructions
Dockerfile            Container image
```

## Performance

| Path | Time |
| --- | --- |
| `GET /health` | < 5 ms |
| Language model interpretation | 0.3 – 0.9 s typical |
| Cached interpretation | microseconds |
| Linear program solve and finalisation | < 10 ms |
| Validation and serialisation | < 5 ms |
| **End-to-end, uncached** | **≈ 0.4 – 1.0 s** |

Well inside the 30 s per-request timeout, and comfortably under the 5 s p95
target. On a **free** provider tier, token-per-minute quotas are the limiting
factor under bursts; the service paces itself using the provider's rate-limit
headers, retries within a bounded budget, and falls back deterministically rather
than failing. A paid provider tier or a model with a higher quota removes the
limit.

## Reliability and failure handling

| Situation | Behaviour |
| --- | --- |
| Malformed or empty body | `400` with a controlled JSON error |
| Schema violation | `422` with a controlled JSON error |
| Body over 256 KB | `413` |
| Model returns non-JSON or nonsense | Guardrails downgrade to `no_op`; a valid plan is still returned |
| Model returns an unsupported directive type | Downgraded to `no_op`, never invented |
| Provider timeout, 5xx or rate limit | Bounded retry, then the deterministic fallback interpreter |
| Provider rejects strict JSON mode | Automatic retry without it |
| Directives mutually infeasible | Degrades to the largest feasible directive subset and still returns a valid plan |
| Scenario has no feasible schedule | `422` `infeasible_scenario` |
| Produced plan fails validation | `500` `invalid_schedule` — never a silently invalid success |
| Unexpected internal error | Generic `500`, no stack trace, no configuration values |

The service never returns 5xx for a merely invalid request, never crashes on bad
model output, and never leaks credentials, prompts or stack traces.

## Limitations

- **Provider dependency.** Interpretation needs a reachable language model. If
  the provider is unavailable the deterministic fallback interpreter takes over;
  it is accurate on the directive phrasings tested here but is deliberately
  conservative and cannot generalise as well as the model.
- **Rate limits.** On a free provider tier, bursts of requests beyond the
  token-per-minute quota are paced or fall back. A paid tier or higher-quota
  model is recommended for evaluation.
- **Ephemeral public URL.** The verified URL is a Cloudflare quick tunnel, which
  has no uptime guarantee. Use the deployment bundle for a permanent URL.
- **Docker build not exercised in the authoring environment.** The image was
  written and reviewed but no Docker daemon was available where it was built, so
  `docker build` itself was not run. The container's runtime path was instead
  reproduced exactly — a clean virtual environment holding only the runtime
  requirements, the same `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
  command, and both endpoints exercised against it (`/health` 200, SAMPLE-09
  `34873.00 BDT`). Run `docker build` once on a machine with Docker to close this
  gap.
- **Whole-hour resolution.** Windows are whole hours; sub-hour windows are out of
  scope for this challenge.
- **No grid export.** As specified, surplus solar is curtailed rather than sold.
- **Single-process cache.** The interpretation cache is in-process, so a
  multi-worker deployment would keep separate caches (correctness is unaffected).
- **Battery parameters are fixed.** The model cannot change demand, solar,
  tariff or battery limits, by design.

## Dependencies and credits

Built for the BUP CSE Fest 2026 Hackathon preliminary round. Core architecture,
directive interpretation, guardrails, optimizer formulation, validation and
tests are the team's own work.

| Dependency | Role | Licence |
| --- | --- | --- |
| [FastAPI](https://fastapi.tiangolo.com/) | HTTP framework | MIT |
| [Starlette](https://www.starlette.io/) / [uvicorn](https://www.uvicorn.org/) | ASGI toolkit and server | BSD-3-Clause |
| [Pydantic](https://docs.pydantic.dev/) | Request and response schemas | MIT |
| [httpx](https://www.python-httpx.org/) | Provider HTTP client | BSD-3-Clause |
| [NumPy](https://numpy.org/) | Vectorised numerics | BSD-3-Clause |
| [SciPy](https://scipy.org/) — HiGHS | Linear programming solver | BSD-3-Clause |
| [pytest](https://pytest.org/) | Test runner (development only) | MIT |
| [Groq](https://groq.com/) — `openai/gpt-oss-20b` | Operator-note interpretation | hosted service |

`gpt-oss-20b` is an open-weight model released by OpenAI under Apache-2.0 and
served here by Groq. It is used strictly as the language interpreter for
`operator_notes`; it performs no scheduling and no arithmetic on the scenario.

The three authoritative competition documents are kept unmodified in
[`docs/official/`](docs/official) for reference.

This project uses only the synthetic challenge data supplied by the harness. No
live campus, utility, billing or personal data is used, and no credentials are
committed to the repository.
