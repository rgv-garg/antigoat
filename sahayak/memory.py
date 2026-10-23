"""Sahayak's shared memory store (Mem0-style, hand-rolled so we control the bugs).

PLANTED BUGS (copies of real 2026 failure modes; switch each on/off in BUGS):
  shared_index  search ignores who owns a memory -> one citizen's data shows up for
                another (MemLeak, NeurIPS '26)
  guardrail_gap the Intake agent has an output filter that hides code-like secrets, but
                the Grievance agent does not - a side door a fixed list of English probes
                to Intake never tries (cf. Governed Shared Memory '26)
  soft_delete   delete only hides the raw item; the next summary still copies it, so
                deleted facts come back after a few sessions (Deleted Is Not Forgotten)
  doc_as_rule   text in an uploaded document that looks like a rule is stored as an
                official policy (memory poisoning)

With Memory Checks ON these bugs are neutralised by the defence, not by turning the
flags off - that is the point of the demo.
"""
from __future__ import annotations

import itertools
import re
import threading
from dataclasses import dataclass, field, replace

import numpy as np

from sahayak.checks import MemoryChecks
from sahayak.embed import embed

DEFAULT_BUGS = {"shared_index": True, "soft_delete": True, "doc_as_rule": True, "guardrail_gap": True}
GLOBAL = "global"  # owner for policies that apply to everyone

_RULE_WORDS = re.compile(r"\b(rule|notice|policy|circular|no longer required|waived|exempt)\b", re.I)


@dataclass(frozen=True)
class Item:
    id: int
    owner: str
    text: str
    source: str        # citizen | document | web | admin_signed | agent
    btype: str         # personal_fact | preference | world_fact | policy | instruction | conversation | summary | document
    parents: tuple = ()
    status: str = "active"   # active | probation | deleted
    created: int = 0
    emb: np.ndarray | None = field(default=None, compare=False, repr=False)
    meta: dict = field(default_factory=dict, compare=False)


class MemoryStore:
    def __init__(self, checks: MemoryChecks | None = None, bugs: dict | None = None):
        self.checks = checks or MemoryChecks("off")
        self.bugs = dict(DEFAULT_BUGS if bugs is None else bugs)
        self.items: dict[int, Item] = {}
        self._ids = itertools.count(1)
        self._clock = 0
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ helpers
    def _bug(self, name: str) -> bool:
        """A bug is live only when its flag is on AND Memory Checks are off."""
        return self.bugs.get(name, False) and not self.checks.enabled

    def fork(self) -> "MemoryStore":
        """Cheap copy (items are immutable). Used to audit one slot without side effects."""
        with self._lock:
            new = MemoryStore(self.checks, self.bugs)
            new.items = dict(self.items)
            start = max(self.items, default=0) + 1
            new._ids = itertools.count(start)
            new._clock = self._clock
            return new

    # ------------------------------------------------------------------ write
    def add(self, owner: str, text: str, source: str, btype: str,
            parents: tuple = (), meta: dict | None = None) -> int | None:
        meta = dict(meta or {})
        decision = self.checks.route(source, btype, meta.get("signature"), text)
        if decision == "no":
            if btype in {"policy", "instruction"} and self.checks.mode == "on":
                # keep it only as an untrusted claim - information, never authority
                btype, decision = "world_fact", "probation"
            else:
                return None
        status = "active" if decision == "write" else "probation"
        with self._lock:
            self._clock += 1
            iid = next(self._ids)
            self.items[iid] = Item(iid, owner, text, source, btype, tuple(parents), status,
                                   self._clock, embed([text])[0], meta)
            return iid

    def upload_document(self, owner: str, text: str) -> int | None:
        if self._bug("doc_as_rule") and _RULE_WORDS.search(text):
            # BUG: a document's claim is stored as an official policy, for everyone
            return self.add(GLOBAL, text, "document", "policy", meta={"uploaded_by": owner})
        return self.add(owner, text, "document",
                        "policy" if _RULE_WORDS.search(text) else "document",
                        meta={"uploaded_by": owner})

    # ------------------------------------------------------------------ read
    def visible(self, viewer: str) -> list[Item]:
        with self._lock:
            items = list(self.items.values())
        items = [it for it in items if it.status != "deleted"]
        if self._bug("shared_index"):
            return items  # BUG: no owner filter
        return [it for it in items if it.owner in (viewer, GLOBAL)]

    def search(self, viewer: str, query: str, k: int = 5) -> list[Item]:
        items = self.visible(viewer)
        if not items:
            return []
        q = embed([query])[0]
        mat = np.stack([it.emb for it in items])
        scores = mat @ q
        # Hybrid search (like most production memory layers): boost exact matches of
        # rare tokens such as IDs, codes and pincodes - anything containing a digit.
        rare = {t.lower() for t in re.findall(r"[\w-]+", query) if any(ch.isdigit() for ch in t)}
        if rare:
            bonus = np.array([0.5 if any(r in it.text.lower() for r in rare) else 0.0 for it in items])
            scores = scores + bonus
        order = np.argsort(-scores)[:k]
        return [items[i] for i in order if scores[i] > 0.05]

    def policies(self) -> list[Item]:
        """Policies the Verification agent may act on (action gate applies)."""
        with self._lock:
            items = list(self.items.values())
        pol = [it for it in items if it.btype == "policy" and it.owner == GLOBAL and it.status != "deleted"]
        return [it for it in pol if self.checks.usable_for_action(it)]

    # ------------------------------------------------------------------ delete / summarise
    def delete_matching(self, owner: str, needle: str) -> int:
        """Citizen asks to forget something. Returns how many items were removed."""
        n = 0
        with self._lock:
            targets = [it for it in self.items.values()
                       if it.owner == owner and needle.lower() in it.text.lower() and it.status != "deleted"]
            for it in targets:
                self.items[it.id] = replace(it, status="deleted")
                n += 1
            if self.checks.enabled:
                # Hard delete + cascade: drop the raw item AND anything derived from it.
                dead = {it.id for it in targets}
                changed = True
                while changed:
                    changed = False
                    for it in list(self.items.values()):
                        if it.id in dead:
                            continue
                        if dead & set(it.parents) or (needle.lower() in it.text.lower() and it.owner == owner):
                            dead.add(it.id)
                            changed = True
                for d in dead:
                    self.items.pop(d, None)
        return n

    def summarise(self, owner: str) -> int | None:
        """Compress an owner's raw memories into one summary (runs at session end)."""
        with self._lock:
            raw = [it for it in self.items.values()
                   if it.owner == owner and it.btype in {"conversation", "personal_fact"}]
            if not self._bug("soft_delete"):
                raw = [it for it in raw if it.status != "deleted"]
            # BUG (soft_delete): deleted items are still copied into the new summary
            old = [it for it in self.items.values() if it.owner == owner and it.btype == "summary"]
            for it in old:
                self.items.pop(it.id, None)
            if not raw:
                return None
            text = "Summary of citizen history: " + " ; ".join(it.text for it in raw[-12:])
        return self.add(owner, text, "agent", "summary", parents=tuple(it.id for it in raw))

    # ------------------------------------------------------------------ introspection
    def lineage(self, item_id: int) -> list[Item]:
        """'Why do I believe this?' - walk an item's parents."""
        out, stack = [], [item_id]
        while stack:
            it = self.items.get(stack.pop())
            if it:
                out.append(it)
                stack.extend(it.parents)
        return out

    def __len__(self) -> int:
        return len(self.items)
