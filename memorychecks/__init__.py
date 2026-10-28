"""Memory Checks: governed memory for AI agents.

Put it between any agent and its memory. Every write is labelled with where it came from and how
far that source may be trusted; memory from an untrusted source is a claim, never an authority -
it can be recalled, but it cannot authorise a risky decision; "forget X" removes X everywhere it lives, with a signed receipt; and every memory can
be traced, contradicted, attributed and rolled back.

    from memorychecks import GovernedMemory
    mem = GovernedMemory()                                  # backend="ours" | "mem0" | "langgraph"
    mem.write("asha", "My phone is 98765 43210.", source="user")
    mem.write("asha", page_text, source="web")              # untrusted: stored as information only
    ctx = mem.read("asha", "what is my phone number?")     # ctx.prompt -> paste into your prompt
    ok = mem.allow("asha", "waive address proof", evidence=ctx)
    receipt = mem.erase("asha", "please forget my phone number")

Modules: checks (the policy engine, 14 switchable checks), erasure (Verified Erasure),
store / mem0_store / langgraph_store (three memory backends behind one interface),
governance (provenance, contradictions, attribution, rollback, retraction), api (GovernedMemory).
"""
from __future__ import annotations

__all__ = ["GovernedMemory", "Context", "Decision", "MemoryChecks", "ALL_CHECKS"]


def __getattr__(name):  # lazy, so importing one module never drags in optional backends
    if name in {"GovernedMemory", "Context", "Decision"}:
        from memorychecks import api
        return getattr(api, name)
    if name in {"MemoryChecks", "ALL_CHECKS"}:
        from memorychecks import checks
        return getattr(checks, name)
    raise AttributeError(name)
