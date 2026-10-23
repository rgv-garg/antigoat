"""Expose Sahayak over HTTP, so it can be tested as a true black box.

  uvicorn serve_sahayak:app --host 0.0.0.0 --port 8100

Endpoints
  POST /v1/chat/completions   OpenAI-compatible: lets external red-team tools such as
                              NVIDIA garak (the fixed-list baseline) attack Sahayak.
                              The `user` field picks the citizen account.
  POST /chat /upload /forget /apply /admin_policy   the full Sahayak interface

Set SAHAYAK_CHECKS=off|on|paranoid before starting.
"""
from __future__ import annotations

import os
import time

from fastapi import FastAPI
from pydantic import BaseModel

from sahayak.agents import Sahayak

app = FastAPI(title="Sahayak (AntiGOAT testbed)")
S = Sahayak(checks_mode=os.environ.get("SAHAYAK_CHECKS", "off"))


class ChatIn(BaseModel):
    user_id: str
    message: str
    agent: str = "intake"


class TextIn(BaseModel):
    user_id: str = "admin"
    text: str


class ApplyIn(BaseModel):
    user_id: str
    has_address_proof: bool = False


@app.post("/chat")
def chat(x: ChatIn):
    return {"reply": S.chat(x.user_id, x.message, x.agent)}


@app.post("/upload")
def upload(x: TextIn):
    S.upload(x.user_id, x.text)
    return {"ok": True}


@app.post("/forget")
def forget(x: TextIn):
    return {"removed": S.forget(x.user_id, x.text)}


@app.post("/apply")
def apply(x: ApplyIn):
    return S.apply(x.user_id, x.has_address_proof)


@app.post("/admin_policy")
def admin_policy(x: TextIn):
    S.admin_policy(x.text, signed=True)
    return {"ok": True}


@app.post("/v1/chat/completions")
def openai_compat(body: dict):
    msgs = body.get("messages", [])
    text = next((m["content"] for m in reversed(msgs) if m.get("role") == "user"), "")
    reply = S.chat(body.get("user", "garak-user"), text)
    return {"id": "sahayak", "object": "chat.completion", "created": int(time.time()),
            "model": "sahayak", "choices": [{"index": 0, "finish_reason": "stop",
                                             "message": {"role": "assistant", "content": reply}}]}
