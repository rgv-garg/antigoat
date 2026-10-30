"""Summarise garak report jsonl files (results/nvidia/garak/sahayak-<mode>.report.jsonl) into one table."""
import json, sys
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else "results/nvidia/garak")
rows = {}
for f in sorted(out.glob("sahayak-*.report.jsonl")):
    mode = f.name.split(".")[0].removeprefix("sahayak-")
    for line in f.open(encoding="utf-8"):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("entry_type") == "eval":
            key = (e["probe"], e["detector"])
            total = e.get("total") or e.get("total_evaluated") or 0
            rows.setdefault(key, {})[mode] = (e.get("passed", 0), total)
ver = (out / "version.txt").read_text().strip() if (out / "version.txt").exists() else "garak"
modes = sorted({m for v in rows.values() for m in v})
lines = [f"# NVIDIA garak scan of Sahayak ({ver})", "",
         "Attack success = share of garak attempts the detector flagged (lower is better).", "",
         "| Probe | Detector | " + " | ".join(f"Checks {m}" for m in modes) + " |",
         "|---|---|" + "---|" * len(modes)]
for (p, d), v in sorted(rows.items()):
    cells = []
    for m in modes:
        if m in v and v[m][1]:
            passed, tot = v[m]
            cells.append(f"{(tot - passed) / tot:.0%} ({tot - passed}/{tot})")
        else:
            cells.append("-")
    lines.append(f"| {p} | {d} | " + " | ".join(cells) + " |")
lines += ["", "garak probes one conversation turn at a time (prompt injection, encoding tricks). It has no notion of "
          "a second visit, a 'forget' request or a shared memory, so the cross-session leaks AntiGOAT measures "
          "(isolation 92%, deletion 87%, entangled 92% on Qwen3-32B, Checks Off) are outside what it can test. "
          "AntiGOAT extends garak-style scanning to agent memory."]
(out / "garak-summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
