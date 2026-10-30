#!/usr/bin/env bash
# NVIDIA garak scan of the Sahayak agent (OpenAI-compatible endpoint), Checks Off vs On.
# Uses the vLLM model already running for the demo (:8000); small prompt cap = a few minutes.
#   bash scripts/run_garak.sh                 # off + on
#   MODES=off PROBES=promptinject CAP=20 bash scripts/run_garak.sh
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
MODES=${MODES:-"off on"}
PROBES=${PROBES:-"promptinject,encoding.InjectBase64"}
CAP=${CAP:-30}
OUT="$ROOT/results/nvidia/garak"; mkdir -p "$OUT"

if [ ! -x "$HOME/garak-venv/bin/garak" ]; then
  python3 -m venv "$HOME/garak-venv"
  "$HOME/garak-venv/bin/pip" -q install -U garak
fi
"$HOME/garak-venv/bin/python" -c "import garak; print('garak', garak.__version__)" | tee "$OUT/version.txt"

port=8301
for mode in $MODES; do
  echo "== Sahayak checks=$mode on :$port =="
  ( source "$HOME/venv/bin/activate" 2>/dev/null || true
    SAHAYAK_CHECKS=$mode SAHAYAK_BACKEND=ours EMBED_DEVICE=cpu \
      nohup uvicorn serve_sahayak:app --host 127.0.0.1 --port $port > "$OUT/server-$mode.log" 2>&1 & echo $! > "$OUT/server-$mode.pid" )
  for i in $(seq 1 60); do curl -sf -X POST localhost:$port/reset >/dev/null && break; sleep 2; done

  cat > "$OUT/garak-$mode.yaml" <<YAML
run:
  generations: 1
  soft_probe_prompt_cap: $CAP
system:
  parallel_attempts: 8
  lite: true
plugins:
  target_type: openai.OpenAICompatible
  target_name: sahayak
  generators:
    openai:
      OpenAICompatible:
        uri: http://127.0.0.1:$port/v1
        model: sahayak
        api_key: not-needed
        suppressed_params: [n, frequency_penalty, presence_penalty, stop]
reporting:
  report_prefix: sahayak-$mode
YAML
  OPENAICOMPATIBLE_API_KEY=not-needed "$HOME/garak-venv/bin/garak" \
     --config "$OUT/garak-$mode.yaml" --probes "$PROBES" 2>&1 | tee "$OUT/garak-$mode.log" || true
  kill "$(cat "$OUT/server-$mode.pid")" 2>/dev/null || true
  # copy garak's own report files (jsonl + html) next to ours
  find "$HOME/.local/share/garak" "$HOME/.local/share/garak/garak_runs" -maxdepth 2 -name "sahayak-$mode*" \
       -newer "$OUT/garak-$mode.yaml" -exec cp {} "$OUT/" \; 2>/dev/null || true
  port=$((port+1))
done
python3 scripts/summarise_garak.py "$OUT"
