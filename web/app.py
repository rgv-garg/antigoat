"""AntiGOAT web app: Sahayak (the agent under test) + the Memory X-ray + AntiGOAT findings.

  uvicorn web.app:app --host 0.0.0.0 --port 8100      (or: bash scripts/serve_web.sh)

Pages (static, in web/static), talking to the JSON API below:
  /          Sahayak - a citizen chats (text or voice, any Indian language), a Memory Checks
             switch (OFF / v2 / ON / Strict), a backend switch (our store / real Mem0), and
             the Memory X-ray: after "please forget my name" it shows every place the value
             still lives - with the actual leftover text - and "Verify with AntiGOAT" attacks
             that one erasure live.
  /report    AntiGOAT findings from the big twin-world runs; click a cell to replay the
             attacker's real conversations.

The experiment numbers on /report come from the runs in results/, not from this server.
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from antigoat.runner import load
from antigoat.stats import scorecard
from antigoat.worlds import RULES
from config import SETTINGS
from sahayak.agents import Sahayak, is_forget_request
from sahayak.erasure import pattern

STATIC = Path(__file__).parent / "static"
RESULTS = Path(os.environ.get("RESULTS_DIR", "results"))
app = FastAPI(title="AntiGOAT")

# ---- live sessions -----------------------------------------------------------------
_sessions: dict[str, dict] = {}   # sid -> {"s": Sahayak, "tracked": {user: {...}}, "t": last use}
_lock = threading.Lock()
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "60"))

def _mem0_available() -> bool:
    try:
        import mem0  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _get(sid: str) -> dict | None:
    with _lock:
        st = _sessions.get(sid)
        if st:
            st["t"] = time.time()
        return st


def _user(s: Sahayak, name: str = "", pincode: str = "") -> str:
    """The citizen this request is from. Typing a new name logs in as a NEW citizen on the
    SAME Sahayak (same shared memory) - that is how you play the attacker for Isolation."""
    name = (name or "").strip() or next(iter(s.profiles), "ramesh")
    if name not in s.profiles:
        s.register(name, (pincode or "").strip() or "560012")
    elif (pincode or "").strip():
        s.profiles[name]["pincode"] = pincode.strip()
    return name


class NewSession(BaseModel):
    checks: str = "off"
    user_id: str = "ramesh"
    pincode: str = "560012"
    backend: str = "ours"


class ChatIn(BaseModel):
    sid: str
    message: str
    agent: str = "intake"
    user: str = ""
    pincode: str = ""


class ActionIn(BaseModel):
    sid: str
    text: str = ""
    has_address_proof: bool = False
    user: str = ""
    pincode: str = ""


def _mem_snapshot(s: Sahayak, user: str) -> list[dict]:
    out = []
    for it in s.store.visible(user):
        out.append({"id": it.id, "owner": it.owner, "type": it.btype, "source": it.source,
                    "status": it.status, "trust": getattr(it, "trust", 2), "text": it.text,
                    "redacted": bool((it.meta or {}).get("redacted"))})
    return out


def _xray(st: dict, user: str) -> dict:
    """The Memory X-ray for the values this citizen last asked to erase."""
    s: Sahayak = st["s"]
    tr = st["tracked"].get(user)
    if not tr:
        return {"tracked": False}
    found = s.xray_find(user, tr["values"])
    counts = s.xray(user, tr["values"])
    rxs = [pattern(v) for v in tr["values"]]

    def mark(t: str) -> str:
        # wrap the leftover value in \u0001..\u0002 so the UI can highlight it safely
        for rx in rxs:
            t = rx.sub(lambda m: "\u0001" + m.group(0) + "\u0002", t)
        return t

    return {"tracked": True, "topic": tr["topic"], "label": tr["label"], "mode": tr["mode"],
            "counts": counts, "total": sum(counts.values()),
            "hits": [{"where": w, "text": mark(t)[:220]} for w, t in found[:24]],
            "receipt": tr.get("receipt"), "verify": tr.get("verify")}


def _state(st: dict, user: str) -> dict:
    s: Sahayak = st["s"]
    return {"memory": _mem_snapshot(s, user), "checks": s.checks.log[-8:], "xray": _xray(st, user),
            "tombstones": s.store.tomb.count(user) if s.checks.feature("tombstone") else 0}


def _forget_reply(ev: dict) -> str:
    """Never repeats the erased value (a reply that echoed it would itself be a new copy)."""
    what = " / ".join(ev["topics"]) or ("the detail you mentioned" if ev["n_values"] else "that")
    if not ev["removed"]:
        return "I could not find a saved detail matching that to erase."
    if ev["mode"] == "verified-erasure":
        return (f"Done - I have erased your {what} from every place I had it ({ev['removed']} record(s)), "
                f"and I will not store it again unless you tell me yourself. Your signed erasure receipt is "
                f"in the Memory X-ray. (DPDP right to erasure)")
    return f"Done - I have deleted {ev['removed']} saved detail(s) about your {what}."


# ---- API ---------------------------------------------------------------------------
_model_names: dict[str, str] = {}


def _real_model_name(cfg) -> str:
    """vLLM is served under a short alias ("target"); show the real model ("Qwen/Qwen3-32B-FP8")."""
    if cfg.base_url == "mock":
        return "offline mock"
    if cfg.base_url not in _model_names:
        name = cfg.model
        try:
            import requests
            r = requests.get(cfg.base_url.split(",")[0].strip().rstrip("/") + "/models", timeout=3,
                             headers={"Authorization": f"Bearer {cfg.api_key}"})
            for m in r.json().get("data", []):
                if m.get("id") == cfg.model and m.get("root"):
                    name = m["root"]
        except Exception:  # noqa: BLE001
            pass
        _model_names[cfg.base_url] = name
    return _model_names[cfg.base_url]


@app.get("/api/info")
def info():
    mock = SETTINGS.sahayak.base_url == "mock"
    from voice import sarvam
    return {"model": _real_model_name(SETTINGS.sahayak), "mock": mock,
            "attacker_model": _real_model_name(SETTINGS.attacker),
            "mem0": _mem0_available(), "voice": sarvam.available(), "embed": SETTINGS.embed_model}


@app.post("/api/session")
def new_session(x: NewSession):
    backend = "mem0" if x.backend == "mem0" and _mem0_available() else "ours"
    s = Sahayak(checks_mode=x.checks, backend=backend)
    s.register(x.user_id, x.pincode)
    sid = uuid.uuid4().hex[:10]
    with _lock:
        if len(_sessions) >= MAX_SESSIONS:  # evict the least recently used session
            oldest = min(_sessions, key=lambda k: _sessions[k]["t"])
            _sessions.pop(oldest, None)
        _sessions[sid] = {"s": s, "tracked": {}, "t": time.time()}
    return {"sid": sid, "mode": s.checks.label, "backend": backend, "user_id": x.user_id,
            "pincode": x.pincode, **_state(_sessions[sid], x.user_id)}


@app.post("/api/chat")
def chat(x: ChatIn):
    st = _get(x.sid)
    if st is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    s: Sahayak = st["s"]
    user = _user(s, x.user, x.pincode)
    agent = x.agent if x.agent in {"intake", "grievance"} else "intake"
    try:
        # Natural-language erasure: a citizen who can't read just SAYS "forget my number".
        if is_forget_request(x.message):
            ev = s.forget_request(user, x.message)
            if ev["_values"] or ev["removed"]:
                st["tracked"][user] = {"values": ev["_values"], "topic": " / ".join(ev["topics"]) or "detail",
                                       "label": ", ".join(ev["values_masked"]) or "(no value found)",
                                       "mode": ev["mode"], "receipt": ev["receipt"], "verify": None,
                                       "before": ev["before"]}
            reply = _forget_reply(ev)
            said = x.message
            if s.checks.feature("entity_erasure"):  # "please delete kesar-4135" must not re-add it
                for v in ev["_values"]:
                    said = pattern(v).sub("[erased]", said)
            with s._lock:  # keep the visit's context in order (the reply never contains the value)
                h = s.history.setdefault(user, [])
                h += [{"role": "user", "content": said}, {"role": "assistant", "content": reply}]
            public = {k: v for k, v in ev.items() if not k.startswith("_")}
            return {"reply": reply, "agent": agent, "event": {"kind": "forget", **public}, **_state(st, user)}
        reply = s.chat(user, x.message, agent, history=True)
    except Exception as e:  # noqa: BLE001 - show the reason in the chat instead of a blank 500
        return JSONResponse({"error": f"model call failed: {e}"}, status_code=502)
    return {"reply": reply, "agent": agent, **_state(st, user)}


@app.post("/api/xray")
def xray(x: ActionIn):
    """X-ray any value the presenter types ("teja", "98765 43210"): where does it live right
    now? Becomes the tracked value until the next forget-request."""
    st = _get(x.sid)
    if st is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = _user(st["s"], x.user, x.pincode)
    v = (x.text or "").strip()
    if v:
        prev = st["tracked"].get(user) or {}
        st["tracked"][user] = {"values": [v], "topic": "value you typed", "label": v,
                               "mode": prev.get("mode", "scan"), "receipt": prev.get("receipt"), "verify": None}
    return {"ok": True, **_state(st, user)}


@app.post("/api/verify")
def verify(x: ActionIn):
    """Verify with AntiGOAT: attack the citizen's last erasure live (a few adaptive probes)."""
    st = _get(x.sid)
    if st is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    s: Sahayak = st["s"]
    user = _user(s, x.user, x.pincode)
    tr = st["tracked"].get(user)
    if not tr or not tr["values"]:
        return JSONResponse({"error": "ask Sahayak to forget something first"}, status_code=400)
    from antigoat.live import verify_erasure
    try:
        res = verify_erasure(s, user, tr["values"], tr["topic"], probes=int(os.environ.get("VERIFY_PROBES", "4")))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"attacker model call failed: {e}"}, status_code=502)
    tr["verify"] = {"recovered": res["recovered"], "verdict": res["verdict"], "probes": res["probes"]}
    rxs = [pattern(v) for v in tr["values"]]
    for t in res["transcript"]:  # highlight what leaked
        for rx in rxs:
            t["reply"] = rx.sub(lambda m: "\u0001" + m.group(0) + "\u0002", t["reply"] or "")
    return {"result": res, **_state(st, user)}


