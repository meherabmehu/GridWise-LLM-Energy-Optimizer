# GridWise LLM Energy Optimizer - container image
#
# Build:  docker build -t gridwise-llm-energy-optimizer:1.0.0 .
# Run:    docker run --rm -p 8000:8000 -e LLM_PROVIDER=groq -e LLM_API_KEY=... \
#           gridwise-llm-energy-optimizer:1.0.0
#
# No credentials are baked into the image; the language-model key is supplied at
# run time. PORT is read from the environment so the same image runs locally, on
# a hosting platform, or on a Hugging Face Docker Space (which uses 7860).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY docs ./docs

RUN useradd --create-home --uid 10001 gridwise \
 && chown -R gridwise:gridwise /app
USER gridwise

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
