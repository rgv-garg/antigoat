"""Deterministic, offline reproduction: Mem0's Memory.delete() does not erase.

No API key, no network, no randomness. Mem0's real storage code (SQLite history,
messages table, local Qdrant) runs unchanged. Only the two model calls are replaced:

  * Embedder -> a fixed hash-based bag-of-words vector (same text => same vector).
  * LLM      -> a scripted extractor that RECORDS every prompt Mem0 sends it and
               returns a fixed answer. It never invents memories, so it cannot
               "cause" a leak. We use it only to see what Mem0 puts in the prompt.

Every check is an assertion with a precondition, so a broken setup FAILS loudly
instead of printing a misleading "deleted".

    pip install mem0ai==2.2.1
    python mem0_delete_repro.py            # exit code 0 = all claims reproduced
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile

os.environ["MEM0_TELEMETRY"] = "False"          # no network calls
WORK = tempfile.mkdtemp(prefix="mem0_repro_")    # fresh state every run
os.environ["MEM0_DIR"] = WORK                     # keep ~/.mem0 out of it

import mem0                                       # noqa: E402
from mem0 import Memory                           # noqa: E402
from mem0.utils import factory                    # noqa: E402

USER = "alice"
NEEDLE = "kesar-7342"                             # the value that must be erased
SECRET_TURN = f"Please remember my emergency backup code is {NEEDLE}."
FACT = f"User's emergency backup code is {NEEDLE}"
DIMS = 64

# ---------------------------------------------------------------- stand-ins
class HashEmbedder:
    def _vec(self, text):
        v = [0.0] * DIMS
        for w in re.findall(r"\w+", str(text).lower()):
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % DIMS] += 1.0
        n = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / n for x in v]

    def embed(self, text, memory_action=None):
        return self._vec(text)

    def embed_batch(self, texts, memory_action=None):
        return [self._vec(t) for t in texts]


class ScriptedLLM:
    """Returns a fact only for the secret turns in the CURRENT new message.
    Everything else -> no new memories. All prompts are recorded."""
    def __init__(self):
        self.prompts: list[str] = []

    def generate_response(self, messages, **kw):
        user_prompt = messages[-1]["content"]
        self.prompts.append(user_prompt)
        # Read ONLY the "## New Messages" section, never the history sections.
        new_part = user_prompt.split("## New Messages", 1)[1].split("## Observation Date", 1)[0]
        if SECRET_TURN in new_part:
            return json.dumps({"memory": [{"text": FACT}]})
        if "my name is Teja Sharma" in new_part:
            return json.dumps({"memory": [{"text": "User's name is Teja Sharma"}]})
        return json.dumps({"memory": []})


LLM = ScriptedLLM()
factory.EmbedderFactory.create = classmethod(lambda cls, *a, **k: HashEmbedder())
factory.LlmFactory.create = classmethod(lambda cls, *a, **k: LLM)


def build() -> Memory:
    return Memory.from_config({
        "vector_store": {"provider": "qdrant", "config": {
            "collection_name": "repro", "path": os.path.join(WORK, "qdrant"),
            "embedding_model_dims": DIMS, "on_disk": True}},
        "history_db_path": os.path.join(WORK, "history.db"),
    })

# ---------------------------------------------------------------- helpers
results: list[tuple[str, bool, str]] = []

def check(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {detail}" if detail else ""))

def visible(m: Memory) -> list[str]:
    rows = m.get_all(filters={"user_id": USER}, top_k=1000).get("results", [])
    return [r["memory"] for r in rows if NEEDLE in r.get("memory", "")]

def sqlite_rows_with_needle(path: str) -> dict[str, int]:
    """Scan EVERY text column of EVERY table — not a hand-picked list."""
    con = sqlite3.connect(path)
    out = {}
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        for col in [c[1] for c in con.execute(f"PRAGMA table_info('{t}')")]:
            n = con.execute(f'SELECT COUNT(*) FROM "{t}" WHERE CAST("{col}" AS TEXT) LIKE ?',
                            (f"%{NEEDLE}%",)).fetchone()[0]
            if n:
                out[f"{t}.{col}"] = n
    con.close()
    return out

def files_with_needle(root: str) -> list[str]:
    hits = []
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            try:
                if NEEDLE.encode() in open(p, "rb").read():
                    hits.append(os.path.relpath(p, root))
            except OSError:
                pass
    return sorted(hits)

# ---------------------------------------------------------------- run
def main() -> int:
    print(f"mem0ai {getattr(mem0, '__version__', '?')}  |  state dir {WORK}\n")
    m = build()

    # Control: a clean store contains no trace of the value.
    check("C0 control: fresh store has no copy of the value",
          files_with_needle(WORK) == [], str(files_with_needle(WORK)))

    m.add(SECRET_TURN, user_id=USER)                      # infer=True (default path)
    ids = [r["id"] for r in m.get_all(filters={"user_id": USER}, top_k=1000)["results"]
           if NEEDLE in r["memory"]]
    check("C1 precondition: add() stored exactly one memory with the value",
          len(ids) == 1, str(visible(m)))
    if len(ids) != 1:
        return 2
    mid = ids[0]

    resp = m.delete(mid)
    print(f"\n   delete() returned: {resp}\n")

    # What the developer can see: it looks deleted.
    check("A1 delete looks successful: get(id) is None", m.get(mid) is None)
    check("A2 delete looks successful: get_all()/search() no longer show it",
          visible(m) == [] and not any(NEEDLE in r["memory"] for r in
          m.search(NEEDLE, filters={"user_id": USER}, top_k=10)["results"]))

    # What is actually still there.
    hist = m.history(mid)
    leaked = [(h["event"], h.get("old_memory"), h.get("new_memory")) for h in hist
              if NEEDLE in str(h.get("old_memory")) + str(h.get("new_memory"))]
    check("B1 BUG: public m.history(id) still returns the deleted text",
          bool(leaked), str(leaked))
    rows = sqlite_rows_with_needle(os.path.join(WORK, "history.db"))
    check("B2 BUG: Mem0's SQLite still has rows containing the value",
          bool(rows), str(rows))
    check("B3 BUG: raw turn kept in `messages` table after delete()",
          rows.get("messages.content", 0) > 0, f"messages.content rows = {rows.get('messages.content', 0)}")

    # Re-feed: the next ordinary add() sends the deleted value to the LLM.
    LLM.prompts.clear()
    m.add("What documents do I need to update my address?", user_id=USER)
    fed = [p for p in LLM.prompts if NEEDLE in p]
    check("B4 BUG: next add() sends the deleted value to the LLM (resurrection route)",
          bool(fed), ("...in prompt section '" + fed[0][:fed[0].find(NEEDLE)].rsplit("## ", 1)[-1].split("\n")[0]
                      + "': " + fed[0][max(0, fed[0].find(NEEDLE) - 60): fed[0].find(NEEDLE) + 12].replace("\n", " ")
                      if fed else "not in prompt"))

    # Survives a restart (new process, same files).
    del m
    m2 = build()
    check("B5 BUG: after restart, history(id) still returns it",
          any(NEEDLE in str(h) for h in m2.history(mid)))

    # Entity store after a restart (needs spaCy: pip install "mem0ai[nlp]==2.2.1").
    try:
        import spacy; spacy.load("en_core_web_sm")
        has_spacy = True
    except Exception:
        has_spacy = False
    if not has_spacy:
        print("[SKIP] B6 needs spaCy + en_core_web_sm")
    else:
        name, bob = "Teja Sharma", "bob"
        m2.add(f"Please remember my name is {name}.", user_id=bob)
        def ents(mm):
            rows = mm.entity_store.list(filters={"user_id": bob}, top_k=1000)
            rows = rows[0] if rows and isinstance(rows[0], list) else rows
            return [(x.payload.get("data"), x.payload.get("linked_memory_ids")) for x in rows]
        bid = [r["id"] for r in m2.get_all(filters={"user_id": bob})["results"]]
        before = ents(m2)
        if len(bid) != 1 or not any(e[0] == name for e in before):
            check("B6 precondition: name memory + entity created", False, f"{bid} {before}")
        else:
            del m2; m3 = build()                  # restart, as any server would
            m3.delete(bid[0])
            gone = m3.get(bid[0]) is None
            after = [e for e in ents(m3) if e[0] == name]
            check("B6 BUG: delete() after a restart leaves the name in the entity store, "
                  "still linked to the deleted id", gone and bool(after) and bid[0] in after[0][1],
                  f"memory gone={gone}; entity store still has {after}")

    leftover = files_with_needle(WORK)
    print(f"\n[INFO] files still containing '{NEEDLE}' (incl. unzeroed SQLite slack space, "
          f"a weaker forensic-only claim): {leftover}")

    bugs = [r for r in results if r[0].startswith("B")]
    ok = all(r[1] for r in results)
    print(f"\n{sum(r[1] for r in bugs)}/{len(bugs)} deletion failures reproduced; "
          f"{'all checks passed' if ok else 'SOME CHECKS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        code = main()
    finally:
        if "--keep" not in sys.argv:
            shutil.rmtree(WORK, ignore_errors=True)
    sys.exit(code)
