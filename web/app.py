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
# Hinglish is spelled many ways (bhool/bhul, jao/jaiye/jaana), so match the stem + an imperative
# ending, not one exact spelling. A plain "main bhool gaya" (I forgot) is NOT an erasure request.
_FORGET_RE = re.compile(
    r"\b(forget|delete|erase|remove)\b"
    r"|\bbh(?:oo|u)l\s*ja(?:o|ao|iye|iyega|na|)\b"
    r"|\bbh(?:oo|u)la\s*(?:do|dijiye|dijiyega|de|dena)\b"
    r"|\b(?:mita|mitaa|hata|hataa|nikal|nikaal)\s*(?:do|dijiye|dijiyega|de|dena)\b"
    r"|भूल\s*जा|भुला\s*द|मिटा\s*द|हटा\s*द|निकाल\s*द", re.I)
_CODE_RE = re.compile(r"\b[a-z]+-\d{3,4}\b|\b\d{4,}\b", re.I)
# What a spoken forget-request is about ("forget my name" -> the name). Matched against the
# request AND against each stored memory, so only memories on that topic are erased.
_TOPICS = {
    "name": r"\bname\b|\bnaam\b|\bnam\b|नाम",
    "phone": r"phone|mobile|फ़ोन|फोन|मोबाइल",
    "address": r"address|pin\s?code|\bpata\b|पता",
    "code": r"\bcode\b|code\s?word|password|secret|कोड",
    "email": r"e-?mail|ईमेल",
    "aadhaar": r"aadhaa?r|\buid\b|आधार",
    "birth": r"birth|\bdob\b|janam|जन्म",
    "family": r"father|mother|wife|husband|\bson\b|daughter|family|\bpita\b|\bmata\b|papa|mummy|पिता|माता|पत्नी|पति",
}
_ALL_RE = re.compile(r"\b(everything|all|sab|sabhi|saara|sara)\b|सब", re.I)


def _get(sid: str) -> Sahayak:
    with _lock:
        return _sessions.get(sid)


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


def _forget_request(s: Sahayak, user: str, message: str) -> dict:
    """Spoken erasure. Exact values ("kesar-4135") are erased wherever they appear; a topic
    ("my name") erases only memories on that topic; "forget everything" erases all personal
    facts; a bare "forget it" erases what the citizen told us most recently. Each erased fact
    takes the raw chat turn it came from with it (that turn was what leaked before)."""
    hard = s.checks.feature("hard_delete")
    codes = _CODE_RE.findall(message)
    if codes:
        removed = sum(s.forget(user, c) for c in codes)
        return {"removed": removed, "erased": codes, "hard": hard}
    mine = [it for it in s.store.items.values() if it.owner == user and it.status != "deleted"
            and it.btype in {"personal_fact", "conversation"}]
    topics = [rx for rx in _TOPICS.values() if re.search(rx, message, re.I)]
    if topics:
        picks = [it for it in mine if any(re.search(rx, it.text, re.I) for rx in topics)]
    elif _ALL_RE.search(message):
        picks = [it for it in mine if it.btype == "personal_fact"]
    else:  # "forget it / that": the latest thing they told us
        facts = [it for it in mine if it.btype == "personal_fact"]
        last = max(facts, key=lambda it: it.created, default=None)
        picks = [it for it in facts if last and it.parents and it.parents == last.parents] or \
            ([last] if last else [])
    erased = s.forget_items(user, [it.id for it in picks], label=message[:60])
    shown = [it.text for it in erased if it.btype == "personal_fact"] or \
        [it.text.removeprefix("Citizen said: ") for it in erased]
    return {"removed": len(erased), "erased": [t[:70] for t in shown[:3]], "hard": hard}


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
    user = _user(s, x.user, x.pincode)
    agent = x.agent if x.agent in {"intake", "grievance"} else "intake"
    # Natural-language erasure: a citizen who can't read just SAYS "forget my number".
    if _FORGET_RE.search(x.message):
        ev = _forget_request(s, user, x.message)
        if ev["removed"]:
            what = "; ".join(f'"{t}"' for t in ev["erased"])
            reply = f"Done - I have erased {ev['removed']} saved detail(s): {what}. (DPDP right to erasure)"
        else:
            reply = "I could not find a saved detail matching that to erase."
        rec = s.store.last_receipt() if ev["hard"] and ev["removed"] else None
        return {"reply": reply, "memory": _mem_snapshot(s, user), "checks": _checks_feed(s),
                "event": {"kind": "forget", **ev, "receipt": rec}}
    reply = s.chat(user, x.message, agent)
    return {"reply": reply, "agent": agent, "memory": _mem_snapshot(s, user), "checks": _checks_feed(s)}


@app.post("/api/login")
def login(x: ActionIn):
    """Switch to another citizen on the SAME Sahayak (memory is kept). Returns what this
    citizen can see - with the shared_index bug live, that includes other citizens' data."""
    s = _get(x.sid)
    if s is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = _user(s, x.user, x.pincode)
    return {"ok": True, "user": user, "memory": _mem_snapshot(s, user), "checks": _checks_feed(s)}


@app.post("/api/end")
def end_visit(x: ActionIn):
    """The citizen's visit ends: Sahayak writes its summary of their history (where the
    soft_delete bug copies 'deleted' details back - the resurrection on /report)."""
    s = _get(x.sid)
    if s is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = _user(s, x.user, x.pincode)
    s.end_session(user)
    return {"ok": True, "memory": _mem_snapshot(s, user), "checks": _checks_feed(s)}


@app.post("/api/upload")
def upload(x: ActionIn):
    s = _get(x.sid)
    if s is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = _user(s, x.user, x.pincode)
    s.upload(user, x.text)
    return {"ok": True, "memory": _mem_snapshot(s, user), "checks": _checks_feed(s)}


@app.post("/api/policy")
def policy(x: ActionIn):
    s = _get(x.sid)
    if s is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = _user(s, x.user, x.pincode)
    s.admin_policy(x.text, signed=True)
    return {"ok": True, "memory": _mem_snapshot(s, user), "checks": _checks_feed(s)}


@app.post("/api/apply")
def apply(x: ActionIn):
    s = _get(x.sid)
    if s is None:
        return JSONResponse({"error": "no such session"}, status_code=404)
    user = _user(s, x.user, x.pincode)
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
