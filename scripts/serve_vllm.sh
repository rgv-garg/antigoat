#!/usr/bin/env bash
# Serve Nemotron 3 Nano on the Brev A100 (80 GB) with vLLM -> OpenAI-compatible API on :8000.
# Run inside tmux so it keeps running:   tmux new -s llm   then   bash scripts/serve_vllm.sh
#
# Settings and why
#   BF16 weights          A100 has no FP8 hardware, so full precision (~60 GB)
#   --max-model-len 32768 our prompts are short; a smaller context leaves more memory
#                         for parallel conversations (the model supports far more)
#   --gpu-memory-utilization 0.85   leaves ~12 GB for bge-m3 embeddings + headroom
#   --max-num-seqs 64     up to 64 conversations decoded at once (raise if GPU memory allows)
#   --served-model-name   short name to put in .env (LLM_MODEL=nemotron-nano)
#   reasoning parser      puts the model's "thinking" in a separate field, so replies are clean
#                         (if these two flags error on your vLLM version, delete them -
#                         llm.py also strips <think> blocks itself)
set -euo pipefail
source ~/venv/bin/activate

MODEL=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16
PARSER=nano_v3_reasoning_parser.py
if [ ! -f "$PARSER" ]; then
  huggingface-cli download "$MODEL" "$PARSER" --local-dir . || echo "parser download failed - remove the reasoning flags below"
fi

vllm serve "$MODEL" \
  --served-model-name nemotron-nano \
  --trust-remote-code \
  --dtype bfloat16 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.85 \
  --max-num-seqs 64 \
  --reasoning-parser-plugin "$PARSER" \
  --reasoning-parser nano_v3 \
  --host 0.0.0.0 --port 8000
