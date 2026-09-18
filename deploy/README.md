# Deployment

The service is a single stateless container that listens on `$PORT` (default
`8000`) and exposes `GET /health` and `POST /optimize-energy`. Only one
environment variable is required: a language-model API key.

## 1. Docker (primary fallback path)

```bash
docker build -t gridwise-llm-energy-optimizer:1.0.0 .

docker run --rm -p 8000:8000 \
  -e LLM_PROVIDER=groq \
  -e LLM_API_KEY=gsk_your_key_here \
  gridwise-llm-energy-optimizer:1.0.0

curl http://127.0.0.1:8000/health
```

Publish it to a registry so organizers can pull an exact tag:

```bash
docker tag gridwise-llm-energy-optimizer:1.0.0 <registry-user>/gridwise-llm-energy-optimizer:1.0.0
docker push <registry-user>/gridwise-llm-energy-optimizer:1.0.0
```

## 2. Hugging Face Docker Space

```bash
HF_TOKEN=hf_write_token \
HF_SPACE=your-user/gridwise-llm-energy-optimizer \
LLM_API_KEY=gsk_your_key_here \
bash deploy/huggingface/push_to_hf_space.sh
```

The script creates the Space, copies the application, stores the key as a Space
secret, sets `LLM_PROVIDER` and `LLM_MODEL` as Space variables, and pushes.
Hugging Face builds the image and serves it at
`https://<owner>-<space-name>.hf.space`.

> Hugging Face requires a PRO subscription to host Docker and Gradio Spaces on
> free `cpu-basic` hardware. Creating the Space returns HTTP 402 without it.
> Static Spaces are free but cannot run a Python service.

## 3. Generic container host (Render, Railway, Koyeb, Fly.io, Cloud Run)

Any host that can run a Dockerfile works unchanged:

| Setting | Value |
| --- | --- |
| Build | Dockerfile in the repository root |
| Port | whatever the platform injects as `PORT` |
| Health check path | `/health` |
| Required env vars | `LLM_API_KEY` (plus optional `LLM_PROVIDER`, `LLM_MODEL`) |

The container binds `0.0.0.0` and reads `PORT` from the environment, so no
platform-specific configuration is needed.

## Environment variables

| Name | Required | Default | Purpose |
| --- | --- | --- | --- |
| `LLM_API_KEY` | yes | - | Provider key used for operator-note interpretation |
| `LLM_PROVIDER` | no | `groq` | `groq`, `openai`, `gemini` or `openai_compatible` |
| `LLM_MODEL` | no | provider default | Model identifier |
| `LLM_BASE_URL` | no | provider default | Override for a self-hosted or proxy endpoint |
| `LLM_TIMEOUT_SECONDS` | no | `12` | Per-attempt timeout |
| `LLM_MAX_ATTEMPTS` | no | `3` | Attempts before the fallback interpreter is used |
| `LLM_MAX_TOKENS` | no | `600` | Completion budget per interpretation |
| `LLM_REASONING_EFFORT` | no | `low` on Groq | Reasoning budget for reasoning-capable models |
| `LLM_CACHE_SIZE` | no | `512` | Number of cached interpretations |
| `LLM_CACHE_TTL_SECONDS` | no | `900` | Cache entry lifetime |
| `PORT` | no | `8000` | Listen port (`7860` on Hugging Face Spaces) |
| `HOST` | no | `0.0.0.0` | Listen address |
| `LOG_LEVEL` | no | `info` | Log verbosity |

Provider-specific key names are also accepted: `GROQ_API_KEY`,
`OPENAI_API_KEY`, `GEMINI_API_KEY`.

## Verified deployment

Both endpoints are exercised from outside the development environment with

```bash
curl -sS "<PUBLIC_URL>/health"
python scripts/run_public_samples.py --url "<PUBLIC_URL>" --check-health
```
