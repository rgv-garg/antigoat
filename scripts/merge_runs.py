"""Merge the parallel jobs of scripts/bigrun.sh into one published run, or show their progress.

  python scripts/merge_runs.py final-full big-full-off,big-full-v2,big-full-on,big-full-paranoid
  python scripts/merge_runs.py --status big-full-off,big-calib,big-mem0-off

For each tag it takes the newest results/*-<tag>-*.jsonl. Safe while jobs are still running: a
half-written last line is skipped, and the merged run is marked unfinished until every part is done.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "results"
sys.path.insert(0, str(ROOT))


def newest(tag: str) -> Path | None:
    files = sorted(RES.glob(f"*-{tag}-*.jsonl"), key=lambda f: f.stat().st_mtime)
    return files[-1] if files else None


def records(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass  # the line being written right now
    return out


def meta_of(path: Path) -> dict:
    m = path.with_suffix(".meta.json")
    return json.loads(m.read_text(encoding="utf-8")) if m.exists() else {}


def done_cells(recs: list[dict]) -> str:
    """'isolation 0,1 | deletion 0' : checkpoints with at least one scored guess, per rule."""
    seen: dict[str, set] = defaultdict(set)
    for r in recs:
        seen[r["rule"]].add(int(r["sessions"]))
    return " | ".join(f"{rule} {','.join(map(str, sorted(s)))}" for rule, s in seen.items()) or "nothing scored yet"


def status(tags: list[str]) -> None:
    for tag in tags:
        p = newest(tag)
        if not p:
            print(f"{tag:<18} not started")
            continue
        m = meta_of(p)
        state = "FINISHED" if m.get("finished") else "running "
        age = int((time.time() - p.stat().st_mtime) / 60)
        print(f"{tag:<18} {state} {len(records(p)):>6} guesses  last write {age} min ago   {done_cells(records(p))}")


def merge(out: str, tags: list[str]) -> None:
    parts, recs, metas = [], [], []
    for tag in tags:
        p = newest(tag)
        if not p:
            print(f"  {tag}: no file yet, skipped")
            continue
        r = records(p)
        parts.append({"tag": tag, "file": p.name, "guesses": len(r)})
        recs += r
        metas.append(meta_of(p))
    if not recs:
        print(f"{out}: nothing to merge yet")
        return
    first = next((m for m in metas if m), {})
    if not first:  # no part has finished: describe the run from the settings
        os.environ.setdefault("LLM_BASE_URL", "mock")
        from config import SETTINGS
        first = {"sahayak_model": SETTINGS.sahayak.model, "attacker_model": SETTINGS.attacker.model,
                 "embed_model": SETTINGS.embed_model}
    per_rule: dict[str, set] = defaultdict(set)
    for r in recs:
        per_rule[r["rule"]].add(r["slot"])
    meta = {
        "run_id": out, "parts": parts,
        "sahayak_model": first.get("sahayak_model"), "attacker_model": first.get("attacker_model"),
        "embed_model": first.get("embed_model"),
        "backend": "mem0" if any("mem0" in t for t in tags) else "ours",
        "config": {**(first.get("config") or {}), "slots": max(len(s) for s in per_rule.values()),
                   "checks": sorted({r["checks"] for r in recs}), "tag": out},
        "finished": time.time() if len(metas) == len(tags) and all(m.get("finished") for m in metas) else None,
        "seconds": max((m.get("seconds") or 0) for m in metas) if metas else None,
    }
    with (RES / f"{out}.jsonl").open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (RES / f"{out}.meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{out}: {len(recs)} guesses from {len(parts)} part(s), "
          f"{'finished' if meta['finished'] else 'NOT finished yet (partial)'} -> results/{out}.jsonl")


def main() -> None:
    a = sys.argv[1:]
    if len(a) == 2 and a[0] == "--status":
        status([t for t in a[1].split(",") if t])
    elif len(a) >= 2:
        merge(a[0], [t for x in a[1:] for t in x.split(",") if t])
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
