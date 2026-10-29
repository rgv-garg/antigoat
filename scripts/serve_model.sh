#!/usr/bin/env bash
# Serve one open model with the current vLLM -> OpenAI-compatible API on :8000.
# Default: Qwen3.8-27B (Apache 2.0, 2026), used for BOTH roles - Sahayak with thinking off,
# the attacker with thinking on (llm.py sends enable_thinking per role).
#   tmux new -s llm
#   bash scripts/serve_model.sh                      # Qwen3.8-27B
#   MODEL=google/gemma-4-31B-it bash scripts/serve_model.sh   # another family for the model sweep
#   MODEL=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 GPU_UTIL=0.88 EXTRA_ARGS="--trust-remote-code" \
#       bash scripts/serve_model.sh                          # NVIDIA's Nemotron (3rd model family)
# Settings: --max-model-len 16384 (prompts are short; leaves KV-cache room for many parallel
# conversations). GPU_UTIL=0.70 by default: the experiments run bge-m3 embeddings on the SAME
# GPU, and at 0.88 a 64-thread run hit CUDA out-of-memory. Qwen3-32B-FP8 weights are ~33 GB,
# so 0.70 (~55 GB) still leaves ~20 GB of KV cache.
set -euo pipefail
source ~/vllm-latest/bin/activate
MODEL="${MODEL:-Qwen/Qwen3-32B-FP8}"   # Qwen3.8-27B needs a newer vLLM model loader; 32B-FP8 works today
NAME="${NAME:-target}"
TP="${TP:-1}"
exec vllm serve "$MODEL" \
  --served-model-name "$NAME" \
  --tensor-parallel-size "$TP" \
  --max-model-len "${MAX_LEN:-16384}" \
  --gpu-memory-utilization "${GPU_UTIL:-0.70}" \
  --max-num-seqs 128 \
  --host 0.0.0.0 --port 8000 ${EXTRA_ARGS:-}