@app.post("/api/login")
def login(x: ActionIn):
    """Switch to another citizen on the SAME Sahayak (memory is kept). With the shared_index
    bug live, what they can see includes other citizens' data."""
    st = _get(x.sid)
    if st is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = _user(st["s"], x.user, x.pincode)
    return {"ok": True, "user": user, **_state(st, user)}


@app.post("/api/end")
def end_visit(x: ActionIn):
    """The visit ends: the context window is cleared and Sahayak summarises the citizen's
    history (where the soft_delete bug copies 'deleted' details back)."""
    st = _get(x.sid)
    if st is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = _user(st["s"], x.user, x.pincode)
    st["s"].end_session(user)
    return {"ok": True, **_state(st, user)}


@app.post("/api/upload")
def upload(x: ActionIn):
    st = _get(x.sid)
    if st is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = _user(st["s"], x.user, x.pincode)
    st["s"].upload(user, x.text)
    return {"ok": True, **_state(st, user)}


@app.post("/api/policy")
def policy(x: ActionIn):
    st = _get(x.sid)
    if st is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = _user(st["s"], x.user, x.pincode)
    st["s"].admin_policy(x.text, signed=True)
    return {"ok": True, **_state(st, user)}


@app.post("/api/apply")
def apply(x: ActionIn):
    st = _get(x.sid)
    if st is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = _user(st["s"], x.user, x.pincode)
    try:
        d = st["s"].apply(user, has_address_proof=x.has_address_proof)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"model call failed: {e}"}, status_code=502)
    return {"decision": d, **_state(st, user)}


