#!/usr/bin/env bash
# OPTIONAL alternative to vLLM: run the model as an NVIDIA NIM container (sponsor points!).
# Use EITHER this OR serve_vllm.sh on port 8000, not both.
#
# 1. On build.nvidia.com open the Nemotron 3 Nano page -> "Deploy" / "Docker" tab and copy
#    the image name (looks like nvcr.io/nim/...:latest).
# 2. export NGC_API_KEY=nvapi-...      (the lead's key)
# 3. NIM_IMAGE=<that image> bash scripts/serve_nim.sh
set -euo pipefail
: "${NGC_API_KEY:?export NGC_API_KEY=nvapi-... first}"
: "${NIM_IMAGE:?set NIM_IMAGE to the image name from the model's Deploy tab on build.nvidia.com}"

echo "$NGC_API_KEY" | docker login nvcr.io -u '$oauthtoken' --password-stdin
mkdir -p ~/.cache/nim
docker run -d --name nim-llm --gpus all --shm-size=16g \
  -e NGC_API_KEY \
  -v ~/.cache/nim:/opt/nim/.cache \
  -p 8000:8000 \
  "$NIM_IMAGE"

echo "Started. First start downloads the model (can take 20-40 min). Watch with:"
echo "  docker logs -f nim-llm"
echo "Ready when this works:  curl localhost:8000/v1/models"
echo "Then put the model id from /v1/models into .env as LLM_MODEL."
