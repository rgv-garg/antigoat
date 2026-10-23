"""Memory Checks - the defence under test.

Every new memory gets a "passport" (source + belief type) and is checked before it is
stored. Four ideas, matching the deck:

  1. Where did it come from?          -> every item carries `source` and `parents`
  2. Is that source allowed to say it? -> AUTHORITY matrix below (deck appendix A)
  3. Ten copies != ten witnesses       -> count independent origins, not copies
  4. Risky actions need clean memory   -> action gate: only signed admin policy can
                                          change an application decision

Modes
  off       no checks (the bugs in BUGS are live)
  on        the real defence
  paranoid  a deliberately over-cautious defence that rejects everything except a
            citizen's own facts. It passes every "must NOT" rule but fails the "must"
            rule (Authority) - this is what our "must still learn" rows are for.
"""
from __future__ import annotations

import hashlib
import hmac

# Decision for (source, belief type). "write" = store as active, "probation" = store
# but never use for actions until a second independent source agrees, "no" = never
# stored as that type (kept only as an untrusted 'claim').
AUTHORITY: dict[str, dict[str, str]] = {
    #                personal_fact  preference  world_fact   policy  instruction
    "citizen":      {"personal_fact": "write", "preference": "write", "world_fact": "probation", "policy": "no", "instruction": "no"},
    "document":     {"personal_fact": "probation", "preference": "no", "world_fact": "probation", "policy": "no", "instruction": "no"},
    "web":          {"personal_fact": "no", "preference": "no", "world_fact": "probation", "policy": "no", "instruction": "no"},
    "admin_signed": {"personal_fact": "no", "preference": "no", "world_fact": "write", "policy": "write", "instruction": "write"},
}
# Types that are bookkeeping, not beliefs - always allowed.
INTERNAL_TYPES = {"conversation", "summary", "document"}

# Demo signing key for "signed" UIDAI policies. In real life: a proper PKI.
_ADMIN_KEY = b"uidai-demo-signing-key"


def sign(text: str) -> str:
    return hmac.new(_ADMIN_KEY, text.encode(), hashlib.sha256).hexdigest()


def verify(text: str, signature: str | None) -> bool:
    return bool(signature) and hmac.compare_digest(sign(text), signature)


class MemoryChecks:
    def __init__(self, mode: str = "off"):
        assert mode in {"off", "on", "paranoid"}, mode
        self.mode = mode
        self.log: list[dict] = []  # every decision, for the "why do I believe this?" view

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def route(self, source: str, btype: str, signature: str | None = None, text: str = "") -> str:
        """Return 'write' | 'probation' | 'no' for a new memory."""
        if not self.enabled:
            return "write"
        if self.mode == "paranoid":
            decision = "write" if (source == "citizen" and btype in {"personal_fact", "conversation", "summary"}) else "no"
        elif btype in INTERNAL_TYPES:
            decision = "write"
        else:
            decision = AUTHORITY.get(source, {}).get(btype, "no")
            if source == "admin_signed" and not verify(text, signature):
                decision = "no"  # claims to be admin, signature does not check out
        self.log.append({"source": source, "type": btype, "decision": decision, "text": text[:120]})
        return decision

    def usable_for_action(self, item) -> bool:
        """Action gate: may this memory influence approve/reject decisions?"""
        if not self.enabled:
            return True
        if self.mode == "paranoid":
            return False
        return item.status == "active" and item.source == "admin_signed" and verify(item.text, item.meta.get("signature"))

    @staticmethod
    def independent_sources(items) -> int:
        """Ten copies are not ten witnesses: count distinct root origins.

        TODO(defence owner): use this in a fake-consensus test - promote a probation
        claim to active only when independent_sources >= 2.
        """
        roots = set()
        for it in items:
            roots.add(it.meta.get("origin", it.source + ":" + it.owner))
        return len(roots)
