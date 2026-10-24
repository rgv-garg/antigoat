"""Run the two bonus analyses (blast radius R0, fake-consensus) and save JSON for the dashboard.

  python run_extras.py --tag demo
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from antigoat.blast import measure_r0
from antigoat.consensus import run_comparison


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--citizens", type=int, default=20)
    p.add_argument("--tag", default="")
    p.add_argument("--out-dir", default="results")
    a = p.parse_args()

    blast = {m: asdict(measure_r0(m, n_citizens=a.citizens)) for m in ["off", "on"]}
    consensus = [asdict(r) for r in run_comparison()]
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + (f"-{a.tag}" if a.tag else "")
    path = out / f"extras-{stamp}.json"
    path.write_text(json.dumps({"blast": blast, "consensus": consensus}, indent=2))

    print("\n=== Blast radius (memory R0): one poisoned upload ===")
    for m, r in blast.items():
        print(f"  Memory Checks {m:3s}:  R0 = {r['r0']:3d} secondary victims"
              f"   (patient zero approved: {r['patient_zero_approved']})")
    print("\n=== Fake consensus: ten copies != ten witnesses ===")
    print(f"  {'defence':18s} {'fooled by 10 forged copies':30s} accepts 2 real sources")
    for r in consensus:
        print(f"  {r['defence']:18s} {str(r['fooled_by_forgery']):30s} {r['accepts_genuine']}")
    print(f"\nsaved -> {path}")


if __name__ == "__main__":
    main()
