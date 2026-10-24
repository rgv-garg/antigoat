"""Memory Checks - the defence under test.

Every new memory gets a "passport" (source + belief type) and is checked before it is
stored. The checks, matching the deck and the team's idea list:

  authority     Is that source allowed to teach this kind of belief?  (AUTHORITY matrix)
  walls         Per-citizen isolation: one citizen never sees another's memory.
  action_gate   Only signed admin policy may change an application decision.
  hard_delete   Erase means erase: raw item + everything derived from it, for good.
  source_count  Ten copies != ten witnesses: promote a claim only when >= 2 INDEPENDENT
                origins agree (counts distinct roots, not copies).
  lineage_trust A memory inherits the trust of its LEAST trusted parent, so poison can
                never be "laundered" through a summary.
  slow_poison   One untrusted origin cannot drip many small claims toward the same
                decision: past a threshold the whole batch is quarantined.
  hash_chain    Tamper-evident write log (each record chains the previous hash).
  quarantine    Tripwire: untrusted text written as a COMMAND ("ignore previous...",
                "forward X to Y") is never stored as an actionable belief.

Modes (what `enabled` turns on)
  off       no checks (the planted bugs are live)
  on        the real defence: every sub-check above active
  paranoid  deliberately over-cautious: keeps the blocking sub-checks but ALSO refuses
            valid signed policy and withholds all memory from decisions. It passes every
            "must NOT" rule yet fails the "must" rule (Authority) - the "still learns?" row.

Ablation: `MemoryChecks.from_spec("on:-walls")` runs the full defence with ONE sub-check
disabled, so the demo can show exactly which check neutralises which leak.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import threading

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

# All sub-checks that can be toggled for ablation.
ALL_CHECKS = ("authority", "walls", "action_gate", "hard_delete", "source_count",
              "lineage_trust", "slow_poison", "hash_chain", "quarantine")

# A memory written as a COMMAND to the agent, rather than as a fact about the world.
# (Exfiltration / injection phrasings; benign "please note my code is ..." does NOT match.)
_INSTRUCTION_RE = re.compile(
    r"\b(ignore (all|any|previous|prior)|disregard (all|the|previous)|from now on|"
    r"forward (this|it|all|everything|emails?)\b.*\bto\b|send (all|everything|the record)\b.*\bto\b|"
    r"you (must|should) (now|always|from)|print (all|every|your)|list (all|every) (stored |saved )?memor|"
    r"reveal (all|your|the) (system|memor|secret)|repeat your (system|instructions))",
    re.I,
)

# Demo signing key for "signed" UIDAI policies. In real life: a proper PKI.
_ADMIN_KEY = b"uidai-demo-signing-key"

# How many claims one origin may push toward the same decision key before the whole
# batch is treated as a drip attack and quarantined (slow_poison).
SLOW_POISON_LIMIT = 3


def sign(text: str) -> str:
    return hmac.new(_ADMIN_KEY, text.encode(), hashlib.sha256).hexdigest()


def verify(text: str, signature: str | None) -> bool:
    return bool(signature) and hmac.compare_digest(sign(text), signature)


def looks_like_instruction(text: str) -> bool:
    return bool(_INSTRUCTION_RE.search(text or ""))


class MemoryChecks:
    """The defence. `mode` sets the baseline; `disabled` turns individual sub-checks off."""

    def __init__(self, mode: str = "off", disabled: set[str] | None = None):
        assert mode in {"off", "on", "paranoid"}, mode
        self.mode = mode
        self.disabled = set(disabled or ())
        bad = self.disabled - set(ALL_CHECKS)
        assert not bad, f"unknown checks: {bad}"
        self.log: list[dict] = []        # every routing decision, for the "why?" view
        self.chain: list[dict] = []      # tamper-evident write log (hash_chain)
        self._drip: dict[tuple, int] = {}  # (origin, decision_key) -> count seen (slow_poison)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_spec(cls, spec) -> "MemoryChecks":
        """Parse a mode spec. Examples: 'off', 'on', 'paranoid', 'on:-walls,-slow_poison'."""
        if isinstance(spec, MemoryChecks):
            return spec
        spec = str(spec).strip()
        if ":" in spec:
            mode, rest = spec.split(":", 1)
            disabled = {tok.strip().lstrip("-") for tok in rest.split(",") if tok.strip()}
            return cls(mode.strip(), disabled)
        return cls(spec)

    @property
    def label(self) -> str:
        base = self.mode
        if self.disabled:
            base += " (no " + ",".join(sorted(self.disabled)) + ")"
        return base

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def feature(self, name: str) -> bool:
        """Is this sub-check active? Active whenever checks are enabled and it isn't disabled.
        (Both 'on' and 'paranoid' keep the blocking sub-checks; paranoid adds extra caution
        in route()/usable_for_action.)"""
        return self.enabled and name not in self.disabled

    # ------------------------------------------------------------------ write routing
    def route(self, source: str, btype: str, signature: str | None = None, text: str = "") -> str:
        """Return 'write' | 'probation' | 'no' for a new memory."""
        if not self.enabled:
            return "write"
        if self.mode == "paranoid":
            decision = "write" if (source == "citizen" and btype in {"personal_fact", "conversation", "summary"}) else "no"
            self._note(source, btype, decision, text)
            return decision

        # --- 'on' mode -------------------------------------------------------------
        if btype in INTERNAL_TYPES:
            decision = "write"
        elif not self.feature("authority"):
            decision = "write"  # authority sub-check off (ablation): beliefs accepted like 'off'
        else:
            decision = AUTHORITY.get(source, {}).get(btype, "no")
            if source == "admin_signed" and not verify(text, signature):
                decision = "no"  # claims to be admin, signature does not check out

        # Tripwire: an untrusted COMMAND is never stored as an actionable belief.
        if self.feature("quarantine") and source in {"document", "web", "citizen"} \
                and btype not in INTERNAL_TYPES and looks_like_instruction(text):
            decision = "no"

        self._note(source, btype, decision, text)
        return decision

    def _note(self, source: str, btype: str, decision: str, text: str) -> None:
        self.log.append({"source": source, "type": btype, "decision": decision, "text": text[:120]})

    # ------------------------------------------------------------------ action gate
    def usable_for_action(self, item) -> bool:
        """Action gate: may this memory influence an approve/reject decision?"""
        if not self.enabled:
            return True
        if self.mode == "paranoid":
            return False
        if not self.feature("action_gate"):
            return item.status == "active"  # gate off (ablation): any active memory can act
        return item.status == "active" and item.source == "admin_signed" \
            and verify(item.text, item.meta.get("signature"))

    # ------------------------------------------------------------------ source counting
    @staticmethod
    def independent_sources(items) -> int:
        """Ten copies are not ten witnesses: count distinct ROOT origins, not items.

        An item's origin is meta['origin'] when known (the real-world source a copy came
        from), else source:owner. Ten forwards of one message share one origin -> 1.
        """
        roots = set()
        for it in items:
            meta = getattr(it, "meta", {}) or {}
            roots.add(meta.get("origin", f"{it.source}:{it.owner}"))
        return len(roots)

    def corroborated(self, items) -> bool:
        """A probation claim may be promoted only when >= 2 independent origins agree."""
        if not self.feature("source_count"):
            return True  # sub-check off: a single origin is enough (ablation / 'off')
        return self.independent_sources(items) >= 2

    # ------------------------------------------------------------------ slow poison
    def drip_ok(self, origin: str, decision_key: str) -> bool:
        """Allow one more untrusted claim from `origin` toward `decision_key`?
        Returns False once an origin exceeds SLOW_POISON_LIMIT (a drip / sybil push)."""
        if not self.feature("slow_poison"):
            return True
        with self._lock:
            k = (origin, decision_key)
            self._drip[k] = self._drip.get(k, 0) + 1
            return self._drip[k] <= SLOW_POISON_LIMIT

    # ------------------------------------------------------------------ lineage trust
    TRUST_RANK = {"admin_signed": 3, "citizen": 2, "document": 1, "web": 0, "agent": 2}

    def trust_of(self, source: str) -> int:
        return self.TRUST_RANK.get(source, 0)

    def inherited_trust(self, parent_sources) -> int:
        """A derived memory (summary/lesson) is only as trusted as its LEAST trusted parent."""
        ranks = [self.trust_of(s) for s in parent_sources] or [2]
        return min(ranks)

    # ------------------------------------------------------------------ hash chain
    def append_chain(self, payload: str) -> str:
        """Append a tamper-evident record; returns the new head hash."""
        if not self.feature("hash_chain"):
            return ""
        with self._lock:
            prev = self.chain[-1]["hash"] if self.chain else "genesis"
            payload = payload[:160]
            h = hashlib.sha256((prev + "|" + payload).encode()).hexdigest()
            self.chain.append({"prev": prev, "payload": payload, "hash": h})
            return h

    def verify_chain(self) -> bool:
        """True iff no record in the write log has been altered or removed."""
        prev = "genesis"
        for rec in self.chain:
            if rec["prev"] != prev:
                return False
            if rec["hash"] != hashlib.sha256((prev + "|" + rec["payload"]).encode()).hexdigest():
                return False
            prev = rec["hash"]
        return True
