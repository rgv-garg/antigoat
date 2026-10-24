#!/usr/bin/env bash
# One-time setup on the Brev GPU machine. Run inside `brev shell antigoat`:
#   git clone <your repo url> antigoat && cd antigoat && bash scripts/setup_brev.sh
set -euo pipefail

sudo apt-get update -y && sudo apt-get install -y tmux python3-venv
python3 -m venv ~/venv
source ~/venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install sentence-transformers 'huggingface_hub[cli]'   # bge-m3 embeddings
pip install -r requirements-mem0.txt  # real Mem0 library for --backend mem0

# vLLM in its own venv, pinned to 0.12.0: the A100 driver (CUDA 12.7) cannot run the newest vLLM (CUDA 13)
[ -d ~/vllm-env ] || { python3 -m venv ~/vllm-env && ~/vllm-env/bin/pip install "vllm==0.12.0"; }

grep -q "source ~/venv/bin/activate" ~/.bashrc || echo "source ~/venv/bin/activate" >> ~/.bashrc
[ -f .env ] || bash scripts/use_env.sh mock

echo
echo "Done. Next:"
echo "  1) tmux new -s llm      then   bash scripts/serve_vllm.sh      (Ctrl+B then D to detach)"
echo "  2) edit .env -> use the 'Brev' block (LLM_BASE_URL=http://localhost:8000/v1)"
echo "  3) python scripts/check_endpoint.py"
