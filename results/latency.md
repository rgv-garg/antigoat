# What Memory Checks cost (latency)

*400 writes and 400 reads across 20 users per cell; CPU, hash embeddings (isolates the checks' own cost). Reproduce: `python scripts/latency.py`.*

| Backend | Write, off -> on (median / p95 ms) | Added per write | Read, off -> on (median / p95 ms) | Added per read |
|---|---|---|---|---|
| ours | 0.02 / 0.04 -> 0.22 / 0.59 | +0.19 ms | 0.09 / 0.15 -> 0.09 / 0.15 | ~0 (within noise) |
| langgraph | 0.06 / 0.10 -> 0.68 / 1.17 | +0.62 ms | 0.69 / 1.22 -> 0.59 / 0.93 | ~0 (within noise) |
