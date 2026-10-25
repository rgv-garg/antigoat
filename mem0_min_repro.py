"""Minimal, standalone reproduction: Mem0's delete() is not durable.

Depends ONLY on mem0 (no AntiGOAT code), so a maintainer can run it as-is. It shows:
  (A) after Memory.delete(), a search no longer returns the memory  -> looks deleted
  (B) but the deleted text is still physically in Mem0's own `messages` + `history`
      tables                                                          -> data at rest
  (C) because that buffer is re-fed to the extraction LLM, a few ordinary turns later
      the "deleted" fact is re-learned and becomes retrievable again  -> resurrection

(A) and (B) are deterministic and model-independent (B is a direct DB read, no model
judgement). (C) depends on the extraction model choosing to re-store the buffered text.

Run with Mem0's default stack:
    pip install mem0ai==2.2.1
    export OPENAI_API_KEY=sk-...
    python mem0_min_repro.py

Or point it at any OpenAI-compatible endpoint (e.g. a local vLLM) without changing code:
    export OPENAI_API_KEY=not-needed
    export OPENAI_BASE_URL=http://localhost:8000/v1
    export MEM0_LLM_MODEL=nemotron-nano
    python mem0_min_repro.py
"""
from __future__ import annotations

import os
import time

from mem0 import Memory

USER = "alice"
SECRET = "Please remember my emergency backup code is kesar-7342."
NEEDLE = "kesar-7342"


def build() -> Memory:
    model = os.environ.get("MEM0_LLM_MODEL", "gpt-4o-mini")
    cfg = {"llm": {"provider": "openai", "config": {"model": model, "temperature": 0}}}
    # text-embedding-3-small is the Mem0 default; override only if you must.
    return Memory.from_config(cfg)


def finds(m: Memory, needle: str) -> bool:
    res = m.search(needle, filters={"user_id": USER}, top_k=10).get("results", [])
    return any(needle.lower() in (r.get("memory", "").lower()) for r in res)


def residue(m: Memory, needle: str) -> dict:
    """Count rows in Mem0's own SQLite that still contain the deleted text."""
    db = m.db  # mem0's SQLiteManager
    like = f"%{needle}%"
    out = {}
    for table, col in [("history", "old_memory"), ("history", "new_memory"), ("messages", "content")]:  # both history columns
        try:
            n = db.connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} LIKE ?", (like,)).fetchone()[0]
            out[f"{table}.{col}"] = n
        except Exception as e:  # table/column may differ across versions
            out[f"{table}.{col}"] = f"n/a ({e})"
    return out


def main() -> None:
    m = build()

    m.add(SECRET, user_id=USER)
    time.sleep(1)
    print("1. after add       -> search finds the code:   ", finds(m, NEEDLE))

    deleted = []
    for r in m.get_all(filters={"user_id": USER}, top_k=10000).get("results", []):
        if NEEDLE.lower() in r.get("memory", "").lower():
            m.delete(r["id"])
            deleted.append(r["id"])
    time.sleep(1)
    print("2. after delete()  -> search finds the code:   ", finds(m, NEEDLE), " (expect False)")
    print("3. but deleted text is still in Mem0 storage:  ", residue(m, NEEDLE))
    for mid in deleted:  # Mem0's own PUBLIC API returns the deleted text
        rows = m.history(mid)
        print("   public m.history(id) after delete returns:",
              [(h.get("event"), h.get("old_memory") or h.get("new_memory")) for h in rows])

    for msg in ["What documents do I need to update my address?",
                "Thank you for the help.",
                "When will my application be processed?"]:
        m.add(msg, user_id=USER)
        time.sleep(0.5)
    print("4. after a few ordinary turns -> search finds it AGAIN:", finds(m, NEEDLE),
          " (resurrection)")


if __name__ == "__main__":
    main()
