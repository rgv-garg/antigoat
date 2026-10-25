"""Mem0 backend: run Sahayak - and so AntiGOAT - on the REAL open-source Mem0 library.

Why: a judge will ask "you planted the bugs you catch - does AntiGOAT find anything in a
real system?". This adapter swaps our hand-rolled store for Mem0 OSS (pinned to the version
in requirements-mem0.txt) with NO planted bugs. Whatever AntiGOAT measures here is Mem0's
own behaviour.

  * Mem0 does its own LLM fact extraction (infer=True) - we do not pre-digest anything.
  * Mem0's LLM and embedder are bridged to OUR single client (llm.py / embed.py), so it
    runs on hosted NIM, Brev vLLM, or the offline mock with no extra keys.
  * Memory Checks can be layered ON TOP of Mem0 (checks_mode=on): authority routing on
    writes, the action gate on decisions, and erasure that also purges Mem0's raw-message
    buffer and history log.

Observation from reading mem0 v2.2.1 source (memory/main.py, memory/storage.py):
  Memory.delete() removes the vector and logs a DELETE row in `history` (old text kept),
  but the raw message stays in the `messages` table (last 10 per session scope), and that
  buffer is sent to the extraction LLM as "Last k Messages" on the next add(). The
  Deletion rule measures whether that ever brings a deleted fact back.

Limitation: Mem0 cannot be forked cheaply, so audits run on the live store (attacker chat
is never stored; attacker uploads are scrubbed of the canary).
"""
from __future__ import annotations

import os
import re
import tempfile
import threading
import uuid

from sahayak.checks import MemoryChecks
from sahayak.embed import embed
from sahayak.erasure import MASK, Tombstones, pattern, still_useful
from sahayak.memory import GLOBAL, Item

os.environ.setdefault("MEM0_TELEMETRY", "False")

_RULE_WORDS = re.compile(r"\b(rule|notice|policy|circular|no longer required|waived|exempt)\b", re.I)


# ----------------------------------------------------------------------------- bridges
class _LLMBridge:
    """Looks like a mem0 LLM; sends everything through llm.chat('sahayak', ...)."""

    def generate_response(self, messages, response_format=None, tools=None, tool_choice="auto", **kw):
        from config import SETTINGS
        from llm import chat

        if SETTINGS.sahayak.base_url == "mock":
            return _mock_extract(messages)
        sys_extra = "\nReturn ONLY a JSON object." if response_format else ""
        msgs = [dict(m) for m in messages]
        if msgs and msgs[0]["role"] == "system":
            msgs[0]["content"] += sys_extra
        return chat("sahayak", msgs, temperature=0, max_tokens=1024)


def _mock_extract(messages) -> str:
    import json
    user = messages[-1]["content"]
    new = user.split("## New Messages", 1)[-1].split("## Observation Date", 1)[0]
    parts = [x.strip(" -") for x in re.split(r"(?<=[.!?])\s+|\n|,\s+(?=(?:my|mera|meri)\b)", new) if x.strip(" -")]
    parts = [re.sub(r"^\W*(user|citizen)\W*:\s*", "", f, flags=re.I) for f in parts]
    # same rule as the Sahayak mock: numbers/codes, and statements of 5+ words (not questions)
    facts = [x for x in parts if re.search(r"\d|\bname\b|\bnaam\b|नाम", x, re.I)
             or (not x.endswith("?") and len(x.split()) >= 5 and not re.match(r"(?i)(please|kya|can|could|what|when|how|which|where)\b", x))]
    return json.dumps({"memory": [{"text": f} for f in facts if f]})


class _EmbedBridge:
    def embed(self, text, memory_action=None):
        return embed([text if isinstance(text, str) else str(text)])[0].tolist()

    def embed_batch(self, texts, memory_action=None):
        return [v.tolist() for v in embed([str(t) for t in texts])]


class _Locked:
    """Serialise calls into an object that is not thread-safe (local Qdrant client)."""

    def __init__(self, obj):
        self._obj, self._lock = obj, threading.RLock()

    def __getattr__(self, name):
        attr = getattr(self._obj, name)
        if not callable(attr):
            return attr

        def call(*a, **k):
            with self._lock:
                return attr(*a, **k)
        return call


