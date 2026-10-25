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
from functools import lru_cache
import re
import threading
from dataclasses import dataclass, field, replace

import numpy as np

from sahayak.checks import MemoryChecks
from sahayak.embed import embed
from sahayak.erasure import MASK, Tombstones, pattern, still_useful

DEFAULT_BUGS = {"shared_index": True, "soft_delete": True, "doc_as_rule": True, "guardrail_gap": True}
GLOBAL = "global"  # owner for policies that apply to everyone

# Which Memory Checks sub-check neutralises each planted bug. A bug is live when its flag
# is set AND (checks are off, OR the neutralising sub-check has been disabled for ablation).
_NEUTRALISED_BY = {"shared_index": "walls", "guardrail_gap": "walls",
                   "soft_delete": "hard_delete", "doc_as_rule": "authority"}

@lru_cache(maxsize=200_000)
def _tokens(text: str) -> frozenset:
    return frozenset(re.findall(r"\w+", text.lower()))


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
    trust: int = field(default=2, compare=False)  # lineage trust tier (admin 3 > citizen/agent 2 > doc 1 > web 0)


class MemoryStore:
    def __init__(self, checks: MemoryChecks | None = None, bugs: dict | None = None):
        self.checks = checks or MemoryChecks("off")
        self.bugs = dict(DEFAULT_BUGS if bugs is None else bugs)
        self.items: dict[int, Item] = {}
        self.receipts: list[dict] = []   # signed DPDP erasure receipts (hard_delete)
        self.tomb = Tombstones()          # hashes of erased values (tombstone check)
        self._ids = itertools.count(1)
        self._clock = 0
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ helpers
    def _bug(self, name: str) -> bool:
        """A bug is live when its flag is on AND the neutralising Memory Check is not active.

        With checks off, every flagged bug is live. With checks on, a bug is live only if
        the sub-check that neutralises it has been disabled for ablation - that is how the
        demo shows 'turn off exactly this check and exactly this leak comes back'.
        """
        if not self.bugs.get(name, False):
            return False
        if not self.checks.enabled:
            return True
        feat = _NEUTRALISED_BY.get(name)
        return not self.checks.feature(feat) if feat else False

    def fork(self) -> "MemoryStore":
        """Cheap copy (items are immutable). Used to audit one slot without side effects."""
        with self._lock:
            new = MemoryStore(self.checks, self.bugs)
            new.items = dict(self.items)
            new.receipts = list(self.receipts)
            new.tomb = self.tomb  # audits never erase, so sharing is safe
            start = max(self.items, default=0) + 1
            new._ids = itertools.count(start)
            new._clock = self._clock
            return new

    # ------------------------------------------------------------------ write
    def add(self, owner: str, text: str, source: str, btype: str,
            parents: tuple = (), meta: dict | None = None) -> int | None:
        meta = dict(meta or {})
        if self.checks.feature("tombstone"):
            # an erased value can never be written back - not by a summary, not by re-extraction
            text, n_tomb = self.tomb.redact(meta.get("uploaded_by", owner), text)
            if n_tomb:
                meta["tombstoned"] = n_tomb
        decision = self.checks.route(source, btype, meta.get("signature"), text)
        if decision == "no":
            if btype in {"policy", "instruction"} and self.checks.mode == "on":
                # keep it only as an untrusted claim - information, never authority
                btype, decision = "world_fact", "probation"
            else:
                return None

        # slow_poison: stop one untrusted origin dripping many claims toward one decision.
        if decision == "probation" and source in {"document", "web", "citizen"} and btype == "world_fact":
            origin = meta.get("origin", f"{source}:{owner}")
            key = self._decision_key(text)
            if not self.checks.drip_ok(origin, key):
                meta["quarantined"] = "slow_poison"
                return None  # refuse: looks like a drip / sybil push

        status = "active" if decision == "write" else "probation"
        # lineage trust: a derived item is only as trusted as its least-trusted parent.
        trust = self.checks.trust_of(source) if self.checks.enabled else 2
        if parents and self.checks.feature("lineage_trust"):
            ptrust = [self.items[p].trust for p in parents if p in self.items]
            if ptrust:
                trust = min(trust, min(ptrust))
        with self._lock:
            self._clock += 1
            iid = next(self._ids)
            self.items[iid] = Item(iid, owner, text, source, btype, tuple(parents), status,
                                   self._clock, embed([text])[0], meta, trust)
            self.checks.append_chain(f"{iid}|{owner}|{source}|{btype}|{text[:80]}")
        # source_count: a probation claim is promoted to active only once >= 2 INDEPENDENT
        # origins assert it (ten copies of one forward stay probation).
        if status == "probation":
            self._maybe_corroborate(iid)
        return iid

    @staticmethod
    def _decision_key(text: str) -> str:
        """A coarse topic key for drip detection: the pincode a claim is about, else 'general'."""
        m = re.search(r"\b(\d{6})\b", text)
        return m.group(1) if m else "general"

    def _maybe_corroborate(self, iid: int) -> None:
        """Promote a probation claim (and its agreeing copies) to active when independent
        origins >= 2. Uses token overlap to group 'the same claim'."""
        if not self.checks.feature("source_count"):
            return
        with self._lock:
            it = self.items.get(iid)
            if it is None or it.status != "probation":
                return
            key = _tokens(it.text)
            agree = [o for o in self.items.values()
                     if o.btype == it.btype and o.status in {"probation", "active"}
                     and len(key & _tokens(o.text)) >= max(2, len(key) // 2)]
            if self.checks.independent_sources(agree) >= 2:
                for o in agree:
                    if o.status == "probation":
                        self.items[o.id] = replace(o, status="active")

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
        # Hybrid search (like most production memory layers, e.g. vector + BM25): boost exact
        # matches of RARE tokens - IDs, codes, pincodes (anything with a digit) and words that
        # occur in only a few memories (a name, a code word).
        toks = [_tokens(it.text) for it in items]
        qtok = {t for t in _tokens(query) if len(t) >= 3}
        rare = {t for t in qtok if any(ch.isdigit() for ch in t)}
        for t in qtok - rare:
            if 0 < sum(1 for tk in toks if t in tk) <= 3:
                rare.add(t)
        if rare:
            bonus = np.array([0.5 if rare & tk else 0.0 for tk in toks])
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
        """Citizen asks to forget something (DPDP erasure). Returns how many items removed.

        With hard_delete active this is a true erasure: the raw item AND everything derived
        from it are dropped, and a signed deletion receipt is recorded. Without it (checks
        off, or hard_delete disabled for ablation) it is only a soft hide, so the soft_delete
        bug can resurrect it through the next summary.
        """
        if self.checks.feature("entity_erasure"):
            rep = self.erase_values(owner, [needle], label="exact value")
            return rep["memories_deleted"] + rep["memories_redacted"]
        n = 0
        with self._lock:
            targets = [it for it in self.items.values()
                       if it.owner == owner and needle.lower() in it.text.lower() and it.status != "deleted"]
            for it in targets:
                self.items[it.id] = replace(it, status="deleted")
                n += 1
            if self.checks.feature("hard_delete"):
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
                self._receipt(owner, needle, len(dead))
        return n

    def delete_items(self, owner: str, ids, label: str = "") -> list[Item]:
        """Erase specific memories of `owner`, plus the raw chat turn each was extracted from.

        delete_matching needs the exact text ("kesar-4135"); a citizen saying "forget my name"
        gives a topic instead, so the caller picks the items. Same two behaviours: without
        hard_delete it is a soft hide (the soft_delete bug can bring it back in the next
        summary); with hard_delete the items, their source turns and everything derived from
        them are purged, with a signed receipt. Returns the items that were erased.
        """
        with self._lock:
            targets = {i for i in ids if i in self.items and self.items[i].owner == owner
                       and self.items[i].status != "deleted"}
            for i in list(targets):  # the raw turn a fact was extracted from says the same thing
                for p in self.items[i].parents:
                    src = self.items.get(p)
                    if src and src.owner == owner and src.btype == "conversation" and src.status != "deleted":
                        targets.add(p)
            removed = [self.items[i] for i in sorted(targets)]
            for it in removed:
                self.items[it.id] = replace(it, status="deleted")
            if targets and self.checks.feature("hard_delete"):
                dead, changed = set(targets), True
                while changed:  # cascade: anything derived from an erased item goes too
                    changed = False
                    for it in list(self.items.values()):
                        if it.id not in dead and dead & set(it.parents):
                            dead.add(it.id)
                            changed = True
                for d in dead:
                    self.items.pop(d, None)
                self._receipt(owner, label or f"{len(targets)} item(s)", len(dead))
        return removed

    def _receipt(self, owner: str, needle: str, n_purged: int, values=(), residue: dict | None = None) -> dict:
        """Record a tamper-evident proof that an erasure happened (deletion receipt).
        The receipt never contains the erased text: values are recorded as salted hashes."""
        import hashlib
        import time as _t
        from sahayak.checks import sign
        hashed = [hashlib.sha256(self.tomb.salt + str(v).lower().encode()).hexdigest()[:12] for v in values]
        what = needle
        for v in values:
            what = pattern(v).sub(MASK, what)
        body = f"ERASURE owner={owner} what={what!r} values={hashed} purged={n_purged} at={int(_t.time())}"
        rec = {"owner": owner, "what": what, "values_hashed": hashed, "purged": n_purged,
               "residue_after": residue, "at": int(_t.time()),
               "signature": sign(body), "chain_head": self.checks.append_chain(body)}
        self.receipts.append(rec)
        return rec

    # ------------------------------------------------------------------ Verified Erasure (v3)
    def erase_values(self, owner: str, values, label: str = "") -> dict:
        """Entity-level erasure: remove each VALUE from every item of `owner` it appears in.

        An item that was only about the value is deleted; an entangled item keeps its useful
        part ("[erased] and Raghu had a fight"). Soft-deleted copies are purged too. The
        routing log is scrubbed, a tombstone (hash) is kept so the value cannot be written
        back, and the store is re-scanned - the receipt carries that residue (all zeros)."""
        values = [v for v in values if v]
        rxs = [pattern(v) for v in values]
        rep = {"memories_deleted": 0, "memories_redacted": 0, "log_lines": 0}
        if not rxs:
            return rep
        with self._lock:
            for it in list(self.items.values()):
                if not (it.owner == owner or it.meta.get("uploaded_by") == owner):
                    continue
                new, n = it.text, 0
                for rx in rxs:
                    new, k = rx.subn(MASK, new)
                    n += k
                if not n:
                    continue
                if it.status == "deleted" or not still_useful(new):
                    self.items.pop(it.id, None)
                    rep["memories_deleted"] += 1
                else:
                    self.items[it.id] = replace(it, text=new, emb=embed([new])[0],
                                                meta={**it.meta, "redacted": True})
                    rep["memories_redacted"] += 1
            for d in self.checks.log:
                t, hit = d.get("text", ""), 0
                for rx in rxs:
                    t, k = rx.subn(MASK, t)
                    hit += k
                if hit:
                    d["text"] = t
                    rep["log_lines"] += 1
            if self.checks.feature("tombstone"):
                for v in values:
                    self.tomb.add(owner, v, label)
        rep["residue_after"] = self.scan(owner, values)
        rep["receipt"] = self._receipt(owner, label or "erasure", rep["memories_deleted"] + rep["memories_redacted"],
                                       values, rep["residue_after"])
        return rep

    LOCATIONS = ("memories", "chat turns", "summaries", "hidden (soft-deleted) copies",
                 "other citizens' records", "routing log", "audit chain", "erasure receipts")

    def find(self, owner: str, values) -> list[tuple[str, str]]:
        """Memory X-ray: every (location, text) where one of `values` still lives.
        Runs with Checks OFF too - the same scan before and after a forget-request."""
        rxs = [pattern(v) for v in values if v]
        if not rxs:
            return []

        def hit(t) -> bool:
            return any(rx.search(t or "") for rx in rxs)

        out = []
        with self._lock:
            items = sorted(self.items.values(), key=lambda it: it.id)
        for it in items:
            if not hit(it.text):
                continue
            mine = it.owner == owner or it.meta.get("uploaded_by") == owner
            if not mine:
                loc = "other citizens' records"
            elif it.status == "deleted":
                loc = "hidden (soft-deleted) copies"
            elif it.btype == "summary":
                loc = "summaries"
            elif it.btype == "conversation":
                loc = "chat turns"
            else:
                loc = "memories"
            out.append((loc, it.text))
        out += [("routing log", d.get("text", "")) for d in self.checks.log if hit(d.get("text", ""))]
        out += [("audit chain", r.get("payload", "")) for r in self.checks.chain if hit(r.get("payload", ""))]
        out += [("erasure receipts", str(r.get("what") or r.get("needle", ""))) for r in self.receipts
                if hit(str(r.get("what", ""))) or hit(str(r.get("needle", "")))]
        return out

    def scan(self, owner: str, values) -> dict:
        """Counts per location (see find)."""
        loc = {k: 0 for k in self.LOCATIONS}
        for where, _ in self.find(owner, values):
            loc[where] += 1
        return loc

    def last_receipt(self) -> dict | None:
        return self.receipts[-1] if self.receipts else None

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