@app.post("/api/governance")
def governance(x: ActionIn):
    """The Memory Checks half, made clickable: provenance (origin + trust of every memory),
    contradiction detection, and the post-incident auditor (which memory caused the decision,
    and roll it back). `text` selects the view: provenance | contradictions | why | rollback | retract."""
    st = _get(x.sid)
    if st is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    s: Sahayak = st["s"]
    user = _user(s, x.user, x.pincode)
    view = (x.text or "provenance").strip().lower()
    try:
        if view == "provenance":
            data = {"view": "provenance", "rows": s.provenance(user)}
        elif view == "contradictions":
            data = {"view": "contradictions", "rows": s.contradictions(user)}
        elif view == "why":
            data = {"view": "why", **s.why_approved(user)}
        elif view == "rollback":
            data = {"view": "rollback", **s.quarantine_cause(user)}
        elif view == "retract":
            data = {"view": "retract", **s.retract_source(user, "document")}
        else:
            return JSONResponse({"error": f"unknown view {view!r}"}, status_code=400)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"governance call failed: {e}"}, status_code=502)
    return {"governance": data, **_state(st, user)}


@app.post("/api/voice/stt")
async def stt(sid: str = "", file: UploadFile = File(...)):
    from voice import sarvam
    if not sarvam.available():
        return JSONResponse({"error": "no SARVAM_API_KEY set"}, status_code=400)
    data = await file.read()
    try:
        return {"transcript": sarvam.speech_to_text(data, filename=file.filename or "audio.wav")}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)