# ----------------------------------------------------------------------------- store
class Mem0Store:
    """Implements the subset of MemoryStore that Sahayak uses."""

    is_mem0 = True

    def __init__(self, checks: MemoryChecks | None = None, bugs: dict | None = None):
        from mem0 import Memory

        self.checks = checks or MemoryChecks("off")
        self.bugs = {}  # nothing planted: we test Mem0 as shipped
        self._dir = tempfile.mkdtemp(prefix="antigoat-mem0-")
        dims = int(embed(["x"]).shape[1])
        self.m = Memory.from_config({
            "vector_store": {"provider": "qdrant", "config": {
                "collection_name": f"antigoat_{uuid.uuid4().hex[:8]}", "path": self._dir,
                "embedding_model_dims": dims, "on_disk": False}},
            "llm": {"provider": "openai", "config": {"api_key": "bridged", "model": "bridged"}},
            "embedder": {"provider": "openai", "config": {"api_key": "bridged", "embedding_dims": dims}},
            "history_db_path": os.path.join(self._dir, "history.db"),
        })
        self.m.llm = _LLMBridge()
        self.m.embedding_model = _EmbedBridge()
        self.m.vector_store = _Locked(self.m.vector_store)
        self._ids: dict[str, int] = {}
        self._rev: dict[int, str] = {}       # our int id -> mem0 id
        self._owner_of: dict[str, str] = {}  # mem0 id -> owner (history rows carry no user id)
        self.tomb = Tombstones()
        self.receipts: list[dict] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ helpers
    def fork(self) -> "Mem0Store":
        return self  # see module docstring

    def _iid(self, mid: str) -> int:
        with self._lock:
            iid = self._ids.setdefault(mid, len(self._ids) + 1)
            self._rev[iid] = mid
            return iid

    def _track(self, out, owner: str) -> None:
        for r in (out or {}).get("results", []) if isinstance(out, dict) else []:
            if r.get("id"):
                self._owner_of[r["id"]] = owner

    def _item(self, r: dict) -> Item:
        md = r.get("metadata") or {}
        owner = r.get("user_id") or md.get("owner", "")
        self._owner_of[r["id"]] = owner
        return Item(self._iid(r["id"]), owner, r.get("memory", ""),
                    md.get("source", "citizen"), md.get("btype", "personal_fact"), (),
                    md.get("status", "active"), 0, None, {"mem0_id": r["id"], **md})

    def _all(self, owner: str) -> list[dict]:
        return self.m.get_all(filters={"user_id": owner}, top_k=10000).get("results", [])

    # ------------------------------------------------------------------ write
    def ingest(self, owner: str, message: str, source: str = "citizen", btype: str = "personal_fact") -> None:
        """A conversation turn: Mem0 decides what to remember (its own LLM extraction)."""
        md = {"source": source, "btype": btype, "owner": owner}
        decision = self.checks.route(source, btype, None, message)
        if decision == "no":
            if self.checks.mode != "on":
                return
            md.update(btype="world_fact", status="probation")
        elif decision == "probation":
            md["status"] = "probation"
        if self.checks.feature("tombstone"):
            message = self.tomb.redact(owner, message)[0]
        self._track(self.m.add([{"role": "user", "content": message}], user_id=owner, metadata=md, infer=True), owner)

    def add(self, owner: str, text: str, source: str, btype: str, parents: tuple = (),
            meta: dict | None = None) -> None:
        """Verbatim write (no LLM) - used for admin policies and direct facts."""
        meta = dict(meta or {})
        decision = self.checks.route(source, btype, meta.get("signature"), text)
        if decision == "no":
            if btype in {"policy", "instruction"} and self.checks.mode == "on":
                btype, decision = "world_fact", "probation"
            else:
                return None
        md = {"source": source, "btype": btype, "owner": owner,
              "status": "active" if decision == "write" else "probation", **meta}
        if self.checks.feature("tombstone"):
            text = self.tomb.redact(owner, text)[0]
        self._track(self.m.add([{"role": "user", "content": text}], user_id=owner, metadata=md, infer=False), owner)

    def upload_document(self, owner: str, text: str) -> None:
        btype = "policy" if _RULE_WORDS.search(text) else "document"
        self.ingest(owner, f"[uploaded document] {text}", source="document", btype=btype)

    # ------------------------------------------------------------------ read
    def search(self, viewer: str, query: str, k: int = 5) -> list[Item]:
        out = []
        for owner in (viewer, GLOBAL):
            res = self.m.search(query, filters={"user_id": owner}, top_k=k).get("results", [])
            out += [(r.get("score", 0), self._item(r)) for r in res]
        out.sort(key=lambda t: -t[0])
        return [it for _, it in out[:k]]

    def visible(self, viewer: str) -> list[Item]:
        return [self._item(r) for o in (viewer, GLOBAL) for r in self._all(o)]

    def policies(self) -> list[Item]:
        pol = [self._item(r) for r in self._all(GLOBAL)]
        pol = [it for it in pol if it.btype == "policy"]
        return [it for it in pol if self.checks.usable_for_action(it)]

    # ------------------------------------------------------------------ delete
    def delete_matching(self, owner: str, needle: str) -> int:
        """Right to erasure using Mem0's own API (delete by id)."""
        if self.checks.feature("entity_erasure"):
            rep = self.erase_values(owner, [needle], label="exact value")
            return rep["memories_deleted"] + rep["memories_redacted"]
        n = 0
        for r in self._all(owner):
            if needle.lower() in r.get("memory", "").lower():
                self.m.delete(r["id"])
                n += 1
        if self.checks.feature("hard_delete"):
            # Memory Checks: erasure must also cover Mem0's derived stores.
            db = self.m.db
            with db._lock:
                db.connection.execute("DELETE FROM messages WHERE content LIKE ?", (f"%{needle}%",))
                db.connection.execute("UPDATE history SET old_memory = NULL WHERE old_memory LIKE ?", (f"%{needle}%",))
                db.connection.commit()
        return n

    def residue(self, needle: str) -> dict:
        """Data-at-rest check: where does a deleted string still live inside Mem0?
        (Both history columns: Mem0 keeps the text in the ADD row's new_memory AND in the
        DELETE row's old_memory, and returns both from its public history() call.)"""
        db = self.m.db
        like = f"%{needle}%"
        with db._lock:
            msgs = db.connection.execute("SELECT COUNT(*) FROM messages WHERE content LIKE ?", (like,)).fetchone()[0]
            hist = db.connection.execute("SELECT COUNT(*) FROM history WHERE old_memory LIKE ? OR new_memory LIKE ?",
                                         (like, like)).fetchone()[0]
        return {"messages_table": msgs, "history_table": hist}

    # ------------------------------------------------------------------ fact-level delete (by id)
    def delete_items(self, owner: str, ids, label: str = "") -> list[Item]:
        """What an app on Mem0 does for 'forget my name': delete the matching memories by id.
        (Mem0 has no 'source turn' to cascade to; its raw buffer is a separate table.)"""
        removed = []
        for iid in ids:
            mid = self._rev.get(iid)
            if not mid or self._owner_of.get(mid) != owner:
                continue
            got = self.m.get(mid)
            if got:
                removed.append(self._item(got))
                self.m.delete(mid)
        return removed

    def last_receipt(self) -> dict | None:
        return self.receipts[-1] if self.receipts else None

    # ------------------------------------------------------------------ Verified Erasure (v3)
    def _scope(self, owner: str) -> str:
        return f"user_id={owner}"

    def erase_values(self, owner: str, values, label: str = "") -> dict:
        """Erase each value from the owner's Mem0 memories AND Mem0's own tables: the
        raw-message buffer (re-fed to extraction on every add) and the history log."""
        rxs = [pattern(v) for v in values if v]
        rep = {"memories_deleted": 0, "memories_redacted": 0, "log_lines": 0, "mem0_rows": 0}
        if not rxs:
            return rep

        def red(t):
            n = 0
            for rx in rxs:
                t, k = rx.subn(MASK, t)
                n += k
            return t, n

        for r in self._all(owner):
            new, n = red(r.get("memory", ""))
            if not n:
                continue
            if still_useful(new):
                self.m.update(r["id"], new)
                rep["memories_redacted"] += 1
            else:
                self.m.delete(r["id"])
                rep["memories_deleted"] += 1
        db = self.m.db
        mine = {mid for mid, o in self._owner_of.items() if o == owner}
        with db._lock:
            for rid, content in db.connection.execute(
                    "SELECT id, content FROM messages WHERE session_scope = ?", (self._scope(owner),)).fetchall():
                new, n = red(content or "")
                if n:
                    db.connection.execute("UPDATE messages SET content = ? WHERE id = ?", (new, rid))
                    rep["mem0_rows"] += 1
            for rid, mid, old, newm in db.connection.execute(
                    "SELECT id, memory_id, old_memory, new_memory FROM history").fetchall():
                if mid not in mine:
                    continue
                o2, n1 = red(old or "")
                n2_, n2 = red(newm or "")
                if n1 or n2:
                    db.connection.execute("UPDATE history SET old_memory = ?, new_memory = ? WHERE id = ?",
                                          (o2 if old is not None else None, n2_ if newm is not None else None, rid))
                    rep["mem0_rows"] += 1
            db.connection.commit()
        for d in self.checks.log:
            t, n = red(d.get("text", ""))
            if n:
                d["text"] = t
                rep["log_lines"] += 1
        if self.checks.feature("tombstone"):
            for v in values:
                self.tomb.add(owner, v, label)
        rep["residue_after"] = self.scan(owner, values)
        import hashlib
        import time as _t
        from sahayak.checks import sign
        hashed = [hashlib.sha256(self.tomb.salt + str(v).lower().encode()).hexdigest()[:12] for v in values]
        body = f"ERASURE owner={owner} what={label!r} values={hashed} at={int(_t.time())}"
        rec = {"owner": owner, "what": label, "values_hashed": hashed,
               "purged": rep["memories_deleted"] + rep["memories_redacted"] + rep["mem0_rows"],
               "residue_after": rep["residue_after"], "at": int(_t.time()),
               "signature": sign(body), "chain_head": self.checks.append_chain(body)}
        self.receipts.append(rec)
        rep["receipt"] = rec
        return rep

    LOCATIONS = ("memories", "mem0 messages buffer", "mem0 history log", "other citizens' records", "routing log")

    def find(self, owner: str, values) -> list[tuple[str, str]]:
        """Memory X-ray on Mem0: every place a value still lives, incl. Mem0's own tables."""
        rxs = [pattern(v) for v in values if v]
        if not rxs:
            return []

        def hit(t) -> bool:
            return any(rx.search(t or "") for rx in rxs)

        out = [("memories", r.get("memory", "")) for r in self._all(owner) if hit(r.get("memory", ""))]
        db = self.m.db
        mine = {mid for mid, o in self._owner_of.items() if o == owner}
        with db._lock:
            rows = db.connection.execute("SELECT session_scope, content FROM messages ORDER BY created_at").fetchall()
            hist = db.connection.execute("SELECT memory_id, event, old_memory, new_memory FROM history ORDER BY created_at").fetchall()
        for sc, c in rows:
            if hit(c):
                out.append(("mem0 messages buffer" if sc == self._scope(owner) else "other citizens' records", c))
        for mid, ev, o, n in hist:
            if mid in mine and (hit(o) or hit(n)):
                out.append(("mem0 history log", f"[{ev}] " + (o if hit(o) else n)))
        out += [("routing log", d.get("text", "")) for d in self.checks.log if hit(d.get("text", ""))]
        return out

    def scan(self, owner: str, values) -> dict:
        loc = {k: 0 for k in self.LOCATIONS}
        for where, _ in self.find(owner, values):
            loc[where] += 1
        return loc

    def summarise(self, owner: str) -> None:
        return None  # Mem0 consolidates on every add()

    def lineage(self, item_id: int) -> list[Item]:
        return []

    def __len__(self) -> int:
        return len(self._ids)
