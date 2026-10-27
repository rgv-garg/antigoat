"""Memory Checks on LangGraph's long-term memory store.

LangGraph agents (and LangMem, which writes into the same store) keep long-term memory in a
`langgraph.store.base.BaseStore`: namespaced key-value documents, read with `get` / `search`,
written with `put`, removed with `delete`. This backend runs Sahayak - and every Memory
Check - on that API. Nothing is planted: the store is the library's own `InMemoryStore`
(swap in `PostgresStore` and nothing else changes, it is the same interface).

How it fits: our store keeps its memories in an `items` map. Here that map is a LIVE VIEW of
the LangGraph store - every lookup is a `get`, every write a `put`, every removal a `delete`
- so routing, trust, tombstones, Verified Erasure, quarantine and rollback all run unchanged
on LangGraph-held memory. Decoded items are cached per (key, updated_at), so a value is
re-read from the store whenever LangGraph says it changed.
"""
from __future__ import annotations

import itertools
from collections.abc import MutableMapping

import numpy as np
from langgraph.store.memory import InMemoryStore

from memorychecks.checks import MemoryChecks
from memorychecks.store import Item, MemoryStore

NAMESPACE = "antigoat-memory"
NOTHING_PLANTED = {"shared_index": False, "soft_delete": False, "doc_as_rule": False, "guardrail_gap": False}


def _encode(it: Item) -> dict:
    return {"id": it.id, "owner": it.owner, "text": it.text, "source": it.source, "btype": it.btype,
            "parents": list(it.parents), "status": it.status, "created": it.created,
            "emb": None if it.emb is None else np.asarray(it.emb, dtype=np.float32).tolist(),
            "meta": dict(it.meta or {}), "trust": it.trust}


def _decode(v: dict) -> Item:
    emb = None if v.get("emb") is None else np.asarray(v["emb"], dtype=np.float32)
    return Item(v["id"], v["owner"], v["text"], v["source"], v["btype"], tuple(v.get("parents", ())),
                v.get("status", "active"), v.get("created", 0), emb, dict(v.get("meta") or {}), v.get("trust", 2))


class LangGraphItems(MutableMapping):
    """`dict[int, Item]` over a LangGraph BaseStore. One namespace per owner:
    (NAMESPACE, owner) -> key str(id) -> the memory document."""

    def __init__(self, store):
        self.store = store
        self._owner: dict[int, str] = {}                 # id -> owner (which namespace holds it)
        self._cache: dict[int, tuple[object, Item]] = {}  # id -> (updated_at, decoded item)

    @staticmethod
    def ns(owner: str) -> tuple[str, str]:
        return (NAMESPACE, owner)

    def __getitem__(self, iid: int) -> Item:
        owner = self._owner[iid]
        doc = self.store.get(self.ns(owner), str(iid))
        if doc is None:
            raise KeyError(iid)
        hit = self._cache.get(iid)
        if hit is not None and hit[0] == doc.updated_at:
            return hit[1]
        item = _decode(doc.value)
        self._cache[iid] = (doc.updated_at, item)
        return item

    def __setitem__(self, iid: int, item: Item) -> None:
        old = self._owner.get(iid)
        if old is not None and old != item.owner:          # owner changed: move namespaces
            self.store.delete(self.ns(old), str(iid))
        self._owner[iid] = item.owner
        self.store.put(self.ns(item.owner), str(iid), _encode(item), index=False)
        self._cache.pop(iid, None)

    def __delitem__(self, iid: int) -> None:
        owner = self._owner.pop(iid)
        self._cache.pop(iid, None)
        self.store.delete(self.ns(owner), str(iid))

    def __iter__(self):
        return iter(list(self._owner))

    def __len__(self) -> int:
        return len(self._owner)

    def namespaces(self) -> list[tuple[str, ...]]:
        """What LangGraph itself reports holding (used by tests to prove the data lives there)."""
        return self.store.list_namespaces(prefix=(NAMESPACE,), limit=100000)


class LangGraphStore(MemoryStore):
    """Sahayak's memory interface on LangGraph's BaseStore, with no planted bugs."""

    is_langgraph = True

    def __init__(self, checks: MemoryChecks | None = None, bugs: dict | None = None, store=None):
        super().__init__(checks, dict(NOTHING_PLANTED))  # we test the library as shipped
        self.lg = store if store is not None else InMemoryStore()
        self.items = LangGraphItems(self.lg)

    def fork(self) -> "LangGraphStore":
        """An isolated copy for auditing one citizen: a fresh LangGraph store holding the same
        documents, so the audit's own messages cannot leak into other audits."""
        with self._lock:
            new = LangGraphStore(self.checks)
            for iid in list(self.items):
                new.items[iid] = self.items[iid]
            new.receipts = list(self.receipts)
            new.tomb = self.tomb  # audits never erase, so sharing is safe
            new._ids = itertools.count(max(self.items, default=0) + 1)
            new._clock = self._clock
            return new
