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

# Sized for a 27B model (Qwen3.8-27B) on one H100 so it finishes overnight (~5-7 h).
# On a faster setup raise SLOTS / SESSIONS:  SLOTS=200 SESSIONS=0,1,5,10 bash scripts/overnight.sh
SLOTS="${SLOTS:-120}"
SESSIONS="${SESSIONS:-0,1,5}"

# 1) The headline twin-world sweep: all five rules (incl. the new entangled-deletion rule),
#    OFF vs v2 (before Verified Erasure) vs ON vs Strict, goal attacker + fixed-list baseline.
run main   run_experiment.py --slots "$SLOTS" --sessions "$SESSIONS" --bg-sample 0.5 \
           --checks off,v2,on,paranoid --attackers goal,fixed --tag full

# 2) False-alarm calibration: a CLEAN system (no planted bugs) should be flagged ~1% of the time.
run calib  run_experiment.py --no-bugs --checks off --slots "$SLOTS" --sessions 0,1 --bg-sample 0.5 \
           --attackers goal --tag calib

# 3) Real library: Mem0 2.2.1 as shipped (its own extraction), nothing planted.
#    Deletion (resurrection curve) + entangled deletion, OFF vs v2 vs ON.
run mem0   run_experiment.py --backend mem0 --rules deletion,entangled --slots 60 --sessions "$SESSIONS" \
           --checks off,v2,on --attackers goal --tag mem0

# 3b) White-box deletion-at-rest probe inside Mem0's own storage (quotable numbers).
run mem0probe run_mem0_probe.py --n 30 --tag full

# 4) Which check stops which leak (deterministic, instant).
run abl    run_ablation.py --tag full

# 5) Blast radius R0 + fake-consensus table (deterministic).
run extras run_extras.py --citizens 25 --tag full

# 6) Autonomous detect -> patch -> re-verify loop (future-scaling demo, deterministic).
run advisor run_advisor.py --tag full

# 7) Publish: copy the newest run of each kind to results/final-*.jsonl so they can be
#    committed and shown on the hosted /report page.
for tag in full calib mem0; do
  f=$(ls -t results/*-"$tag"-*.jsonl 2>/dev/null | head -1)
  if [ -n "$f" ]; then
    cp "$f" "results/final-$tag.jsonl"
    cp "${f%.jsonl}.meta.json" "results/final-$tag.meta.json" 2>/dev/null || true
    echo "published $f -> results/final-$tag.jsonl"
  fi
done
for f in results/ablation-full.json results/mem0-probe-full.json results/extras-full.json results/advisor-full.json; do
  [ -f "$f" ] && cp "$f" "results/final-$(basename "$f")"
done

echo; echo "================ overnight done $(date) ================"
echo "Scorecards are in results/*.jsonl ; open the dashboard to view."
echo "When satisfied:  brev stop antigoat   (stops compute charges)"
