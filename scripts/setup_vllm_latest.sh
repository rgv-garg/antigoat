#!/usr/bin/env bash
# Install a CURRENT vLLM (for 2026 models like Qwen3.8-27B) in its own venv: ~/vllm-latest.
# Needs a recent NVIDIA driver (>= 580). The old A100 box (driver 565) cannot run it - use a new
# instance (H100/H200 80GB+) for this. Safe to re-run.
#   bash scripts/setup_vllm_latest.sh
set -euo pipefail
DRV=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)
GPU=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -1)
echo "GPU: $GPU   driver: $DRV"
if [ "${DRV%%.*}" -lt 580 ]; then
  echo "Driver $DRV is too old for the current vLLM (needs >= 580). Create a newer instance instead."
  exit 1
fi
sudo apt-get update -y && sudo apt-get install -y tmux python3-venv python3-dev build-essential git  # dev headers: vLLM compiles kernels at start
[ -d ~/vllm-latest ] || python3 -m venv ~/vllm-latest
~/vllm-latest/bin/pip install -U pip
~/vllm-latest/bin/pip install -U vllm "huggingface_hub[hf_transfer]"
~/vllm-latest/bin/python -c "import vllm, torch; print('vllm', vllm.__version__, '| torch', torch.__version__, '| cuda ok:', torch.cuda.is_available())"
echo "Done. Next: tmux new -s llm   then   bash scripts/serve_model.sh"
