#!/usr/bin/env bash
# Serve one open model with the current vLLM -> OpenAI-compatible API on :8000.
# Default: Qwen3.8-27B (Apache 2.0, 2026), used for BOTH roles - Sahayak with thinking off,
# the attacker with thinking on (llm.py sends enable_thinking per role).
#   tmux new -s llm
#   bash scripts/serve_model.sh                      # Qwen3.8-27B
#   MODEL=google/gemma-4-31B-it bash scripts/serve_model.sh   # another family for the model sweep
# Settings: --max-model-len 16384 (prompts are short; leaves KV-cache room for many parallel
# conversations), --gpu-memory-utilization 0.88 (room for bge-m3 embeddings on the same GPU).
set -euo pipefail
source ~/vllm-latest/bin/activate
MODEL="${MODEL:-Qwen/Qwen3.8-27B}"
NAME="${NAME:-target}"
TP="${TP:-1}"
export HF_HUB_ENABLE_HF_TRANSFER=1
exec vllm serve "$MODEL" \
  --served-model-name "$NAME" \
  --tensor-parallel-size "$TP" \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.88 \
  --max-num-seqs 128 \
  --host 0.0.0.0 --port 8000
