"""Export the AntiGOAT findings page as a static site for GitHub Pages (free hosting).

Writes docs/index.html + docs/static/* + docs/data/* from the runs in results/. GitHub Pages
then serves it at https://<user>.github.io/<repo>/ (Settings -> Pages -> main, /docs).

  python scripts/export_static.py                                   # every run in results/
  python scripts/export_static.py --runs final-full,final-mem0,demo-mock-v3 \\
         --demo-url https://<your-brev-share-url>

The live Sahayak page (chat + Memory X-ray) needs a Python server, so the static site shows the
findings, the attacker's real conversations, and screenshots, and links to the live demo.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LLM_BASE_URL", "mock")

from antigoat.runner import load  # noqa: E402
from antigoat.stats import scorecard  # noqa: E402
from antigoat.worlds import RULES  # noqa: E402

REPO = "https://github.com/rgv-garg/antigoat"


def clean(x):
    """JSON for browsers: NaN/inf are not valid JSON."""
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    return x


ALIASES = {"target": "Qwen3-32B-FP8", "nemotron-nano": "Nemotron 3 Nano"}


def label(run: str, meta: dict) -> str:
    model = ALIASES.get(meta.get("sahayak_model"), meta.get("sahayak_model")) or "?"
    backend = "Mem0" if meta.get("backend") == "mem0" else "Sahayak store"
    kind = {"full": "full sweep", "calib": "false-alarm check (no planted bugs)", "mem0": "real Mem0",
            "gpu-first": "first real-model run"}
    tag = next((v for k, v in kind.items() if k in run), "")
    if model == "mock":
        return f"Offline mock model, {backend} (wiring check, not model behaviour)"
    return f"{model}, {backend}" + (f", {tag}" if tag else "")


def export_run(run: str, out: Path) -> dict:
    path = ROOT / "results" / f"{run}.jsonl"
    records = load(path)
    meta_p = path.with_suffix(".meta.json")
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    m = {k: meta.get(k) for k in ("sahayak_model", "attacker_model", "backend", "seconds", "embed_model")}
    m["slots"] = (meta.get("config") or {}).get("slots")
    m["sahayak_model"] = ALIASES.get(m.get("sahayak_model"), m.get("sahayak_model"))
    m["finished"] = bool(meta.get("finished"))
    findings = {"run": run, "rows": scorecard(records), "titles": {r: RULES[r].title for r in RULES},
                "expect": {r: RULES[r].expect for r in RULES}, "meta": m}
    (out / "findings").mkdir(parents=True, exist_ok=True)
    (out / "findings" / f"{run}.json").write_text(json.dumps(clean(findings), ensure_ascii=False), encoding="utf-8")

    cells = defaultdict(list)  # world-B conversations of the goal/decision attacker, per cell
    for r in records:
        if r.get("attacker") == "fixed" or r.get("coin") != 1:
            continue
        tr = [{"channel": t.get("channel"), "message": str(t.get("message", ""))[:500],
               "reply": None if t.get("reply") is None else str(t["reply"])[:700]}
              for t in (r.get("transcript") or [])[:6]]
        cells[f"{r['rule']}|{r['checks']}|{int(r['sessions'])}"].append(
            {"slot": r["slot"], "coin": 1, "guess": r["guess"], "correct": r["correct"], "world": "B", "transcript": tr})
    replay = {k: {"slots": sorted(v, key=lambda d: (-d["correct"], d["slot"]))[:10]} for k, v in cells.items()}
    (out / "replay").mkdir(parents=True, exist_ok=True)
    (out / "replay" / f"{run}.json").write_text(json.dumps(clean(replay), ensure_ascii=False), encoding="utf-8")
    return {"id": run, "label": label(run, m)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", default="", help="comma list of run ids in results/ (default: all non-empty)")
    p.add_argument("--demo-url", default="", help="public URL of the live Sahayak demo (Brev share link)")
    p.add_argument("--out", default=str(ROOT / "docs"))
    a = p.parse_args()

    docs = Path(a.out)
    data = docs / "data"
    if data.exists():
        shutil.rmtree(data)
    runs = [r for r in a.runs.split(",") if r] or [
        f.stem for f in sorted((ROOT / "results").glob("*.jsonl")) if f.stat().st_size > 0]
    if not a.runs:  # real-model runs first, published ones first, offline mock last (else: the order given)
        runs.sort(key=lambda r: (0 if r.startswith("final-") else (2 if "mock" in r else 1), r))
    exported = [export_run(r, data) for r in runs]
    (data / "runs.json").write_text(json.dumps({"runs": [e["id"] for e in exported],
                                                "labels": {e["id"]: e["label"] for e in exported}},
                                               ensure_ascii=False, indent=1), encoding="utf-8")

    static = docs / "static"
    static.mkdir(parents=True, exist_ok=True)
    for f in ("styles.css", "report.js", "goat.jpeg"):
        shutil.copyfile(ROOT / "web" / "static" / f, static / f)

    html = (ROOT / "web" / "static" / "report.html").read_text(encoding="utf-8")
    html = html.replace('href="/static/', 'href="static/').replace('src="/static/', 'src="static/')
    html = html.replace('href="/report"', 'href="./"')
    live = a.demo_url.strip()
    nav = (f'<a class="navlink" href="{live}" style="margin-left:auto">Try the live demo</a>'
           f'<a class="navlink" href="{REPO}">Code on GitHub</a>') if live else \
        f'<a class="navlink" href="{REPO}" style="margin-left:auto">Code on GitHub</a>'
    html = html.replace('<a class="navlink" href="/" style="margin-left:auto">Open Sahayak</a>', nav)
    shots = f'''
  <section class="shots" aria-label="The Memory X-ray">
    <h2>The Memory X-ray</h2>
    <p>The live demo shows, after a citizen says “please forget my name”, every place Sahayak still keeps
      that name. Left: Memory Checks off. Middle: Verified Erasure on. Right: the real Mem0 library's own
      history log still holding a deleted name.{" " if live else ""}{f'<a href="{live}">Try it live</a>.' if live else ""}</p>
    <div class="gallery">
      <a href="img/xray-checks-off.jpg"><img src="img/xray-checks-off.jpg" alt="Checks off: the X-ray lights up every leftover copy of the name" loading="lazy"></a>
      <a href="img/xray-checks-on.jpg"><img src="img/xray-checks-on.jpg" alt="Checks on: clean film, signed erasure receipt, 0 of 4 probes recover it" loading="lazy"></a>
      <a href="img/mem0-history-residue.jpg"><img src="img/mem0-history-residue.jpg" alt="Mem0's history log still holding the deleted name" loading="lazy"></a>
    </div>
  </section>'''
    html = html.replace('  <section class="replay" id="replay" hidden>', shots + '\n  <section class="replay" id="replay" hidden>')
    html = html.replace('<script src="static/report.js"></script>',
                        '<script>window.ANTIGOAT_STATIC = {base: "data/"};</script>\n<script src="static/report.js"></script>')
    (docs / "index.html").write_text(html, encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is
    size = sum(f.stat().st_size for f in docs.rglob("*") if f.is_file() and "data" in f.parts)
    print(f"exported {len(exported)} run(s) -> {docs}/index.html  (data {size // 1024} KB)")
    for e in exported:
        print(f"  {e['id']}: {e['label']}")


if __name__ == "__main__":
    main()
