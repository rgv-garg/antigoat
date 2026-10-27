"""Expose Sahayak over HTTP, so AntiGOAT (or anyone) can test it as a true black box.

  SAHAYAK_CHECKS=off SAHAYAK_BACKEND=ours uvicorn serve_sahayak:app --host 0.0.0.0 --port 8300

Endpoints (what targets/sahayak_http.json maps):
  POST /chat          {user, message, channel, remember}  -> {reply}   erasure requests are handled in
                      conversation; remember=false answers without storing (an audit probe)
  POST /end           {user}                    end the visit (memory is summarised)
  POST /register      {user, pincode}
  POST /upload        {user, text}              submit a document
  POST /apply         {user, proof}             -> {approved, reason}   the risky decision
  POST /admin_policy  {text}                    a signed operator policy
  POST /reset                                   empty memory (a fresh deployment)
  POST /v1/chat/completions                     OpenAI-compatible, for external red-team tools

SAHAYAK_CHECKS: off | v2 | on | paranoid.  SAHAYAK_BACKEND: ours | mem0 | langgraph.
"""
from __future__ import annotations

import os
import threading
import time

from fastapi import FastAPI
from pydantic import BaseModel

from sahayak.agents import Sahayak

app = FastAPI(title="Sahayak (AntiGOAT reference agent)")
_lock = threading.Lock()


def _fresh() -> Sahayak:
    return Sahayak(checks_mode=os.environ.get("SAHAYAK_CHECKS", "off"),
                   backend=os.environ.get("SAHAYAK_BACKEND", "ours"))


S = _fresh()


class ChatIn(BaseModel):
    user: str
    message: str
    channel: str = "intake"
    remember: bool = True   # false = answer without storing anything (like an API's store:false)


class UserIn(BaseModel):
    user: str
    pincode: str = "560012"


class TextIn(BaseModel):
    user: str = "admin"
    text: str


class ApplyIn(BaseModel):
    user: str
    proof: bool = False


def _known(user: str, pincode: str = "560012") -> None:
    if user not in S.profiles:
        S.register(user, pincode)


@app.post("/chat")
def chat(x: ChatIn):
    _known(x.user)
    agent = x.channel if x.channel in {"intake", "grievance"} else "intake"
    if not x.remember:  # a probe: answered from memory, leaves no trace in it
        return {"reply": S.chat(x.user, x.message, agent, remember=False)}
    return {"reply": S.converse(x.user, x.message, agent)}


@app.post("/end")
def end(x: UserIn):
    _known(x.user)
    S.end_session(x.user)
    return {"ok": True}


@app.post("/register")
def register(x: UserIn):
    S.register(x.user, x.pincode)
    return {"ok": True}


@app.post("/upload")
def upload(x: TextIn):
    _known(x.user)
    S.upload(x.user, x.text)
    return {"ok": True}


@app.post("/apply")
def apply(x: ApplyIn):
    _known(x.user)
    return S.apply(x.user, x.proof)


@app.post("/admin_policy")
def admin_policy(x: TextIn):
    S.admin_policy(x.text, signed=True)
    return {"ok": True}


@app.post("/reset")
def reset():
    global S
    with _lock:
        S = _fresh()
    return {"ok": True, "checks": S.checks.label, "backend": S.backend}


@app.post("/v1/chat/completions")
def openai_compat(body: dict):
    msgs = body.get("messages", [])
    text = next((m["content"] for m in reversed(msgs) if m.get("role") == "user"), "")
    user = body.get("user", "redteam-user")
    _known(user)
    reply = S.converse(user, text)
    return {"id": "sahayak", "object": "chat.completion", "created": int(time.time()),
            "model": "sahayak", "choices": [{"index": 0, "finish_reason": "stop",
                                             "message": {"role": "assistant", "content": reply}}]}
