#!/usr/bin/env bash
# Public-benchmark runs on ONE GPU box (antigoat2, H100): AgentDojo + MemEvoBench, with Qwen3-32B-FP8.
# Run the steps in order; each one says what to do next.
#
#   bash scripts/run_benchmarks.sh setup     # once: a separate Python env with agentdojo + the benchmark data
#   bash scripts/run_benchmarks.sh serve     # inside tmux "llm": the model WITH tool calling switched on
#   bash scripts/run_benchmarks.sh check     # the model answers a tool call
#   bash scripts/run_benchmarks.sh pilot     # ~5 min: a small slice of both, prints the speed
#   bash scripts/run_benchmarks.sh full      # inside tmux "bench": both full runs, hard time cap
#   bash scripts/run_benchmarks.sh status    # progress
#
# Cost control: the full run stops starting new AgentDojo cases after CAP_MIN minutes (default 150)
# and can be resumed later with the same command. Nothing here uses the GPU except the model server.
set -euo pipefail
cd "$(dirname "$0")/.."
VENV="$HOME/venv-bench"
PY="$VENV/bin/python"
TAG="${TAG:-qwen32}"
CAP_MIN="${CAP_MIN:-150}"

case "${1:-}" in
  setup)
    [ -d "$VENV" ] || python3 -m venv "$VENV"
    "$VENV/bin/pip" install -q --upgrade pip
    "$VENV/bin/pip" install -q "agentdojo==0.1.35" -r requirements.txt
    bash scripts/fetch_external.sh
    bash scripts/use_env.sh open
    LLM_BASE_URL=mock "$PY" scripts/eval_agentdojo.py --list-tools | head -20
    echo
    echo "setup done. Next: start the model with tool calling ->  tmux new -s llm   then   bash scripts/run_benchmarks.sh serve"
    ;;
  serve)
    # tool calling for Qwen3 (hermes format), longer context (AgentDojo's workspace tasks carry long
    # inboxes), and more of the GPU for the model: these runs use no embedding model on the GPU.
    MODEL="${MODEL:-Qwen/Qwen3-32B-FP8}" MAX_LEN="${MAX_LEN:-32768}" GPU_UTIL="${GPU_UTIL:-0.90}" \
      EXTRA_ARGS="--enable-auto-tool-choice --tool-call-parser hermes --enable-prefix-caching ${EXTRA_ARGS:-}" \
      exec bash scripts/serve_model.sh
    ;;
  check)
    "$PY" - <<'PY'
from openai import OpenAI
c = OpenAI(base_url="http://localhost:8000/v1", api_key="x")
tools = [{"type": "function", "function": {"name": "get_balance", "description": "Get the account balance",
          "parameters": {"type": "object", "properties": {}}}}]
r = c.chat.completions.create(model="target", messages=[{"role": "user", "content": "What is my balance?"}],
                              tools=tools, tool_choice="auto", temperature=0,
                              extra_body={"chat_template_kwargs": {"enable_thinking": False}})
m = r.choices[0].message
print("tool calls:", [t.function.name for t in (m.tool_calls or [])], "| text:", (m.content or "")[:80])
print("OK: tool calling works" if m.tool_calls else "PROBLEM: no tool call - is the server started with 'serve'?")
PY
    ;;
  pilot)
    echo "== AgentDojo pilot (1 user task x 3 attacks per suite, + benign, 3 defences) =="
    "$PY" scripts/eval_agentdojo.py --tag "$TAG-pilot" --limit 1 --inj-limit 3 --arms none,spotlight,checks
    echo; echo "== MemEvoBench pilot (2 items per domain, 4 arms, with feedback) =="
    "$PY" scripts/eval_memevobench.py --tag "$TAG-pilot" --limit 2 --feedback
    echo; echo "pilot done. Send Claude the two tables and the 'episodes ... /min' lines."
    ;;
  full)
    echo "== AgentDojo full: 1,046 cases x 3 defences, time cap ${CAP_MIN} min == $(date)"
    "$PY" scripts/eval_agentdojo.py --tag "$TAG" --arms none,spotlight,checks --max-minutes "$CAP_MIN"
    echo; echo "== MemEvoBench full, with feedback == $(date)"
    "$PY" scripts/eval_memevobench.py --tag "$TAG" --feedback
    echo; echo "== MemEvoBench full, without feedback == $(date)"
    "$PY" scripts/eval_memevobench.py --tag "$TAG"
    echo; echo "ALL DONE $(date). Results: results/external/agentdojo-$TAG.md, memevobench-$TAG-fb.md, memevobench-$TAG.md"
    ;;
  status)
    for f in results/external/agentdojo-"$TAG".jsonl results/external/memevobench-"$TAG"-fb.jsonl results/external/memevobench-"$TAG".jsonl; do
      [ -f "$f" ] && echo "$f: $(wc -l < "$f") done" || echo "$f: not started"
    done
    echo "AgentDojo full run = 3,138 episodes; MemEvoBench = 432 items per file."
    ;;
  *) sed -n 2,13p "$0"; exit 1 ;;
esac
