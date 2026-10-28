"""Governance tools: provenance, consistency, attribution, rollback and retraction.

These work on any "subject" that has a memory `store` (and `fork()` for attribution): Sahayak,
a GovernedMemory, or your own agent built on Memory Checks.

  provenance(subject, user)            every memory: where it came from, how trusted, usable or not
  contradictions(subject, user)        topics where the user's own memory holds conflicting values
  attribute(subject, user, decide)     leave-one-out: which memory caused this decision?
  quarantine(store, ids)               quarantine memories AND everything derived only from them
  retract_source(subject, user, src)   a source turns out untrustworthy: quarantine what it supports
  quarantine_cause(subject, user, decide)   post-incident rollback: find the cause, quarantine it,
                                       confirm the decision no longer stands
"""
from __future__ import annotations

import dataclasses
import re
from typing import Callable

from memorychecks.store import GLOBAL

TIERS = {3: "signed official", 2: "the user", 1: "an uploaded document", 0: "the web / untrusted"}


def provenance(subject, user: str) -> list[dict]:
    """Origin and trustworthiness of every memory this user can see (their own + global)."""
    checks, store = subject.store.checks, subject.store
    out = []
    for it in store.visible(user):
        if it.owner not in (user, GLOBAL):
            continue
        rank = checks.TRUST_RANK.get(it.source, 0)
        out.append({"id": it.id, "text": it.text[:140], "source": it.source, "trust_rank": rank,
                    "origin": TIERS.get(rank, "unknown"), "status": it.status, "btype": it.btype,
                    "parents": list(getattr(it, "parents", ()) or ()),
                    "usable_for_decisions": checks.usable_for_action(it)})
    return out


def contradictions(subject, user: str) -> list[dict]:
    """Topics where the user's OWN statements hold two or more different values. Only memories
    actually about the topic count (phone digits are not a 'code' conflict), and an uploaded
    document or a signed policy is not the user's own statement."""
    from memorychecks.erasure import TOPICS, normalize, values_in
    items = [it for it in subject.store.visible(user)
             if it.owner == user and it.source == "citizen" and it.status not in ("deleted", "quarantined")]
    out, claimed = [], set()  # a value counts for the FIRST (most specific) topic that matches
    for topic, keywords in TOPICS.items():
        seen: dict[str, str] = {}
        for it in items:
            if not re.search(keywords, it.text, re.I):
                continue
            for v in values_in(it.text, topic):
                n = normalize(v)
                if n not in claimed:
                    seen.setdefault(n, v)
        if len(seen) >= 2:
            out.append({"topic": topic, "values": list(seen.values())})
            claimed |= set(seen)
    return out


def attribute(subject, user: str, decide: Callable) -> dict:
    """Leave-one-out attribution: re-run `decide(copy)` with each memory hidden in turn; a memory
    is a cause if hiding it flips the outcome. (Needs a store whose fork is isolated: ours and
    LangGraph's. Mem0's fork is the live store, so per-item replay is not available there.)"""
    if getattr(subject.store, "is_mem0", False):
        return {"decision": decide(subject), "caused_by": [], "note": "per-item replay needs an isolated fork"}
    base = decide(subject)
    mine = [m for m in subject.store.visible(user) if m.owner in (user, GLOBAL)]

    def without(ids) -> object:
        fk = subject.fork()
        with fk.store._lock:
            for i in ids:
                fk.store.items.pop(i, None)
        return fk

    causes = []
    for it in mine:
        if decide(without([it.id])) != base:
            causes.append({"id": it.id, "text": it.text[:140], "source": it.source, "status": it.status})
    if not causes:
        # Redundant causes (e.g. two forged copies of one notice): hiding either alone changes nothing,
        # so plain leave-one-out finds no cause. Fall back to sufficiency: hide every untrusted memory at
        # once; if that flips the outcome, each untrusted memory that ALONE restores it is a cause.
        untrusted = [m for m in mine if m.source != "admin_signed"]
        ids = [m.id for m in untrusted]
        if ids and decide(without(ids)) != base:
            for it in untrusted:
                if decide(without([i for i in ids if i != it.id])) == base:
                    causes.append({"id": it.id, "text": it.text[:140], "source": it.source,
                                   "status": it.status, "redundant": True})
    return {"decision": base, "caused_by": causes}


def quarantine(store, seed_ids) -> int:
    """Quarantine these memories and every memory derived ONLY from quarantined ones (lineage).
    Quarantined memory is kept for audit but never retrieved or used again."""
    if getattr(store, "is_mem0", False):
        return 0
    with store._lock:
        items = store.items
        bad = set(seed_ids) & set(items)
        changed = True
        while changed:  # a memory whose every parent is quarantined is quarantined too
            changed = False
            for i in list(items):
                it = items[i]
                if i not in bad and it.parents and all(p in bad for p in it.parents):
                    bad.add(i)
                    changed = True
        for i in bad:
            items[i] = dataclasses.replace(items[i], status="quarantined")
    return len(bad)


def retract_source(subject, user: str, source: str) -> dict:
    """A source is judged untrustworthy: quarantine every memory from it (and what derives only
    from it), leaving independently supported memories active."""
    seeds = [it.id for it in subject.store.visible(user)
             if it.owner in (user, GLOBAL) and it.source == source]
    return {"retracted_source": source, "quarantined": quarantine(subject.store, seeds)}


def quarantine_cause(subject, user: str, decide: Callable) -> dict:
    """Post-incident rollback: attribute the decision, quarantine its cause(s) and derivatives,
    then re-run the decision to confirm it no longer stands."""
    r = attribute(subject, user, decide)
    n = quarantine(subject.store, [c["id"] for c in r["caused_by"] if "id" in c])
    return {**r, "quarantined": n, "decision_after": decide(subject)}
