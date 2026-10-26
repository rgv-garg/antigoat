#!/usr/bin/env bash
# The "100-score" grid: the poisoning attack suite + the leak rules, on UNMODIFIED Mem0 and on
# our own app, across defence settings and >=3 seeds, with a self-hosted attacker. No API key.
#
# Run ONE copy per machine, each serving one victim model, each taking a share via JOBS=.
#   tmux new -s llm  ->  bash scripts/serve_many.sh            (wait for "All N model servers are up")
#   tmux new -s run  ->  MODEL_TAG=qwen32 JOBS=ours bash scripts/bigrun2.sh
# Then on the other machines, same but JOBS=mem0 / JOBS=poison / JOBS=calib, and MODEL_TAG set to
# whatever each machine serves (so a 2nd model's results are labelled separately).
#
# A "job unit" = (backend, rulegroup, mode, seed). JOBS picks units by substring, comma-separated:
#   JOBS=ours        -> every unit whose name contains "ours"
#   JOBS=mem0,poison -> mem0 units and poison units
#   JOBS=all         -> everything on this machine (fine for a single powerful box)
# Suggested 4-machine split (all serving Qwen32 unless you serve a 2nd model):
#   antigoat3: JOBS=ours-leak      antigoat4: JOBS=mem0
#   antigoat5: JOBS=ours-poison,calib   antigoat6: JOBS=mem0-poison   (mem0 poison is cheap)
set -uo pipefail
cd "$(dirname "$0")/.."
[ -d ~/venv ] && source ~/venv/bin/activate

MODEL_TAG="${MODEL_TAG:-qwen32}"           # label for the served victim model (per machine)
SEEDS="${SEEDS:-1,2,3}"                      # >=3 seeds: we report mean and spread, not the best seed
LEAK_SLOTS="${LEAK_SLOTS:-150}"; LEAK_SESS="${LEAK_SESS:-0,1,5}"
POIS_SLOTS="${POIS_SLOTS:-120}"; POIS_SESS="${POIS_SESS:-0,1,5}"
JOBS="${JOBS:-all}"
POISON="poisoning,inject_chat,inject_consolidate,inject_authority,inject_overwrite,inject_sleeper,inject_crossuser"

case "${1:-}" in
  status)  python scripts/merge_runs.py --status "$(ls results | sed -n 's/.*-\(g2-[a-z0-9_]*\)-.*/\1/p' | sort -u | paste -sd,)"; exit 0 ;;
  publish) python scripts/analyze.py "$MODEL_TAG"; exit 0 ;;
esac

[ -f results/llm_urls.txt ] || { echo "Start model servers first: bash scripts/serve_many.sh"; exit 1; }
grep -q "^LLM_MODEL=target" .env 2>/dev/null || bash scripts/use_env.sh open
export LLM_BASE_URL="$(cat results/llm_urls.txt)"
# attacker: a 2nd, stronger model if its URLs file exists (scripts/serve_many.sh on another box,
# copied here as results/attacker_urls.txt); otherwise the victim model is the attacker.
if [ -f results/attacker_urls.txt ]; then
  export ATTACKER_BASE_URL="$(cat results/attacker_urls.txt)"; export ATTACKER_MODEL="${ATTACKER_MODEL:-target}"
  echo "strong attacker: $ATTACKER_BASE_URL"
fi
export MAX_WORKERS="${MAX_WORKERS:-96}"
export REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-300}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
N=$(nvidia-smi -L | wc -l); i=0
LOG=results/bigrun2-$MODEL_TAG.log; exec > >(tee -a "$LOG") 2>&1
echo "==== bigrun2 $(date) model=$MODEL_TAG seeds=$SEEDS jobs=$JOBS gpus=$N ===="

