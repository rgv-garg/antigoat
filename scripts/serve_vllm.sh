#!/usr/bin/env bash
# Serve Nemotron 3 Nano on the Brev A100 (80 GB) with vLLM -> OpenAI-compatible API on :8000.
# Run inside tmux so it keeps running:   tmux new -s llm   then   bash scripts/serve_vllm.sh
#
# Why a separate venv (~/vllm-env) with vLLM 0.12.0:
#   the Brev A100 driver is 565 (CUDA 12.7). Newest vLLM ships PyTorch for CUDA 13 and refuses
#   to start. vLLM 0.12.0 uses PyTorch 2.9 + CUDA 12.8 (works on this driver) and is the version
#   Nemotron 3 Nano launched with. setup_brev.sh creates ~/vllm-env.
#
# Settings and why
#   BF16 weights          A100 has no FP8 hardware, so full precision (~60 GB)
#   --max-model-len 8192  our prompts are short (<2k) and answers small; a small context
#                         leaves far more KV-cache room for parallel conversations
#   --gpu-memory-utilization 0.90   leaves headroom for bge-m3 embeddings
#   --max-num-seqs 192    up to ~192 conversations decoded at once (≈3x the old throughput)
#   --served-model-name   short name to put in .env (LLM_MODEL=nemotron-nano)
#   reasoning parser      puts the model's "thinking" in a separate field (the parser file ships
#                         with the model on Hugging Face); llm.py also strips <think> blocks itself
set -euo pipefail
source ~/vllm-env/bin/activate

MODEL=nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16
PARSER=nano_v3_reasoning_parser.py
if [ ! -f "$PARSER" ]; then
  python -c "from huggingface_hub import hf_hub_download as d; d('$MODEL', '$PARSER', local_dir='.')"
fi

vllm serve "$MODEL" \
  --served-model-name nemotron-nano \
  --trust-remote-code \
  --dtype bfloat16 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90 \
  --max-num-seqs 192 \
  --reasoning-parser-plugin "$PARSER" \
  --reasoning-parser nano_v3 \
  --host 0.0.0.0 --port 8000