class TTSIn(BaseModel):
    text: str
    language_code: str = "hi-IN"


@app.post("/api/voice/tts")
def tts(x: TTSIn):
    from voice import sarvam
    if not sarvam.available():
        return JSONResponse({"error": "no SARVAM_API_KEY set"}, status_code=400)
    import base64
    try:
        wav = sarvam.text_to_speech(x.text, language_code=x.language_code)
        return {"audio_b64": base64.b64encode(wav).decode()}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)


# ---- findings / replay -------------------------------------------------------------
MODEL_ALIASES = {"target": "Qwen3-32B-FP8", "nemotron-nano": "Nemotron 3 Nano", "mock": "offline mock model"}
# every model is served under the alias "target", so a grid run names its model in its tag (g3-<model>-...)
MODEL_TAGS = {"qwen32": "Qwen3-32B", "qwen8": "Qwen3-8B", "nemotron": "Nemotron 3 Nano"}
KINDS = [("refagent-plain", "as written"), ("refagent-governed", "with Memory Checks"),
         ("poison", "poisoning suite"), ("leak", "leak rules"), ("calib", "false-alarm check (no planted bugs)"),
         ("full", "full sweep"), ("mem0", "real Mem0 library"), ("gpu-first", "first real-model run"),
         ("first-real", "first real-model run"), ("mock", "wiring check")]


def _describe(stem: str, m: dict) -> tuple[str, str, str]:
    """(model, agent/memory, kind) for a run, from its tag and metadata."""
    tag = re.search(r"g\d-([a-z0-9]+)-", stem)
    model = (MODEL_TAGS.get(tag.group(1)) if tag else None) \
        or MODEL_ALIASES.get(m.get("sahayak_model"), m.get("sahayak_model")) \
        or ("offline mock model" if "mock" in stem else "")
    if "refagent" in stem:
        backend = "reference agent over HTTP (not Sahayak)"
    elif m.get("backend") == "langgraph" or "langgraph" in stem:
        backend = "LangGraph store"
    elif m.get("backend") == "mem0" or "mem0" in stem:
        backend = "Mem0"
    else:
        backend = "Sahayak store"
    kind = next((v for k, v in KINDS if k in stem), "")
    if kind == "real Mem0 library" and backend == "Mem0":
        kind = ""
    return model, backend, kind


def _load(path: Path) -> list[dict]:
    """Like antigoat.runner.load, but tolerant: a run that is still writing can end in a half line."""
    import json
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _clean(x):
    """Browsers reject NaN in JSON (e.g. a rule with no scored guesses yet)."""
    import math
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    return x


def _meta(path: Path) -> dict:
    import json
    mp = path.with_suffix(".meta.json")
    try:
        return json.loads(mp.read_text(encoding="utf-8")) if mp.exists() else {}
    except ValueError:
        return {}


def _label(path: Path) -> str:
    """A human name for a run: model, memory backend, what kind of run, when, and whether it finished."""
    import time as _t
    m = _meta(path)
    stem = path.stem
    model, backend, kind = _describe(stem, m)
    when = _t.strftime("%d %b %H:%M", _t.localtime(m["started"])) if m.get("started") else stem[:13]
    parts = [p for p in (model, backend, kind) if p]
    status = "" if m.get("finished") else " (still running, or stopped early)"
    return ", ".join(parts) + f" ({when})" + status


