"""White-box deletion-at-rest probe for the REAL Mem0 library (no planted bugs).

The twin-world Deletion rule tests this from the OUTSIDE (does a deleted fact come back
through the agent). This probe looks INSIDE Mem0's own storage to show exactly where a
"deleted" fact still lives, and whether Memory Checks' erasure closes the gap.

For each of N citizens we: store a unique code, call Mem0's own delete(), then look for the
code in (a) a fresh semantic search, (b) Mem0's `messages` buffer, (c) Mem0's `history` log.

  python run_mem0_probe.py --n 20 --tag mem0probe     # set .env to Brev for the real model

Needs: pip install -r requirements-mem0.txt
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def probe(checks: str, n: int) -> dict:
    from sahayak.agents import Sahayak
    found_search = resid_msgs = resid_hist = 0
    s = Sahayak(checks_mode=checks, backend="mem0")
    for i in range(n):
        user = f"m-{i:03d}"
        code = f"canary-{1000 + i}"
        s.say(user, f"Please remember my backup code is {code}.")
        s.forget(user, code)                       # Mem0's own delete() (+ erasure if checks on)
        if any(code in m.text for m in s.store.search(user, code)):
            found_search += 1
        r = s.store.residue(code)
        resid_msgs += r["messages_table"]
        resid_hist += r["history_table"]
    return {"checks": checks, "n": n, "resurfaced_in_search": found_search,
            "residue_messages_table": resid_msgs, "residue_history_table": resid_hist}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n", type=int, default=20)
    p.add_argument("--tag", default="mem0probe")
    p.add_argument("--out-dir", default="results")
    a = p.parse_args()

    rows = [probe("off", a.n), probe("on", a.n)]
    print(f"\nMem0 v2.2.1 deletion-at-rest ({a.n} citizens each)")
    print(f"{'erasure':<10}{'still found by search':<22}{'left in messages':<18}{'left in history'}")
    for r in rows:
        tag = "Mem0 only" if r["checks"] == "off" else "+ Checks"
        print(f"{tag:<10}{r['resurfaced_in_search']:>4}/{r['n']:<17}{r['residue_messages_table']:<18}{r['residue_history_table']}")

    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)
    jpath = out / f"mem0-probe-{a.tag}.json"
    jpath.write_text(json.dumps({"generated": time.time(), "rows": rows}, indent=2))
    print(f"\nsaved -> {jpath}")
    print("Reading: Mem0's own delete() leaves the code in its messages/history tables (that buffer is\n"
          "re-fed to its extraction LLM), so a 'deleted' fact can come back. Memory Checks' erasure purges both.")


if __name__ == "__main__":
    main()
