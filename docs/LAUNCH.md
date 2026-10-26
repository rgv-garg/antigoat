# The grid launch sequence (the "100-score" run)

Everything is built and mock-tested. This runs the poisoning attack suite + leak rules on
**unmodified Mem0** and our app, with baselines, an adaptive attacker, a held-out set, 3 seeds,
and a self-hosted attacker. ~4-6 h on 4x H100, roughly **$130-200**. No API key needed.

## 0. Push first (laptop WSL)
```bash
cd "/mnt/c/Users/hp/Downloads/AEGIS Hackathon/antigoat"
pip show mem0ai >/dev/null 2>&1 || true   # (grid needs mem0ai + langmem already in requirements)
git add -A && git commit -m "Poisoning suite, baselines, adaptive + held-out attacker, hardened stats"
git tag frozen-defence && git push && git push --tags   # the FREEZE: defence is not touched after this
```

## 1. Start the machines
antigoat4 is up; start the others. On brev.nvidia.com or the CLI:
```bash
brev start antigoat3; brev start antigoat5; brev start antigoat6
```

## 2. On EACH machine: pull, serve the model, run its share
In `brev shell antigoatN`:
```bash
cd ~/antigoat && git pull && source ~/venv/bin/activate
pip install -q -r requirements-mem0.txt langmem 2>/dev/null || true
tmux new -s llm                      # then:
bash scripts/serve_many.sh           # wait for "All 1 model servers are up", Ctrl+B then D
tmux new -s run                      # then run this machine's share (table below), Ctrl+B then D
```

| Machine | command in the `run` window |
|---|---|
| antigoat3 | `JOBS=ours-leak,heldout-ours bash scripts/bigrun2.sh` |
| antigoat4 | `JOBS=mem0-leak,heldout-mem0 bash scripts/bigrun2.sh` |
| antigoat5 | `JOBS=ours-poison,ours-curve,ours-adaptive,calib bash scripts/bigrun2.sh` |
| antigoat6 | `JOBS=mem0-poison,mem0-curve,mem0-adaptive bash scripts/bigrun2.sh` |

(All four serve Qwen3-32B, so leave `MODEL_TAG` at its default `qwen32`.)

## 3. Watch progress (any machine, any time)
```bash
tail -f ~/antigoat/results/bigrun2-qwen32.log      # Ctrl+C to stop watching
grep -c OK ~/antigoat/results/bigrun2-qwen32.log   # how many job units finished
```

## 4. When all four say "bigrun2 done": copy results to the laptop
```bash
cd "/mnt/c/Users/hp/Downloads/AEGIS Hackathon/antigoat" && mkdir -p results/qwen2
for m in antigoat3 antigoat4 antigoat5 antigoat6; do scp "$m:~/antigoat/results/*g2-qwen32-*" results/qwen2/; done
```
Then tell me - I'll merge, run `scripts/analyze.py`, and refresh the findings site, handoff and slides
with the new numbers (per-stack tables, the strictness-vs-utility curve, the adaptive residual bounds,
and the held-out headline).

## 5. Stop paying
When the copy is done: `brev stop antigoat3 antigoat5 antigoat6` (keep antigoat4 or antigoat2 for the demo).

## Optional: a second model for the per-model-variance story
If budget/time remain after the Qwen32 grid, start one more machine, serve a small model and run a
reduced share tagged separately:
```bash
MODEL=Qwen/Qwen3-8B bash scripts/serve_many.sh     # 8B loads easily on one H100
MODEL_TAG=qwen8 JOBS=ours-poison,mem0-poison,ours-leak bash scripts/bigrun2.sh
```
That gives a large-vs-small column with no extra risk (same family, guaranteed to load).

## Quick live demo (no grid needed)
```bash
python scripts/harm_story.py        # the cross-user harm story, off vs on, < 60s
```