def _runs() -> list[Path]:
    """Finished real-model runs first (published final-* on top), then unfinished ones, then mock demos."""
    files = [p for p in RESULTS.glob("*.jsonl") if p.stat().st_size > 0]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    # published runs in story order: the headline sweep, the real-library and false-alarm runs, then the
    # generality grid (another agent, another memory, another model family)
    story = ["final-full", "final-mem0", "final-calib", "final-g3-qwen32-refagent-plain",
             "final-g3-qwen32-refagent-governed", "final-g3-qwen32-langgraph-poison",
             "final-g3-qwen32-mem0-poison-on", "final-g3-qwen32-langgraph-leak", "final-g3-nemotron-ours-leak",
             "final-g3-nemotron-refagent-plain", "final-g3-nemotron-refagent-governed"]

    def rank(p: Path) -> tuple:
        if "mock" in p.stem:
            return (3, 0)
        if not _meta(p).get("finished"):
            return (2, 0)
        if p.stem.startswith("final-"):
            return (0, story.index(p.stem) if p.stem in story else len(story))
        return (1, 0)
    return sorted(files, key=rank)


@app.get("/api/runs")
def runs():
    files = _runs()
    return {"runs": [p.stem for p in files], "labels": {p.stem: _label(p) for p in files}}


@app.get("/api/findings")
def findings(run: str = ""):
    path = _run_path(run)
    if path is None:
        return JSONResponse({"error": "no runs found"}, status_code=404)
    records = _load(path)
    rows = scorecard(records) if records else []
    titles = {r: RULES[r].title for r in RULES}
    expect = {r: RULES[r].expect for r in RULES}
    m = _meta(path)
    meta = {k: m.get(k) for k in ("sahayak_model", "attacker_model", "backend", "seconds", "embed_model")}
    meta["sahayak_model"], meta["memory"], meta["kind"] = _describe(path.stem, m)
    meta["slots"] = (m.get("config") or {}).get("slots")
    meta["finished"] = bool(m.get("finished"))
    return _clean({"run": path.stem, "rows": rows, "titles": titles, "expect": expect, "meta": meta})


@app.get("/api/benchmarks")
def benchmarks():
    """Public-benchmark results (InjecAgent), one entry per model, from results/external/."""
    import json
    out = []
    order = ["qwen32", "qwen8", "nemotron"]
    files = sorted((RESULTS / "external").glob("injecagent-*.json"),
                   key=lambda f: (order.index(f.stem[11:]) if f.stem[11:] in order else len(order), f.stem))
    for p in files:
        tag = p.stem.split("injecagent-", 1)[1]
        if tag.startswith("mock"):
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        out.append({"benchmark": d.get("benchmark", "InjecAgent"), "model": MODEL_TAGS.get(tag, tag),
                    "arms": d.get("arms", {})})
    return _clean({"benchmarks": out})


@app.get("/api/replay")
def replay(run: str, rule: str, checks: str = "off", sessions: int = 0, only_b: bool = True):
    path = _run_path(run)
    if path is None:
        return JSONResponse({"error": "no runs found"}, status_code=404)
    out = []
    for r in _load(path):
        if r.get("attacker") == "fixed":
            continue  # show the goal-driven (or decision) attacker, not the fixed-list duplicate
        if r["rule"] == rule and r["checks"] == checks and int(r["sessions"]) == int(sessions):
            if only_b and r.get("coin") != 1:
                continue
            out.append({"slot": r["slot"], "coin": r["coin"], "guess": r["guess"],
                        "correct": r["correct"], "world": "B" if r["coin"] else "A",
                        "transcript": r.get("transcript", [])})
    out.sort(key=lambda d: (-d["correct"], d["slot"]))
    return {"rule": rule, "checks": checks, "sessions": sessions, "slots": out[:60]}


def _run_path(run: str):
    if run:
        p = RESULTS / f"{run}.jsonl"
        return p if p.exists() else None
    files = _runs()
    return files[0] if files else None


# ---- static pages (mounted last so /api/* wins) -----------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/report")
def report():
    return FileResponse(STATIC / "report.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
