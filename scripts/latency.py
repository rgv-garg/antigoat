#!/usr/bin/env python3
"""What do Memory Checks cost? Median / p95 milliseconds per write and per read, checks off vs on,
on each memory backend. CPU only, hash embeddings (so the numbers isolate the checks' own cost,
not an embedding model's):

    LLM_BASE_URL=mock EMBED_MODEL=hash python scripts/latency.py

Writes results/latency.md.
"""
from __future__ import annotations

import os
import pathlib
import statistics
import sys
import time

os.environ.setdefault("LLM_BASE_URL", "mock")
os.environ.setdefault("EMBED_MODEL", "hash")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from memorychecks import GovernedMemory  # noqa: E402

N_WRITES, N_READS, USERS = 400, 400, 20


def _p(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def bench(backend: str, mode: str) -> dict:
    m = GovernedMemory(mode=mode, backend=backend)
    w, r = [], []
    for i in range(N_WRITES):
        u = f"user{i % USERS}"
        t0 = time.perf_counter()
        m.write(u, f"My note number {i}: my locker code is kesar-{1000 + i} and my phone is 98{i:08d}.",
                source="user" if i % 3 else "web", kind="fact" if i % 3 else "note")
        w.append((time.perf_counter() - t0) * 1000)
    for i in range(N_READS):
        t0 = time.perf_counter()
        m.read(f"user{i % USERS}", f"what is my locker code {i}?")
        r.append((time.perf_counter() - t0) * 1000)
    return {"write_med": statistics.median(w), "write_p95": _p(w, .95),
            "read_med": statistics.median(r), "read_p95": _p(r, .95)}


def _stable(backend: str, mode: str, reps: int = 3) -> dict:
    """Warm up once, then take the median of `reps` repeated runs (alternating with the other
    mode in main) so run order and caches do not masquerade as a difference."""
    runs = [bench(backend, mode) for _ in range(reps)]
    return {k: statistics.median(r[k] for r in runs) for k in runs[0]}


def _delta(a: float, b: float, noise: float) -> str:
    d = b - a
    return "~0 (within noise)" if abs(d) < noise else f"{d:+.2f} ms"


def main() -> None:
    rows = []
    for backend in ("ours", "langgraph"):
        bench(backend, "off"); bench(backend, "on")          # warm-up
        off, on = _stable(backend, "off"), _stable(backend, "on")
        rows.append((backend, off, on))
        print(f"{backend:10} write {off['write_med']:.2f} -> {on['write_med']:.2f} ms | "
              f"read {off['read_med']:.2f} -> {on['read_med']:.2f} ms")
    out = pathlib.Path("results/latency.md")
    out.parent.mkdir(exist_ok=True)
    with out.open("w") as f:
        f.write("# What Memory Checks cost (latency)\n\n")
        f.write(f"*{N_WRITES} writes and {N_READS} reads across {USERS} users per cell; CPU, hash embeddings "
                f"(isolates the checks' own cost). Reproduce: `python scripts/latency.py`.*\n\n")
        f.write("| Backend | Write, off -> on (median / p95 ms) | Added per write | Read, off -> on (median / p95 ms) | Added per read |\n")
        f.write("|---|---|---|---|---|\n")
        for b, off, on in rows:
            f.write(f"| {b} | {off['write_med']:.2f} / {off['write_p95']:.2f} -> {on['write_med']:.2f} / "
                    f"{on['write_p95']:.2f} | {_delta(off['write_med'], on['write_med'], 0.05)} | "
                    f"{off['read_med']:.2f} / {off['read_p95']:.2f} -> {on['read_med']:.2f} / {on['read_p95']:.2f} | "
                    f"{_delta(off['read_med'], on['read_med'], 0.1)} |\n")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
