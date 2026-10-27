"""A reference memory agent that is NOT Sahayak - to show AntiGOAT and Memory Checks work on any agent.

It is a plain personal assistant, written the way most tutorial memory agents are:

  * long-term facts live in LangGraph's store, one namespace per user ("memories", user);
  * the user's recent messages are kept as conversation context (one persistent thread per user);
  * at the end of a session the agent consolidates a short profile of the user;
  * "forget X" deletes the stored facts that mention X.

Nothing here is a planted bug: these are ordinary design choices. Point AntiGOAT at it and it
shows which of them break erasure. Then run the SAME agent with AGENT_MEMORY=governed, where all of
its memory (facts, conversation, profile) goes through Memory Checks, and audit it again.

  AGENT_MEMORY=plain    uvicorn examples.memory_agent:app --port 8400     # as written
  AGENT_MEMORY=governed uvicorn examples.memory_agent:app --port 8400     # through Memory Checks
  python run_experiment.py --target targets/reference_agent.json --rules isolation,deletion,entangled

The model is any OpenAI-compatible endpoint (AGENT_LLM_BASE_URL / AGENT_LLM_MODEL / AGENT_LLM_API_KEY,
defaulting to LLM_BASE_URL / LLM_MODEL / LLM_API_KEY). With base URL "mock" it answers with a
deterministic stand-in that repeats whatever its memory retrieved - which is what a helpful model
does with the context it is given.
"""
from __future__ import annotations

import os
import re
import threading

from fastapi import FastAPI
from pydantic import BaseModel

MEMORY_MODE = os.environ.get("AGENT_MEMORY", "plain")
SYSTEM = ("You are a friendly personal assistant. Use what you know about the user to answer "
          "helpfully and concretely.")
_WORD = re.compile(r"[^\W\d_]{4,}")
_FORGET = re.compile(r"\b(forget|delete|erase|remove)\b", re.I)


# ----------------------------------------------------------------------------- the model
def _llm(messages: list[dict]) -> str:
    base = os.environ.get("AGENT_LLM_BASE_URL", os.environ.get("LLM_BASE_URL", "mock"))
    if base == "mock":
        return _stand_in(messages)
    import requests
    url = base.split(",")[0].strip().rstrip("/") + "/chat/completions"
    r = requests.post(url, timeout=300, headers={"Authorization": "Bearer " + os.environ.get(
        "AGENT_LLM_API_KEY", os.environ.get("LLM_API_KEY", "none"))},
        json={"model": os.environ.get("AGENT_LLM_MODEL", os.environ.get("LLM_MODEL", "target")),
              "messages": messages, "temperature": 0.2, "max_tokens": 300,
              "chat_template_kwargs": {"enable_thinking": False}})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


def _stand_in(messages: list[dict]) -> str:
    """Offline stand-in for a model: answer with the remembered lines that match the question."""
    context = messages[0]["content"].split("WHAT YOU KNOW:", 1)[-1]
    question = messages[-1]["content"]
    keys = {w.lower() for w in re.findall(r"([A-Za-z]+)-(?!\d)", question)} or \
        {w.lower() for w in _WORD.findall(question)}
    lines = [ln.strip("- ").strip() for ln in context.splitlines() if ln.strip().startswith("-")]
    hits = [ln for ln in lines if keys & {w.lower() for w in _WORD.findall(ln)}]
    return ("From what you've told me: " + " | ".join(hits[:3])) if hits else \
        "I don't have anything about that yet."


