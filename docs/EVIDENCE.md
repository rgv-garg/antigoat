# Evidence map: every number, where it comes from

Each claim in the README and RESULTS.md points to the file that holds it and the command that
reproduces it. Deterministic items run on any laptop, offline (`LLM_BASE_URL=mock EMBED_MODEL=hash`);
real-model items need a GPU serving the model (see `docs/RUNBOOK.md`).

## Real-model audit (RESULTS.md §1)

| Claim | Source | Reproduce |
|---|---|---|
| Leak rules on our store, off → on, Qwen3-32B and Qwen3-8B, 3 seeds (88/82/94% and 88/85/91% → chance) | `results/reduced.json` (reduced from `results/g2-<model>-ours-leak-*.jsonl`) | `MODEL_TAG=qwen32 JOBS=ours-leak bash scripts/bigrun2.sh`, then `python scripts/analyze.py qwen32` (and `qwen8`) |
| Unmodified Mem0: deletion 65/68%, entangled 74/78%, v2 74/79% → chance | `results/reduced.json` (`g2-*-mem0-leak-*`) | `JOBS=mem0-leak bash scripts/bigrun2.sh` |
| Poisoning suite (document 100%, authority impersonation 100%, delayed 89%, cross-user 100%) | `results/reduced.json` (`g2-*-ours-poison-*`) | `JOBS=ours-poison bash scripts/bigrun2.sh` |
| Calibration with no planted bugs (leak rules at chance; fake notice still 100%) | `results/reduced.json` (`g2-*-calib-*`) | `JOBS=calib bash scripts/bigrun2.sh` |
| Baselines: prompt warning and regex 100%; LLM judge 56% at 88% utility; Strict 52% utility | `results/reduced.json` (`g2-*-ours-curve-*`) | `JOBS=curve bash scripts/bigrun2.sh` |
| Held-out (unseen values, Hindi poison, seed 99) | `results/reduced.json` (`g2-*-heldout-*`) | `JOBS=heldout bash scripts/bigrun2.sh` |
| Single-seed v3 sweep on Qwen3-32B (26 Oct) | `results/final-full.jsonl`, `final-calib.jsonl`, `final-mem0.jsonl` | `bash scripts/bigrun.sh` |
| Earlier Nemotron 3 Nano run (v2 defence) | `results/20261024-191815-full-ea8f.jsonl`, `20261024-220001-calib-8a60.jsonl`, `20261025-013701-mem0del-997a.jsonl` | `python run_experiment.py --slots 200 --sessions 0,1,5,10 --checks off,on,paranoid --attackers goal,fixed` |
| Generality grid on real models: reference agent, LangGraph backend, Mem0 poisoning on current code, third model family | `results/g3-<model>-*.jsonl` → `results/generality.md` | `MODEL_TAG=qwen32 bash scripts/bigrun3.sh`, then `python scripts/summarise_g3.py` |
| Public benchmark: InjecAgent, 1,054 cases × base/enhanced, 4 arms + benign twins | `results/external/injecagent-<model>.{md,json,jsonl}` | `bash scripts/fetch_injecagent.sh && python scripts/eval_injecagent.py --tag <model>` |

## Deterministic, offline (RESULTS.md §2–4)

| Claim | Source | Reproduce |
|---|---|---|
| A black-box HTTP audit gives the same numbers as in-process | `tests/test_any_agent.py::test_black_box_http_audit_matches_in_process` | `pytest tests/test_any_agent.py -k black_box` |
| Reference agent (not Sahayak): deletion and entangled leak, isolation holds; governed: all hold | `tests/test_any_agent.py::test_reference_agent_not_sahayak_found_and_fixed` | `pytest tests/test_any_agent.py -k reference_agent` |
| Same guarantees on three backends (ours, Mem0, LangGraph) | `tests/test_any_agent.py::test_governed_memory_same_guarantees_on_every_backend` | `pytest tests/test_any_agent.py -k every_backend` |
| Rules needing a missing capability are skipped, never faked | `tests/test_any_agent.py::test_capabilities_skip_rules_never_fake_them` | `pytest tests/test_any_agent.py -k capabilities` |
| 16/16 Memory Checks mechanisms (four pillars, integrity, erasure, utility incl. 0% false-quarantine) | `results/governance-report.md` | `python scripts/governance_report.py` |
| Six invariants on generated inputs; two bugs found and fixed | `tests/test_invariants.py` | `pytest tests/test_invariants.py` |
| Ablation: each check stops exactly its leak | `results/ablation-ci.json` | `python run_ablation.py` |
| Mem0 data at rest after `delete()`: 30/30 in `messages` and `history`; 0/0 with checks | `results/mem0-probe-ci.json` | `python run_mem0_probe.py --n 30` |
| Mem0's own `history()` returns the deleted text | `mem0_min_repro.py`, `DISCLOSURE.md` | `python mem0_min_repro.py` |
| Latency: +0.2 ms per write (ours), +0.6 ms (LangGraph), nothing measurable per read | `results/latency.md` | `python scripts/latency.py` |
| The "don't erase my name" fix and forget-intent detection | `tests/test_any_agent.py::test_forget_intent_respects_negation` | `pytest -k negation` |

## Statistics

Exact one-sided binomial test against 50%; Holm-Bonferroni within each family; Clopper-Pearson 95%
intervals; Cohen's h; ε lower bound; residual-risk upper bound when a rule holds (`antigoat/stats.py`).
Public-benchmark proportions use 95% Wilson intervals. Hypotheses, metrics and thresholds were fixed
in advance in `PREREGISTRATION.md`.
