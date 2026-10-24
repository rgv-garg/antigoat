#!/usr/bin/env bash
# Overnight AntiGOAT runs. Start inside tmux so it survives the laptop closing:
#   tmux new -s run
#   bash scripts/overnight.sh
#   (Ctrl+B then D to detach; `tmux attach -t run` to look again)
#
# Needs: vLLM already serving on :8000 and .env pointing at the Brev block
# (bash scripts/use_env.sh brev). Runs each job in turn and logs to results/overnight.log.
# It does NOT stop the GPU at the end - check the results first, then `brev stop antigoat`.
set -uo pipefail
cd "$(dirname "$0")/.."
[ -d ~/venv ] && source ~/venv/bin/activate || true
mkdir -p results
LOG=results/overnight.log
exec > >(tee -a "$LOG") 2>&1

echo "================ overnight start $(date) ================"

run () {  # run <name> <args...>
  local name="$1"; shift
  echo; echo ">>> [$name] $(date '+%H:%M:%S')  python $*"
  if python "$@"; then echo "<<< [$name] OK"; else echo "<<< [$name] FAILED (continuing)"; fi
}

# 1) The headline twin-world sweep: 200 citizens/rule, all checkpoints, OFF vs ON vs paranoid,
#    goal attacker + fixed-list baseline.
run main   run_experiment.py --slots 200 --sessions 0,1,5,10 \
           --checks off,on,paranoid --attackers goal,fixed --tag full

# 2) False-alarm calibration: a CLEAN system (no planted bugs) should be flagged ~1% of the time.
run calib  run_experiment.py --no-bugs --checks off --slots 200 --sessions 0,1 \
           --attackers goal --tag calib

# 3) Real library: Mem0 OSS as shipped (its own extraction). Deletion-at-rest finding.
run mem0   run_experiment.py --backend mem0 --slots 60 --sessions 0,1,5 \
           --checks off,on --attackers goal --tag mem0

# 4) Which check stops which leak (deterministic, instant).
run abl    run_ablation.py --tag full

# 5) Blast radius R0 + fake-consensus table (deterministic).
run extras run_extras.py --citizens 25 --tag full

echo; echo "================ overnight done $(date) ================"
echo "Scorecards are in results/*.jsonl ; open the dashboard to view."
echo "When satisfied:  brev stop antigoat   (stops compute charges)"
