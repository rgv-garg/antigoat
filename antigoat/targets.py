"""Targets: anything AntiGOAT can audit.

AntiGOAT does not need to see inside an agent. It needs the same handful of things a real user
can do - talk to it, tell it something, ask it to forget, come back later - plus, for the
poisoning rules, one risky decision to watch. That contract is all an agent has to offer:

  register(user, pincode)                identify a user (a no-op is fine)
  say(user, message)                     the user tells the agent something it may remember
  chat(user, message, agent=..., remember=True) -> str      one turn, returns the reply
  forget(user, value)                    erasure of an exact value  } sent as plain conversation
  forget_request(user, text)             erasure by topic           } unless the agent has an API
  end_session(user)                      a visit ends (where summaries/consolidation happen)
  upload(user, text)                     submit a document                  [capability "upload"]
  apply(user, has_address_proof)         a risky decision -> {"approved"}   [capability "decide"]
  admin_policy(text, signed=True)        a trusted operator write           [capability "admin"]
  fork() -> target                       an isolated copy per audited user (black boxes: itself)
  probe endpoint (optional)              answer WITHOUT remembering (an API's "store: false")

Isolation of the audit itself: in-process targets are forked per audited user, so an attack
leaves no trace. A black box that offers a no-memory "probe" endpoint gets the same isolation.
Without one, the attacker's own messages are remembered by the agent; that can only HIDE a leak
(they crowd the secret out of retrieval), never fake one - a leak still needs the real secret in
a reply - so LEAK verdicts stay sound and PASS verdicts are reported as conservative.

Three ways to provide it:
  * Sahayak (in-process)       - our reference agent; implements every capability.
  * HTTPTarget(spec)           - ANY deployed agent behind HTTP, described by a small JSON file:
                                 which URL to call for a chat turn and where the reply is. No code.
  * FunctionTarget(chat=fn)    - ANY Python agent: pass its chat function (and optional hooks).

Rules that need a capability the target lacks are skipped and reported, never faked: a chat-only
agent gets the isolation / deletion / entangled audit; add a decision endpoint to unlock the
poisoning family.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable

# what each rule needs beyond plain conversation
RULE_NEEDS: dict[str, set[str]] = {
    "isolation": set(), "deletion": set(), "entangled": set(),
    "poisoning": {"upload", "decide"}, "inject_chat": {"decide"}, "inject_consolidate": {"decide"},
    "inject_authority": {"upload", "decide"}, "inject_overwrite": {"decide"},
    "inject_sleeper": {"decide"}, "inject_crossuser": {"upload", "decide"},
    "inject_adaptive": {"decide"}, "authority": {"admin", "decide"},
}
ALL_CAPABILITIES = {"chat", "upload", "decide", "admin", "end_session", "probe"}


def capabilities_of(target) -> set[str]:
    """Sahayak (and anything without a declaration) offers everything."""
    return set(getattr(target, "capabilities", ALL_CAPABILITIES))


def supported_rules(target, rules: list[str]) -> tuple[list[str], dict[str, set[str]]]:
    """Split rules into (runnable, {skipped rule: missing capabilities})."""
    have = capabilities_of(target)
    ok, skipped = [], {}
    for r in rules:
        missing = RULE_NEEDS.get(r, set()) - have
        if missing:
            skipped[r] = missing
        else:
            ok.append(r)
    return ok, skipped


class CapabilityMissing(RuntimeError):
    pass


# ----------------------------------------------------------------------------- shared behaviour
class _BlackBox:
    """Defaults for targets AntiGOAT can only talk to: erasure is asked for in conversation,
    a 'say' is just a turn, there is no isolated fork (each audited user has its own id)."""

    name = "agent"
    label = "as-deployed"
    capabilities: set[str] = {"chat"}
    forget_template = "Please forget {value} and delete it from your memory."

    def say(self, user: str, message: str) -> None:
        self.chat(user, message)

    def forget(self, user: str, value: str) -> int:
        self.chat(user, self.forget_template.format(value=value))
        return 1

    def forget_request(self, user: str, text: str) -> dict:
        self.chat(user, text)
        return {}

    def fork(self):
        return self

    def _need(self, cap: str) -> None:
        if cap not in self.capabilities:
            raise CapabilityMissing(f"{self.name} has no '{cap}' capability")

    def describe(self) -> dict:
        return {"name": self.name, "label": self.label, "kind": type(self).__name__,
                "capabilities": sorted(self.capabilities)}


# ----------------------------------------------------------------------------- any Python agent
class FunctionTarget(_BlackBox):
    """Wrap any Python agent. Only `chat(user, message) -> reply` is required."""

    def __init__(self, chat: Callable[[str, str], str], *, name: str = "python-agent",
                 label: str = "as-deployed", register: Callable | None = None,
                 end_session: Callable | None = None, upload: Callable | None = None,
                 decide: Callable | None = None, admin: Callable | None = None,
                 forget: Callable | None = None, forget_template: str | None = None,
                 probe: Callable | None = None):
        self._chat, self._register, self._end, self._probe = chat, register, end_session, probe
        self._upload, self._decide, self._admin, self._forget = upload, decide, admin, forget
        self.name, self.label = name, label
        if forget_template:
            self.forget_template = forget_template
        self.capabilities = {"chat"} | {c for c, f in (("end_session", end_session), ("upload", upload),
                                                       ("decide", decide), ("admin", admin),
                                                       ("probe", probe)) if f}

    def register(self, user: str, pincode: str = "") -> None:
        if self._register:
            self._register(user, pincode)

    def chat(self, user: str, message: str, agent: str = "default", remember: bool = True,
             respond: bool = True, history: bool = False) -> str:
        fn = self._probe if (not remember and self._probe) else self._chat
        return str(fn(user, message) or "")

    def forget(self, user: str, value: str) -> int:
        if self._forget:
            return int(self._forget(user, value) or 0)
        return super().forget(user, value)

    def end_session(self, user: str) -> None:
        if self._end:
            self._end(user)

    def upload(self, user: str, text: str) -> None:
        self._need("upload")
        self._upload(user, text)

    def apply(self, user: str, has_address_proof: bool = False) -> dict:
        self._need("decide")
        return {"approved": bool(self._decide(user))}

    def admin_policy(self, text: str, signed: bool = True) -> None:
        self._need("admin")
        self._admin(text)


# ----------------------------------------------------------------------------- any HTTP agent
def _fill(template: Any, values: dict) -> Any:
    """Put request values into a JSON body template. A string that is exactly '{name}' becomes
    the raw value (keeps booleans and numbers); '{name}' inside a longer string is substituted."""
    if isinstance(template, dict):
        return {k: _fill(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, values) for v in template]
    if isinstance(template, str):
        for k, v in values.items():
            if template == "{" + k + "}":
                return v
        for k, v in values.items():
            template = template.replace("{" + k + "}", str(v))
    return template


def _dig(obj: Any, path: str) -> Any:
    """Read 'a.b.0.c' out of a JSON reply."""
    for part in path.split(".") if path else []:
        if isinstance(obj, list):
            obj = obj[int(part)]
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


class HTTPTarget(_BlackBox):
    """Any agent behind HTTP. Described by a JSON spec, e.g. targets/sahayak_http.json:

      {"name": "my-agent", "base_url": "http://127.0.0.1:8200",
       "endpoints": {"chat":        {"path": "/chat", "body": {"user": "{user}", "message": "{message}"},
                                     "reply": "reply"},
                     "end_session": {"path": "/end", "body": {"user": "{user}"}},
                     "decide":      {"path": "/apply", "body": {"user": "{user}"}, "approved": "approved"}}}

    Placeholders: {user} {message} {channel} {text} {pincode} {proof}. Only "chat" is required;
    every other endpoint present switches on its capability. An OpenAI-style chat agent works too:
    point "chat" at /v1/chat/completions with reply "choices.0.message.content".
    """

    def __init__(self, spec: dict):
        self.spec = spec
        self.name = spec.get("name", "http-agent")
        self.label = spec.get("label", "as-deployed")
        self.base = spec["base_url"].rstrip("/")
        self.eps: dict = spec["endpoints"]
        if "chat" not in self.eps:
            raise ValueError("an HTTP target needs at least a 'chat' endpoint")
        self.timeout = float(spec.get("timeout", 120))
        self.headers = spec.get("headers", {})
        self.forget_template = spec.get("forget_template", self.forget_template)
        self.capabilities = {"chat"} | (set(self.eps) & ALL_CAPABILITIES)
        self._local = threading.local()

    @classmethod
    def from_file(cls, path: str | Path) -> "HTTPTarget":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def _session(self):
        import requests
        if not hasattr(self._local, "s"):
            self._local.s = requests.Session()
        return self._local.s

    def _call(self, ep: str, **values) -> Any:
        e = self.eps[ep]
        sess = self._session()
        import requests
        kw = {"timeout": self.timeout} if isinstance(sess, requests.Session) else {}
        r = sess.request(e.get("method", "POST"), self.base + e["path"],
                         json=_fill(e.get("body", {}), values), headers=self.headers, **kw)
        r.raise_for_status()
        return r.json() if r.content else {}

    def register(self, user: str, pincode: str = "") -> None:
        if "register" in self.eps:
            self._call("register", user=user, pincode=pincode)

    def chat(self, user: str, message: str, agent: str = "default", remember: bool = True,
             respond: bool = True, history: bool = False) -> str:
        # an audit probe goes to the agent's no-memory endpoint when it has one, so the attack
        # leaves no trace that could crowd the secret out of later retrieval
        ep = "probe" if (not remember and "probe" in self.eps) else "chat"
        out = self._call(ep, user=user, message=message, channel=agent)
        reply = _dig(out, self.eps[ep].get("reply", "reply"))
        return "" if reply is None else str(reply)

    def end_session(self, user: str) -> None:
        if "end_session" in self.eps:
            self._call("end_session", user=user)

    def upload(self, user: str, text: str) -> None:
        self._need("upload")
        self._call("upload", user=user, text=text)

    def apply(self, user: str, has_address_proof: bool = False) -> dict:
        self._need("decide")
        out = self._call("decide", user=user, proof=has_address_proof)
        return {"approved": bool(_dig(out, self.eps["decide"].get("approved", "approved")))}

    def admin_policy(self, text: str, signed: bool = True) -> None:
        self._need("admin")
        self._call("admin", text=text)

    def reset(self) -> None:
        """Start from an empty memory, if the agent offers it (so runs don't mix)."""
        if "reset" in self.eps:
            self._call("reset")


def load_target(spec: str | Path | dict):
    """A target from a JSON spec (path or dict). Kinds: 'http' (default)."""
    if isinstance(spec, (str, Path)):
        spec = json.loads(Path(spec).read_text(encoding="utf-8"))
    kind = spec.get("kind", "http")
    if kind == "http":
        return HTTPTarget(spec)
    raise ValueError(f"unknown target kind {kind!r}")
