"""Check Advisor: close the loop from finding -> fix -> re-verify, with no human in between.

Future-scaling demo for the idea "any leak AntiGOAT finds, an agent patches the defence and
AntiGOAT re-verifies". Here the Advisor picks from the KNOWN Memory Checks library (it does
not invent new code - that's the honest limit, stated as future work). The loop is:

  1. AntiGOAT probes the undefended agent  -> a set of leaks.
  2. For each leak, the Advisor enables the single check responsible for it.
  3. AntiGOAT re-probes with ONLY the enabled checks  -> confirms the leak is closed.

Deterministic, so it runs offline in a second and is reproducible on stage.

  python run_advisor.py
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from run_ablation import PROBES          # {rule: (responsible_checks, probe_fn)}
from sahayak.checks import ALL_CHECKS


def _enable_only(checks: set[str]) -> str:
    """A spec that runs 'on' with every sub-check disabled EXCEPT the ones named."""
    off = [c for c in ALL_CHECKS if c not in checks]
    return "on" + (":" + ",".join(f"-{c}" for c in off) if off else "")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tag", default="advisor")
    p.add_argument("--out-dir", default="results")
    a = p.parse_args()

    steps = []
    print("Check Advisor - autonomous detect -> patch -> re-verify\n")
    for rule, (resp, probe) in PROBES.items():
        needed = set(resp.replace("-", "").split(","))
        leak_before = probe("off")
        spec = _enable_only(needed)
        leak_after = probe(spec)
        fixed = leak_before and not leak_after
        pretty = " + ".join(sorted(needed))
        steps.append({"leak": rule, "detected": leak_before, "advisor_enabled": pretty,
                      "spec": spec, "leak_after": leak_after, "closed": fixed})
        print(f"● AntiGOAT: '{rule}' leak detected ...... {'YES' if leak_before else 'no'}")
        print(f"  Advisor : enable [{pretty}]")
        print(f"  Re-check: leak now ................... {'STILL OPEN' if leak_after else 'CLOSED ✓'}\n")

    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    jpath = out / f"advisor-{a.tag}.json"
    jpath.write_text(json.dumps({"generated": time.time(), "steps": steps}, indent=2))
    ok = all(s["closed"] for s in steps)
    print(("All leaks were detected and closed automatically." if ok
           else "Some leaks were not closed - inspect above.") + f"\nsaved -> {jpath}")


if __name__ == "__main__":
    main()
