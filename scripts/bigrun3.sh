#!/usr/bin/env bash
# The generality grid: any agent, any memory, any model, plus a public benchmark.
#
# Run on any GPU box that already serves a model on :8000 (bash scripts/serve_model.sh) or
# several (bash scripts/serve_many.sh). Pick this machine's share with JOBS (substring match):
#
#   MODEL_TAG=qwen32 JOBS=injecagent,refagent,langgraph,mem0poison bash scripts/bigrun3.sh
#   MODEL_TAG=nemotron JOBS=injecagent,refagent,leak bash scripts/bigrun3.sh   # a 3rd model family
#   JOBS=all  (default) runs everything below.   DRYRUN=1: offline wiring check, tiny sizes.
#
# Units:
#   injecagent   Memory Checks on the PUBLIC InjecAgent benchmark (1,054 cases x base/enhanced,
#                4 arms + benign twins). Fetches the public data first.
#   refagent     AntiGOAT audits an agent that is NOT Sahayak (examples/memory_agent.py, LangGraph
#                store) over HTTP, as written and with its memory routed through Memory Checks.
#   langgraph    Sahayak on LangGraph's BaseStore (a 3rd real memory library, nothing planted):
#                leak rules + the poisoning suite, checks off vs on.
#   mem0poison   the poisoning suite on unmodified Mem0 with checks on, on the current code.
#   leak         the leak rules on our store, off vs on (for a new model family).
set -uo pipefail
cd "$(dirname "$0")/.."
[ -d ~/venv ] && source ~/venv/bin/activate

MODEL_TAG="${MODEL_TAG:-qwen32}"
JOBS="${JOBS:-all}"
SEED="${SEED:-1}"
POISON="poisoning,inject_chat,inject_consolidate,inject_authority,inject_overwrite,inject_sleeper,inject_crossuser"

if [ "${DRYRUN:-}" = 1 ]; then          # wiring check on any laptop: offline mock model, tiny sizes
  export LLM_BASE_URL=mock LLM_MODEL=mock EMBED_MODEL=hash
  SLOTS_L=12; SLOTS_P=10; SESS_L=0,1; SESS_P=0; LIMIT="--limit 20 --model mock"
else
  grep -q "^LLM_MODEL=target" .env 2>/dev/null || bash scripts/use_env.sh open
  set -a; source .env; set +a                                 # the reference agent reads these too
  if [ -f results/llm_urls.txt ]; then export LLM_BASE_URL="$(cat results/llm_urls.txt)"; fi
  curl -sf "${LLM_BASE_URL%%,*}/models" >/dev/null || { echo "No model server at ${LLM_BASE_URL%%,*} - start one first (bash scripts/serve_model.sh)"; exit 1; }
  SLOTS_L=100; SLOTS_P=80; SESS_L=0,1,5; SESS_P=0,1; LIMIT=""
fi
export MAX_WORKERS="${MAX_WORKERS:-64}" REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-300}"
export EMBED_DEVICE="${EMBED_DEVICE:-cuda:0}" PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
LOG=results/bigrun3-$MODEL_TAG.log; exec > >(tee -a "$LOG") 2>&1
echo "==== bigrun3 $(date) model=$MODEL_TAG jobs=$JOBS server=${LLM_BASE_URL%%,*} ===="

want () { [ "$JOBS" = all ] || { for p in ${JOBS//,/ }; do [[ "$1" == *"$p"* ]] && return 0; done; return 1; }; }
run () {  # run <unit-name> <run_experiment args...>
  local name="g3-$MODEL_TAG-$1"; shift
  echo ">>> [$name] $(date '+%H:%M:%S')"
  python run_experiment.py "$@" --tag "$name" > "results/$name.log" 2>&1 \
    && echo "<<< [$name] OK" || echo "<<< [$name] FAILED (see results/$name.log)"
}

if want injecagent; then
  bash scripts/fetch_injecagent.sh >/dev/null && echo ">>> [injecagent] $(date '+%H:%M:%S')"
  python scripts/eval_injecagent.py --tag "$MODEL_TAG" --workers "$MAX_WORKERS" $LIMIT > "results/g3-$MODEL_TAG-injecagent.log" 2>&1 \
    && echo "<<< [injecagent] OK -> results/external/injecagent-$MODEL_TAG.md" || echo "<<< [injecagent] FAILED"
fi

if want refagent; then
  for MEM in plain governed; do
    AGENT_MEMORY=$MEM uvicorn examples.memory_agent:app --host 127.0.0.1 --port 8400 --log-level warning \
      > "results/g3-$MODEL_TAG-refagent-$MEM.server.log" 2>&1 &
    SRV=$!
    for _ in $(seq 60); do curl -sf -XPOST localhost:8400/reset >/dev/null && break; sleep 1; done
    run "refagent-$MEM" --target targets/reference_agent.json --rules isolation,deletion,entangled \
        --slots "$SLOTS_L" --sessions "$SESS_L" --attackers goal --seed "$SEED"
    kill $SRV 2>/dev/null; wait $SRV 2>/dev/null
  done
fi

if want langgraph; then
  run "langgraph-leak" --backend langgraph --rules deletion,entangled --checks off,on \
      --slots "$SLOTS_P" --sessions "$SESS_L" --attackers goal --seed "$SEED"
  run "langgraph-poison" --backend langgraph --rules "$POISON" --checks off,on \
      --slots "$SLOTS_P" --sessions "$SESS_P" --seed "$SEED"
fi

if want mem0poison; then
  run "mem0-poison-on" --backend mem0 --rules "$POISON" --checks on --slots "$SLOTS_P" --sessions "$SESS_P" --seed "$SEED"
fi

if want leak; then
  run "ours-leak" --rules isolation,deletion,entangled,authority --checks off,on \
      --slots "$SLOTS_L" --sessions "$SESS_P" --attackers goal --seed "$SEED" --bg-sample 0.5
fi

echo "==== bigrun3 done $(date) ===="
echo "Summarise:  python scripts/summarise_g3.py"