want () { [ "$JOBS" = all ] || { for p in ${JOBS//,/ }; do [[ "$1" == *"$p"* ]] && return 0; done; return 1; }; }
run () {  # run <unit-name> <run_experiment args...>
  local name="g2-$MODEL_TAG-$1"; shift
  want "${name#g2-$MODEL_TAG-}" || return 0
  echo ">>> [$name] $(date '+%H:%M:%S')"
  EMBED_DEVICE="cuda:$((i % N))" python run_experiment.py "$@" --tag "$name" > "results/$name.log" 2>&1 \
    && echo "<<< [$name] OK" || echo "<<< [$name] FAILED (see results/$name.log)"
  i=$((i + 1))
}

for seed in ${SEEDS//,/ }; do
  # --- our app (planted bugs; used for ABLATION only, never the headline) ---
  for m in off on; do
    run "ours-leak-$m-s$seed"   --rules isolation,deletion,entangled,authority --checks "$m" \
        --slots "$LEAK_SLOTS" --sessions "$LEAK_SESS" --attackers goal,fixed --seed "$seed" --bg-sample 0.5
    run "ours-poison-$m-s$seed" --rules "$POISON" --checks "$m" \
        --slots "$POIS_SLOTS" --sessions "$POIS_SESS" --seed "$seed"
  done
  # --- UNMODIFIED Mem0 (nothing planted; the headline) ---
  for m in off v2 on; do
    run "mem0-leak-$m-s$seed"   --backend mem0 --rules deletion,entangled --checks "$m" \
        --slots 80 --sessions 0,1,5,10 --attackers goal --seed "$seed"
    run "mem0-poison-$m-s$seed" --backend mem0 --rules "$POISON" --checks "$m" \
        --slots 80 --sessions "$POIS_SESS" --seed "$seed"
  done
  # --- false-alarm calibration (no planted bugs): must stay at chance ---
  run "calib-s$seed" --no-bugs --rules isolation,deletion,entangled,poisoning,inject_chat,inject_authority \
      --checks off --slots "$LEAK_SLOTS" --sessions 0,1 --attackers goal --seed "$seed" --bg-sample 0.5
done

# --- strictness-vs-utility curve (MH5): baseline defences + paranoid on the poison suite + the
#     must-learn rule, so we can plot attack-success vs utility over >=5 defence levels (seed 1).
#     off / on are already above; this adds base_prompt, base_regex, base_judge, paranoid.
for m in base_prompt base_regex base_judge paranoid; do
  run "ours-curve-$m" --rules "$POISON,authority" --checks "$m" --slots "$POIS_SLOTS" --sessions 0,1 --seed 1
  run "mem0-curve-$m" --backend mem0 --rules "$POISON,authority" --checks "$m" --slots 80 --sessions 0,1 --seed 1
done

# --- adaptive white-box attacker (MH6): the attacker is told the defence and crafts evasive poison.
#     Run across every defence level so we can report its BEST attack + residual-risk upper bound.
for m in off base_prompt base_regex base_judge on paranoid; do
  run "ours-adaptive-$m" --rules inject_adaptive --checks "$m" --slots "$LEAK_SLOTS" --sessions 0,1 --seed 1
  run "mem0-adaptive-$m" --backend mem0 --rules inject_adaptive --checks "$m" --slots 100 --sessions 0,1 --seed 1
done

# --- HELD-OUT (MH7): unseen canary values + Hindi poison + an unseen seed. Same FROZEN defence.
#     These numbers, not the development ones, are the headline for "not fitted to our evaluator".
#     FREEZE first:  git tag frozen-defence && git push --tags
for m in off on; do
  run "heldout-ours-leak-$m"   --held-out --rules isolation,deletion,entangled --checks "$m" \
      --slots "$LEAK_SLOTS" --sessions 0,1,5 --attackers goal --seed 99 --bg-sample 0.5
  run "heldout-ours-poison-$m" --held-out --rules "$POISON,inject_adaptive" --checks "$m" \
      --slots "$POIS_SLOTS" --sessions 0,1 --seed 99
  run "heldout-mem0-$m" --held-out --backend mem0 --rules "entangled,$POISON" --checks "$m" \
      --slots 80 --sessions 0,1,5 --attackers goal --seed 99
done

echo "==== bigrun2 done $(date) ===="
echo "Merge/analyse when the machines are all finished:  bash scripts/bigrun2.sh publish"