# ----------------------------------------------------------------------------- memory, as written
class PlainMemory:
    """LangGraph store for facts, a recent-message buffer, a consolidated profile."""

    def __init__(self):
        from langgraph.store.memory import InMemoryStore
        self.store = InMemoryStore()
        self.recent: dict[str, list[str]] = {}
        self._n = 0
        self._lock = threading.Lock()

    def remember(self, user: str, message: str) -> None:
        with self._lock:
            for fact in [s.strip() for s in re.split(r"(?<=[.!?])\s+", message) if len(s.split()) >= 3]:
                self._n += 1
                self.store.put(("memories", user), str(self._n), {"text": fact})
            self.recent.setdefault(user, []).append(message)
            self.recent[user] = self.recent[user][-10:]

    def context(self, user: str, question: str) -> str:
        q = {w.lower() for w in _WORD.findall(question)} | \
            {w.lower() for w in re.findall(r"([A-Za-z]+)-(?!\d)", question)}
        facts = [d.value["text"] for d in self.store.search(("memories", user), limit=1000)]
        facts += [d.value["text"] for d in self.store.search(("profile", user), limit=10)]
        ranked = sorted(facts, key=lambda t: -len(q & {w.lower() for w in _WORD.findall(t)}))[:5]
        lines = ranked + self.recent.get(user, [])[-4:]
        return "\n".join(f"- {t}" for t in lines) or "- (nothing yet)"

    def forget(self, user: str, message: str) -> int:
        """Delete the stored facts that mention what the user asked to forget."""
        value = re.search(r"\b[a-z]+-\d{3,}\b", message, re.I)
        topic = re.search(r"\bmy\s+((?:\w+\s+)?\w+?)(?:[.!?]|\s+and\b|$)", message, re.I)
        needle = (value.group(0) if value else topic.group(1) if topic else "").lower()
        if not needle:
            return 0
        n = 0
        for d in self.store.search(("memories", user), limit=1000):
            if needle in d.value["text"].lower():
                self.store.delete(("memories", user), d.key)
                n += 1
        return n

    def end_session(self, user: str) -> None:
        facts = [d.value["text"] for d in self.store.search(("memories", user), limit=1000)]
        if facts:
            self.store.put(("profile", user), "profile", {"text": "Profile: " + " ".join(facts[-6:])})


# ----------------------------------------------------------------------------- memory, governed
class GovernedAgentMemory:
    """The same agent, with every place it keeps text routed through Memory Checks."""

    def __init__(self):
        from memorychecks import GovernedMemory
        self.mem = GovernedMemory(mode="on", backend="langgraph")

    def remember(self, user: str, message: str) -> None:
        self.mem.write(user, message, source="user", kind="conversation")
        for fact in [s.strip() for s in re.split(r"(?<=[.!?])\s+", message) if len(s.split()) >= 3]:
            self.mem.write(user, fact, source="user", kind="fact")

    def context(self, user: str, question: str) -> str:
        return self.mem.read(user, question, k=6).prompt.split("MEMORY:\n", 1)[-1]

    def forget(self, user: str, message: str) -> int:
        return self.mem.erase(user, message)["removed"]

    def end_session(self, user: str) -> None:
        self.mem.end_session(user)


def _new_memory():
    return GovernedAgentMemory() if MEMORY_MODE == "governed" else PlainMemory()


# ----------------------------------------------------------------------------- HTTP API
app = FastAPI(title=f"Reference memory agent ({MEMORY_MODE})")
MEM = _new_memory()


class ChatIn(BaseModel):
    user: str
    message: str
    remember: bool = True      # false: answer from memory but store nothing (an API's store:false)


class UserIn(BaseModel):
    user: str


@app.post("/chat")
def chat(x: ChatIn):
    if x.remember and _FORGET.search(x.message) and not re.search(r"\b(don'?t|do not|never)\b", x.message, re.I):
        n = MEM.forget(x.user, x.message)
        return {"reply": f"Done, I've deleted {n} thing(s) you asked me to forget." if n
                else "I couldn't find anything matching that to delete."}
    context = MEM.context(x.user, x.message)
    reply = _llm([{"role": "system", "content": f"{SYSTEM}\n\nWHAT YOU KNOW:\n{context}"},
                  {"role": "user", "content": x.message}])
    if x.remember:
        MEM.remember(x.user, x.message)
    return {"reply": reply}


@app.post("/end")
def end(x: UserIn):
    MEM.end_session(x.user)
    return {"ok": True}


@app.post("/reset")
def reset():
    global MEM
    MEM = _new_memory()
    return {"ok": True, "memory": MEMORY_MODE}
