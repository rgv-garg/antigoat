"""Run an AntiGOAT experiment from the command line.

Examples
  # 2-minute smoke test with the offline mock LLM (no GPU needed):
  python run_experiment.py --slots 40 --sessions 0,1 --tag smoke

  # the full overnight run on Brev (set .env to the Brev endpoint first):
  python run_experiment.py --slots 200 --sessions 0,1,5,10 --checks off,on,paranoid --attackers goal,fixed --tag full

  # strong-attacker bonus run (attacker = hosted Nemotron 3 Super, set ATTACKER_* in .env):
  python run_experiment.py --rules isolation,deletion --slots 60 --sessions 0,5 --checks off,on --tag super
"""
from __future__ import annotations

import argparse

from antigoat.runner import RunConfig, load, run
from antigoat.stats import scorecard
from antigoat.worlds import RULES


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rules", default=",".join(RULES), help="comma list: " + ",".join(RULES))
    p.add_argument("--slots", type=int, default=100, help="slots (synthetic citizens) per rule")
    p.add_argument("--sessions", default="0,1,5,10", help="checkpoints, e.g. 0,1,5,10")
    p.add_argument("--checks", default="off,on", help="Memory Checks modes: off,v2,on,paranoid (v2 = before Verified Erasure)")
    p.add_argument("--attackers", default="goal", help="goal,fixed")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--learn-frac", type=float, default=0.2)
    p.add_argument("--turns", type=int, default=3)
    p.add_argument("--bg-sample", type=float, default=1.0)
    p.add_argument("--no-bugs", action="store_true", help="turn all planted bugs off (false-alarm calibration)")
    p.add_argument("--held-out", action="store_true",
                   help="held-out eval: unseen canary values + Hindi poison (sets ANTIGOAT_HELDOUT=1)")
    p.add_argument("--tag", default="")
    p.add_argument("--out-dir", default="results")
    p.add_argument("--backend", default="ours", choices=["ours", "mem0"],
                   help="ours = Sahayak's store with planted bugs; mem0 = real Mem0 OSS (pip install -r requirements-mem0.txt)")
    a = p.parse_args()
    if a.held_out:
        import os
        os.environ["ANTIGOAT_HELDOUT"] = "1"  # read by the planter (word pool) and worlds (poison language)

    cfg = RunConfig(
        rules=a.rules.split(","), slots=a.slots, sessions=[int(x) for x in a.sessions.split(",")],
        checks=a.checks.split(","), attackers=a.attackers.split(","), seed=a.seed,
        learn_frac=a.learn_frac, turns=a.turns, bg_sample=a.bg_sample, tag=a.tag, out_dir=a.out_dir, backend=a.backend,
    )
    if a.no_bugs:
        cfg.bugs = {k: False for k in cfg.bugs}
    path = run(cfg)
    print_scorecard(load(path))


def print_scorecard(records: list[dict]) -> None:
    rows = scorecard(records)
    print(f"\n{'rule':<10} {'checks':<9} {'attacker':<9} {'sess':>4} {'n':>4} {'acc':>6} {'95% CI':>13} {'p':>9} {'eps>=':>6}  verdict")
    for r in rows:
        eps = f"{r['eps_lb']:.2f}" if r["eps_lb"] is not None else "  -"
        print(f"{r['rule']:<10} {r['checks']:<9} {r['attacker']:<9} {r['sessions']:>4} {r['n']:>4} "
              f"{r['acc']:>6.2f} [{r['ci_lo']:.2f}, {r['ci_hi']:.2f}] {r['p_value']:>9.2e} {eps:>6}  {r['verdict']}"
              + (f"   ({r['parse_errors']} unreadable attacker answers!)" if r["parse_errors"] else ""))


if __name__ == "__main__":
    main()
