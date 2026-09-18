#!/usr/bin/env bash
#
# Publish this project to a Hugging Face Docker Space.
#
# Requirements:
#   * an HF account with a PRO subscription - Hugging Face requires PRO to host
#     Gradio and Docker Spaces on free cpu-basic hardware
#   * an HF access token with the "write" role
#   * git and curl
#
# Usage:
#   HF_TOKEN=hf_xxx HF_SPACE=my-user/gridwise-llm-energy-optimizer \
#     LLM_API_KEY=gsk_xxx bash deploy/huggingface/push_to_hf_space.sh
#
# The Space is created if it does not exist, the language-model key is stored as
# a Space secret (never in the repository or the image), and the service is
# bound to port 7860 which is what Spaces route to.

set -euo pipefail

: "${HF_TOKEN:?set HF_TOKEN to a Hugging Face write token}"
: "${HF_SPACE:?set HF_SPACE to the target repo id, for example user/space-name}"

LLM_PROVIDER="${LLM_PROVIDER:-groq}"
LLM_MODEL="${LLM_MODEL:-openai/gpt-oss-20b}"
SPACE_NAME="${HF_SPACE##*/}"
OWNER="${HF_SPACE%%/*}"
APP_PORT=7860

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

echo "==> Creating Space ${HF_SPACE} (ignored if it already exists)"
curl -sS -X POST \
  -H "Authorization: Bearer ${HF_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${SPACE_NAME}\",\"type\":\"space\",\"private\":false,\"sdk\":\"docker\",\"hardware\":\"cpu-basic\"}" \
  "https://huggingface.co/api/repos/create" >/dev/null || true

echo "==> Cloning the Space repository"
git clone -q "https://user:${HF_TOKEN}@huggingface.co/spaces/${HF_SPACE}" "${WORK_DIR}/space"

echo "==> Copying the application"
mkdir -p "${WORK_DIR}/space/app" "${WORK_DIR}/space/scripts" "${WORK_DIR}/space/docs"
cp -r "${REPO_ROOT}/app/." "${WORK_DIR}/space/app/"
cp -r "${REPO_ROOT}/scripts/." "${WORK_DIR}/space/scripts/"
cp -r "${REPO_ROOT}/docs/." "${WORK_DIR}/space/docs/"
cp "${REPO_ROOT}/requirements.txt" "${WORK_DIR}/space/requirements.txt"
cp "${REPO_ROOT}/.gitignore" "${WORK_DIR}/space/.gitignore"

# Space card: the YAML front matter tells Hugging Face how to run the image.
cat > "${WORK_DIR}/space/README.md" <<EOF
---
title: GridWise LLM Energy Optimizer
emoji: ⚡
colorFrom: green
colorTo: blue
sdk: docker
app_port: ${APP_PORT}
pinned: false
---

# GridWise LLM Energy Optimizer

LLM-assisted operator directive interpretation and deterministic 24-hour energy
optimization for the BUP CSE Fest 2026 Hackathon preliminary round.

* \`GET  /health\` - readiness probe returning \`{"status": "ok"}\`
* \`POST /optimize-energy\` - operator-note interpretation and optimized schedule

Full documentation, architecture and local setup instructions live in the source
repository: https://github.com/meherabmehu/GridWise-LLM-Energy-Optimizer
EOF

# Spaces route to app_port, so the container must listen there.
python3 - "$REPO_ROOT/Dockerfile" "${WORK_DIR}/space/Dockerfile" "${APP_PORT}" <<'PY'
import sys
source, target, port = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(source, encoding="utf-8").read()
text = text.replace("PORT=8000", f"PORT={port}").replace("EXPOSE 8000", f"EXPOSE {port}")
open(target, "w", encoding="utf-8").write(text)
PY

echo "==> Storing the provider key as a Space secret"
if [[ -n "${LLM_API_KEY:-}" ]]; then
  curl -sS -X POST \
    -H "Authorization: Bearer ${HF_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"key\":\"LLM_API_KEY\",\"value\":\"${LLM_API_KEY}\",\"description\":\"Language model key used for operator-note interpretation\"}" \
    "https://huggingface.co/api/spaces/${HF_SPACE}/secrets" >/dev/null
else
  echo "    LLM_API_KEY not set - add it under Settings > Variables and secrets in the Space."
fi

for pair in "LLM_PROVIDER:${LLM_PROVIDER}" "LLM_MODEL:${LLM_MODEL}"; do
  key="${pair%%:*}"; value="${pair#*:}"
  curl -sS -X POST \
    -H "Authorization: Bearer ${HF_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"key\":\"${key}\",\"value\":\"${value}\"}" \
    "https://huggingface.co/api/spaces/${HF_SPACE}/variables" >/dev/null
done

echo "==> Pushing"
cd "${WORK_DIR}/space"
git add -A
git -c user.name="GridWise Deploy" -c user.email="deploy@example.com" \
  commit -q -m "Deploy GridWise LLM Energy Optimizer"
git push -q origin HEAD:main

echo
echo "Space:    https://huggingface.co/spaces/${HF_SPACE}"
echo "Endpoint: https://${OWNER}-${SPACE_NAME}.hf.space"
echo "The first build takes a few minutes, then: curl https://${OWNER}-${SPACE_NAME}.hf.space/health"
