# Brev GPU runbook

The real-model runs and the fast demo use a GPU on NVIDIA Brev (instance `antigoat`). Your laptop only
connects to it.

## Start
```bash
brev ls                      # STOPPED? ->  brev start antigoat   (wait until RUNNING / READY)
brev shell antigoat
cd ~/antigoat && git pull
bash scripts/use_env.sh brev # .env now points at the local vLLM server
```

## Serve the model (once per boot, 3-5 minutes)
```bash
tmux new -s llm
bash scripts/serve_vllm.sh   # wait for "Application startup complete", then Ctrl+B, D
```

## The web demo
```bash
tmux new -s web
bash scripts/serve_web.sh    # "Uvicorn running on http://0.0.0.0:8100", then Ctrl+B, D
```
From the laptop: `brev port-forward antigoat -p 8100:8100`, then open http://localhost:8100
(Sahayak and the X-ray) and http://localhost:8100/report (findings).

## Overnight runs
```bash
tmux new -s run
bash scripts/overnight.sh    # logs to results/overnight.log; publishes results/final-*.jsonl
```
Then commit the published results so the hosted demo shows them:
```bash
git add results/final-* && git commit -m "Real-model results" && git push
```

## Sanity checks before trusting numbers
- Checks off: isolation and poisoning should leak clearly. If isolation is near 50%, fix the attacker
  prompt, not the statistics.
- The calibration run (no planted bugs) should hold every rule, at about 50%.

## Stop paying
`brev stop antigoat` whenever nobody is using it. This also stops the model and the site.
