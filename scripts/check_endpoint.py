"""Sanity-check that the LLM endpoint in .env works for both roles.

  python scripts/check_endpoint.py
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import SETTINGS  # noqa: E402
from llm import chat  # noqa: E402

for role in ["sahayak", "attacker"]:
    cfg = getattr(SETTINGS, role)
    print(f"\n[{role}] {cfg.base_url}  model={cfg.model}  thinking={cfg.thinking}")
    t = time.time()
    out = chat(role, [{"role": "user", "content": "Mera Aadhaar address update karna hai, kya documents chahiye? Answer in 2 lines."}])
    print(f"  {time.time() - t:.1f}s -> {out[:300]!r}")

# throughput: 32 parallel short requests
n = 32
t = time.time()
with ThreadPoolExecutor(n) as ex:
    list(ex.map(lambda i: chat("sahayak", [{"role": "user", "content": f"Say hello number {i}."}], max_tokens=20), range(n)))
dt = time.time() - t
print(f"\nthroughput: {n} requests in {dt:.1f}s = {n / dt:.1f} req/s")
print("A full run (4 rules x 200 slots x 4 checkpoints x 3 modes) needs roughly 60-80k calls;")
print(f"at this rate that is about {70000 / (n / dt) / 3600:.1f} hours. Lower --slots or --bg-sample if too slow.")
