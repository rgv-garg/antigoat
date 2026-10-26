"""Aggregate a bigrun2 grid across seeds into one honest table per memory stack.

  python scripts/analyze.py qwen32              # reads results/g2-qwen32-*.jsonl
  python scripts/analyze.py qwen32 --json docs/data/findings/g2-qwen32.json

For each (stack, rule, defence, sessions) it POOLS the trials from every seed (more power, one CI)
and also reports the per-seed accuracy spread, so a reader sees both the combined estimate and how
much it wobbles between seeds. Verdicts use the Holm-corrected p across the whole leak family.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LLM_BASE_URL", "mock")

from antigoat.runner import load  # noqa: E402
from antigoat.stats import summarize_group, holm_adjust, _verdict, ALPHA  # noqa: E402
from antigoat.worlds import RULES  # noqa: E402


def meta_of(path: Path) -> dict:
    mp = path.with_suffix(".meta.json")
    try:
        return json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    except ValueError:
        return {}


def stack_of(path: Path, meta: dict) -> str:
    stem = path.stem
    if "calib" in stem:
        return "calibration (no bugs)"
    if meta.get("backend") == "mem0" or "-mem0-" in stem:
        return "Mem0 (unmodified)"
    return "our app (planted bugs - ablation)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model", help="model tag, e.g. qwen32")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    files = [Path(f) for f in glob.glob(str(ROOT / "results" / f"*g2-{a.model}-*.jsonl")) if os.path.getsize(f) > 0]
    if not files:
        print(f"no results for model '{a.model}' (results/g2-{a.model}-*.jsonl)")
        return

    # key = (stack, rule, checks, sessions, attacker) -> list of per-seed (records, seed)
    byseed: dict[tuple, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    for f in files:
        meta = meta_of(f)
        seed = (meta.get("config") or {}).get("seed", 0)
        stack = stack_of(f, meta)
        for r in load(f):
            if r.get("attacker") == "fixed":
                continue  # keep the headline on the adaptive attacker; fixed is a separate baseline table
            key = (stack, r["rule"], r["checks"], int(r["sessions"]))
            byseed[key][seed].append(r)

    rows = []
    for (stack, rule, checks, sess), seeds in byseed.items():
        pooled = [r for recs in seeds.values() for r in recs]
        summ = summarize_group(pooled)
        accs = []
        for recs in seeds.values():
            s = summarize_group(recs)
            if s["n"]:
                accs.append(s["acc"])
        spread = (min(accs), max(accs)) if accs else (float("nan"), float("nan"))
        rows.append({"stack": stack, "rule": rule, "checks": checks, "sessions": sess,
                     "seeds": len(seeds), "seed_acc_min": spread[0], "seed_acc_max": spread[1], **summ})

    # Holm across the whole leak family (every must_not cell in this model's grid)
    fam = [r for r in rows if r["expect"] == "must_not" and r["n"] > 0]
    for r, pa in zip(fam, holm_adjust([r["p_value"] for r in fam])):
        r["p_adj"] = pa
    for r in rows:
        r["verdict"] = _verdict(r)

    order = {"off": 0, "base_prompt": 1, "base_regex": 2, "base_judge": 3, "v2": 4, "on": 5, "paranoid": 6}
    rows.sort(key=lambda r: (r["stack"], r["rule"], order.get(r["checks"], 9), r["sessions"]))
    cur = None
    for r in rows:
        if r["stack"] != cur:
            cur = r["stack"]; print(f"\n===== {cur} =====")
            print(f"{'rule':<20}{'def':<5}{'s':>3}{'n':>6}{'acc':>7}{'seed-range':>14}{'p_adj':>10}{'h':>6}  verdict")
        sr = f"{r['seed_acc_min']:.2f}-{r['seed_acc_max']:.2f}" if r["seeds"] > 1 else "  (1 seed)"
        h = f"{r['effect_h']:.2f}" if r["effect_h"] is not None else "   -"
        print(f"{r['rule']:<20}{r['checks']:<5}{r['sessions']:>3}{r['n']:>6}{r['acc']:>7.2f}{sr:>14}"
              f"{r['p_adj']:>10.1e}{h:>6}  {r['verdict']}"
              + (f"  (leak<= {r['adv_hi']*100:.0f}%)" if r["verdict"] == "PASS" and r["expect"] == "must_not" else ""))

    if a.json:
        out = {"model": a.model, "alpha": ALPHA,
               "rows": [{k: r[k] for k in ("stack", "rule", "checks", "sessions", "n", "seeds", "acc",
                                           "seed_acc_min", "seed_acc_max", "ci_lo", "ci_hi", "p_value",
                                           "p_adj", "adv_hi", "effect_h", "verdict", "expect")} for r in rows],
               "titles": {k: RULES[k].title for k in RULES}}
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nwrote {a.json}")


if __name__ == "__main__":
    main()
