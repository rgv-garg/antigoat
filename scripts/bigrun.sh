#!/usr/bin/env bash
# The big parallel run for a multi-GPU machine. Every Memory Checks mode runs as its own job, all
# at the same time, spread over the model servers from scripts/serve_many.sh. Each job keeps its
# search model (bge-m3) on its own GPU.
#   tmux new -s run
#   bash scripts/bigrun.sh               (Ctrl+B then D to leave it running)
#   bash scripts/bigrun.sh status        what each job has finished so far
#   bash scripts/bigrun.sh publish       merge whatever is finished into results/final-*.jsonl now
#
# Sizes: 200 citizens per rule and checkpoints 0,1,5,10 sessions (same as the Nemotron run);
# Mem0 80 citizens per rule. Override like:  SLOTS=150 SESSIONS=0,1,5 bash scripts/bigrun.sh
# Split over several machines: JOBS picks which jobs run here, e.g.
#   JOBS=full-off,full-v2 bash scripts/bigrun.sh      (names: full-off full-v2 full-on full-paranoid
#   calib mem0-off mem0-v2 mem0-on extras)  - copy every machine's results/ together afterwards.
set -uo pipefail
cd "$(dirname "$0")/.."
[ -d ~/venv ] && source ~/venv/bin/activate

FULL="big-full-off,big-full-v2,big-full-on,big-full-paranoid"
MEM0="big-mem0-off,big-mem0-v2,big-mem0-on"
publish () {
  python scripts/merge_runs.py final-full $FULL
  python scripts/merge_runs.py final-calib big-calib
  python scripts/merge_runs.py final-mem0 $MEM0
}
case "${1:-}" in
  status)  python scripts/merge_runs.py --status "$FULL,big-calib,$MEM0"; exit 0 ;;
  publish) publish; exit 0 ;;
esac

[ -f results/llm_urls.txt ] || { echo "Start the model servers first:  bash scripts/serve_many.sh"; exit 1; }
grep -q "^LLM_MODEL=target" .env 2>/dev/null || bash scripts/use_env.sh open
export LLM_BASE_URL="$(cat results/llm_urls.txt)"   # overrides .env: all servers, least busy first
export MAX_WORKERS="${MAX_WORKERS:-128}"
SLOTS="${SLOTS:-200}"; SESSIONS="${SESSIONS:-0,1,5,10}"; MEM0_SLOTS="${MEM0_SLOTS:-80}"
N=$(nvidia-smi -L | wc -l)
LOG=results/bigrun.log
exec > >(tee -a "$LOG") 2>&1
echo "================ bigrun start $(date)  gpus=$N slots=$SLOTS sessions=$SESSIONS workers/job=$MAX_WORKERS"

# download the search model once, before 8 jobs try to at the same time
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3', device='cpu')" \
  || { echo "could not load BAAI/bge-m3"; exit 1; }

JOBS="${JOBS:-all}"
want () { [ "$JOBS" = all ] || [[ ",$JOBS," == *",$1,"* ]]; }
echo "jobs on this machine: $JOBS"
i=0
PIDS=()
job () {  # job <name> <run_experiment args...>  -> background, log in results/big-<name>.log
  local name=$1; shift
  want "$name" || return 0
  EMBED_DEVICE="cuda:$((i % N))" nohup python run_experiment.py "$@" --tag "big-$name" \
    > "results/big-$name.log" 2>&1 &
  PIDS+=("$!:$name")
  echo "started $name  (search model on GPU $((i % N)), log results/big-$name.log)"
  i=$((i + 1))
}

# 1) headline sweep: one job per mode, all five rules, adaptive attacker + fixed probe list
for m in off v2 on paranoid; do
  job "full-$m" --slots "$SLOTS" --sessions "$SESSIONS" --bg-sample 0.5 --checks "$m" --attackers goal,fixed
done
# 2) false-alarm check: no planted bugs, should hold every rule
job calib --no-bugs --checks off --slots "$SLOTS" --sessions 0,1 --bg-sample 0.5 --attackers goal
# 3) the real Mem0 library as shipped: deletion over time + entangled deletion
for m in off v2 on; do
  job "mem0-$m" --backend mem0 --rules deletion,entangled --slots "$MEM0_SLOTS" --sessions "$SESSIONS" \
    --checks "$m" --attackers goal
done

echo "All jobs started $(date '+%H:%M'). Check progress any time:  bash scripts/bigrun.sh status"
fails=0
for pn in "${PIDS[@]}"; do
  pid=${pn%%:*}; name=${pn#*:}
  if wait "$pid"; then echo "<<< [$name] OK $(date '+%H:%M')"; else echo "<<< [$name] FAILED $(date '+%H:%M') - see results/big-$name.log"; fails=$((fails + 1)); fi
done

# 4) the quick deterministic ones (Mem0 storage probe, ablation, blast radius, advisor)
export EMBED_DEVICE=cuda:0
want extras && for step in "run_mem0_probe.py --n 30 --tag full" "run_ablation.py --tag full" \
            "run_extras.py --citizens 25 --tag full" "run_advisor.py --tag full"; do
  echo ">>> $step"; python $step || echo "<<< FAILED: $step"
done
want extras && for f in results/ablation-full.json results/mem0-probe-full.json results/extras-full.json results/advisor-full.json; do
  [ -f "$f" ] && cp "$f" "results/final-$(basename "$f")"
done

publish
echo "================ bigrun done $(date)  ($fails job(s) failed)"
echo "Results: results/final-*.  This machine is still running (and billing): brev stop it when done."
