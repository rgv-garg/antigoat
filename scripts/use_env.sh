#!/usr/bin/env bash
# Writes .env for you, so nobody has to hand-edit it.
#   bash scripts/use_env.sh hosted nvapi-XXXX   -> NVIDIA-hosted Nemotron (no GPU needed, rate-limited)
#   bash scripts/use_env.sh brev                -> the model served on this Brev GPU (scripts/serve_vllm.sh)
#   bash scripts/use_env.sh mock                -> offline fake model (tests only)
# Any SARVAM_API_KEY already in .env is kept.
set -euo pipefail
cd "$(dirname "$0")/.."
mode="${1:-}"; key="${2:-}"
sarvam=$(grep -s '^SARVAM_API_KEY=' .env | cut -d= -f2- || true)

case "$mode" in
  hosted)
    [ -n "$key" ] || { echo "usage: bash scripts/use_env.sh hosted nvapi-XXXX"; exit 1; }
    block="LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_API_KEY=$key
LLM_MODEL=nvidia/nemotron-3-nano-30b-a3b
EMBED_MODEL=hash
MAX_WORKERS=4" ;;
  brev)
    block="LLM_BASE_URL=http://localhost:8000/v1
LLM_API_KEY=not-needed
LLM_MODEL=nemotron-nano
EMBED_MODEL=BAAI/bge-m3
MAX_WORKERS=32" ;;
  mock)
    block="LLM_BASE_URL=mock
EMBED_MODEL=hash
MAX_WORKERS=16" ;;
  *) echo "usage: bash scripts/use_env.sh hosted nvapi-XXXX | brev | mock"; exit 1 ;;
esac

cat > .env <<ENV
# written by scripts/use_env.sh $mode  (never commit this file)
$block
SAHAYAK_EXTRACT=llm
SAHAYAK_VERIFY=llm
SAHAYAK_TEMPERATURE=0
SAHAYAK_MAX_TOKENS=512
SAHAYAK_THINKING=false
ATTACKER_TEMPERATURE=0.7
ATTACKER_MAX_TOKENS=1024
ATTACKER_THINKING=true
REQUEST_TIMEOUT=120
SARVAM_API_KEY=$sarvam
SARVAM_STT_MODEL=saaras:v4
SARVAM_TTS_MODEL=bulbul:v4-flash
SARVAM_SPEAKER=simran_en_customer
ENV
echo ".env now uses: $mode"
