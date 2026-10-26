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
from sahayak.agents import Sahayak
from sahayak.erasure import pattern

STATIC = Path(__file__).parent / "static"
RESULTS = Path(os.environ.get("RESULTS_DIR", "results"))
app = FastAPI(title="AntiGOAT")

# ---- live sessions -----------------------------------------------------------------
_sessions: dict[str, dict] = {}   # sid -> {"s": Sahayak, "tracked": {user: {...}}, "t": last use}
_lock = threading.Lock()
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "60"))

# "please forget ..." in English / Hindi / Hinglish. Hinglish is spelled many ways
# (bhool/bhul, jao/jaiye), so match the stem + an imperative ending, not one exact spelling.
# A plain "main bhool gaya" (I forgot) is NOT an erasure request.
_FORGET_RE = re.compile(
    r"\b(forget|delete|erase|remove|wipe)\b"
    r"|\bbh(?:oo|u)l\s*ja(?:o|ao|iye|iyega|na|)\b"
    r"|\bbh(?:oo|u)la\s*(?:do|dijiye|dijiyega|de|dena)\b"
    r"|\b(?:mita|mitaa|hata|hataa|nikal|nikaal)\s*(?:do|dijiye|dijiyega|de|dena)\b"
    r"|भूल\s*जा|भुला\s*द|मिटा\s*द|हटा\s*द|निकाल\s*द", re.I)


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
@app.get("/api/info")
def info():
    mock = SETTINGS.sahayak.base_url == "mock"
    from voice import sarvam
    return {"model": "offline mock" if mock else SETTINGS.sahayak.model, "mock": mock,
            "attacker_model": "offline mock" if SETTINGS.attacker.base_url == "mock" else SETTINGS.attacker.model,
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
    return {"sid": sid, "checks": s.checks.label, "backend": backend, "user_id": x.user_id,
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
        if _FORGET_RE.search(x.message):
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
def _runs() -> list[Path]:
    """Published real runs (final-*) first, then real runs, then offline mock demos; newest first."""
    files = sorted(RESULTS.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    rank = lambda p: 0 if p.stem.startswith("final-") else (2 if "mock" in p.stem else 1)  # noqa: E731
    return sorted(files, key=rank)


@app.get("/api/runs")
def runs():
    return {"runs": [p.stem for p in _runs() if p.stat().st_size > 0]}


@app.get("/api/findings")
def findings(run: str = ""):
    path = _run_path(run)
    if path is None:
        return JSONResponse({"error": "no runs found"}, status_code=404)
    records = load(path)
    rows = scorecard(records)
    titles = {r: RULES[r].title for r in RULES}
    expect = {r: RULES[r].expect for r in RULES}
    meta_p = path.with_suffix(".meta.json")
    meta = {}
    if meta_p.exists():
        import json
        m = json.loads(meta_p.read_text(encoding="utf-8"))
        meta = {k: m.get(k) for k in ("sahayak_model", "attacker_model", "backend", "seconds", "embed_model")}
        meta["slots"] = (m.get("config") or {}).get("slots")
    return {"run": path.stem, "rows": rows, "titles": titles, "expect": expect, "meta": meta}


@app.get("/api/replay")
def replay(run: str, rule: str, checks: str = "off", sessions: int = 0, only_b: bool = True):
    path = _run_path(run)
    if path is None:
        return JSONResponse({"error": "no runs found"}, status_code=404)
    out = []
    for r in load(path):
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
    files = [p for p in _runs() if p.stat().st_size > 0]
    return files[0] if files else None


# ---- static pages (mounted last so /api/* wins) -----------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/report")
def report():
    return FileResponse(STATIC / "report.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
