"""AntiGOAT web app: a real chat UI for Sahayak + a findings/replay view.

  uvicorn web.app:app --host 0.0.0.0 --port 8100     (add port 8100 on Brev to share)

Two pages, both static (served from web/static), talking to the small JSON API below:
  /            Talk to Sahayak - chat + voice, a Memory Checks switch, a live memory panel,
               and natural-language "please forget ..." that actually erases.
  /report      AntiGOAT findings from the overnight runs; click a leak to replay the exact
               conversation where Sahayak gave the secret away.

The chat path here is demo-only sugar (e.g. spoken forget-requests). The experiment code in
antigoat/ is untouched, so the numbers on /report come from the real runs, not this server.
"""
from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from antigoat.runner import load
from antigoat.stats import scorecard
from antigoat.worlds import RULES
from sahayak.agents import Sahayak

STATIC = Path(__file__).parent / "static"
RESULTS = Path("results")
app = FastAPI(title="AntiGOAT")

# ---- live chat sessions ------------------------------------------------------------
_sessions: dict[str, Sahayak] = {}
_lock = threading.Lock()

# "please forget ..." in English / Hindi / Hinglish. Demo-only; experiments don't use this.
_FORGET_RE = re.compile(
    r"\b(forget|delete|erase|remove|bhool\s*ja|bhula\s*do|hata\s*do|mita\s*do|nikal\s*do)\b", re.I)
_CODE_RE = re.compile(r"\b[a-z]+-\d{3,4}\b|\b\d{4,}\b", re.I)


def _get(sid: str) -> Sahayak:
    with _lock:
        return _sessions.get(sid)


class NewSession(BaseModel):
    checks: str = "off"
    user_id: str = "ramesh"
    pincode: str = "560012"


class ChatIn(BaseModel):
    sid: str
    message: str
    agent: str = "intake"


class ActionIn(BaseModel):
    sid: str
    text: str = ""
    has_address_proof: bool = False


def _mem_snapshot(s: Sahayak, user: str) -> list[dict]:
    out = []
    for it in s.store.visible(user):
        out.append({"id": it.id, "owner": it.owner, "type": it.btype, "source": it.source,
                    "status": it.status, "trust": getattr(it, "trust", 2), "text": it.text})
    return out


def _checks_feed(s: Sahayak, n: int = 6) -> list[dict]:
    """The last few routing decisions, so the UI can show what the defence did."""
    return [d for d in s.checks.log[-n:]]


# ---- API ---------------------------------------------------------------------------
@app.post("/api/session")
def new_session(x: NewSession):
    sid = uuid.uuid4().hex[:8]
    s = Sahayak(checks_mode=x.checks)
    s.register(x.user_id, x.pincode)
    with _lock:
        _sessions[sid] = s
    return {"sid": sid, "checks": s.checks.label, "user_id": x.user_id, "pincode": x.pincode,
            "memory": _mem_snapshot(s, x.user_id)}


@app.post("/api/chat")
def chat(x: ChatIn):
    s = _get(x.sid)
    if s is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = next(iter(s.profiles), "ramesh")
    # Natural-language erasure: a citizen who can't read just SAYS "forget my number".
    if _FORGET_RE.search(x.message):
        codes = _CODE_RE.findall(x.message)
        removed, needles = 0, []
        if codes:
            for c in codes:
                removed += s.forget(user, c); needles.append(c)
        else:
            # no explicit value: erase this citizen's remembered personal facts
            facts = [it.text for it in s.store.visible(user) if it.btype == "personal_fact"]
            for f in facts:
                removed += s.forget(user, f); needles.append(f[:40])
        rec = s.store.last_receipt()
        reply = (f"Done - I have erased {removed} saved detail(s) and they will not come back. "
                 f"(DPDP right to erasure)") if removed else \
                "I could not find a saved detail matching that to erase."
        return {"reply": reply, "memory": _mem_snapshot(s, user), "checks": _checks_feed(s),
                "event": {"kind": "forget", "removed": removed, "needles": needles,
                          "receipt": rec}}
    reply = s.chat(user, x.message, x.agent)
    return {"reply": reply, "memory": _mem_snapshot(s, user), "checks": _checks_feed(s)}


@app.post("/api/upload")
def upload(x: ActionIn):
    s = _get(x.sid)
    if s is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = next(iter(s.profiles), "ramesh")
    s.upload(user, x.text)
    return {"ok": True, "memory": _mem_snapshot(s, user), "checks": _checks_feed(s)}


@app.post("/api/policy")
def policy(x: ActionIn):
    s = _get(x.sid)
    if s is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = next(iter(s.profiles), "ramesh")
    s.admin_policy(x.text, signed=True)
    return {"ok": True, "memory": _mem_snapshot(s, user), "checks": _checks_feed(s)}


@app.post("/api/apply")
def apply(x: ActionIn):
    s = _get(x.sid)
    if s is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = next(iter(s.profiles), "ramesh")
    d = s.apply(user, has_address_proof=x.has_address_proof)
    return {"decision": d, "memory": _mem_snapshot(s, user), "checks": _checks_feed(s)}


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
@app.get("/api/runs")
def runs():
    files = sorted(RESULTS.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {"runs": [p.stem for p in files]}


@app.get("/api/findings")
def findings(run: str = ""):
    path = _run_path(run)
    if path is None:
        return JSONResponse({"error": "no runs found"}, status_code=404)
    records = load(path)
    rows = scorecard(records)
    titles = {r: RULES[r].title for r in RULES}
    expect = {r: RULES[r].expect for r in RULES}
    return {"run": path.stem, "rows": rows, "titles": titles, "expect": expect}


@app.get("/api/replay")
def replay(run: str, rule: str, checks: str = "off", sessions: int = 0, only_b: bool = True):
    path = _run_path(run)
    if path is None:
        return JSONResponse({"error": "no runs found"}, status_code=404)
    out = []
    for r in load(path):
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
    files = sorted(RESULTS.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


# ---- static pages (mounted last so /api/* wins) -----------------------------------
@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/report")
def report():
    return FileResponse(STATIC / "report.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
