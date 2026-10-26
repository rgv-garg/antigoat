#!/usr/bin/env bash
# One vLLM server per GPU (ports 8000, 8001, ...) for the big parallel run (scripts/bigrun.sh).
# Each GPU gets its own copy of the model, so 8 GPUs answer ~8x more requests at once, and each
# server leaves ~14 GB of its GPU free for the experiments' search model (bge-m3): no more
# out-of-memory crashes from everything sharing one card.
#   tmux new -s llm
#   bash scripts/serve_many.sh            # every GPU on this machine, Qwen3-32B-FP8
#   bash scripts/serve_many.sh stop       # stop all of them
# Logs: results/vllm-<gpu>.log . The list of server URLs is written to results/llm_urls.txt.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p results
if [ "${1:-}" = "stop" ]; then pkill -f "vllm serve" || true; rm -f results/llm_urls.txt; echo "stopped"; exit 0; fi

MODEL="${MODEL:-Qwen/Qwen3-32B-FP8}"
NAME="${NAME:-target}"
GPU_UTIL="${GPU_UTIL:-0.82}"   # 0.82 of 80 GB = 66 GB for vLLM (33 GB weights + ~30 GB KV cache)
N=$(nvidia-smi -L | wc -l)
source ~/vllm-latest/bin/activate

echo "$N GPU(s). Downloading $MODEL once (skipped if already there)..."
python -c "from huggingface_hub import snapshot_download; snapshot_download('$MODEL')"

start () {  # start <gpu>
  local g=$1
  CUDA_VISIBLE_DEVICES=$g nohup vllm serve "$MODEL" --served-model-name "$NAME" \
    --max-model-len 16384 --gpu-memory-utilization "$GPU_UTIL" --max-num-seqs 128 \
    --host 0.0.0.0 --port $((8000 + g)) > "results/vllm-$g.log" 2>&1 &
}
wait_for () {  # wait_for <gpu> ...
  for g in "$@"; do
    until curl -sf "http://localhost:$((8000 + g))/v1/models" > /dev/null; do
      if ! pgrep -f -- "--port $((8000 + g))" > /dev/null; then
        echo "GPU $g server stopped. Last lines of results/vllm-$g.log:"; tail -20 "results/vllm-$g.log"; exit 1
      fi
      sleep 10
    done
    echo "  GPU $g ready  (port $((8000 + g)))"
  done
}

echo "Starting GPU 0 first (it compiles the model once; the others reuse that, ~3-6 min)..."
start 0; wait_for 0
if [ "$N" -gt 1 ]; then
  echo "Starting GPUs 1-$((N - 1))..."
  for g in $(seq 1 $((N - 1))); do start "$g"; done
  wait_for $(seq 1 $((N - 1)))
fi

URLS=""
for g in $(seq 0 $((N - 1))); do URLS="${URLS:+$URLS,}http://localhost:$((8000 + g))/v1"; done
echo "$URLS" > results/llm_urls.txt
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv
echo
echo "All $N model servers are up. Next (in another tmux window):  bash scripts/bigrun.sh"
