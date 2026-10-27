"""Runs a full AntiGOAT experiment and streams one JSON line per guess.

The one-run trick: ONE Sahayak deployment per checks mode holds the slots for ALL rules
(hundreds of synthetic citizens, each with its own coin). Then:

  setup all slots -> for each checkpoint (0, 1, 5, 10 sessions):
      advance normal traffic -> audit every slot on a forked copy -> record guesses
"""
from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import llm
from antigoat.attacker import DecisionObserver, FixedProbeAttacker, GoalAttacker
from antigoat.planter import make_slots
from antigoat.sessions import SessionDriver
from antigoat.worlds import RULES
from config import SETTINGS
from sahayak.agents import Sahayak
from sahayak.memory import DEFAULT_BUGS


@dataclass
class RunConfig:
    rules: list[str] = field(default_factory=lambda: list(RULES))
    slots: int = 100
    sessions: list[int] = field(default_factory=lambda: [0, 1, 5, 10])
    checks: list[str] = field(default_factory=lambda: ["off", "on"])
    attackers: list[str] = field(default_factory=lambda: ["goal"])
    seed: int = 42
    learn_frac: float = 0.2      # share of attacker-rule slots used for learning (not scored)
    turns: int = 3               # attacker turns per slot
    abstain_below: float = 0.6
    bg_sample: float = 1.0       # fraction of citizens chatting per background session
    bugs: dict = field(default_factory=lambda: dict(DEFAULT_BUGS))
    out_dir: str = "results"
    backend: str = "ours"        # ours (planted bugs) | mem0 | langgraph (real libraries, nothing planted)
    target: str = ""             # "" = Sahayak in-process; else a target spec (JSON path) for ANY agent
    tag: str = ""


def _log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def _size(t) -> str:
    """How many memories the target holds, if it can say (a black box can't)."""
    store = getattr(t, "store", None)
    try:
        return f"{len(store)} items" if store is not None else "size unknown (black box)"
    except TypeError:
        return "size unknown"


def _factory(cfg: RunConfig):
    """(modes, make(mode) -> target, description). Sahayak runs once per Memory Checks mode;
    an external agent runs once, as deployed (we cannot switch its defences)."""
    if cfg.target:
        from antigoat.targets import load_target
        probe = load_target(cfg.target)
        if hasattr(probe, "reset"):
            probe.reset()
        return [probe.label], (lambda mode: probe), probe.describe()
    return (list(cfg.checks), (lambda mode: Sahayak(checks_mode=mode, bugs=cfg.bugs, backend=cfg.backend)),
            {"name": "sahayak", "kind": "Sahayak", "backend": cfg.backend})


def run(cfg: RunConfig) -> Path:
    run_id = time.strftime("%Y%m%d-%H%M%S") + (f"-{cfg.tag}" if cfg.tag else "") + "-" + uuid.uuid4().hex[:4]
    out = Path(cfg.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{run_id}.jsonl"
    modes, make, target_desc = _factory(cfg)
    meta = {"run_id": run_id, "config": asdict(cfg), "target": target_desc,
            "sahayak_model": SETTINGS.sahayak.model if SETTINGS.sahayak.base_url != "mock" else "mock",
            "attacker_model": SETTINGS.attacker.model if SETTINGS.attacker.base_url != "mock" else "mock",
            "embed_model": SETTINGS.embed_model, "backend": cfg.backend if not cfg.target else target_desc["name"],
            "extract_mode": SETTINGS.extract_mode, "verify_mode": SETTINGS.verify_mode, "started": time.time()}
    t0 = time.time()
    libraries = {}

    with path.open("w", encoding="utf-8") as f:
        def write(rec: dict) -> None:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()

        for mode in modes:
            _log(f"=== {'target ' + target_desc['name'] if cfg.target else 'Memory Checks'}: {mode} ===")
            sah = make(mode)
            from antigoat.targets import supported_rules
            rules, skipped = supported_rules(sah, cfg.rules)
            for r, missing in skipped.items():
                _log(f"  skip {r}: target has no {', '.join(sorted(missing))} capability")
            caps = getattr(sah, "capabilities", None)
            if caps is not None and "probe" not in caps:
                _log("  note: target has no no-memory probe endpoint, so audit messages are remembered by it; "
                     "this can only hide a leak, never fake one (PASS verdicts are conservative)")
                meta["audit_isolation"] = "none (probes remembered; PASS conservative)"
            elif caps is not None:
                meta["audit_isolation"] = "probe endpoint (probes leave no trace)"
            meta.setdefault("skipped_rules", {}).update({r: sorted(m) for r, m in skipped.items()})
            slots = {r: make_slots(r, cfg.slots, cfg.seed,
                                   cfg.learn_frac if RULES[r].observer == "attacker" else 0.0)
                     for r in rules}
            jobs = [(r, s) for r in rules for s in slots[r]]
            with ThreadPoolExecutor(SETTINGS.max_workers) as ex:  # setup makes LLM calls now
                list(ex.map(lambda rs: RULES[rs[0]].setup(sah, rs[1]), jobs))
            citizens = [s.citizen for r in rules for s in slots[r]]
            _log(f"planted {len(citizens)} slots, memory: {_size(sah)}")
            driver = SessionDriver(seed=cfg.seed, sample=cfg.bg_sample)

            for cp in sorted(cfg.sessions):
                driver.advance(sah, citizens, cp)
                _log(f"[{mode}] checkpoint {cp} sessions, memory: {_size(sah)}")
                for r in rules:
                    spec = RULES[r]
                    if spec.observer == "decision":
                        attackers = [DecisionObserver()]
                    else:
                        attackers = []
                        for a in cfg.attackers:
                            if a == "goal":
                                key = (mode, r)
                                attackers.append(GoalAttacker(cfg.turns, cfg.abstain_below, libraries.get(key)))
                                libraries[key] = attackers[-1].library
                            elif a == "fixed":
                                attackers.append(FixedProbeAttacker())

                    for atk in attackers:
                        learn = [s for s in slots[r] if s.split == "learn"]
                        score = [s for s in slots[r] if s.split == "score"]

                        def audit(slot, atk=atk, spec=spec):
                            res = atk.run(sah.fork(), spec, slot)
                            return slot, res

                        for phase in (learn, score):
                            with ThreadPoolExecutor(SETTINGS.max_workers) as ex:
                                for slot, res in ex.map(audit, phase):
                                    if slot.split == "learn":
                                        atk.learn(res, slot)
                                    write({
                                        "run_id": run_id, "rule": r, "expect": spec.expect, "checks": mode,
                                        "attacker": atk.name, "sessions": cp, "slot": slot.idx,
                                        "split": slot.split, "coin": slot.coin, "guess": res.guess,
                                        "correct": int(res.guess == slot.world), "conf": res.confidence,
                                        "abstain": bool(res.abstain), "parse_ok": res.parse_ok, "strategy": res.strategy[:300],
                                        "transcript": res.transcript[:6],
                                    })
                        _log(f"  {r:<10} {atk.name:<8} done ({len(learn)} learn + {len(score)} score slots)")

    meta.update({"finished": time.time(), "seconds": round(time.time() - t0, 1), "usage": dict(llm.USAGE),
                 "strategy_libraries": {f"{m}/{r}": lib.to_dict() for (m, r), lib in libraries.items()}})
    (out / f"{run_id}.meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    _log(f"done in {meta['seconds']}s -> {path}")
    return path


def load(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
